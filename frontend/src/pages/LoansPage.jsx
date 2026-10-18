import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
import { Package, Search } from "lucide-react";
import { canWrite } from "../lib/roles";
import { fmtDateTime } from "../components/loans/LoanForms";
import LoanDashboard from "../components/loans/LoanDashboard";

export const STATUS_STYLE = {
  pending_supervisor: "bg-amber-50 text-amber-700 border-amber-200",
  pending_ict: "bg-amber-50 text-amber-700 border-amber-200",
  submitted: "bg-amber-50 text-amber-700 border-amber-200",
  approved: "bg-blue-50 text-blue-700 border-blue-200",
  partially_approved: "bg-blue-50 text-blue-700 border-blue-200",
  in_use: "bg-emerald-50 text-emerald-700 border-emerald-200",
  completed: "bg-slate-100 text-slate-600 border-slate-200",
  rejected: "bg-rose-50 text-rose-700 border-rose-200",
  cancelled: "bg-slate-100 text-slate-500 border-slate-200",
  overdue: "bg-rose-50 text-rose-700 border-rose-300 font-medium",
  problem: "bg-rose-50 text-rose-700 border-rose-300 font-medium",
};

export function StatusBadge({ status, t }) {
  return <span className={`text-xs px-2 py-0.5 border ${STATUS_STYLE[status] || STATUS_STYLE.completed}`} data-testid="loan-status">{t(`ln_st_${status}`)}</span>;
}

const STATE_STYLE = {
  available: "text-emerald-700 bg-emerald-50 border-emerald-200",
  on_loan: "text-amber-700 bg-amber-50 border-amber-200",
  repair: "text-rose-700 bg-rose-50 border-rose-200",
  lost: "text-rose-700 bg-rose-50 border-rose-200",
  inactive: "text-slate-500 bg-slate-50 border-slate-200",
};

const EMPTY = { start_at: "", end_at: "", purpose: "", class_name: "", subject: "", use_location: "", note: "", take_home: false, terms_accepted: false, override_reason: "" };

function RequestDialog({ asset, onClose, onDone, t, canOverride }) {
  const [f, setF] = useState(EMPTY);
  const [avail, setAvail] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (patch) => setF((p) => ({ ...p, ...patch }));

  useEffect(() => {
    setF(EMPTY); setAvail(null);
  }, [asset?.id]);

  useEffect(() => {
    if (!asset || !f.start_at || !f.end_at || f.end_at <= f.start_at) { setAvail(null); return; }
    const h = setTimeout(() => {
      api.get("/loans/availability", { params: { asset_id: asset.id, start_at: f.start_at, end_at: f.end_at } })
        .then((r) => setAvail(r.data)).catch(() => setAvail(null));
    }, 300);
    return () => clearTimeout(h);
  }, [asset, f.start_at, f.end_at]);

  if (!asset) return null;
  const p = asset.policy || {};
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post("/loans", { asset_id: asset.id, ...f });
      toast.success(`${t("ln_submitted")} ${r.data.number}`);
      (r.data.warnings || []).forEach((w) => toast.message(w));
      onDone(r.data);
    } catch (e) {
      toast.error(formatErr(e));
    } finally { setBusy(false); }
  };
  return (
    <Dialog open={!!asset} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none max-w-xl max-h-[90vh] overflow-y-auto" data-testid="loan-request-dialog">
        <DialogHeader><DialogTitle>{t("ln_request_title")}: {asset.name}</DialogTitle></DialogHeader>
        <div className="text-xs text-slate-500 border border-slate-200 bg-slate-50 px-3 py-2">
          <span className="font-mono">{asset.asset_tag}</span> · {t("ln_policy_max")} {p.max_loan_days} {t("ln_days")} ·{" "}
          {p.requires_approval ? t("ln_policy_approval") : t("ln_policy_auto")} ·{" "}
          {p.can_leave_campus ? t("ln_policy_takehome_ok") : t("ln_policy_takehome_no")}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="label-mono">{t("ln_start")} *</Label>
            <Input type="datetime-local" value={f.start_at} onChange={(e) => set({ start_at: e.target.value })} className="mt-2 rounded-none" data-testid="loan-start" /></div>
          <div><Label className="label-mono">{t("ln_end")} *</Label>
            <Input type="datetime-local" value={f.end_at} onChange={(e) => set({ end_at: e.target.value })} className="mt-2 rounded-none" data-testid="loan-end" /></div>
        </div>
        {avail && (
          <div className={`text-xs px-3 py-2 border ${avail.blocked ? "border-rose-200 bg-rose-50 text-rose-700" : avail.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-rose-200 bg-rose-50 text-rose-700"}`} data-testid="loan-availability">
            {avail.blocked || (avail.ok ? t("ln_available") : t("ln_not_available"))}
            {avail.pending > 0 && !avail.blocked ? ` · ${avail.pending} ${t("ln_pending_others")}` : ""}
          </div>
        )}
        <div><Label className="label-mono">{t("ln_purpose")} *</Label>
          <Textarea rows={2} value={f.purpose} onChange={(e) => set({ purpose: e.target.value })} className="mt-2 rounded-none" data-testid="loan-purpose" /></div>
        <div className="grid grid-cols-2 gap-3">
          <div><Label className="label-mono">{t("ln_class")}</Label>
            <Input value={f.class_name} onChange={(e) => set({ class_name: e.target.value })} className="mt-2 rounded-none" /></div>
          <div><Label className="label-mono">{t("ln_subject")}</Label>
            <Input value={f.subject} onChange={(e) => set({ subject: e.target.value })} className="mt-2 rounded-none" /></div>
        </div>
        <div><Label className="label-mono">{t("ln_use_location")}</Label>
          <Input value={f.use_location} onChange={(e) => set({ use_location: e.target.value })} className="mt-2 rounded-none" /></div>
        <div><Label className="label-mono">{t("ln_note")}</Label>
          <Textarea rows={2} value={f.note} onChange={(e) => set({ note: e.target.value })} className="mt-2 rounded-none" /></div>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={f.take_home} onChange={(e) => set({ take_home: e.target.checked })} className="mt-1" data-testid="loan-takehome" />
          <span>{t("ln_take_home")}
            {f.take_home && !p.can_leave_campus && <span className="block text-xs text-amber-700">{t("ln_take_home_warn")}</span>}</span>
        </label>
        {canOverride && (
          <div><Label className="label-mono">{t("ln_override")}</Label>
            <Input value={f.override_reason} onChange={(e) => set({ override_reason: e.target.value })} placeholder={t("ln_override_hint")} className="mt-2 rounded-none" /></div>
        )}
        <label className="flex items-start gap-2 text-sm border border-slate-200 p-3">
          <input type="checkbox" checked={f.terms_accepted} onChange={(e) => set({ terms_accepted: e.target.checked })} className="mt-1" data-testid="loan-terms" />
          <span>{t("ln_terms")}</span>
        </label>
        <DialogFooter>
          <Button variant="outline" className="rounded-none" onClick={onClose}>{t("cancel")}</Button>
          <Button className="rounded-none" disabled={busy || !f.start_at || !f.end_at || !f.purpose.trim() || !f.terms_accepted} onClick={submit} data-testid="loan-submit">{t("ln_submit")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LoanTable({ rows, t, showRequester }) {
  if (!rows.length) return <div className="bg-white border border-slate-200 p-10 text-center text-sm text-slate-500">{t("ln_empty")}</div>;
  return (
    <div className="bg-white border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-slate-200 text-left">
          <th className="label-mono py-3 px-4">{t("ln_number")}</th>
          <th className="label-mono py-3 px-4">{t("ln_asset")}</th>
          {showRequester && <th className="label-mono py-3 px-4">{t("ln_requester")}</th>}
          <th className="label-mono py-3 px-4">{t("ln_period")}</th>
          <th className="label-mono py-3 px-4">{t("ln_status")}</th>
        </tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`loan-row-${r.number}`}>
            <td className="py-3 px-4 font-mono text-xs"><Link className="text-blue-700 hover:underline" to={`/loans/${r.id}`}>{r.number}</Link></td>
            <td className="py-3 px-4">{r.asset_name || "—"} <span className="font-mono text-xs text-slate-400">{r.asset_tag}</span></td>
            {showRequester && <td className="py-3 px-4">{r.requester_name}</td>}
            <td className="py-3 px-4 text-xs text-slate-600">{fmtDateTime(r.start_at)} → {fmtDateTime(r.end_at)}</td>
            <td className="py-3 px-4"><StatusBadge status={r.status} t={t} /></td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

export default function LoansPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const role = user?.role;
  const writer = canWrite(role);
  const manager = ["super_admin", "admin", "ict_admin"].includes(role);
  const viewAll = ["super_admin", "leader"].includes(role);
  const dashboard = ["super_admin", "admin", "ict_admin", "leader"].includes(role);
  const tabs = useMemo(() => [
    ...(dashboard ? [{ id: "dashboard", label: "ln_tab_dashboard" }] : []),
    ...(writer ? [{ id: "borrow", label: "ln_tab_borrow" }, { id: "mine", label: "ln_tab_mine" }] : []),
    ...(manager ? [{ id: "manage", label: "ln_tab_manage" }] : []),
    ...(viewAll ? [{ id: "all", label: "ln_tab_all" }] : []),
  ], [dashboard, writer, manager, viewAll]);
  const [tab, setTab] = useState(params.get("tab") || (params.get("asset") ? "borrow" : tabs[0]?.id) || "mine");
  const [catalog, setCatalog] = useState([]);
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [target, setTarget] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    if (tab === "dashboard") { setLoading(false); return; }
    if (tab === "borrow") {
      api.get("/loans/assets", { params: { search: search || undefined, category: category === "all" ? undefined : category } })
        .then((r) => setCatalog(r.data)).catch((e) => toast.error(formatErr(e))).finally(() => setLoading(false));
    } else {
      api.get("/loans", { params: { scope: tab, status: statusFilter === "all" ? undefined : statusFilter } })
        .then((r) => setRows(r.data)).catch((e) => toast.error(formatErr(e))).finally(() => setLoading(false));
    }
  }, [tab, search, category, statusFilter]);

  useEffect(() => { load(); }, [load]);

  // /loans?asset=<id> (from the asset page) opens the request form for that asset
  useEffect(() => {
    const aid = params.get("asset");
    if (aid && catalog.length) {
      const a = catalog.find((c) => c.id === aid);
      if (a) { setTarget(a); params.delete("asset"); setParams(params, { replace: true }); }
    }
  }, [catalog, params, setParams]);

  const categories = useMemo(() => [...new Set(catalog.map((c) => c.category))], [catalog]);

  return (
    <div className="p-6 lg:p-10 max-w-[1400px] mx-auto" data-testid="loans-page">
      <div className="label-mono mb-2">{t("ln_kicker")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">{t("ln_title")}</h1>
      <p className="text-sm text-slate-500 mt-2 max-w-2xl">{t("ln_subtitle")}</p>

      <div className="flex gap-1 border-b border-slate-200 mt-6 mb-6 overflow-x-auto">
        {tabs.map((x) => (
          <button key={x.id} onClick={() => setTab(x.id)} data-testid={`loan-tab-${x.id}`}
            className={`px-4 py-2 text-sm border-b-2 -mb-px whitespace-nowrap ${tab === x.id ? "border-slate-900 text-slate-900 font-medium" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {t(x.label)}
          </button>))}
      </div>

      {tab === "dashboard" ? <LoanDashboard /> : tab === "borrow" ? (
        <>
          <div className="flex gap-3 flex-wrap mb-5">
            <div className="relative flex-1 min-w-[220px] max-w-md">
              <Search className="w-4 h-4 absolute left-3 top-3 text-slate-400" />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("ln_search")} className="pl-9 rounded-none" data-testid="loan-search" />
            </div>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger className="w-52 rounded-none"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("ln_all_categories")}</SelectItem>
                {categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {!loading && catalog.length === 0 && <div className="bg-white border border-slate-200 p-10 text-center text-sm text-slate-500">{t("ln_no_borrowable")}</div>}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {catalog.map((a) => (
              <div key={a.id} className="bg-white border border-slate-200 p-5 flex flex-col" data-testid={`loan-asset-${a.asset_tag}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-slate-900 truncate">{a.name}</div>
                    <div className="text-xs text-slate-500">{[a.brand, a.model].filter(Boolean).join(" ") || a.category}</div>
                    <div className="font-mono text-xs text-slate-400 mt-1">{a.asset_tag}</div>
                  </div>
                  <span className={`text-xs px-2 py-0.5 border whitespace-nowrap ${STATE_STYLE[a.state]}`}>{t(`ln_state_${a.state}`)}</span>
                </div>
                {a.on_loan && <div className="text-xs text-slate-500 mt-2">{t("ln_with")} {a.on_loan.requester_name} · {t("ln_until")} {fmtDateTime(a.on_loan.end_at)}</div>}
                <div className="text-xs text-slate-500 mt-2">{a.location}{a.storage_slot ? ` · ${a.storage_slot}` : ""}</div>
                <Button className="rounded-none mt-4" variant="outline" disabled={!["available", "on_loan"].includes(a.state)}
                  onClick={() => setTarget(a)} data-testid={`loan-request-${a.asset_tag}`}>
                  <Package className="w-4 h-4 mr-2" strokeWidth={1.75} /> {t("ln_request")}
                </Button>
              </div>))}
          </div>
        </>
      ) : (
        <>
          <div className="mb-4">
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-60 rounded-none" data-testid="loan-status-filter"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("ln_all_statuses")}</SelectItem>
                {Object.keys(STATUS_STYLE).map((s) => <SelectItem key={s} value={s}>{t(`ln_st_${s}`)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <LoanTable rows={rows} t={t} showRequester={tab !== "mine"} />
        </>
      )}

      <RequestDialog asset={target} t={t} canOverride={manager} onClose={() => setTarget(null)}
        onDone={() => { setTarget(null); setTab("mine"); }} />
    </div>
  );
}
