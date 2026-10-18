import { useState } from "react";
import api, { formatErr } from "../../lib/api";
import { useLang } from "../../context/LangContext";
import { useAuth } from "../../context/AuthContext";
import { toast } from "sonner";
import { FileSpreadsheet } from "lucide-react";
import { campusLabel } from "../../lib/campus";
import { fmtDateTime } from "./LoanForms";

const thisMonth = () => new Date().toISOString().slice(0, 7);

async function downloadXlsx(url, params, fallback) {
  const res = await api.get(url, { params: { ...params, format: "xlsx" }, responseType: "blob" });
  const m = (res.headers["content-disposition"] || "").match(/filename="?([^"]+)"?/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(res.data);
  a.download = m ? m[1] : fallback;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function LoanReports() {
  const { t } = useLang();
  const { user } = useAuth();
  const [month, setMonth] = useState(thisMonth());
  const [campus, setCampus] = useState("");
  const [range, setRange] = useState({ from: `${thisMonth()}-01`, to: new Date().toISOString().slice(0, 10) });
  const [usage, setUsage] = useState(null);
  const [incidents, setIncidents] = useState(null);
  const canPickCampus = user?.role !== "ict_admin";
  const cp = campus ? { campus } : {};

  const run = async (fn) => { try { await fn(); } catch (e) { toast.error(formatErr(e)); } };
  const loadUsage = () => run(async () => setUsage((await api.get("/loans/reports/usage", { params: { month, ...cp } })).data));
  const loadIncidents = () => run(async () => setIncidents((await api.get("/loans/reports/incidents", { params: { date_from: range.from, date_to: range.to, ...cp } })).data));
  const Btn = ({ onClick, children, testid }) => <button onClick={onClick} data-testid={testid} className="inline-flex items-center gap-2 border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">{children}</button>;
  const Th = ({ k }) => <th className="label-mono py-2 px-2 text-left">{t(k)}</th>;

  return (
    <div className="mt-10" data-testid="loan-reports">
      <div className="label-mono mb-2">{t("ln_kicker")}</div>
      <h2 className="font-display text-2xl font-semibold tracking-tight text-slate-900 mb-4">{t("rp_loans_title")}</h2>
      {canPickCampus && (
        <select className="border border-slate-200 bg-white px-3 py-2 text-sm h-10 w-56 mb-4" value={campus} onChange={(e) => setCampus(e.target.value)}>
          <option value="">{t("all_campuses")}</option>
          {["YPJ Kuala Kencana", "YPJ TPRA"].map((x) => <option key={x} value={x}>{campusLabel(x)}</option>)}
        </select>)}

      <div className="bg-white border border-slate-200 p-5 mb-6">
        <div className="font-semibold text-slate-900">{t("rp_usage")}</div>
        <p className="text-sm text-slate-500 mb-3">{t("rp_usage_desc")}</p>
        <div className="flex gap-2 flex-wrap items-center">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="border border-slate-200 px-3 py-2 text-sm h-10" data-testid="rp-month" />
          <Btn onClick={loadUsage} testid="rp-usage-show">{t("rp_show")}</Btn>
          <Btn onClick={() => run(() => downloadXlsx("/loans/reports/usage", { month, ...cp }, `laporan-peminjaman-${month}.xlsx`))} testid="rp-usage-xlsx"><FileSpreadsheet className="w-4 h-4" /> {t("report_download_xlsx")}</Btn>
        </div>
        {usage && (
          <div className="mt-5 space-y-6" data-testid="rp-usage-result">
            <div><div className="label-mono mb-2">{t("rp_by_class")}</div>
              <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-slate-200"><Th k="ln_class" /><Th k="su_resource" /><Th k="rp_fixed" /><Th k="rp_extra" /><Th k="rp_hours" /></tr></thead>
                <tbody>{usage.by_class.map((r, i) => <tr key={i} className="border-b border-slate-100"><td className="py-2 px-2">{r.class_name}</td><td className="py-2 px-2">{r.resource}</td><td className="py-2 px-2">{r.fixed_sessions}</td><td className="py-2 px-2">{r.extra_sessions}</td><td className="py-2 px-2">{r.hours}</td></tr>)}
                  {usage.by_class.length === 0 && <tr><td colSpan="5" className="py-3 text-slate-500">{t("ln_empty")}</td></tr>}</tbody></table></div></div>
            <div><div className="label-mono mb-1">{t("rp_off_schedule")}</div><p className="text-xs text-slate-500 mb-2">{t("rp_off_hint")}</p>
              <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-slate-200"><Th k="su_resource" /><Th k="rp_requests" /><Th k="rp_approved" /><Th k="rp_partial" /><Th k="rp_rejected" /><Th k="rp_units_req" /><Th k="rp_units_ok" /></tr></thead>
                <tbody>{usage.off_schedule.map((r, i) => <tr key={i} className="border-b border-slate-100"><td className="py-2 px-2">{r.resource}</td><td className="py-2 px-2">{r.requests}</td><td className="py-2 px-2">{r.approved}</td><td className="py-2 px-2">{r.partial}</td><td className="py-2 px-2 text-rose-700">{r.rejected}</td><td className="py-2 px-2">{r.units_requested}</td><td className="py-2 px-2">{r.units_approved}</td></tr>)}
                  {usage.off_schedule.length === 0 && <tr><td colSpan="7" className="py-3 text-slate-500">{t("ln_empty")}</td></tr>}</tbody></table></div></div>
            <div><div className="label-mono mb-2">{t("rp_items")}</div>
              <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-slate-200"><Th k="ln_asset" /><Th k="su_category" /><Th k="rp_loans" /><Th k="rp_problems" /></tr></thead>
                <tbody>{usage.items.map((r, i) => <tr key={i} className="border-b border-slate-100"><td className="py-2 px-2">{r.asset}</td><td className="py-2 px-2">{r.category}</td><td className="py-2 px-2">{r.loans}</td><td className="py-2 px-2 text-rose-700">{r.problems}</td></tr>)}
                  {usage.items.length === 0 && <tr><td colSpan="4" className="py-3 text-slate-500">{t("ln_empty")}</td></tr>}</tbody></table></div></div>
          </div>)}
      </div>

      <div className="bg-white border border-slate-200 p-5">
        <div className="font-semibold text-slate-900">{t("rp_incidents")}</div>
        <p className="text-sm text-slate-500 mb-3">{t("rp_incidents_desc")}</p>
        <div className="flex gap-2 flex-wrap items-center">
          <input type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} className="border border-slate-200 px-3 py-2 text-sm h-10" data-testid="rp-from" />
          <input type="date" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} className="border border-slate-200 px-3 py-2 text-sm h-10" data-testid="rp-to" />
          <Btn onClick={loadIncidents} testid="rp-inc-show">{t("rp_show")}</Btn>
          <Btn onClick={() => run(() => downloadXlsx("/loans/reports/incidents", { date_from: range.from, date_to: range.to, ...cp }, "kerusakan-kehilangan.xlsx"))} testid="rp-inc-xlsx"><FileSpreadsheet className="w-4 h-4" /> {t("report_download_xlsx")}</Btn>
        </div>
        {incidents && (
          <div className="overflow-x-auto mt-4" data-testid="rp-incidents-result"><table className="w-full text-sm"><thead><tr className="border-b border-slate-200"><Th k="rp_code" /><Th k="db_last_user" /><Th k="rp_chronology" /><Th k="rp_follow_up" /><Th k="ln_checkin" /></tr></thead>
            <tbody>{incidents.map((r, i) => <tr key={i} className="border-b border-slate-100 align-top"><td className="py-2 px-2"><div className="font-mono text-xs">{r.asset_tag}</div><div>{r.asset_name}</div></td><td className="py-2 px-2">{r.last_user}</td>
              <td className="py-2 px-2">{r.chronology}<div className="text-xs text-slate-400">{r.number} · {t(`ln_res_${r.result}`)}</div></td><td className="py-2 px-2">{r.follow_up}</td><td className="py-2 px-2 text-xs">{fmtDateTime(r.in_at)}</td></tr>)}
              {incidents.length === 0 && <tr><td colSpan="5" className="py-3 text-slate-500">{t("ln_empty")}</td></tr>}</tbody></table></div>)}
      </div>
    </div>
  );
}
