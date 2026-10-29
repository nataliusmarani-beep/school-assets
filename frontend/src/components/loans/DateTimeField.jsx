import { useEffect, useState } from "react";

const SEL = "h-10 px-2 text-sm border border-slate-300 bg-white rounded-none min-w-0";
const pad = (n) => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const MINUTES = Array.from({ length: 12 }, (_, i) => pad(i * 5));

const split = (v) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || "");
  return m ? { y: m[1], mo: m[2], d: m[3], h: m[4], mi: m[5] } : null;
};

/* Date + time picker made of plain selects ("YYYY-MM-DDTHH:mm" in and out). The native datetime-local input
   does not open a picker in some phone browsers / WebViews, selects work everywhere. */
export default function DateTimeField({ value, onChange, testId }) {
  const [p, setP] = useState(() => split(value) || { y: "", mo: "", d: "", h: "08", mi: "00" });
  const thisYear = new Date().getFullYear();

  const built = (x) => {
    if (!x.y || !x.mo || !x.d) return "";
    const last = new Date(Number(x.y), Number(x.mo), 0).getDate();
    return `${x.y}-${x.mo}-${pad(Math.min(Number(x.d), last))}T${x.h}:${x.mi}`;
  };

  // follow outside changes (form reset, prefilled decision)
  useEffect(() => {
    const ext = split(value);
    if (ext) { if (built(p) !== value) setP(ext); }
    else if (built(p)) setP({ y: "", mo: "", d: "", h: "08", mi: "00" });
  }, [value]); // eslint-disable-line

  const set = (patch) => {
    const n = { ...p, ...patch };
    setP(n);
    const out = built(n);
    if (out !== (value || "")) onChange(out);
  };

  const years = [...new Set([thisYear, thisYear + 1, p.y ? Number(p.y) : thisYear])].sort();
  return (
    <div className="mt-2 space-y-2" data-testid={testId}>
      <div className="grid grid-cols-[1fr_1.4fr_1.2fr] gap-1.5">
        <select className={SEL} value={p.d} onChange={(e) => set({ d: e.target.value })} aria-label="Tanggal" data-testid={testId && `${testId}-day`}>
          <option value="">Tgl</option>
          {Array.from({ length: 31 }, (_, i) => pad(i + 1)).map((d) => <option key={d} value={d}>{Number(d)}</option>)}
        </select>
        <select className={SEL} value={p.mo} onChange={(e) => set({ mo: e.target.value })} aria-label="Bulan" data-testid={testId && `${testId}-month`}>
          <option value="">Bulan</option>
          {MONTHS.map((m, i) => <option key={m} value={pad(i + 1)}>{m}</option>)}
        </select>
        <select className={SEL} value={p.y} onChange={(e) => set({ y: e.target.value })} aria-label="Tahun" data-testid={testId && `${testId}-year`}>
          <option value="">Tahun</option>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        <select className={SEL} value={p.h} onChange={(e) => set({ h: e.target.value })} aria-label="Jam" data-testid={testId && `${testId}-hour`}>
          {Array.from({ length: 24 }, (_, i) => pad(i)).map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
        <select className={SEL} value={p.mi} onChange={(e) => set({ mi: e.target.value })} aria-label="Menit" data-testid={testId && `${testId}-minute`}>
          {[...new Set([...MINUTES, p.mi])].sort().map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
    </div>
  );
}
