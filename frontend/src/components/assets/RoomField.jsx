import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, Search, Plus } from "lucide-react";
import { toast } from "sonner";
import api, { formatErr } from "../../lib/api";
import { useAuth } from "../../context/AuthContext";
import { isManagerRole } from "../../lib/roles";
import { Input } from "../ui/input";
import { Label } from "../ui/label";

/**
 * Room picker fed by the master list (Classrooms page). No free text: search the registered rooms and pick one.
 * Admins can register a missing room from here; it goes through the same master list (and its near-duplicate guard).
 */
export default function RoomField({ label, value, onChange, campus, t, testid, required, placeholder }) {
  const { user } = useAuth();
  const canCreate = isManagerRole(user?.role);
  const [rooms, setRooms] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const boxRef = useRef(null);

  const load = () => api.get("/rooms", { params: campus ? { campus } : {} })
    .then((r) => { setRooms(r.data); setLoaded(true); }).catch(() => setLoaded(true));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [campus]);
  useEffect(() => {
    const close = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const names = useMemo(() => [...new Set(rooms.map((r) => r.name))].sort((a, b) => a.localeCompare(b)), [rooms]);
  const query = q.trim().toLowerCase();
  const matches = useMemo(() => (query ? names.filter((n) => n.toLowerCase().includes(query)) : names), [names, query]);
  const registered = !!value && names.some((n) => n.toLowerCase() === (value || "").trim().toLowerCase().replace(/\s+/g, " "));
  const exactQuery = names.some((n) => n.toLowerCase() === query.replace(/\s+/g, " "));

  const pick = (n) => { onChange(n); setOpen(false); setQ(""); };

  const register = async (extra = {}) => {
    setBusy(true);
    try {
      await api.post("/classrooms", { name: q.trim(), campus: campus || "", ...extra });
      toast.success(t("cr_created"));
      await load();
      pick(q.trim().replace(/\s+/g, " "));
    } catch (e) {
      const d = e.response?.data?.detail;
      if (d && d.code === "similar_room") {
        if (window.confirm(t("room_confirm_use").replace("{name}", d.name).replace("{list}", d.suggestions.join(", ")).replace("{first}", d.suggestions[0]))) pick(d.suggestions[0]);
        else if (window.confirm(t("room_confirm_new").replace("{name}", d.name))) { setBusy(false); return register({ allow_similar: true }); }
      } else toast.error(formatErr(e));
    } finally { setBusy(false); }
  };

  return (
    <div className="relative" ref={boxRef} data-testid={`${testid}-field`}>
      <Label className="label-mono">{label}{required ? " *" : ""}</Label>
      <div className="relative mt-2">
        <Input readOnly required={required} value={value || ""} placeholder={placeholder || t("room_pick")} data-testid={testid}
          onClick={() => setOpen((o) => !o)} className="rounded-none pr-9 cursor-pointer bg-white" />
        <ChevronDown className="w-4 h-4 text-slate-400 absolute right-3 top-3 pointer-events-none" />
      </div>
      {open && (
        <div className="absolute z-50 left-0 right-0 mt-1 bg-white border border-slate-300 shadow-md" data-testid={`${testid}-popover`}>
          <div className="relative border-b border-slate-200">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("room_search")} data-testid={`${testid}-search`}
              className="w-full h-10 pl-9 pr-3 text-sm outline-none" />
          </div>
          <div className="max-h-56 overflow-y-auto">
            {!loaded ? <div className="px-3 py-2 text-sm text-slate-400">…</div> :
              matches.length === 0 ? <div className="px-3 py-2 text-sm text-slate-500">{t("room_none")}</div> :
              matches.map((n) => (
                <button key={n} type="button" onClick={() => pick(n)} data-testid={`${testid}-option`}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-slate-50 border-b border-slate-100 last:border-0 ${n === value ? "bg-slate-50 font-medium" : ""}`}>{n}</button>
              ))}
          </div>
          {query && !exactQuery && (
            canCreate ? (
              <button type="button" disabled={busy} onClick={() => register()} data-testid={`${testid}-create`}
                className="w-full text-left px-3 py-2 text-sm text-blue-800 hover:bg-blue-50 border-t border-slate-200 inline-flex items-center gap-2">
                <Plus className="w-4 h-4" /> {t("room_register").replace("{name}", q.trim())}
              </button>
            ) : <div className="px-3 py-2 text-xs text-slate-500 border-t border-slate-200">{t("room_ask_admin")}</div>
          )}
        </div>
      )}
      {value && loaded && !registered && <p className="mt-1.5 text-xs text-amber-700" data-testid={`${testid}-unregistered`}>{t("room_unregistered")}</p>}
      {value && registered && <p className="mt-1.5 text-xs text-emerald-700" data-testid={`${testid}-registered`}>✓ {t("room_registered")}</p>}
      <p className="mt-1 text-xs text-slate-400">{t("room_manage")} <Link to="/classrooms" className="underline hover:text-slate-700">{t("cr_title")}</Link></p>
    </div>
  );
}
