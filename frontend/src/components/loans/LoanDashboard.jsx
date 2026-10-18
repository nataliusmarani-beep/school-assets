import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { formatErr } from "../../lib/api";
import { useLang } from "../../context/LangContext";
import { useAuth } from "../../context/AuthContext";
import { toast } from "sonner";
import { campusLabel } from "../../lib/campus";
import { fmtDateTime } from "./LoanForms";

function Stat({ label, value, tone, testid }) {
  const tones = { amber: "text-amber-700", rose: "text-rose-700", emerald: "text-emerald-700", slate: "text-slate-900" };
  return <div className="bg-white border border-slate-200 p-4" data-testid={testid}><div className={`text-3xl font-semibold ${tones[tone] || tones.slate}`}>{value}</div><div className="text-xs text-slate-500 mt-1">{label}</div></div>;
}

function Block({ title, empty, t, children, count }) {
  return (
    <div className="bg-white border border-slate-200 p-5">
      <div className="label-mono mb-3">{title}{count !== undefined ? ` (${count})` : ""}</div>
      {count === 0 ? <div className="text-sm text-slate-500">{empty || t("ln_empty")}</div> : children}
    </div>
  );
}

export default function LoanDashboard() {
  const { t } = useLang();
  const { user } = useAuth();
  const [d, setD] = useState(null);
  const [campus, setCampus] = useState("");
  const canPickCampus = user?.role !== "ict_admin";

  useEffect(() => {
    const load = () => api.get("/loans/dashboard", { params: { campus: campus || undefined } }).then((r) => setD(r.data)).catch((e) => toast.error(formatErr(e)));
    load();
    const h = setInterval(load, 60000);
    return () => clearInterval(h);
  }, [campus]);

  if (!d) return <div className="text-sm text-slate-400">…</div>;
  const c = d.counts;
  return (
    <div className="space-y-6" data-testid="loan-dashboard">
      {canPickCampus && (
        <select className="border border-slate-200 bg-white px-3 py-2 text-sm h-10 w-56" value={campus} onChange={(e) => setCampus(e.target.value)} data-testid="dash-campus">
          <option value="">{t("all_campuses")}</option>
          {["YPJ Kuala Kencana", "YPJ TPRA"].map((x) => <option key={x} value={x}>{campusLabel(x)}</option>)}
        </select>)}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label={t("db_pending")} value={c.pending} tone={c.pending ? "amber" : "slate"} testid="stat-pending" />
        <Stat label={t("db_out")} value={c.out} tone="emerald" testid="stat-out" />
        <Stat label={t("db_not_returned")} value={c.not_returned} tone={c.not_returned ? "rose" : "slate"} testid="stat-not-returned" />
        <Stat label={t("db_broken")} value={c.broken} tone={c.broken ? "rose" : "slate"} testid="stat-broken" />
        <Stat label={t("db_today")} value={c.today} testid="stat-today" />
      </div>

      <Block title={t("db_not_returned")} count={d.not_returned.length} t={t} empty={t("db_none_late")}>
        <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="not-returned-table">
          <thead><tr className="text-left border-b border-slate-200">{["ln_asset", "db_last_user", "ln_number", "db_due", "db_contact"].map((k) => <th key={k} className="label-mono py-2 px-2">{t(k)}</th>)}</tr></thead>
          <tbody>{d.not_returned.map((r) => (
            <tr key={`${r.booking_id}-${r.asset_id}`} className="border-b border-slate-100 bg-rose-50/40 align-top">
              <td className="py-2 px-2"><div className="font-medium">{r.asset_name}</div><div className="font-mono text-xs text-slate-400">{r.asset_tag}</div></td>
              <td className="py-2 px-2">{r.user_label || r.requester_name}{r.user_label && r.user_label !== r.requester_name ? <div className="text-xs text-slate-500">{r.requester_name}</div> : null}</td>
              <td className="py-2 px-2 font-mono text-xs"><Link className="text-blue-700 hover:underline" to={`/loans/${r.booking_id}`}>{r.number}</Link></td>
              <td className="py-2 px-2 text-xs">{fmtDateTime(r.end_at)}</td>
              <td className="py-2 px-2 text-xs space-y-0.5">
                {r.phone && <div><a className="text-emerald-700 underline" href={`https://wa.me/${r.phone}`} target="_blank" rel="noreferrer">WhatsApp +{r.phone}</a></div>}
                {r.email && <div><a className="text-blue-700 underline" href={`mailto:${r.email}`}>{r.email}</a></div>}
                {r.supervisor && <div className="text-slate-500">{t("supervisor_email")}: {r.supervisor}</div>}
              </td>
            </tr>))}</tbody></table></div>
      </Block>

      <div className="grid lg:grid-cols-2 gap-6">
        <Block title={t("db_pending")} count={d.pending.length} t={t}>
          <ul className="divide-y divide-slate-100 text-sm">{d.pending.map((b) => (
            <li key={b.id} className="py-2 flex justify-between gap-3"><span><Link className="font-mono text-xs text-blue-700 hover:underline" to={`/loans/${b.id}`}>{b.number}</Link> · {b.asset_name} · {b.requester_name}</span><span className="text-xs text-slate-500 whitespace-nowrap">{fmtDateTime(b.start_at)}</span></li>))}</ul>
        </Block>
        <Block title={t("db_today")} count={d.today.length} t={t}>
          <ul className="divide-y divide-slate-100 text-sm">{d.today.map((b) => (
            <li key={b.id} className="py-2 flex justify-between gap-3"><span><Link className="font-mono text-xs text-blue-700 hover:underline" to={`/loans/${b.id}`}>{b.number}</Link> · {b.asset_name} · {b.requester_name}</span><span className="text-xs text-slate-500 whitespace-nowrap">{t(`ln_st_${b.status}`)}</span></li>))}</ul>
        </Block>
        <Block title={t("db_out")} count={d.out.length} t={t}>
          <ul className="divide-y divide-slate-100 text-sm">{d.out.map((b) => (
            <li key={b.id} className="py-2 flex justify-between gap-3"><span><Link className="font-mono text-xs text-blue-700 hover:underline" to={`/loans/${b.id}`}>{b.number}</Link> · {b.asset_name} · {b.requester_name}</span><span className="text-xs text-slate-500 whitespace-nowrap">{t("ln_until")} {fmtDateTime(b.end_at)}</span></li>))}</ul>
        </Block>
        <Block title={t("db_broken")} count={d.broken.length} t={t}>
          <ul className="divide-y divide-slate-100 text-sm">{d.broken.map((a) => (
            <li key={a.id} className="py-2 flex justify-between gap-3"><Link className="text-blue-700 hover:underline" to={`/assets/${a.id}`}>{a.name} <span className="font-mono text-xs text-slate-400">{a.asset_tag}</span></Link><span className="text-xs text-rose-700">{t(a.status === "lost" ? "ln_state_lost" : "ln_state_repair")}</span></li>))}</ul>
        </Block>
      </div>
    </div>
  );
}
