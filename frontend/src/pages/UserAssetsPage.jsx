import { useCallback, useEffect, useMemo, useState } from "react";
import api, { fmtCurrency, fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import AssetBundle from "../components/assets/AssetBundle";
import HandoverDialog from "../components/assets/HandoverDialog";
import { toast } from "sonner";
import { Users, Boxes, PackageX, Clock, ArrowRightLeft } from "lucide-react";
import { ownerName } from "../lib/format";

function Kpi({ label, value, icon: Icon, testid }) {
  return (
    <div className="bg-white border border-slate-200 p-6" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div className="label-mono">{label}</div>
        <Icon className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
      </div>
      <div className="font-display text-3xl font-semibold text-slate-900 mt-3">{value}</div>
    </div>
  );
}

export default function UserAssetsPage() {
  const { t } = useLang();
  const [data, setData] = useState(null);
  const [pending, setPending] = useState([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [handoverOpen, setHandoverOpen] = useState(false);

  const load = useCallback(() => {
    api.get("/dashboard/users").then((r) => setData(r.data)).catch((e) => toast.error(formatErr(e)));
    api.get("/assignments", { params: { status: "pending" } }).then((r) => setPending(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    api.get(`/users/${selected}/assets`).then((r) => setDetail(r.data)).catch((e) => toast.error(formatErr(e)));
  }, [selected, data]);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data?.users || []).filter((u) => !s || u.name.toLowerCase().includes(s)
      || (u.department || "").toLowerCase().includes(s) || (u.email || "").toLowerCase().includes(s));
  }, [data, q]);

  const cancel = async (id) => {
    try { await api.put(`/assignments/${id}/cancel`); toast.success(t("ua_cancelled_toast")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };

  if (!data) return <div className="p-10 text-sm text-slate-400">{t("loading")}</div>;
  const { totals } = data;

  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto" data-testid="user-assets-page">
      <div className="flex items-end justify-between gap-4 flex-wrap mb-8">
        <div>
          <div className="label-mono mb-2">{t("ma_eyebrow")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-1">{t("ua_title")}</h1>
          <p className="text-sm text-slate-500 max-w-2xl">{t("ua_subtitle")}</p>
        </div>
        <Button onClick={() => setHandoverOpen(true)} className="rounded-none bg-slate-900" data-testid="handover-button">
          <ArrowRightLeft className="w-4 h-4 mr-2" strokeWidth={1.75} /> {t("ua_handover_btn")}
        </Button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Kpi testid="ua-kpi-users" label={t("ua_kpi_users")} value={totals.users} icon={Users} />
        <Kpi testid="ua-kpi-held" label={t("ua_kpi_with_users")} value={totals.assets_with_users} icon={Boxes} />
        <Kpi testid="ua-kpi-unassigned" label={t("ua_kpi_unassigned")} value={totals.unassigned_assets} icon={PackageX} />
        <Kpi testid="ua-kpi-pending" label={t("ua_kpi_pending")} value={totals.pending} icon={Clock} />
      </div>

      {pending.length > 0 && (
        <section className="bg-white border border-amber-300 p-6 mb-8" data-testid="admin-pending">
          <h2 className="font-display text-xl font-medium text-slate-900 mb-4">{t("ua_pending_list")} ({pending.length})</h2>
          <div className="divide-y divide-slate-100">
            {pending.map((p) => (
              <div key={p.id} className="py-2.5 flex items-center gap-3 flex-wrap text-sm" data-testid="admin-pending-row">
                <div className="flex-1 min-w-[200px]">
                  <span className="font-medium text-slate-900">{p.asset_name}</span>
                  <span className="font-mono text-xs text-slate-500 ml-2">({p.asset_tag})</span>
                  <div className="text-xs text-slate-500">
                    {(ownerName(p.from_name) || t("ma_new_asset"))} → <span className="text-slate-800 font-medium">{ownerName(p.to_name)}</span> · {fmtDate(p.created_at)}
                  </div>
                </div>
                <span className="text-xs px-2 py-0.5 border bg-slate-50 text-slate-600 border-slate-200">
                  {p.kind === "class" ? t("ma_kind_class") : t("ma_kind_personal")}
                </span>
                <Button size="sm" variant="outline" className="rounded-none" onClick={() => cancel(p.id)}>{t("ua_cancel")}</Button>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="mb-3 max-w-sm">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("ua_search")} className="rounded-none" data-testid="ua-search" />
      </div>
      <div className="overflow-x-auto border border-slate-200 bg-white mb-8">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left label-mono bg-slate-50">
              <th className="px-4 py-3">{t("ua_col_user")}</th>
              <th className="px-4 py-3 text-right">{t("ua_col_personal")}</th>
              <th className="px-4 py-3 text-right">{t("ua_col_class")}</th>
              <th className="px-4 py-3 text-right">{t("ua_col_pending")}</th>
              <th className="px-4 py-3 text-right">{t("ua_col_value")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-500">{t("ua_none")}</td></tr>}
            {rows.map((u) => (
              <tr key={u.id} onClick={() => setSelected(u.id)} data-testid="ua-row"
                className={`border-t border-slate-100 cursor-pointer hover:bg-slate-50 ${selected === u.id ? "bg-blue-50/60" : ""}`}>
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900">{u.name}</div>
                  <div className="text-xs text-slate-500">{[u.department, u.campus].filter(Boolean).join(" · ") || u.email}</div>
                </td>
                <td className="px-4 py-3 text-right font-mono">{u.personal_count}</td>
                <td className="px-4 py-3 text-right font-mono">{u.class_count}</td>
                <td className="px-4 py-3 text-right font-mono">
                  {u.pending_count > 0 ? <span className="text-amber-700 font-semibold">{u.pending_count}</span> : 0}
                </td>
                <td className="px-4 py-3 text-right font-mono">{fmtCurrency(u.book_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section data-testid="ua-detail">
        {!detail ? (
          <div className="text-sm text-slate-500">{t("ua_detail_hint")}</div>
        ) : (
          <>
            <h2 className="font-display text-xl font-medium text-slate-900 mb-4">
              {t("ua_detail_title").replace("{name}", detail.user.name)}
            </h2>
            <AssetBundle bundle={detail} t={t} testid="ua-bundle" />
          </>
        )}
      </section>

      <HandoverDialog open={handoverOpen} onOpenChange={setHandoverOpen} t={t} onDone={load} />
    </div>
  );
}
