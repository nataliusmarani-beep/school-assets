import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { formatErr } from "../../lib/api";
import { useLang } from "../../context/LangContext";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";
import { toast } from "sonner";
import { canWrite } from "../../lib/roles";
import { fileSrc, fmtDateTime } from "./LoanForms";

const tri = (v) => (v === null || v === undefined ? "" : v ? "1" : "0");
const fromTri = (v) => (v === "" ? null : v === "1");

function TriSelect({ value, onChange, t, testid }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} data-testid={testid}
      className="mt-2 w-full border border-slate-200 bg-white px-3 py-2 text-sm rounded-none">
      <option value="">{t("ln_use_category_rule")}</option>
      <option value="1">{t("ln_yes")}</option>
      <option value="0">{t("ln_no")}</option>
    </select>
  );
}

export default function LoanSettingsCard({ assetId }) {
  const { t } = useLang();
  const { user } = useAuth();
  const [s, setS] = useState(null);
  const [form, setForm] = useState(null);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.get(`/loans/assets/${assetId}/settings`).then((r) => {
      setS(r.data);
      setForm({
        borrowable: !!r.data.borrowable, loan_type: r.data.loan_type || "item", accessories: (r.data.accessories || []).join("\n"),
        storage_slot: r.data.storage_slot || "", max_loan_days: r.data.max_loan_days ?? "",
        requires_approval: tri(r.data.requires_approval), can_leave_campus: tri(r.data.can_leave_campus),
      });
    }).catch((e) => toast.error(formatErr(e)));
    api.get(`/loans/assets/${assetId}/history`).then((r) => setHistory(r.data)).catch(() => setHistory([]));
  };
  useEffect(load, [assetId]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!s || !form) return <div className="text-sm text-slate-400">…</div>;
  const p = s.policy || {};
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/loans/assets/${assetId}/settings`, {
        borrowable: form.borrowable, loan_type: form.loan_type,
        accessories: form.accessories.split("\n"), storage_slot: form.storage_slot,
        max_loan_days: form.max_loan_days === "" ? null : Number(form.max_loan_days),
        requires_approval: fromTri(form.requires_approval), can_leave_campus: fromTri(form.can_leave_campus),
      });
      toast.success(t("ln_saved"));
      load();
    } catch (e) { toast.error(formatErr(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-6" data-testid="loan-settings-card">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm">
          {s.borrowable ? <span className="text-emerald-700">{t("ln_borrowable_yes")}</span> : <span className="text-slate-500">{t("ln_borrowable_no")}</span>}
          <div className="text-xs text-slate-500 mt-1">{t("ln_policy_max")} {s.max_loan_days ?? p.max_loan_days} {t("ln_days")} ·{" "}
            {(s.requires_approval ?? p.requires_approval) ? t("ln_policy_approval") : t("ln_policy_auto")} ·{" "}
            {(s.can_leave_campus ?? p.can_leave_campus) ? t("ln_policy_takehome_ok") : t("ln_policy_takehome_no")}</div>
        </div>
        {s.borrowable && canWrite(user?.role) && (
          <Link to={`/loans?asset=${assetId}`}><Button variant="outline" className="rounded-none" data-testid="loan-request-button">{t("ln_request")}</Button></Link>)}
      </div>

      {s.can_edit && (
        <div className="border border-slate-200 p-4 space-y-4">
          <div className="label-mono">{t("ln_settings")}</div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.borrowable} onChange={(e) => setForm({ ...form, borrowable: e.target.checked })} data-testid="loan-borrowable" />
            {t("ln_borrowable")}
          </label>
          <div className="grid sm:grid-cols-2 gap-4">
            <div><Label className="label-mono">{t("ln_storage_slot")}</Label>
              <Input value={form.storage_slot} onChange={(e) => setForm({ ...form, storage_slot: e.target.value })} className="mt-2 rounded-none" /></div>
            <div><Label className="label-mono">{t("ln_max_days")}</Label>
              <Input type="number" min="1" value={form.max_loan_days} placeholder={String(p.max_loan_days ?? "")} onChange={(e) => setForm({ ...form, max_loan_days: e.target.value })} className="mt-2 rounded-none" /></div>
            <div><Label className="label-mono">{t("ln_needs_approval")}</Label>
              <TriSelect value={form.requires_approval} onChange={(v) => setForm({ ...form, requires_approval: v })} t={t} /></div>
            <div><Label className="label-mono">{t("ln_can_leave")}</Label>
              <TriSelect value={form.can_leave_campus} onChange={(v) => setForm({ ...form, can_leave_campus: v })} t={t} /></div>
          </div>
          <div><Label className="label-mono">{t("ln_accessories_standard")}</Label>
            <Textarea rows={3} value={form.accessories} onChange={(e) => setForm({ ...form, accessories: e.target.value })} placeholder={t("ln_accessories_hint")} className="mt-2 rounded-none" data-testid="loan-accessories" /></div>
          <Button className="rounded-none" disabled={busy} onClick={save} data-testid="loan-settings-save">{t("save_changes")}</Button>
        </div>
      )}

      <div>
        <div className="label-mono mb-2">{t("ln_history")}</div>
        {history.length === 0 ? <div className="text-sm text-slate-500">{t("ln_history_empty")}</div> : (
          <ol className="space-y-3">{history.map((h) => (
            <li key={h.id} className="border border-slate-200 p-3 text-sm">
              <div className="flex justify-between flex-wrap gap-2">
                <span><Link to={`/loans/${h.booking_id}`} className="font-mono text-xs text-blue-700 hover:underline">{h.number}</Link> · {h.user_label || h.requester_name}</span>
                <span className="text-xs text-slate-500">{fmtDateTime(h.out_at)} → {fmtDateTime(h.in_at)} · {t(`ln_unit_${h.status}`)}</span>
              </div>
              {(h.pre_photo || h.post_photo) && (
                <div className="flex gap-3 mt-2">
                  {[h.pre_photo, h.post_photo].map((ph, i) => ph ? <a key={i} href={fileSrc(ph)} target="_blank" rel="noreferrer"><img src={fileSrc(ph)} alt="" className="h-16 w-24 object-cover border border-slate-200" /></a> : null)}
                </div>)}
              {h.in_check?.note && <div className="text-xs text-rose-600 mt-1">{h.in_check.note}</div>}
            </li>))}</ol>)}
      </div>
    </div>
  );
}
