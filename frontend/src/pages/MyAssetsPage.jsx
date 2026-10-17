import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtCurrency, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import AssetBundle from "../components/assets/AssetBundle";
import { toast } from "sonner";
import { Boxes, Users, Clock, Wallet, PackageCheck } from "lucide-react";
import { ownerName } from "../lib/format";

function Kpi({ label, value, icon: Icon, testid, accent }) {
  return (
    <div className={`bg-white border p-6 ${accent ? "border-amber-300" : "border-slate-200"}`} data-testid={testid}>
      <div className="flex items-start justify-between">
        <div className="label-mono">{label}</div>
        <Icon className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
      </div>
      <div className="font-display text-3xl font-semibold text-slate-900 mt-3">{value}</div>
    </div>
  );
}

const daysSince = (iso) => Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));

export default function MyAssetsPage() {
  const { t } = useLang();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState(new Set());
  const [rejectIds, setRejectIds] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    return api.get("/my/assets")
      .then((r) => { setData(r.data); setSel(new Set()); })
      .catch((e) => toast.error(formatErr(e)))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const respond = async (ids, action, why = "") => {
    setBusy(true);
    try {
      const r = await api.post("/assignments/respond", { ids, action, reason: why });
      const msg = action === "accept" ? t("ma_accepted_toast") : t("ma_rejected_toast");
      toast.success(msg.replace("{n}", r.data.done));
      setRejectIds(null); setReason("");
      await load();
      window.dispatchEvent(new Event("assignments-changed"));
    } catch (e) { toast.error(formatErr(e)); }
    finally { setBusy(false); }
  };

  if (loading || !data) return <div className="p-10 text-sm text-slate-400">{t("loading")}</div>;
  const { summary, pending } = data;
  const pendingIds = pending.map((p) => p.id);
  const selected = [...sel].filter((id) => pendingIds.includes(id));

  return (
    <div className="p-6 lg:p-10 max-w-[1100px] mx-auto" data-testid="my-assets-page">
      <div className="label-mono mb-2">{t("ma_eyebrow")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-1">{t("ma_title")}</h1>
      <p className="text-sm text-slate-500 mb-8 max-w-2xl">{t("ma_subtitle")}</p>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Kpi testid="ma-kpi-personal" label={t("ma_kpi_personal")} value={summary.personal_count} icon={Boxes} />
        <Kpi testid="ma-kpi-class" label={t("ma_kpi_class")} value={summary.class_count} icon={Users} />
        <Kpi testid="ma-kpi-pending" label={t("ma_kpi_pending")} value={summary.pending_count} icon={Clock} accent={summary.pending_count > 0} />
        <Kpi testid="ma-kpi-value" label={t("ma_kpi_value")} value={fmtCurrency(summary.book_value)} icon={Wallet} />
      </div>

      {pending.length > 0 && (
        <section className="bg-amber-50/60 border border-amber-300 p-6 mb-8" data-testid="pending-section">
          <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
            <div>
              <h2 className="font-display text-xl font-medium text-slate-900">{t("ma_pending_title")}</h2>
              <p className="text-sm text-slate-600 mt-1 max-w-xl">{t("ma_pending_hint")}</p>
            </div>
            <div className="flex gap-2 flex-wrap">
              {selected.length > 0 && (
                <>
                  <Button disabled={busy} onClick={() => respond(selected, "accept")} className="rounded-none bg-emerald-700 hover:bg-emerald-800" data-testid="accept-selected">
                    {t("ma_accept_selected").replace("{n}", selected.length)}
                  </Button>
                  <Button disabled={busy} variant="outline" onClick={() => setRejectIds(selected)} className="rounded-none" data-testid="reject-selected">
                    {t("ma_reject_selected").replace("{n}", selected.length)}
                  </Button>
                </>
              )}
              <Button disabled={busy} onClick={() => respond(pendingIds, "accept")} className="rounded-none bg-slate-900" data-testid="accept-all">
                <PackageCheck className="w-4 h-4 mr-2" strokeWidth={1.75} /> {t("ma_accept_all")}
              </Button>
            </div>
          </div>
          <div className="space-y-2">
            {pending.map((p) => (
              <div key={p.id} className="bg-white border border-slate-200 p-4 flex items-center gap-4 flex-wrap" data-testid="pending-row">
                <input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} className="w-4 h-4" aria-label={p.asset_name} />
                <div className="flex-1 min-w-[220px]">
                  <Link to={`/assets/${p.asset_id}`} className="font-medium text-slate-900 hover:text-blue-700">{p.asset_name}</Link>
                  <span className="font-mono text-xs text-slate-500 ml-2">({p.asset_tag})</span>
                  <div className="text-xs text-slate-500 mt-1 flex gap-x-3 gap-y-1 flex-wrap">
                    {p.location && <span>{p.location}</span>}
                    <span>{t("ma_by")} <span className="text-slate-700">{p.created_by_name}</span></span>
                    <span>{t("ma_from")} <span className="text-slate-700">{ownerName(p.from_name) || t("ma_new_asset")}</span></span>
                    <span>{t("ma_waiting_days").replace("{n}", daysSince(p.created_at))}</span>
                  </div>
                  {p.note && <div className="text-xs text-slate-500 italic mt-1">"{p.note}"</div>}
                </div>
                <span className={`text-xs px-2 py-0.5 border ${p.kind === "class" ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-slate-50 text-slate-600 border-slate-200"}`}>
                  {p.kind === "class" ? t("ma_kind_class") : t("ma_kind_personal")}
                </span>
                <div className="flex gap-2">
                  <Button size="sm" disabled={busy} onClick={() => respond([p.id], "accept")} className="rounded-none bg-emerald-700 hover:bg-emerald-800" data-testid="accept-one">
                    {t("ma_accept")}
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => setRejectIds([p.id])} className="rounded-none" data-testid="reject-one">
                    {t("ma_reject")}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <AssetBundle bundle={data} t={t} />

      <Dialog open={!!rejectIds} onOpenChange={(o) => { if (!o) { setRejectIds(null); setReason(""); } }}>
        <DialogContent className="rounded-none">
          <DialogHeader><DialogTitle>{t("ma_reject_title")}</DialogTitle></DialogHeader>
          <label className="label-mono">{t("ma_reject_reason")}</label>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className="rounded-none"
            placeholder={t("ma_reject_placeholder")} data-testid="reject-reason" />
          <DialogFooter>
            <Button disabled={busy || reason.trim().length < 3} onClick={() => respond(rejectIds, "reject", reason.trim())}
              className="rounded-none bg-rose-700 hover:bg-rose-800" data-testid="reject-confirm">
              {t("ma_reject")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
