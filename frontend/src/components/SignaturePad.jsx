import { useEffect, useRef, useState } from "react";

/** Draw-a-signature box (finger or mouse). Calls onChange with a small PNG data URL, or "" when empty. */
export default function SignaturePad({ onChange, clearLabel = "Clear", testid = "signature-pad" }) {
  const ref = useRef(null);
  const drawing = useRef(false);
  const [inked, setInked] = useState(false);

  useEffect(() => {
    const c = ref.current;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#0f172a";
  }, []);

  const pos = (e) => {
    const c = ref.current;
    const r = c.getBoundingClientRect();
    return [(e.clientX - r.left) * (c.width / r.width), (e.clientY - r.top) * (c.height / r.height)];
  };
  const down = (e) => {
    e.preventDefault();
    try { ref.current.setPointerCapture?.(e.pointerId); } catch { /* synthetic pointers cannot be captured */ }
    drawing.current = true;
    const ctx = ref.current.getContext("2d");
    const [x, y] = pos(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 0.1, y + 0.1);
    ctx.stroke();
  };
  const move = (e) => {
    if (!drawing.current) return;
    e.preventDefault();
    const ctx = ref.current.getContext("2d");
    const [x, y] = pos(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  };
  const up = () => {
    if (!drawing.current) return;
    drawing.current = false;
    setInked(true);
    onChange(ref.current.toDataURL("image/png"));
  };
  const clear = () => {
    const c = ref.current;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, c.width, c.height);
    setInked(false);
    onChange("");
  };

  return (
    <div>
      <canvas ref={ref} width={480} height={160} data-testid={testid}
        className="w-full h-40 border-2 border-dashed border-slate-300 bg-white touch-none cursor-crosshair"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onPointerLeave={up} />
      <button type="button" onClick={clear} disabled={!inked} className="mt-1 text-xs text-slate-500 hover:text-slate-900 disabled:opacity-40">{clearLabel}</button>
    </div>
  );
}
