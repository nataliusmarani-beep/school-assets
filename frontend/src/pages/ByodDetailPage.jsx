import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle2, Circle, Printer } from "lucide-react";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import SignaturePad from "../components/SignaturePad";
import { ByodBadge } from "./ByodPage";
import { BYOD_STATEMENTS } from "./ByodSignPage";
import { campusLabel } from "../lib/campus";

const fmt = (v) => (v ? new Date(v).toLocaleString() : "—");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const norm = (x) => (x || "").trim().replace(/\s+/g, " ").toLowerCase();

function Row({ k, children }) {
  return <div className="grid grid-cols-3 gap-3 py-2 border-b border-slate-100 text-sm"><div className="text-slate-500">{k}</div><div className="col-span-2 text-slate-900">{children || "—"}</div></div>;
}

function Step({ label, done, when, who }) {
  return (
    <div className={`flex-1 min-w-[140px] border p-3 ${done ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-white"}`}>
      <div className="flex items-center gap-2 text-sm font-medium">{done ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : <Circle className="w-4 h-4 text-slate-300" />}{label}</div>
      <div className="text-xs text-slate-500 mt-1">{when ? `${fmt(when)}${who ? ` · ${who}` : ""}` : "…"}</div>
    </div>
  );
}

function printForm(v, t) {
  const rows = (pairs) => pairs.map(([k, val]) => `<tr><td class="k">${esc(k)}</td><td>${esc(val)}</td></tr>`).join("");
  const devs = v.devices.map((d) => `<tr><td>${esc(t(`byod_kind_${d.kind}`))}</td><td>${esc(d.brand)} ${esc(d.model)}</td><td>${esc(d.os)} ${esc(d.os_version)}</td><td class="mono">${esc(d.mac)}</td></tr>`).join("");
  const terms = BYOD_STATEMENTS.map((k) => `<li>${esc(t(`byod_s_${k}`))}</li>`).join("");
  const sig = (img, name, when, label) => `<div class="sig"><div class="lbl">${esc(label)}</div>${img ? `<img src="${img}" />` : "<div class='blank'></div>"}<div>${esc(name || "—")}</div><div class="small">${esc(when ? fmt(when) : "")}</div></div>`;
  const w = window.open("", "_blank");
  if (!w) { toast.error("Pop-up blocked"); return; }
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(v.number)}</title><style>
    body{font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#0f172a;margin:28px}h1{font-size:18px;margin:0 0 4px}h2{font-size:14px;margin:18px 0 6px;border-bottom:1px solid #cbd5e1;padding-bottom:3px}
    table{border-collapse:collapse;width:100%}td,th{border:1px solid #e2e8f0;padding:5px 8px;text-align:left;vertical-align:top}td.k{width:32%;color:#475569;background:#f8fafc}.mono{font-family:monospace}
    .sigs{display:flex;gap:16px;margin-top:8px}.sig{flex:1;border:1px solid #cbd5e1;padding:8px}.sig img{height:70px;display:block}.blank{height:70px}.lbl{font-size:11px;text-transform:uppercase;color:#64748b}.small{font-size:11px;color:#64748b}
    ol{padding-left:18px}li{margin:3px 0}</style></head><body>
    <h1>${esc(t("byod_pub_title"))}</h1><div class="small">${esc(v.number)} · ${esc(campusLabel(v.campus))} · ${esc(t(`byod_st_${v.effective_status}`))}</div>
    <h2>${esc(t("byod_info"))}</h2><table>${rows([[t("byod_student"), `${v.student_name} ${v.student_class ? "(" + v.student_class + ")" : ""} ${v.student_no}`], [t("byod_project"), `${v.project.name} ${v.project.subject || ""}`],
      [t("byod_location"), v.project.location], [t("byod_period"), `${v.valid_from} → ${v.valid_to}`], [t("byod_allowed_hours"), `${v.project.hour_from} – ${v.project.hour_to}`], [t("byod_teacher"), v.teacher_name],
      [t("byod_parent"), `${v.parent_name} (${v.parent_relation})`]])}</table>
    <h2>${esc(t("byod_devices"))}</h2><table><tr><th>${esc(t("byod_devices"))}</th><th>${esc(t("byod_model"))}</th><th>${esc(t("byod_os"))}</th><th>${esc(t("byod_mac"))}</th></tr>${devs}</table>
    <h2>${esc(t("byod_terms_h"))}</h2><ol>${terms}</ol><p><b>${esc(t("byod_teacher_sign_title"))}:</b> ${esc(t("byod_teacher_statement"))}</p>
    <h2>${esc(t("byod_signatures"))}</h2><div class="sigs">${sig(v.parent_signature, v.parent_signed_name, v.parent_signed_at, t("byod_step_parent"))}${sig(v.teacher_signature, v.teacher_signed_name, v.teacher_signed_at, t("byod_step_teacher"))}${sig("", v.ict_by_name, v.ict_at, t("byod_step_ict"))}</div>
    ${v.ict_note ? `<p><b>${esc(t("byod_ict_note"))}:</b> ${esc(v.ict_note)}</p>` : ""}
    <script>window.onload=function(){window.print()}</script></body></html>`);
  w.document.close();
}

export default function ByodDetailPage() {
  const { id } = useParams();
  const { t } = useLang();
  const { user } = useAuth();
  const [v, setV] = useState(null);
  const [dialog, setDialog] = useState(null);     // teacher | decide | cancel | revoke | extend
  const [busy, setBusy] = useState(false);
  const [signedName, setSignedName] = useState("");
  const [signature, setSignature] = useState("");
  const [agree, setAgree] = useState(false);
  const [note, setNote] = useState("");
  const [newEnd, setNewEnd] = useState("");
  const [macFix, setMacFix] = useState({});

  const load = useCallback(() => { api.get(`/byod/requests/${id}`).then((r) => setV(r.data)).catch((e) => toast.error(formatErr(e))); }, [id]);
  useEffect(() => { load(); }, [load]);

  const act = async (fn, msg) => {
    setBusy(true);
    try { const r = await fn(); if (r?.data?.id) setV(r.data); setDialog(null); setNote(""); setSignature(""); setAgree(false); setSignedName(""); toast.success(msg); }
    catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
  };

  if (!v) return <div className="p-10 text-sm text-slate-500">…</div>;
  const p = v.permissions;
  const eff = v.effective_status;
  const nameOk = norm(signedName) === norm(user?.name);
  const close = () => setDialog(null);

  return (
    <div className="p-6 lg:p-10 max-w-[1000px] mx-auto" data-testid="byod-detail-page">
      <Link to="/byod" className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1 mb-4"><ArrowLeft className="w-4 h-4" />{t("byod_back")}</Link>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="label-mono mb-1">{v.number}</div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">{v.student_name}</h1>
          <div className="text-xs font-mono text-slate-500 mt-1">{v.project.name} · {campusLabel(v.campus)}</div>
        </div>
        <ByodBadge status={eff} t={t} />
      </div>

      <div className="mt-6">
        <div className="label-mono mb-2">{t("byod_flow")}</div>
        <div className="flex gap-3 flex-wrap">
          <Step label={t("byod_step_parent")} done={!!v.parent_signed_at} when={v.parent_signed_at} who={v.parent_signed_name} />
          <Step label={t("byod_step_teacher")} done={!!v.teacher_signed_at} when={v.teacher_signed_at} who={v.teacher_signed_name} />
          <Step label={t("byod_step_ict")} done={!!v.ict_at && ["approved", "rejected", "revoked"].includes(v.status)} when={v.ict_at} who={v.ict_by_name} />
        </div>
      </div>

      {v.pending_end_date && <div className="mt-4 border border-amber-200 bg-amber-50 text-amber-800 text-sm p-3">{t("byod_ext_pending")} {v.pending_end_date}</div>}
      {v.end_reason && <div className="mt-4 border border-rose-200 bg-rose-50 text-rose-800 text-sm p-3">{t("byod_end_reason")}: {v.end_reason}</div>}

      <div className="flex gap-2 flex-wrap mt-5">
        {p.can_teacher_sign && <Button className="rounded-none" onClick={() => setDialog("teacher")} data-testid="byod-teacher-sign">{t("byod_teacher_sign")}</Button>}
        {p.can_decide && <Button className="rounded-none" onClick={() => { setMacFix({}); setNote(""); setDialog("decide"); }} data-testid="byod-decide">{t("byod_decide")}</Button>}
        {p.can_resend && <Button variant="outline" className="rounded-none" disabled={busy} data-testid="byod-resend"
          onClick={async () => { setBusy(true); try { const r = await api.post(`/byod/requests/${id}/resend`); try { await navigator.clipboard.writeText(r.data.link); } catch { /* ignore */ } toast.success(t("byod_resend_done")); load(); } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); } }}>{t("byod_resend")}</Button>}
        {p.can_extend && <Button variant="outline" className="rounded-none" onClick={() => { setNewEnd(""); setDialog("extend"); }} data-testid="byod-extend">{t("byod_extend")}</Button>}
        {p.can_revoke && <Button variant="outline" className="rounded-none text-rose-700" onClick={() => { setNote(""); setDialog("revoke"); }} data-testid="byod-revoke">{t("byod_revoke")}</Button>}
        {p.can_cancel && <Button variant="outline" className="rounded-none" onClick={() => { setNote(""); setDialog("cancel"); }} data-testid="byod-cancel">{t("byod_cancel")}</Button>}
        {v.parent_signed_at && <Button variant="outline" className="rounded-none" onClick={() => printForm(v, t)} data-testid="byod-print"><Printer className="w-4 h-4 mr-2" />{t("byod_print")}</Button>}
      </div>

      <div className="grid md:grid-cols-2 gap-6 mt-6">
        <div className="bg-white border border-slate-200 p-5">
          <div className="label-mono mb-2">{t("byod_info")}</div>
          <Row k={t("byod_student")}>{v.student_name}{v.student_class ? ` (${v.student_class})` : ""} {v.student_no}</Row>
          <Row k={t("byod_project")}>{v.project.name}{v.project.subject ? ` · ${v.project.subject}` : ""}</Row>
          <Row k={t("byod_location")}>{v.project.location}</Row>
          <Row k={t("byod_period")}>{v.valid_from} → {v.valid_to}</Row>
          <Row k={t("byod_allowed_hours")}>{v.project.hour_from} – {v.project.hour_to}</Row>
          <Row k={t("byod_teacher")}>{v.teacher_name}</Row>
        </div>
        <div className="bg-white border border-slate-200 p-5">
          <div className="label-mono mb-2">{t("byod_parent")}</div>
          <Row k={t("byod_parent_name")}>{v.parent_name}</Row>
          <Row k={t("byod_relation")}>{v.parent_relation}</Row>
          <Row k={t("byod_parent_email")}>{v.parent_email}</Row>
          <Row k={t("byod_parent_phone")}>{v.parent_phone}</Row>
          {v.ict_note && <Row k={t("byod_ict_note")}>{v.ict_note}</Row>}
        </div>
      </div>

      {v.devices.length > 0 && (
        <div className="bg-white border border-slate-200 p-5 mt-6" data-testid="byod-devices">
          <div className="label-mono mb-3">{t("byod_devices")}</div>
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="text-left border-b border-slate-200">{["byod_devices", "byod_model", "byod_os", "byod_mac", "byod_serial"].map((k) => <th key={k} className="label-mono py-2 px-2">{t(k)}</th>)}</tr></thead>
            <tbody>{v.devices.map((d) => (
              <tr key={d.id} className="border-b border-slate-100"><td className="py-2 px-2">{t(`byod_kind_${d.kind}`)}</td><td className="py-2 px-2">{d.brand} {d.model}</td>
                <td className="py-2 px-2">{d.os} {d.os_version}</td><td className="py-2 px-2 font-mono text-xs">{d.mac}</td><td className="py-2 px-2 text-xs">{d.serial || "—"}</td></tr>))}</tbody></table></div>
        </div>)}

      {(v.parent_signature || v.teacher_signature) && (
        <div className="bg-white border border-slate-200 p-5 mt-6">
          <div className="label-mono mb-3">{t("byod_signatures")}</div>
          <div className="grid sm:grid-cols-2 gap-4">
            {[["byod_step_parent", v.parent_signature, v.parent_signed_name, v.parent_signed_at], ["byod_step_teacher", v.teacher_signature, v.teacher_signed_name, v.teacher_signed_at]].map(([k, img, name, when]) => (
              <div key={k} className="border border-slate-200 p-3"><div className="text-xs text-slate-500 mb-1">{t(k)}</div>
                {img ? <img src={img} alt="" className="h-20 bg-white" /> : <div className="h-20 text-xs text-slate-300 flex items-center">…</div>}
                <div className="text-sm mt-1">{name || "—"}</div><div className="text-xs text-slate-400">{when ? fmt(when) : ""}</div></div>))}
          </div>
        </div>)}

      <div className="bg-white border border-slate-200 p-5 mt-6">
        <div className="label-mono mb-3">{t("byod_history")}</div>
        <ul className="text-sm space-y-1.5">{v.events.map((e, i) => (
          <li key={i} className="flex gap-3"><span className="text-xs text-slate-400 w-40 flex-shrink-0">{fmt(e.at)}</span><span className="font-mono text-xs w-36 flex-shrink-0">{e.action}</span><span className="text-slate-600">{e.actor}{e.detail ? ` — ${e.detail}` : ""}</span></li>))}</ul>
      </div>

      {/* teacher signs */}
      <Dialog open={dialog === "teacher"} onOpenChange={(o) => !o && close()}>
        <DialogContent className="rounded-none max-w-lg"><DialogHeader><DialogTitle>{t("byod_teacher_sign_title")}</DialogTitle></DialogHeader>
          <label className="flex items-start gap-3 text-sm"><input type="checkbox" className="mt-1" checked={agree} onChange={(e) => setAgree(e.target.checked)} data-testid="byod-teacher-agree" /><span>{t("byod_teacher_statement")}</span></label>
          <div><Label className="label-mono">{t("byod_sign_name")}</Label><Input className="mt-2 rounded-none" value={signedName} onChange={(e) => setSignedName(e.target.value)} data-testid="byod-teacher-name" />
            <p className="text-xs text-slate-500 mt-1">{t("byod_sign_name_hint")} <b>{user?.name}</b></p></div>
          <div><Label className="label-mono">{t("byod_draw")}</Label><SignaturePad onChange={setSignature} clearLabel={t("byod_clear")} testid="byod-teacher-pad" /></div>
          <DialogFooter><Button className="rounded-none" disabled={busy || !agree || !nameOk || !signature} data-testid="byod-teacher-save"
            onClick={() => act(() => api.put(`/byod/requests/${id}/teacher-sign`, { signed_name: signedName.trim(), signature, agree }), t("byod_saved"))}>{t("byod_teacher_sign")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ICT decides */}
      <Dialog open={dialog === "decide"} onOpenChange={(o) => !o && close()}>
        <DialogContent className="rounded-none max-w-xl max-h-[90vh] overflow-y-auto"><DialogHeader><DialogTitle>{t("byod_decide")}</DialogTitle></DialogHeader>
          <p className="text-xs text-slate-500">{t("byod_decide_hint")}</p>
          {!v.pending_end_date && v.devices.map((d) => (
            <div key={d.id} className="border border-slate-200 p-3 text-sm space-y-1.5">
              <div className="font-medium">{t(`byod_kind_${d.kind}`)} · {d.brand} {d.model} <span className="text-slate-400">{d.os} {d.os_version}</span></div>
              <Label className="label-mono">{t("byod_mac")}</Label>
              <Input className="rounded-none font-mono" defaultValue={d.mac} onChange={(e) => setMacFix((m) => ({ ...m, [d.id]: e.target.value }))} data-testid={`byod-mac-fix-${d.id}`} />
            </div>))}
          {v.pending_end_date && <p className="text-sm">{t("byod_ext_pending")} <b>{v.pending_end_date}</b></p>}
          <div><Label className="label-mono">{t("byod_note")}</Label><Textarea rows={2} className="mt-2 rounded-none" value={note} onChange={(e) => setNote(e.target.value)} data-testid="byod-decide-note" /></div>
          <DialogFooter className="gap-2">
            <Button variant="outline" className="rounded-none" disabled={busy || !note.trim()} data-testid="byod-reject"
              onClick={() => act(() => api.put(`/byod/requests/${id}/decide`, { decision: "rejected", note }), t("byod_saved"))}>{t("byod_reject")}</Button>
            <Button className="rounded-none" disabled={busy} data-testid="byod-approve"
              onClick={() => act(() => api.put(`/byod/requests/${id}/decide`, { decision: "approved", note, devices: Object.entries(macFix).filter(([did, mac]) => mac && mac !== v.devices.find((d) => d.id === did)?.mac).map(([did, mac]) => ({ id: did, mac })) }), t("byod_saved"))}>{t("byod_approve")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* cancel / revoke */}
      <Dialog open={dialog === "cancel" || dialog === "revoke"} onOpenChange={(o) => !o && close()}>
        <DialogContent className="rounded-none max-w-md"><DialogHeader><DialogTitle>{dialog === "revoke" ? t("byod_revoke") : t("byod_cancel")}</DialogTitle></DialogHeader>
          <Textarea rows={3} className="rounded-none" placeholder={t("byod_reason")} value={note} onChange={(e) => setNote(e.target.value)} data-testid="byod-reason" />
          <DialogFooter><Button className="rounded-none" disabled={busy || (dialog === "revoke" && note.trim().length < 3)} data-testid="byod-reason-save"
            onClick={() => act(() => api.put(`/byod/requests/${id}/${dialog}`, { reason: note }), t("byod_saved"))}>{dialog === "revoke" ? t("byod_revoke") : t("byod_cancel")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* extension */}
      <Dialog open={dialog === "extend"} onOpenChange={(o) => !o && close()}>
        <DialogContent className="rounded-none max-w-md"><DialogHeader><DialogTitle>{t("byod_extend")}</DialogTitle></DialogHeader>
          <p className="text-xs text-slate-500">{t("byod_ext_hint")}</p>
          <div><Label className="label-mono">{t("byod_new_end")}</Label><Input type="date" className="mt-2 rounded-none" min={v.valid_to} value={newEnd} onChange={(e) => setNewEnd(e.target.value)} data-testid="byod-new-end" /></div>
          <DialogFooter><Button className="rounded-none" disabled={busy || !newEnd} data-testid="byod-extend-save"
            onClick={() => act(() => api.put(`/byod/requests/${id}/extend`, { new_end_date: newEnd }), t("byod_saved"))}>{t("byod_extend")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
