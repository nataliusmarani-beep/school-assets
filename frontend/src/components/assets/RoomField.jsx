import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api from "../../lib/api";
import { Input } from "../ui/input";
import { Label } from "../ui/label";

const norm = (s) => (s || "").toLowerCase().replace(/[^0-9a-z]/g, "");

/** Room name picker fed by the master list (Classrooms page): pick an existing room, or see that a name is new / looks like an existing one. */
export default function RoomField({ label, value, onChange, campus, t, testid, required, placeholder }) {
  const [names, setNames] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api.get("/rooms", { params: campus ? { campus } : {} })
      .then((r) => { if (alive) setNames([...new Set(r.data.map((x) => x.name))]); })
      .catch(() => {});
    return () => { alive = false; };
  }, [campus]);

  const v = (value || "").trim();
  const exact = useMemo(() => names.some((n) => n.toLowerCase() === v.toLowerCase().replace(/\s+/g, " ")), [names, v]);
  const matches = useMemo(() => (v ? names.filter((n) => n.toLowerCase().includes(v.toLowerCase()) && n !== value) : names).slice(0, 8), [names, v, value]);
  const similar = useMemo(() => {
    if (!v || exact) return [];
    const b = norm(v);
    return names.filter((n) => { const a = norm(n); return a && b && (a === b || (Math.min(a.length, b.length) >= 4 && (a.includes(b) || b.includes(a)))); }).slice(0, 4);
  }, [names, v, exact]);

  return (
    <div className="relative" data-testid={`${testid}-field`}>
      <Label className="label-mono">{label}{required ? " *" : ""}</Label>
      <Input value={value} required={required} placeholder={placeholder} autoComplete="off" className="mt-2 rounded-none" data-testid={testid}
        onChange={(e) => onChange(e.target.value)} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} />
      {open && matches.length > 0 && (
        <div className="absolute z-50 left-0 right-0 bg-white border border-slate-200 shadow-md mt-1 max-h-48 overflow-y-auto">
          {matches.map((n) => (
            <button key={n} type="button" className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 border-b border-slate-100 last:border-0"
              onMouseDown={(e) => { e.preventDefault(); onChange(n); setOpen(false); }}>{n}</button>
          ))}
        </div>
      )}
      {v && exact && <p className="mt-1.5 text-xs text-emerald-700" data-testid={`${testid}-registered`}>✓ {t("room_registered")}</p>}
      {v && !exact && (
        <div className="mt-1.5 text-xs text-amber-700" data-testid={`${testid}-new`}>
          {t("room_new")}
          {similar.length > 0 && (
            <span> {t("room_similar")}{" "}
              {similar.map((n) => (
                <button key={n} type="button" onClick={() => onChange(n)} className="mr-2 underline text-blue-800 hover:text-blue-900" data-testid={`${testid}-similar`}>{n}</button>
              ))}
            </span>
          )}
        </div>
      )}
      <p className="mt-1 text-xs text-slate-400">{t("room_manage")} <Link to="/classrooms" className="underline hover:text-slate-700">{t("cr_title")}</Link></p>
    </div>
  );
}
