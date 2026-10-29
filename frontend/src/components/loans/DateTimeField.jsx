import { useEffect, useState } from "react";
import { CalendarDays, Clock } from "lucide-react";

const SEL = "h-10 px-2 text-sm text-slate-900 border border-slate-300 bg-white rounded-none min-w-0 w-full focus:outline-none focus:border-slate-900";
const CHIP = "px-2.5 py-1 text-xs border transition-colors";
const pad = (n) => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const DAYS = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"];
const MINUTES = Array.from({ length: 12 }, (_, i) => pad(i * 5));
const QUICK_TIMES = ["07:00", "08:00", "10:00", "12:00", "14:00", "16:00"];

const split = (v) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || "");
  return m ? { y: m[1], mo: m[2], d: m[3], h: m[4], mi: m[5] } : null;
};
const fromDate = (dt) => ({ y: String(dt.getFullYear()), mo: pad(dt.getMonth() + 1), d: pad(dt.getDate()) });

/* Date + time picker made of plain selects ("YYYY-MM-DDTHH:mm" in and out). The native datetime-local input
   does not open a picker in some phone browsers / WebViews, selects work everywhere. */
export default function DateTimeField({ value, onChange, testId, tone = "slate" }) {
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

  const full = built(p);
  const parsed = split(full);
  const dt = parsed ? new Date(Number(parsed.y), Number(parsed.mo) - 1, Number(parsed.d)) : null;
  const today = new Date(), tomorrow = new Date(Date.now() + 86400000);
  const isDay = (d) => parsed && parsed.y === String(d.getFullYear()) && parsed.mo === pad(d.getMonth() + 1) && parsed.d === pad(d.getDate());
  const on = tone === "emerald" ? "bg-emerald-700 text-white border-emerald-700" : "bg-slate-900 text-white border-slate-900";
  const off = "bg-white text-slate-600 border-slate-300 hover:border-slate-500";
  const years = [...new Set([thisYear, thisYear + 1, p.y ? Number(p.y) : thisYear])].sort();
  const tid = (s) => (testId ? `${testId}-${s}` : undefined);

  return (
    <div className="mt-2 border border-slate-200 bg-slate-50/60" data-testid={testId}>
      <div className={`flex items-center gap-2 px-3 py-2 border-b border-slate-200 text-sm ${parsed ? "text-slate-900" : "text-slate-400"}`}>
        <CalendarDays className="w-4 h-4 shrink-0 text-slate-400" strokeWidth={1.75} />
        <span className="font-medium truncate" data-testid={tid("summary")}>
          {parsed ? `${DAYS[dt.getDay()]}, ${Number(parsed.d)} ${MONTHS[Number(parsed.mo) - 1]} ${parsed.y}` : "Pilih tanggal"}
        </span>
        {parsed && <span className="ml-auto inline-flex items-center gap-1 font-mono text-xs text-slate-600"><Clock className="w-3.5 h-3.5" strokeWidth={1.75} />{parsed.h}:{parsed.mi}</span>}
      </div>
      <div className="p-3 space-y-3">
        <div className="flex gap-1.5">
          <button type="button" className={`${CHIP} ${isDay(today) ? on : off}`} onClick={() => set(fromDate(today))} data-testid={tid("today")}>Hari ini</button>
          <button type="button" className={`${CHIP} ${isDay(tomorrow) ? on : off}`} onClick={() => set(fromDate(tomorrow))} data-testid={tid("tomorrow")}>Besok</button>
        </div>
        <div className="grid grid-cols-[1fr_1.4fr_1.2fr] gap-1.5">
          <select className={SEL} value={p.d} onChange={(e) => set({ d: e.target.value })} aria-label="Tanggal" data-testid={tid("day")}>
            <option value="">Tgl</option>
            {Array.from({ length: 31 }, (_, i) => pad(i + 1)).map((d) => <option key={d} value={d}>{Number(d)}</option>)}
          </select>
          <select className={SEL} value={p.mo} onChange={(e) => set({ mo: e.target.value })} aria-label="Bulan" data-testid={tid("month")}>
            <option value="">Bulan</option>
            {MONTHS.map((m, i) => <option key={m} value={pad(i + 1)}>{m}</option>)}
          </select>
          <select className={SEL} value={p.y} onChange={(e) => set({ y: e.target.value })} aria-label="Tahun" data-testid={tid("year")}>
            <option value="">Tahun</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <Clock className="w-4 h-4 shrink-0 text-slate-400" strokeWidth={1.75} />
          <select className={SEL} value={p.h} onChange={(e) => set({ h: e.target.value })} aria-label="Jam" data-testid={tid("hour")}>
            {Array.from({ length: 24 }, (_, i) => pad(i)).map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
          <span className="text-slate-400">:</span>
          <select className={SEL} value={p.mi} onChange={(e) => set({ mi: e.target.value })} aria-label="Menit" data-testid={tid("minute")}>
            {[...new Set([...MINUTES, p.mi])].sort().map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_TIMES.map((q) => (
            <button type="button" key={q} className={`${CHIP} font-mono ${`${p.h}:${p.mi}` === q ? on : off}`}
              onClick={() => set({ h: q.slice(0, 2), mi: q.slice(3) })} data-testid={tid(`t-${q.replace(":", "")}`)}>{q}</button>))}
        </div>
      </div>
    </div>
  );
}
