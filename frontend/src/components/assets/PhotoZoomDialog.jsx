import { useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";
import { Button } from "../ui/button";
import { ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

const MIN = 1, MAX = 5, STEP = 0.5;

// Click-to-enlarge viewer for an asset photo: +/- buttons, mouse wheel, drag to pan when zoomed.
export default function PhotoZoomDialog({ open, onOpenChange, src, title }) {
  const [zoom, setZoom] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const drag = useRef(null);

  useEffect(() => { if (open) { setZoom(1); setPos({ x: 0, y: 0 }); } }, [open]);

  const clamp = (z) => Math.min(MAX, Math.max(MIN, z));
  const setZ = (z) => {
    setZoom((cur) => clamp(typeof z === "function" ? z(cur) : z));
    if (typeof z !== "function" && clamp(z) === MIN) setPos({ x: 0, y: 0 });
  };
  useEffect(() => { if (zoom === MIN) setPos({ x: 0, y: 0 }); }, [zoom]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-none max-w-5xl w-[95vw] p-4" data-testid="photo-zoom-dialog">
        <DialogHeader><DialogTitle className="pr-8 truncate">{title}</DialogTitle></DialogHeader>
        <div
          className="relative overflow-hidden bg-slate-100 h-[70vh] flex items-center justify-center select-none"
          style={{ cursor: zoom > 1 ? (drag.current ? "grabbing" : "grab") : "zoom-in" }}
          onWheel={(e) => setZ((z) => z + (e.deltaY < 0 ? STEP : -STEP))}
          onDoubleClick={() => setZ((z) => (z > 1 ? 1 : 2.5))}
          onMouseDown={(e) => { if (zoom > 1) drag.current = { x: e.clientX - pos.x, y: e.clientY - pos.y }; }}
          onMouseMove={(e) => { if (drag.current) setPos({ x: e.clientX - drag.current.x, y: e.clientY - drag.current.y }); }}
          onMouseUp={() => { drag.current = null; }}
          onMouseLeave={() => { drag.current = null; }}
        >
          <img src={src} alt={title} draggable={false} data-testid="photo-zoom-img"
            className="max-w-full max-h-full object-contain"
            style={{ transform: `translate(${pos.x}px, ${pos.y}px) scale(${zoom})`, transition: drag.current ? "none" : "transform 0.15s" }} />
        </div>
        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" size="sm" className="rounded-none" onClick={() => setZ((z) => z - STEP)} disabled={zoom <= MIN} data-testid="zoom-out"><ZoomOut className="w-4 h-4" /></Button>
          <span className="text-sm text-slate-600 w-14 text-center">{Math.round(zoom * 100)}%</span>
          <Button variant="outline" size="sm" className="rounded-none" onClick={() => setZ((z) => z + STEP)} disabled={zoom >= MAX} data-testid="zoom-in"><ZoomIn className="w-4 h-4" /></Button>
          <Button variant="outline" size="sm" className="rounded-none" onClick={() => setZ(1)} data-testid="zoom-reset"><RotateCcw className="w-4 h-4" /></Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
