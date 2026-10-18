import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { StatusBadge } from "./LoansPage";
import { UnitCheck, emptyUnit, fileSrc, fmtDateTime } from "../components/loans/LoanForms";
import { campusLabel } from "../lib/campus";

function Row({ k, children }) {
  return <div className="grid grid-cols-3 gap-3 py-2 border-b border-slate-100 text-sm"><div className="text-slate-500">{k}</div><div className="col-span-2 text-slate-900">{children || "—"}</div></div>;
}

function PhotoPair({ unit, t }) {
  if (!unit.pre_photo && !unit.post_photo) return null;
  const Img = ({ path, label }) => (
    <div>
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      {path ? <a href={fileSrc(path)} target="_blank" rel="noreferrer"><img src={fileSrc(path)} alt={label} className="h-36 w-full max-w-[220px] object-cover border border-slate-200" /></a>
        : <div className="h-36 w-full max-w-[220px] border border-dashed border-slate-200 flex items-center justify-center text-xs text-slate-300">—</div>}
    </div>
  );
  return <div className="flex gap-4 flex-wrap mt-3" data-testid="loan-photo-compare"><Img path={unit.pre_photo} label={t("ln_photo_before")} /><Img path={unit.post_photo} label={t("ln_photo_after")} /></div>;
}

function CheckLine({ c, t }) {
  if (!c || !c.physical) return null;
  return (
    <div className="text-xs text-slate-600 mt-2 space-y-0.5">
      <div>{t("ln_physical")}: <b>{t(`ln_phys_${c.physical}`)}</b> · {t("ln_function")}: <b>{t(`ln_fn_${c.function}`)}</b></div>
      {c.missing?.length > 0 && <div className="text-rose-600">{t("ln_missing")}: {c.missing.join(", ")}</div>}
      {c.note && <div>“{c.note}”</div>}
      {(c.handed_by || c.received_by) && <div className="text-slate-400">{c.handed_by ? `${t("ln_handed_by")}: ${c.handed_by} · ` : ""}{t("ln_received_by")}: {c.received_by}</div>}
    </div>
  );
}

export default function LoanDetailPage() {
  const { id } = useParams();
  const { t } = useLang();
  const [loan, setLoan] = useState(null);
  const [dialog, setDialog] = useState(null);       // decide | supervisor | cancel | out | in
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState({ decision: "approved", units: "", start_at: "", end_at: "", note: "" });
  const [note, setNote] = useState("");
  const [unit, setUnit] = useState(null);

  const load = useCallback(() => {
    api.get(`/loans/${id}`).then((r) => setLoan(r.data)).catch((e) => toast.error(formatErr(e)));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const act = async (fn, okMsg) => {
    setBusy(true);
    try { const r = await fn(); setLoan(r.data); setDialog(null); setNote(""); toast.success(okMsg); }
    catch (e) { toast.error(formatErr(e)); }
    finally { setBusy(false); }
  };

  if (!loan) return <div className="p-10 text-sm text-slate-500">…</div>;
  const p = loan.permissions;
  const a = loan.asset || {};
  const openOut = () => { setUnit(emptyUnit(loan.asset_id, loan.accessories)); setDialog("out"); };
  const openIn = () => {
    const out = loan.units.find((u) => u.status === "out");
    setUnit(emptyUnit(out?.asset_id || loan.asset_id, loan.accessories)); setDialog("in");
  };
  const openDecide = () => {
    setDecision({ decision: "approved", units: String(loan.units_requested), start_at: loan.start_at, end_at: loan.end_at, note: "" });
    setDialog("decide");
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1100px] mx-auto" data-testid="loan-detail-page">
      <Link to="/loans" className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1 mb-4"><ArrowLeft className="w-4 h-4" /> {t("ln_back")}</Link>
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="label-mono mb-1">{loan.number}</div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">{a.name || "—"}</h1>
          <div className="text-xs font-mono text-slate-500 mt-1">{a.asset_tag} · {campusLabel(loan.campus)}</div>
        </div>
        <StatusBadge status={loan.status} t={t} />
      </div>

      <div className="flex gap-2 flex-wrap mt-5" data-testid="loan-actions">
        {p.can_supervise && <Button className="rounded-none" onClick={() => { setNote(""); setDialog("supervisor"); }} data-testid="loan-supervisor-btn">{t("ln_act_supervisor")}</Button>}
        {p.can_decide && <Button className="rounded-none" onClick={openDecide} data-testid="loan-decide-btn">{t("ln_act_decide")}</Button>}
        {p.can_check_out && <Button className="rounded-none" onClick={openOut} data-testid="loan-checkout-btn">{t("ln_act_checkout")}</Button>}
        {p.can_check_in && <Button className="rounded-none" onClick={openIn} data-testid="loan-checkin-btn">{t("ln_act_checkin")}</Button>}
        {p.can_cancel && <Button variant="outline" className="rounded-none" onClick={() => { setNote(""); setDialog("cancel"); }} data-testid="loan-cancel-btn">{t("ln_act_cancel")}</Button>}
      </div>

      <div className="grid lg:grid-cols-2 gap-6 mt-6">
        <div className="bg-white border border-slate-200 p-5">
          <Row k={t("ln_requester")}>{loan.requester_name}</Row>
          <Row k={t("ln_period")}>{fmtDateTime(loan.start_at)} → {fmtDateTime(loan.end_at)}</Row>
          <Row k={t("ln_units")}>{loan.units_approved ?? loan.units_requested}</Row>
          <Row k={t("ln_purpose")}>{loan.purpose}</Row>
          <Row k={t("ln_class")}>{[loan.class_name, loan.subject].filter(Boolean).join(" · ")}</Row>
          <Row k={t("ln_use_location")}>{loan.use_location}</Row>
          <Row k={t("ln_note")}>{loan.note}</Row>
          {loan.take_home ? <Row k={t("ln_take_home")}>{t(`ln_sup_${loan.supervisor_decision || "pending"}`)}{loan.supervisor_note ? ` — ${loan.supervisor_note}` : ""}</Row> : null}
          {loan.is_late_request ? <Row k={t("ln_late")}>{t("ln_late_hint")}</Row> : null}
          {loan.override_reason ? <Row k={t("ln_override")}>{loan.override_reason}</Row> : null}
        </div>
        <div className="bg-white border border-slate-200 p-5">
          <div className="label-mono mb-2">{t("ln_decision")}</div>
          <Row k={t("ln_status")}>{t(`ln_st_${loan.status}`)}</Row>
          <Row k={t("ln_decided_by")}>{loan.decided_by_name ? `${loan.decided_by_name} · ${fmtDateTime(loan.decided_at)}` : ""}</Row>
          <Row k={t("ln_decision_note")}>{loan.decision_note}</Row>
          {loan.accessories.length > 0 && <Row k={t("ln_accessories")}>{loan.accessories.join(", ")}</Row>}
          {loan.faults?.length > 0 && <div className="mt-3 text-sm text-rose-700">{t("ln_fault_created")} <Link to="/faults" className="underline">{t("nav_faults")}</Link></div>}
        </div>
      </div>

      {loan.units.length > 0 && (
        <div className="mt-6 space-y-4" data-testid="loan-units">
          <div className="label-mono">{t("ln_unit_records")}</div>
          {loan.units.map((u) => (
            <div key={u.id} className="bg-white border border-slate-200 p-5">
              <div className="flex justify-between flex-wrap gap-2 text-sm">
                <div><b>{u.asset_name}</b> <span className="font-mono text-xs text-slate-400">{u.asset_tag}{u.serial_number ? ` · SN ${u.serial_number}` : ""}</span></div>
                <div className="text-xs text-slate-500">{t(`ln_unit_${u.status}`)} · {fmtDateTime(u.out_at)} → {fmtDateTime(u.in_at)}</div>
              </div>
              <div className="grid md:grid-cols-2 gap-4">
                <div><div className="text-xs label-mono mt-3">{t("ln_checkout")}</div><CheckLine c={u.out_check} t={t} /></div>
                <div><div className="text-xs label-mono mt-3">{t("ln_checkin")}</div><CheckLine c={u.in_check} t={t} /></div>
              </div>
              <PhotoPair unit={u} t={t} />
            </div>))}
        </div>
      )}

      {/* decide */}
      <Dialog open={dialog === "decide"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="rounded-none max-w-lg"><DialogHeader><DialogTitle>{t("ln_act_decide")}</DialogTitle></DialogHeader>
          <div><Label className="label-mono">{t("ln_decision")}</Label>
            <Select value={decision.decision} onValueChange={(v) => setDecision({ ...decision, decision: v })}>
              <SelectTrigger className="mt-2 rounded-none" data-testid="loan-decision"><SelectValue /></SelectTrigger>
              <SelectContent>{["approved", "partially_approved", "rejected"].map((s) => <SelectItem key={s} value={s}>{t(`ln_st_${s}`)}</SelectItem>)}</SelectContent>
            </Select></div>
          {decision.decision !== "rejected" && (
            <div className="grid grid-cols-3 gap-3">
              <div><Label className="label-mono">{t("ln_units")}</Label>
                <Input type="number" min="1" max={loan.units_requested} value={decision.units} onChange={(e) => setDecision({ ...decision, units: e.target.value })} className="mt-2 rounded-none" /></div>
              <div><Label className="label-mono">{t("ln_start")}</Label>
                <Input type="datetime-local" value={decision.start_at} onChange={(e) => setDecision({ ...decision, start_at: e.target.value })} className="mt-2 rounded-none" /></div>
              <div><Label className="label-mono">{t("ln_end")}</Label>
                <Input type="datetime-local" value={decision.end_at} onChange={(e) => setDecision({ ...decision, end_at: e.target.value })} className="mt-2 rounded-none" /></div>
            </div>)}
          <div><Label className="label-mono">{t("ln_decision_note")}{decision.decision !== "approved" ? " *" : ""}</Label>
            <Textarea rows={2} value={decision.note} onChange={(e) => setDecision({ ...decision, note: e.target.value })} className="mt-2 rounded-none" data-testid="loan-decision-note" /></div>
          <DialogFooter><Button className="rounded-none" disabled={busy} data-testid="loan-decision-save"
            onClick={() => act(() => api.put(`/loans/${id}/decide`, { decision: decision.decision, units: decision.units ? Number(decision.units) : null, start_at: decision.start_at || null, end_at: decision.end_at || null, note: decision.note }), t("ln_saved"))}>{t("save_changes")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* supervisor / cancel */}
      <Dialog open={dialog === "supervisor" || dialog === "cancel"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="rounded-none max-w-md"><DialogHeader><DialogTitle>{dialog === "cancel" ? t("ln_act_cancel") : t("ln_act_supervisor")}</DialogTitle></DialogHeader>
          <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("ln_decision_note")} className="rounded-none" data-testid="loan-dialog-note" />
          <DialogFooter className="gap-2">
            {dialog === "supervisor" ? (<>
              <Button variant="outline" className="rounded-none" disabled={busy} data-testid="loan-sup-reject" onClick={() => act(() => api.put(`/loans/${id}/supervisor`, { approve: false, note }), t("ln_saved"))}>{t("ln_reject")}</Button>
              <Button className="rounded-none" disabled={busy} data-testid="loan-sup-approve" onClick={() => act(() => api.put(`/loans/${id}/supervisor`, { approve: true, note }), t("ln_saved"))}>{t("ln_approve")}</Button>
            </>) : (
              <Button className="rounded-none" disabled={busy} data-testid="loan-cancel-confirm" onClick={() => act(() => api.put(`/loans/${id}/cancel`, { reason: note }), t("ln_saved"))}>{t("ln_act_cancel")}</Button>)}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* check-out / check-in */}
      <Dialog open={dialog === "out" || dialog === "in"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="rounded-none max-w-xl max-h-[90vh] overflow-y-auto" data-testid="loan-check-dialog">
          <DialogHeader><DialogTitle>{dialog === "in" ? t("ln_act_checkin") : t("ln_act_checkout")}</DialogTitle></DialogHeader>
          <div className="text-xs text-slate-500">{a.name} · <span className="font-mono">{a.asset_tag}</span> · {t("ln_borrower")}: {loan.requester_name}</div>
          {unit && <UnitCheck t={t} mode={dialog} accessories={loan.accessories} value={unit} onChange={setUnit} />}
          <DialogFooter><Button className="rounded-none" disabled={busy} data-testid="loan-check-save"
            onClick={() => act(() => api.post(`/loans/${id}/${dialog === "in" ? "check-in" : "check-out"}`, { units: [unit] }), t("ln_saved"))}>{t("save_changes")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
