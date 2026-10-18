import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Settings2 } from "lucide-react";
import { canWrite } from "../lib/roles";
import { campusLabel } from "../lib/campus";

const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const mondayOf = (d) => { const x = new Date(d); x.setHours(12, 0, 0, 0); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
const DAY_KEYS = ["sc_mon", "sc_tue", "sc_wed", "sc_thu", "sc_fri", "sc_sat", "sc_sun"];

function SlotRequestDialog({ slot, resource, onClose, onDone, t, manager }) {
  const [f, setF] = useState({ period_to: "", units: 1, purpose: "", class_name: "", subject: "", use_location: "", note: "", terms_accepted: false, override_reason: "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (slot) setF((p) => ({ ...p, period_to: String(slot.period.period_no), units: 1 })); }, [slot]);
  if (!slot) return null;
  const set = (patch) => setF((p) => ({ ...p, ...patch }));
  const periodsFrom = slot.periods.filter((p) => p.period_no >= slot.period.period_no);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post("/loans", { resource_id: resource.id, date: slot.date, period_from: slot.period.period_no, period_to: Number(f.period_to),
        units: Number(f.units), purpose: f.purpose, class_name: f.class_name, subject: f.subject, use_location: f.use_location, note: f.note,
        terms_accepted: f.terms_accepted, override_reason: f.override_reason });
      toast.success(`${t("ln_submitted")} ${r.data.number}`);
      (r.data.warnings || []).forEach((w) => toast.message(w));
      onDone(r.data);
    } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog open={!!slot} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none max-w-xl max-h-[90vh] overflow-y-auto" data-testid="slot-request-dialog">
        <DialogHeader><DialogTitle>{t("sc_request_title")}: {resource.name}</DialogTitle></DialogHeader>
        <div className="text-xs text-slate-600 border border-slate-200 bg-slate-50 px-3 py-2">
          {slot.date} · {t("sc_period")} {slot.period.period_no} ({slot.period.start_time}–{slot.period.end_time}) · {t("sc_free")} {slot.free}/{slot.capacity}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="label-mono">{t("sc_until_period")}</Label>
            <Select value={f.period_to} onValueChange={(v) => set({ period_to: v })}>
              <SelectTrigger className="mt-2 rounded-none" data-testid="slot-period-to"><SelectValue /></SelectTrigger>
              <SelectContent>{periodsFrom.map((p) => <SelectItem key={p.period_no} value={String(p.period_no)}>{p.period_no} ({p.end_time})</SelectItem>)}</SelectContent>
            </Select></div>
          <div><Label className="label-mono">{t("ln_units")} *</Label>
            <Input type="number" min="1" max={slot.free} value={f.units} onChange={(e) => set({ units: e.target.value })} className="mt-2 rounded-none" data-testid="slot-units" /></div>
        </div>
        <div><Label className="label-mono">{t("ln_purpose")} *</Label>
          <Textarea rows={2} value={f.purpose} onChange={(e) => set({ purpose: e.target.value })} className="mt-2 rounded-none" data-testid="slot-purpose" /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="label-mono">{t("ln_class")}</Label><Input value={f.class_name} onChange={(e) => set({ class_name: e.target.value })} className="mt-2 rounded-none" /></div>
          <div><Label className="label-mono">{t("ln_subject")}</Label><Input value={f.subject} onChange={(e) => set({ subject: e.target.value })} className="mt-2 rounded-none" /></div>
        </div>
        <div><Label className="label-mono">{t("ln_use_location")}</Label><Input value={f.use_location} onChange={(e) => set({ use_location: e.target.value })} className="mt-2 rounded-none" /></div>
        <div><Label className="label-mono">{t("ln_note")}</Label><Textarea rows={2} value={f.note} onChange={(e) => set({ note: e.target.value })} className="mt-2 rounded-none" /></div>
        {manager && <div><Label className="label-mono">{t("ln_override")}</Label>
          <Input value={f.override_reason} onChange={(e) => set({ override_reason: e.target.value })} placeholder={t("ln_override_hint")} className="mt-2 rounded-none" /></div>}
        <label className="flex items-start gap-2 text-sm border border-slate-200 p-3">
          <input type="checkbox" checked={f.terms_accepted} onChange={(e) => set({ terms_accepted: e.target.checked })} className="mt-1" data-testid="slot-terms" />
          <span>{t("ln_terms")}</span></label>
        <DialogFooter>
          <Button variant="outline" className="rounded-none" onClick={onClose}>{t("cancel")}</Button>
          <Button className="rounded-none" disabled={busy || !f.purpose.trim() || !f.terms_accepted || Number(f.units) < 1} onClick={submit} data-testid="slot-submit">{t("ln_submit")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function SchedulePage() {
  const { t } = useLang();
  const { user } = useAuth();
  const navigate = useNavigate();
  const role = user?.role;
  const writer = canWrite(role);
  const manager = ["super_admin", "admin", "ict_admin"].includes(role);
  const [resources, setResources] = useState([]);
  const [rid, setRid] = useState("");
  const [week, setWeek] = useState(mondayOf(new Date()));
  const [cal, setCal] = useState(null);
  const [slot, setSlot] = useState(null);
  const [detail, setDetail] = useState(null);       // cell opened for details / ICT actions
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/loans/resources").then((r) => {
      const active = r.data.filter((x) => x.active);
      setResources(active);
      if (active.length && !rid) setRid(active[0].id);
    }).catch((e) => toast.error(formatErr(e)));
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(() => {
    if (!rid) return;
    api.get("/loans/calendar", { params: { resource_id: rid, week_start: isoDate(week) } })
      .then((r) => setCal(r.data)).catch((e) => toast.error(formatErr(e)));
  }, [rid, week]);
  useEffect(() => { load(); }, [load]);

  const resource = resources.find((r) => r.id === rid);
  const shift = (n) => { const d = new Date(week); d.setDate(d.getDate() + 7 * n); setWeek(d); };
  const days = useMemo(() => (cal ? cal.days.filter((d, i) => i < 5 || d.cells.some((c) => c.items.length)) : []), [cal]);
  const today = isoDate(new Date());

  const cellClick = (day, cell) => {
    if (day.holiday) return;
    setDetail({ day, cell });
  };
  const markLibur = async (item, date) => {
    setBusy(true);
    try { await api.post(`/loans/schedules/${item.schedule_id}/exceptions`, { date, note: "" }); toast.success(t("ln_saved")); setDetail(null); load(); }
    catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
  };
  const openSession = async (item, date) => {
    setBusy(true);
    try { const r = await api.post(`/loans/schedules/${item.schedule_id}/session`, { date }); navigate(`/loans/${r.data.id}`); }
    catch (e) { toast.error(formatErr(e)); setBusy(false); }
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1400px] mx-auto" data-testid="schedule-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="label-mono mb-2">{t("sc_kicker")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">{t("sc_title")}</h1>
          <p className="text-sm text-slate-500 mt-2 max-w-2xl">{t("sc_subtitle")}</p>
        </div>
        {manager && <Link to="/loans/setup"><Button variant="outline" className="rounded-none" data-testid="open-setup"><Settings2 className="w-4 h-4 mr-2" /> {t("sc_setup")}</Button></Link>}
      </div>

      {resources.length === 0 ? (
        <div className="bg-white border border-slate-200 p-10 text-center text-sm text-slate-500 mt-6">{t("sc_no_resources")}</div>
      ) : (
        <>
          <div className="flex items-center gap-3 flex-wrap mt-6 mb-4">
            <Select value={rid} onValueChange={setRid}>
              <SelectTrigger className="w-72 rounded-none" data-testid="schedule-resource"><SelectValue /></SelectTrigger>
              <SelectContent>{resources.map((r) => <SelectItem key={r.id} value={r.id}>{r.name} · {campusLabel(r.campus)}</SelectItem>)}</SelectContent>
            </Select>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon" className="rounded-none" onClick={() => shift(-1)} data-testid="week-prev"><ChevronLeft className="w-4 h-4" /></Button>
              <Button variant="outline" className="rounded-none" onClick={() => setWeek(mondayOf(new Date()))}>{t("sc_this_week")}</Button>
              <Button variant="outline" size="icon" className="rounded-none" onClick={() => shift(1)} data-testid="week-next"><ChevronRight className="w-4 h-4" /></Button>
            </div>
            <span className="text-sm text-slate-600">{cal ? `${cal.days[0].date} – ${cal.days[6].date}` : ""}</span>
            {resource && <span className="text-xs text-slate-500">{t("sc_capacity")}: {resource.effective_capacity}</span>}
            <span className="flex items-center gap-3 text-xs text-slate-500 ml-auto">
              <span className="flex items-center gap-1"><i className="w-3 h-3 bg-emerald-100 border border-emerald-300 inline-block" /> {t("sc_legend_free")}</span>
              <span className="flex items-center gap-1"><i className="w-3 h-3 bg-rose-100 border border-rose-300 inline-block" /> {t("sc_legend_used")}</span>
            </span>
          </div>

          {cal && cal.periods.length === 0 && <div className="border border-amber-200 bg-amber-50 text-amber-800 text-sm p-4 mb-4">{t("sc_no_periods")}</div>}
          {cal && cal.periods.length > 0 && (
            <div className="overflow-x-auto bg-white border border-slate-200">
              <table className="w-full text-xs border-collapse" data-testid="schedule-grid">
                <thead><tr>
                  <th className="w-28 p-2 border-b border-slate-200 text-left label-mono">{t("sc_period")}</th>
                  {days.map((d) => (
                    <th key={d.date} className={`p-2 border-b border-l border-slate-200 text-left ${d.date === today ? "bg-blue-50" : ""}`}>
                      <div className="font-medium text-slate-800">{t(DAY_KEYS[d.weekday])}</div>
                      <div className="font-normal text-slate-500">{d.date.slice(5)}{d.holiday ? ` · ${d.holiday || t("sc_holiday")}` : ""}</div>
                    </th>))}
                </tr></thead>
                <tbody>
                  {cal.periods.map((p) => (
                    <tr key={p.period_no}>
                      <td className="p-2 border-b border-slate-100 align-top"><div className="font-medium">{p.period_no}</div><div className="text-slate-400">{p.start_time}–{p.end_time}</div></td>
                      {days.map((d) => {
                        const c = d.cells.find((x) => x.period_no === p.period_no);
                        const past = c.end < new Date().toISOString().slice(0, 16);
                        const cls = d.holiday ? "bg-slate-100 text-slate-400" : c.free > 0 ? "bg-emerald-50 hover:bg-emerald-100 text-emerald-800" : "bg-rose-50 hover:bg-rose-100 text-rose-800";
                        return (
                          <td key={d.date} onClick={() => cellClick(d, c)} data-testid={`cell-${d.date}-${p.period_no}`}
                            className={`p-2 border-b border-l border-slate-200 align-top cursor-pointer min-w-[130px] ${cls} ${past ? "opacity-60" : ""}`}>
                            {d.holiday ? <span>{t("sc_holiday")}</span> : (<>
                              <div className="font-medium">{c.free > 0 ? `${t("sc_free")} ${c.free}/${c.capacity}` : t("sc_full")}</div>
                              {c.items.map((it, i) => <div key={i} className={`truncate ${it.type === "libur" ? "line-through text-slate-500" : ""}`} title={it.label}>{it.units ? `${it.units}× ` : ""}{it.label}</div>)}
                              {c.pending.length > 0 && <div className="text-amber-700">+{c.pending.length} {t("sc_pending")}</div>}
                            </>)}
                          </td>);
                      })}
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        </>
      )}

      {/* cell details + ICT actions */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="rounded-none max-w-md" data-testid="cell-dialog">
          {detail && (<>
            <DialogHeader><DialogTitle>{detail.day.date} · {t("sc_period")} {detail.cell.period_no}</DialogTitle></DialogHeader>
            <div className="text-sm text-slate-600">{detail.cell.start.slice(11)}–{detail.cell.end.slice(11)} · {t("sc_free")} {detail.cell.free}/{detail.cell.capacity}</div>
            <div className="space-y-2">
              {detail.cell.items.map((it, i) => (
                <div key={i} className="border border-slate-200 p-3 text-sm">
                  <div className="font-medium">{it.units ? `${it.units}× ` : ""}{it.label}</div>
                  <div className="text-xs text-slate-500">{it.number ? <Link className="text-blue-700 hover:underline" to={`/loans/${it.booking_id}`}>{it.number}</Link> : t(`sc_type_${it.type}`)}</div>
                  {manager && it.type === "fixed" && it.status === "scheduled" && (
                    <div className="flex gap-2 mt-2">
                      <Button size="sm" variant="outline" className="rounded-none" disabled={busy} onClick={() => openSession(it, detail.day.date)} data-testid="open-session">{t("sc_open_session")}</Button>
                      <Button size="sm" variant="outline" className="rounded-none" disabled={busy} onClick={() => markLibur(it, detail.day.date)} data-testid="mark-libur">{t("sc_mark_libur")}</Button>
                    </div>)}
                  {manager && it.type === "fixed" && it.booking_id && (
                    <Link to={`/loans/${it.booking_id}`}><Button size="sm" variant="outline" className="rounded-none mt-2">{t("sc_open_loan")}</Button></Link>)}
                </div>))}
              {detail.cell.pending.map((it, i) => (
                <div key={`p${i}`} className="border border-amber-200 bg-amber-50 p-3 text-sm"><Link className="text-blue-700 hover:underline" to={`/loans/${it.booking_id}`}>{it.number}</Link> · {it.units}× {it.label} ({t("sc_pending")})</div>))}
              {detail.cell.items.length === 0 && detail.cell.pending.length === 0 && <div className="text-sm text-slate-500">{t("sc_empty_slot")}</div>}
            </div>
            <DialogFooter>
              {writer && detail.cell.free > 0 && (
                <Button className="rounded-none" data-testid="slot-request-btn" onClick={() => {
                  setSlot({ date: detail.day.date, period: cal.periods.find((p) => p.period_no === detail.cell.period_no), periods: cal.periods, free: detail.cell.free, capacity: detail.cell.capacity });
                  setDetail(null);
                }}>{t("ln_request")}</Button>)}
            </DialogFooter>
          </>)}
        </DialogContent>
      </Dialog>

      {resource && <SlotRequestDialog slot={slot} resource={resource} t={t} manager={manager} onClose={() => setSlot(null)}
        onDone={(loan) => { setSlot(null); load(); navigate(`/loans/${loan.id}`); }} />}
    </div>
  );
}
