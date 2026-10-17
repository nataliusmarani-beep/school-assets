import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { fmtCurrency, fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { isAdminRole } from "../lib/roles";
import { ownerName } from "../lib/format";
import { Button } from "../components/ui/button";
import HandoverDialog from "../components/assets/HandoverDialog";
import { toast } from "sonner";
import { ArrowLeft, ArrowRightLeft } from "lucide-react";

export default function ClassroomDetailPage() {
  const { id } = useParams();
  const { t } = useLang();
  const { user } = useAuth();
  const isAdmin = isAdminRole(user?.role);
  const [room, setRoom] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hoOpen, setHoOpen] = useState(false);
  const [sel, setSel] = useState(new Set());

  const load = useCallback(() => api.get(`/classrooms/${id}`).then((r) => setRoom(r.data))
    .catch((e) => toast.error(formatErr(e))).finally(() => setLoading(false)), [id]);
  useEffect(() => { load(); }, [load]);

  const cancelHandover = async () => {
    if (!window.confirm(t("cr_cancel_confirm"))) return;
    try { await api.post(`/classrooms/${id}/handover/cancel`); toast.success(t("cr_cancelled")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };
  const setKind = async (kind) => {
    try {
      const r = await api.post(`/classrooms/${id}/set-kind`, { asset_ids: [...sel], kind });
      toast.success(t("cr_kind_changed").replace("{n}", r.data.changed));
      setSel(new Set()); load();
    } catch (e) { toast.error(formatErr(e)); }
  };
  const resolve = async (ids) => {
    try { await api.post(`/classrooms/${id}/resolve-discrepancy`, { asset_ids: ids }); toast.success(t("cr_resolved")); load(); }
    catch (e) { toast.error(formatErr(e)); }
  };

  if (loading) return <div className="text-slate-500">{t("loading")}</div>;
  if (!room) return null;
  const h = room.handover;
  const discrepancies = room.assets.filter((a) => a.handover_flag === "discrepancy");

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="classroom-detail">
      <Link to="/classrooms" className="text-sm text-slate-500 hover:text-slate-900 inline-flex items-center gap-1 mb-4">
        <ArrowLeft className="w-4 h-4" /> {t("cr_back")}
      </Link>
      <div className="flex items-end justify-between gap-4 flex-wrap mb-6">
        <div>
          <div className="label-mono mb-2">{t(`cr_type_${room.room_type}`)} · {room.campus || "—"}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-1">{room.name}</h1>
          <p className="text-sm text-slate-500">
            {t("cr_responsible")}: <span className="text-slate-800 font-medium" data-testid="classroom-responsible">
              {room.responsible_name ? ownerName(room.responsible_name) : t("cr_none_resp")}</span>
          </p>
        </div>
        {isAdmin && !h && (
          <Button onClick={() => setHoOpen(true)} className="rounded-none bg-slate-900" data-testid="classroom-handover-btn">
            <ArrowRightLeft className="w-4 h-4 mr-2" strokeWidth={1.75} /> {t("cr_handover_btn")}
          </Button>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[["cr_class_assets", room.class_count], ["cr_personal_assets", room.personal_count],
          ["cr_value", fmtCurrency(room.purchase_value)], ["cr_discrepancy", room.discrepancy_count]].map(([k, v]) => (
          <div key={k} className="bg-white border border-slate-200 p-5">
            <div className="label-mono">{t(k)}</div>
            <div className="font-display text-2xl font-semibold text-slate-900 mt-2">{v}</div>
          </div>
        ))}
      </div>

      {h && (
        <section className="bg-white border border-amber-300 p-5 mb-6" data-testid="classroom-handover-panel">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="font-display text-lg text-slate-900">{t("cr_handover_title")}</div>
              <div className="text-sm text-slate-600 mt-1">
                {ownerName(h.from_name) || t("cr_none_resp")} → <span className="font-medium text-slate-900">{ownerName(h.to_name)}</span>
                {" · "}{t("cr_handover_progress").replace("{c}", h.checked).replace("{t}", h.total)}
              </div>
              <div className="text-xs text-slate-500 mt-1">{t("cr_handover_note")}</div>
            </div>
            {isAdmin && <Button variant="outline" className="rounded-none" onClick={cancelHandover} data-testid="classroom-handover-cancel">{t("cr_cancel_handover")}</Button>}
          </div>
          <div className="h-2 bg-slate-100 mt-4"><div className="h-2 bg-amber-500" style={{ width: `${h.total ? (h.checked / h.total) * 100 : 0}%` }} /></div>
        </section>
      )}

      {discrepancies.length > 0 && (
        <section className="bg-white border border-rose-200 p-5 mb-6" data-testid="classroom-discrepancies">
          <div className="flex items-center justify-between gap-4 mb-3">
            <div className="font-display text-lg text-rose-800">{t("cr_discrepancy")} ({discrepancies.length})</div>
            {isAdmin && <Button size="sm" variant="outline" className="rounded-none" onClick={() => resolve(discrepancies.map((a) => a.id))}>{t("cr_resolve_all")}</Button>}
          </div>
          <p className="text-sm text-slate-600 mb-3">{t("cr_discrepancy_hint")}</p>
          <div className="divide-y divide-slate-100 text-sm">
            {discrepancies.map((a) => (
              <div key={a.id} className="py-2 flex items-center gap-3 flex-wrap">
                <Link to={`/assets/${a.id}`} className="font-medium text-slate-900 hover:text-blue-800">{a.name}</Link>
                <span className="font-mono text-xs text-slate-500">({a.asset_tag})</span>
                <span className="text-xs text-slate-500 flex-1">{t("cr_still_with")} {ownerName(a.assigned_to_name) || "—"}</span>
                {isAdmin && <Button size="sm" variant="outline" className="rounded-none" onClick={() => resolve([a.id])}>{t("cr_resolve")}</Button>}
              </div>
            ))}
          </div>
        </section>
      )}

      {isAdmin && sel.size > 0 && (
        <div className="mb-3 flex items-center gap-4 flex-wrap bg-blue-50 border border-blue-200 px-4 py-2.5 text-sm" data-testid="classroom-kind-bar">
          <span className="font-medium text-blue-900">{t("bt_selected").replace("{n}", sel.size)}</span>
          <button onClick={() => setKind("class")} className="bg-blue-800 hover:bg-blue-900 text-white px-3 py-1.5" data-testid="make-class">{t("cr_make_class")}</button>
          <button onClick={() => setKind("personal")} className="border border-slate-300 bg-white hover:bg-slate-50 px-3 py-1.5" data-testid="make-personal">{t("cr_make_personal")}</button>
          <button onClick={() => setSel(new Set())} className="text-slate-600 hover:text-slate-900">{t("bt_clear")}</button>
        </div>
      )}

      <div className="bg-white border border-slate-200 overflow-x-auto mb-8">
        <table className="w-full text-sm" data-testid="classroom-assets-table">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {isAdmin && (
                <th className="py-3 px-4 w-8">
                  <input type="checkbox" data-testid="room-select-all"
                    checked={room.assets.length > 0 && room.assets.every((a) => sel.has(a.id))}
                    onChange={(e) => setSel(e.target.checked ? new Set(room.assets.filter((a) => !a.pending_assignment).map((a) => a.id)) : new Set())} />
                </th>
              )}
              {["col_tag", "col_asset", "cr_holding", "col_assigned", "col_status"].map((k) => (
                <th key={k} className="text-left font-medium label-mono py-3 px-4">{t(k)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {room.assets.length === 0 ? (
              <tr><td colSpan={6} className="text-center text-slate-500 py-10">{t("cr_no_assets")}</td></tr>
            ) : room.assets.map((a) => (
              <tr key={a.id} className="border-b border-slate-100">
                {isAdmin && (
                  <td className="py-3 px-4">
                    <input type="checkbox" data-testid={`room-select-${a.id}`} disabled={!!a.pending_assignment} checked={sel.has(a.id)}
                      onChange={() => setSel((x) => { const n = new Set(x); n.has(a.id) ? n.delete(a.id) : n.add(a.id); return n; })} />
                  </td>
                )}
                <td className="py-3 px-4 font-mono text-xs text-slate-600"><Link to={`/assets/${a.id}`} className="hover:text-blue-800">{a.asset_tag}</Link></td>
                <td className="py-3 px-4"><Link to={`/assets/${a.id}`} className="font-medium text-slate-900 hover:text-blue-800">{a.name}</Link></td>
                <td className="py-3 px-4">
                  <span className={`inline-flex px-2 py-0.5 text-xs border ${a.is_class_asset ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-slate-50 text-slate-600 border-slate-200"}`}>
                    {a.is_class_asset ? t("cr_held_class") : t("cr_held_personal")}
                  </span>
                </td>
                <td className="py-3 px-4 text-slate-700">
                  {ownerName(a.assigned_to_name) || "—"}
                  {a.pending_assignment && (
                    <div className="mt-1"><span className="inline-flex px-2 py-0.5 text-xs border bg-amber-50 text-amber-800 border-amber-300">
                      {t("awaiting_confirmation")} · {ownerName(a.pending_assignment.to_name)}</span></div>
                  )}
                  {a.handover_flag === "discrepancy" && (
                    <div className="mt-1"><span className="inline-flex px-2 py-0.5 text-xs border bg-rose-50 text-rose-700 border-rose-200">{t("cr_discrepancy")}</span></div>
                  )}
                </td>
                <td className="py-3 px-4 text-slate-700">{a.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {room.history.length > 0 && (
        <section className="bg-white border border-slate-200 p-5" data-testid="classroom-history">
          <div className="font-display text-lg text-slate-900 mb-3">{t("cr_history")}</div>
          <div className="divide-y divide-slate-100 text-sm">
            {room.history.map((x) => (
              <div key={x.id} className="py-2 flex gap-3 flex-wrap items-center">
                <span className="text-slate-500 w-28">{fmtDate(x.created_at)}</span>
                <span className="flex-1">{ownerName(x.from_name) || t("cr_none_resp")} → <span className="font-medium">{ownerName(x.to_name)}</span></span>
                <span className="text-xs text-slate-500">
                  {x.status === "completed" ? t("cr_hist_done").replace("{a}", x.accepted_count).replace("{d}", x.discrepancy_count)
                    : x.status === "cancelled" ? t("cr_hist_cancelled") : t("cr_hist_pending")}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {isAdmin && <HandoverDialog open={hoOpen} onOpenChange={setHoOpen} t={t} classroomId={id} onDone={load} />}
    </div>
  );
}
