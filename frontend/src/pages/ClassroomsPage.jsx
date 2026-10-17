import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtCurrency, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { isAdminRole } from "../lib/roles";
import { ownerName } from "../lib/format";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";

const CAMPUSES = ["YPJ Kuala Kencana", "YPJ Tembagapura"];
const TYPES = ["kelas", "lab", "kantor", "lainnya"];
const SEL = "mt-2 w-full h-10 px-3 text-sm border border-slate-300 bg-white rounded-none";

export default function ClassroomsPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const isAdmin = isAdminRole(user?.role);
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [campus, setCampus] = useState("all");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", campus: CAMPUSES[0], room_type: "kelas" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.get("/classrooms").then((r) => setRooms(r.data))
    .catch((e) => toast.error(formatErr(e))).finally(() => setLoading(false)), []);
  useEffect(() => { load(); }, [load]);

  const shown = useMemo(() => rooms.filter((r) =>
    (campus === "all" || r.campus === campus) &&
    (!q.trim() || `${r.name} ${r.responsible_name || ""}`.toLowerCase().includes(q.trim().toLowerCase()))), [rooms, q, campus]);

  const create = async () => {
    setBusy(true);
    try {
      await api.post("/classrooms", form);
      toast.success(t("cr_created"));
      setOpen(false); setForm({ ...form, name: "" });
      load();
    } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="classrooms-page">
      <div className="flex items-end justify-between gap-4 flex-wrap mb-8">
        <div>
          <div className="label-mono mb-2">{t("cr_eyebrow")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-1">{t("cr_title")}</h1>
          <p className="text-sm text-slate-500 max-w-2xl">{t("cr_subtitle")}</p>
        </div>
        {isAdmin && (
          <Button onClick={() => setOpen(true)} className="rounded-none bg-slate-900" data-testid="classroom-add">
            <Plus className="w-4 h-4 mr-2" strokeWidth={1.75} /> {t("cr_add")}
          </Button>
        )}
      </div>

      <div className="bg-white border border-slate-200 p-4 mb-4 flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("cr_search")} className="pl-9 rounded-none" data-testid="classroom-search" />
        </div>
        <select value={campus} onChange={(e) => setCampus(e.target.value)} className="h-10 px-3 text-sm border border-slate-300 bg-white rounded-none">
          <option value="all">{t("all_campuses")}</option>
          {CAMPUSES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div className="bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm" data-testid="classrooms-table">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {["cr_name", "cr_campus", "cr_type", "cr_responsible", "cr_class_assets", "cr_personal_assets", "cr_value", "cr_status"].map((k) => (
                <th key={k} className="text-left font-medium label-mono py-3 px-4">{t(k)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="text-center text-slate-500 py-12">{t("loading")}</td></tr>
            ) : shown.length === 0 ? (
              <tr><td colSpan={8} className="text-center text-slate-500 py-12">{t("cr_empty")}</td></tr>
            ) : shown.map((r) => (
              <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`classroom-row-${r.id}`}>
                <td className="py-3 px-4"><Link to={`/classrooms/${r.id}`} className="font-medium text-slate-900 hover:text-blue-800">{r.name}</Link></td>
                <td className="py-3 px-4 text-slate-700">{r.campus || "—"}</td>
                <td className="py-3 px-4 text-slate-700">{t(`cr_type_${r.room_type}`)}</td>
                <td className="py-3 px-4 text-slate-700">{r.responsible_name ? ownerName(r.responsible_name) : <span className="text-slate-400">{t("cr_none_resp")}</span>}</td>
                <td className="py-3 px-4 text-slate-700">{r.class_count}</td>
                <td className="py-3 px-4 text-slate-700">{r.personal_count}</td>
                <td className="py-3 px-4 text-slate-700">{fmtCurrency(r.purchase_value)}</td>
                <td className="py-3 px-4 space-y-1">
                  {r.handover && (
                    <span className="inline-flex px-2 py-0.5 text-xs border bg-amber-50 text-amber-800 border-amber-300">
                      {t("cr_handover_short").replace("{n}", r.handover.checked).replace("{t}", r.handover.total)}
                    </span>
                  )}
                  {r.discrepancy_count > 0 && (
                    <span className="inline-flex px-2 py-0.5 text-xs border bg-rose-50 text-rose-700 border-rose-200">
                      {t("cr_discrepancy")} · {r.discrepancy_count}
                    </span>
                  )}
                  {!r.handover && r.discrepancy_count === 0 && <span className="text-slate-400">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="rounded-none" data-testid="classroom-dialog">
          <DialogHeader><DialogTitle>{t("cr_create_title")}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="label-mono">{t("cr_name")}</label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-2 rounded-none" data-testid="classroom-name" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label-mono">{t("cr_campus")}</label>
                <select value={form.campus} onChange={(e) => setForm({ ...form, campus: e.target.value })} className={SEL}>
                  {CAMPUSES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="label-mono">{t("cr_type")}</label>
                <select value={form.room_type} onChange={(e) => setForm({ ...form, room_type: e.target.value })} className={SEL}>
                  {TYPES.map((k) => <option key={k} value={k}>{t(`cr_type_${k}`)}</option>)}
                </select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button disabled={busy || !form.name.trim()} onClick={create} className="rounded-none bg-slate-900" data-testid="classroom-save">{t("cr_save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
