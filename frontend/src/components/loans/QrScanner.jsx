import { useEffect, useRef, useState } from "react";
import jsQR from "jsqr";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { Camera } from "lucide-react";

/* Camera QR reader. Calls onScan(text) for every new code (the same code is ignored for `repeatMs`).
   Falls back to typing the asset code when the camera is unavailable or the label is damaged. */
export default function QrScanner({ onScan, t, repeatMs = 2500, active = true }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const last = useRef({ text: "", at: 0 });
  const handler = useRef(onScan);        // latest callback, so a changing onScan never restarts the camera
  handler.current = onScan;
  const [error, setError] = useState("");
  const [manual, setManual] = useState("");

  useEffect(() => {
    if (!active) return undefined;
    let stream; let raf; let stopped = false;
    const tick = () => {
      const v = videoRef.current; const c = canvasRef.current;
      if (stopped || !v || !c) return;
      if (v.readyState === v.HAVE_ENOUGH_DATA) {
        c.width = v.videoWidth; c.height = v.videoHeight;
        const ctx = c.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(v, 0, 0, c.width, c.height);
        const img = ctx.getImageData(0, 0, c.width, c.height);
        const code = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
        const now = Date.now();
        if (code && code.data && (code.data !== last.current.text || now - last.current.at > repeatMs)) {
          last.current = { text: code.data, at: now };
          handler.current(code.data);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    navigator.mediaDevices?.getUserMedia({ video: { facingMode: "environment" } })
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
          <div className="absolute inset-8 border-2 border-white/70 pointer-events-none" />
        </div>)}
      <canvas ref={canvasRef} className="hidden" />
      <form onSubmit={submitManual} className="flex gap-2">
        <Input className="rounded-none" value={manual} onChange={(e) => setManual(e.target.value)} placeholder={t("qr_manual")} data-testid="qr-manual-input" />
        <Button type="submit" variant="outline" className="rounded-none" data-testid="qr-manual-submit">{t("qr_find")}</Button>
      </form>
    </div>
  );
}
