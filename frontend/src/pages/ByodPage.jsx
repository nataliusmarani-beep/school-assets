import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2, Download, Copy } from "lucide-react";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";

export const BYOD_STATUS_STYLE = {
  waiting_parent: "bg-amber-50 text-amber-700 border-amber-200",
  waiting_teacher: "bg-amber-50 text-amber-700 border-amber-200",
  waiting_ict: "bg-blue-50 text-blue-700 border-blue-200",
  scheduled: "bg-blue-50 text-blue-700 border-blue-200",
  approved: "bg-blue-50 text-blue-700 border-blue-200",
  active: "bg-emerald-50 text-emerald-700 border-emerald-200",
  expired: "bg-slate-100 text-slate-500 border-slate-200",
  rejected: "bg-rose-50 text-rose-700 border-rose-200",
  cancelled: "bg-slate-100 text-slate-500 border-slate-200",
  revoked: "bg-rose-50 text-rose-700 border-rose-300",
};

export function ByodBadge({ status, t }) {
  return <span className={`text-xs px-2 py-0.5 border whitespace-nowrap ${BYOD_STATUS_STYLE[status] || BYOD_STATUS_STYLE.expired}`} data-testid="byod-status">{t(`byod_st_${status}`)}</span>;
}

const todayStr = () => new Date().toISOString().slice(0, 10);
const emptyStudent = () => ({ name: "", class_name: "", student_no: "", parent_name: "", parent_email: "", parent_phone: "" });
const EMPTY = () => ({ name: "", subject: "", location: "", start_date: todayStr(), end_date: "", hour_from: "07:30", hour_to: "15:30", students: [emptyStudent()] });

function NewProjectDialog({ open, onClose, onDone, t }) {
  const [f, setF] = useState(EMPTY());
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  useEffect(() => { if (open) { setF(EMPTY()); setResult(null); } }, [open]);
  const set = (patch) => setF((p) => ({ ...p, ...patch }));
  const setStu = (i, patch) => set({ students: f.students.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const ok = f.name.trim().length >= 3 && f.start_date && f.end_date && f.students.every((s) => s.name.trim().length >= 2 && (s.parent_email.trim() || s.parent_phone.trim()));

  const submit = async () => {
    setBusy(true);
    try { const r = await api.post("/byod/projects", f); setResult(r.data); onDone(); }
    catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
  };
  const copy = async (link) => { try { await navigator.clipboard.writeText(link); toast.success(t("byod_copied")); } catch { toast.message(link); } };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none max-w-3xl max-h-[92vh] overflow-y-auto" data-testid="byod-new-dialog">
        {result ? (
          <>
            <DialogHeader><DialogTitle>{t("byod_created_title")}</DialogTitle></DialogHeader>
            <p className="text-xs text-slate-500">{t("byod_created_hint")}</p>
            <div className="divide-y divide-slate-100 border border-slate-200">
              {result.requests.map((r) => (
                <div key={r.id} className="p-3 flex items-center gap-3 flex-wrap text-sm">
                  <div className="flex-1 min-w-[180px]"><div className="font-medium">{r.student_name}</div>
                    <div className="text-xs text-slate-500">{r.number} · {r.sent.email ? t("byod_sent_email") : ""}{r.sent.email && r.sent.whatsapp ? " · " : ""}{r.sent.whatsapp ? t("byod_sent_wa") : ""}{!r.sent.email && !r.sent.whatsapp ? t("byod_sent_none") : ""}</div></div>
                  <Button variant="outline" size="sm" className="rounded-none" onClick={() => copy(r.link)}><Copy className="w-3.5 h-3.5 mr-1" />{t("byod_copy")}</Button>
                </div>))}
            </div>
            <DialogFooter><Button className="rounded-none" onClick={onClose}>OK</Button></DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader><DialogTitle>{t("byod_new_title")}</DialogTitle></DialogHeader>
            <p className="text-xs text-slate-500 border border-slate-200 bg-slate-50 px-3 py-2">{t("byod_new_hint")}</p>
            <div className="grid sm:grid-cols-3 gap-3">
              <div className="sm:col-span-2"><Label className="label-mono">{t("byod_project_name")} *</Label><Input className="mt-2 rounded-none" value={f.name} onChange={(e) => set({ name: e.target.value })} data-testid="byod-project-name" /></div>
              <div><Label className="label-mono">{t("byod_subject")}</Label><Input className="mt-2 rounded-none" value={f.subject} onChange={(e) => set({ subject: e.target.value })} /></div>
              <div className="sm:col-span-3"><Label className="label-mono">{t("byod_location")}</Label><Input className="mt-2 rounded-none" value={f.location} onChange={(e) => set({ location: e.target.value })} /></div>
              <div><Label className="label-mono">{t("byod_start")} *</Label><Input type="date" className="mt-2 rounded-none" value={f.start_date} min={todayStr()} onChange={(e) => set({ start_date: e.target.value })} data-testid="byod-start" /></div>
              <div><Label className="label-mono">{t("byod_end")} *</Label><Input type="date" className="mt-2 rounded-none" value={f.end_date} min={f.start_date} onChange={(e) => set({ end_date: e.target.value })} data-testid="byod-end" /></div>
              <div className="grid grid-cols-2 gap-2">
                <div><Label className="label-mono">{t("byod_hour_from")}</Label><Input type="time" className="mt-2 rounded-none" value={f.hour_from} onChange={(e) => set({ hour_from: e.target.value })} /></div>
                <div><Label className="label-mono">{t("byod_hour_to")}</Label><Input type="time" className="mt-2 rounded-none" value={f.hour_to} onChange={(e) => set({ hour_to: e.target.value })} /></div>
              </div>
            </div>
            <div>
              <div className="label-mono mb-1">{t("byod_students")} ({f.students.length})</div>
              <p className="text-xs text-slate-500 mb-2">{t("byod_contact_hint")}</p>
              <div className="space-y-3">
                {f.students.map((s, i) => (
                  <div key={i} className="border border-slate-200 p-3 grid sm:grid-cols-6 gap-2" data-testid={`byod-student-${i}`}>
                    <div className="sm:col-span-3"><Input placeholder={`${t("byod_student_name")} *`} className="rounded-none" value={s.name} onChange={(e) => setStu(i, { name: e.target.value })} data-testid={`byod-stu-name-${i}`} /></div>
                    <div><Input placeholder={t("byod_student_class")} className="rounded-none" value={s.class_name} onChange={(e) => setStu(i, { class_name: e.target.value })} /></div>
                    <div><Input placeholder={t("byod_student_no")} className="rounded-none" value={s.student_no} onChange={(e) => setStu(i, { student_no: e.target.value })} /></div>
                    <div className="text-right">{f.students.length > 1 && <button onClick={() => set({ students: f.students.filter((_, j) => j !== i) })} className="text-rose-600 p-2" aria-label={t("byod_remove")}><Trash2 className="w-4 h-4" /></button>}</div>
                    <div className="sm:col-span-2"><Input placeholder={t("byod_parent_name")} className="rounded-none" value={s.parent_name} onChange={(e) => setStu(i, { parent_name: e.target.value })} /></div>
                    <div className="sm:col-span-2"><Input placeholder={t("byod_parent_email")} type="email" className="rounded-none" value={s.parent_email} onChange={(e) => setStu(i, { parent_email: e.target.value })} data-testid={`byod-stu-email-${i}`} /></div>
                    <div className="sm:col-span-2"><Input placeholder={t("byod_parent_phone")} className="rounded-none" value={s.parent_phone} onChange={(e) => setStu(i, { parent_phone: e.target.value })} /></div>
                  </div>))}
              </div>
              {f.students.length < 40 && <Button variant="outline" size="sm" className="rounded-none mt-3" onClick={() => set({ students: [...f.students, emptyStudent()] })} data-testid="byod-add-student"><Plus className="w-4 h-4 mr-1" />{t("byod_add_student")}</Button>}
            </div>
            <DialogFooter>
              <Button variant="outline" className="rounded-none" onClick={onClose}>{t("cancel")}</Button>
              <Button className="rounded-none" disabled={!ok || busy} onClick={submit} data-testid="byod-create">{t("byod_create")}</Button>
            </DialogFooter>
          </>)}
      </DialogContent>
    </Dialog>
  );
}

export default function ByodPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const role = user?.role;
  const canCreate = role !== "leader";
  const manager = ["super_admin", "admin", "campus_admin", "ict_admin"].includes(role);
  const viewAll = ["super_admin", "admin", "leader"].includes(role);
  const tabs = useMemo(() => [
    ...(canCreate ? [{ id: "mine", label: "byod_tab_mine" }] : []),
    ...(manager ? [{ id: "manage", label: "byod_tab_manage" }] : []),
    ...(viewAll ? [{ id: "all", label: "byod_tab_all" }] : []),
  ], [canCreate, manager, viewAll]);
  const [tab, setTab] = useState(tabs[0]?.id || "mine");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get("/byod/requests", { params: { scope: tab } }).then((r) => setRows(r.data)).catch((e) => toast.error(formatErr(e))).finally(() => setLoading(false));
  }, [tab]);
  useEffect(() => { load(); }, [load]);

  const exportDevices = async () => {
    try {
      const res = await api.get("/reports/byod-devices", { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = "byod-devices.xlsx"; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast.error(formatErr(e)); }
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1300px] mx-auto" data-testid="byod-page">
      <div className="label-mono mb-2">{t("byod_kicker")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">{t("byod_title")}</h1>
      <p className="text-sm text-slate-500 mt-2 max-w-2xl">{t("byod_subtitle")}</p>
      <div className="flex gap-3 mt-5 flex-wrap">
        {canCreate && <Button className="rounded-none" onClick={() => setOpen(true)} data-testid="byod-new"><Plus className="w-4 h-4 mr-2" />{t("byod_new")}</Button>}
        {(manager || role === "leader") && <Button variant="outline" className="rounded-none" onClick={exportDevices} data-testid="byod-export"><Download className="w-4 h-4 mr-2" />{t("byod_export")}</Button>}
      </div>
      <div className="flex gap-1 border-b border-slate-200 mt-6 mb-6 overflow-x-auto">
        {tabs.map((x) => (
          <button key={x.id} onClick={() => setTab(x.id)} data-testid={`byod-tab-${x.id}`}
            className={`px-4 py-2 text-sm border-b-2 -mb-px whitespace-nowrap ${tab === x.id ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{t(x.label)}</button>))}
      </div>
      {!loading && rows.length === 0 ? <div className="bg-white border border-slate-200 p-10 text-center text-sm text-slate-500">{t("byod_empty")}</div> : (
        <div className="bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left">
              {["byod_number", "byod_student", "byod_project", "byod_teacher", "byod_period", "byod_status"].map((k) => <th key={k} className="label-mono py-3 px-4">{t(k)}</th>)}</tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`byod-row-${r.number}`}>
                <td className="py-3 px-4 font-mono text-xs"><Link className="text-blue-700 hover:underline" to={`/byod/${r.id}`}>{r.number}</Link></td>
                <td className="py-3 px-4">{r.student_name}{r.student_class ? <span className="text-slate-400"> · {r.student_class}</span> : null}</td>
                <td className="py-3 px-4">{r.project_name}</td>
                <td className="py-3 px-4">{r.teacher_name}</td>
                <td className="py-3 px-4 text-xs text-slate-600 whitespace-nowrap">{r.valid_from} → {r.valid_to}</td>
                <td className="py-3 px-4"><ByodBadge status={r.effective_status} t={t} /></td>
              </tr>))}</tbody>
          </table>
        </div>)}
      <NewProjectDialog open={open} t={t} onClose={() => setOpen(false)} onDone={load} />
    </div>
  );
}
