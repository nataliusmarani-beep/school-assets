import { useEffect, useRef, useState } from "react";
import jsQR from "jsqr";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { Camera } from "lucide-react";

// the guide rectangle, as a fraction of the preview (left/right inset x, top/bottom inset y)
const GUIDE = { x: 0.06, y: 0.22 };

/* Camera QR reader. Calls onScan(text) for every new code (the same code is ignored for `repeatMs`).
   Falls back to typing the asset code when the camera is unavailable or the label is damaged. */
const dist = (f, c) => { const b = f.boundingBox; return Math.hypot(b.x + b.width / 2 - c.width / 2, b.y + b.height / 2 - c.height / 2); };

export default function QrScanner({ onScan, t, repeatMs = 2500, active = true, paused = false }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const last = useRef({ text: "", at: 0 });
  const detector = useRef(null);
  const zx = useRef(null);
  const handler = useRef(onScan);        // latest callback, so a changing onScan never restarts the camera
  handler.current = onScan;
  const pausedRef = useRef(paused);      // while a result is on screen the camera keeps running but reads are ignored
  pausedRef.current = paused;
  const [error, setError] = useState("");
  const [manual, setManual] = useState("");
  const [seen, setSeen] = useState("");     // what the camera is reading right now, so a misread is visible

  useEffect(() => {
    if (!active) return undefined;
    let stream; let raf; let stopped = false; let lastTry = 0; let busy = false;
    // a code is accepted only after the same text was read in several frames in a row, so a single misread
    // (or a neighbouring label sliding through the frame) never reaches the loan screens
    const streak = { text: "", n: 0, at: 0 };
    const emit = (text, need = 3) => {
      const now = Date.now();
      if (!text || pausedRef.current) { streak.n = 0; return; }
      setSeen(text);
      if (text !== streak.text || now - streak.at > 1200) { streak.text = text; streak.n = 0; }
      streak.n += 1; streak.at = now;
      if (streak.n < need) return;
      if (text && (text !== last.current.text || now - last.current.at > repeatMs)) {
        last.current = { text, at: now };
        handler.current(text);
      }
    };
    // 1D barcodes (Code 128 / 39, EAN ...): the phone's own detector when it has one, otherwise zxing loaded on demand
    const zxingRead = async (c) => {
      const Z = await import("@zxing/library");
      if (!zx.current) {
        const reader = new Z.MultiFormatReader();
        reader.setHints(new Map([[Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.CODE_128, Z.BarcodeFormat.CODE_39, Z.BarcodeFormat.EAN_13,
          Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.ITF, Z.BarcodeFormat.CODABAR]], [Z.DecodeHintType.TRY_HARDER, true]]));
        zx.current = reader;
      }
      try { return zx.current.decode(new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(c)))).getText(); }
      catch (e) { return ""; }
    };
    let flip = 0;
    const readBars = async (c) => {
      if (window.BarcodeDetector) {
        if (!detector.current) {
          const want = ["code_128", "code_39", "ean_13", "ean_8", "upc_a", "itf", "codabar"];
          const have = (await window.BarcodeDetector.getSupportedFormats?.()) || want;
          detector.current = new window.BarcodeDetector({ formats: want.filter((f) => have.includes(f)) });
        }
        const found = await detector.current.detect(c);
        // several labels in view: take the one nearest the middle of the guide
        const mid = found.filter((f) => f.rawValue).sort((a, b) => dist(a, c) - dist(b, c))[0];
        if (mid) return mid.rawValue;
        // the phone's detector missed this frame: let zxing have every other frame
        if ((flip += 1) % 2) return "";
      }
      return zxingRead(c);
    };
    const tick = () => {
      const v = videoRef.current; const c = canvasRef.current;
      if (stopped || !v || !c) return;
      if (v.readyState === v.HAVE_ENOUGH_DATA) {
        // read only what is inside the green guide, so the labels above / below / beside it can never be picked up
        const cw = v.clientWidth || 1; const ch = v.clientHeight || 1;
        const k = Math.max(cw / v.videoWidth, ch / v.videoHeight);          // object-cover scale
        const ox = (v.videoWidth - cw / k) / 2; const oy = (v.videoHeight - ch / k) / 2;
        const sx = Math.max(0, ox + GUIDE.x * cw / k); const sy = Math.max(0, oy + GUIDE.y * ch / k);
        const sw = Math.min(v.videoWidth - sx, (1 - 2 * GUIDE.x) * cw / k); const sh = Math.min(v.videoHeight - sy, (1 - 2 * GUIDE.y) * ch / k);
        c.width = Math.round(sw); c.height = Math.round(sh);
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(v, sx, sy, sw, sh, 0, 0, c.width, c.height);
        const img = ctx.getImageData(0, 0, c.width, c.height);
        const code = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
        if (code && code.data) emit(code.data, 2);
        else if (!busy && Date.now() - lastTry > 150) {
          busy = true; lastTry = Date.now();
          readBars(c).then((txt) => { if (!stopped) emit(txt, 3); }).catch(() => {}).finally(() => { busy = false; });
        }
      }
      raf = requestAnimationFrame(tick);
    };
    navigator.mediaDevices?.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } } })
      .then((s) => {
        if (stopped) { s.getTracks().forEach((x) => x.stop()); return; }
        stream = s;
        const v = videoRef.current;
        if (v) { v.srcObject = s; v.setAttribute("playsinline", "true"); v.play().catch(() => {}); raf = requestAnimationFrame(tick); }
      })
      .catch(() => setError(t("qr_camera_error")));
    if (!navigator.mediaDevices) setError(t("qr_camera_error"));
    return () => { stopped = true; if (raf) cancelAnimationFrame(raf); stream?.getTracks().forEach((x) => x.stop()); };
  }, [active, repeatMs, t]);

  const submitManual = (e) => { e.preventDefault(); if (manual.trim()) { onScan(manual.trim()); setManual(""); } };

  return (
    <div className="space-y-3" data-testid="qr-scanner">
      {error ? (
        <div className="border border-amber-200 bg-amber-50 text-amber-800 text-sm p-3 flex items-center gap-2"><Camera className="w-4 h-4" /> {error}</div>
      ) : (
        <div className="relative bg-black aspect-video overflow-hidden">
          <video ref={videoRef} className="w-full h-full object-cover" muted playsInline />
          <div style={{ left: `${GUIDE.x * 100}%`, right: `${GUIDE.x * 100}%`, top: `${GUIDE.y * 100}%`, bottom: `${GUIDE.y * 100}%` }} className={`absolute border-2 pointer-events-none ${paused ? "border-emerald-400" : "border-white/70"}`} />
        </div>)}
      {!error && <div className="text-xs text-slate-500 font-mono truncate" data-testid="qr-seen">{seen ? `${t("qr_reading")}: ${seen}` : t("qr_searching")}</div>}
      <canvas ref={canvasRef} className="hidden" />
      <form onSubmit={submitManual} className="flex gap-2">
        <Input className="rounded-none" autoFocus value={manual} onChange={(e) => setManual(e.target.value)} placeholder={t("qr_manual")} data-testid="qr-manual-input" />
        <Button type="submit" variant="outline" className="rounded-none" data-testid="qr-manual-submit">{t("qr_find")}</Button>
      </form>
    </div>
  );
}
