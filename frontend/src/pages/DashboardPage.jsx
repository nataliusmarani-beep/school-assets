import { useEffect, useState } from "react";
import api, { fmtCurrency, fmtDate } from "../lib/api";
import {
  Boxes,
  CircleDollarSign,
  TrendingDown,
  Wrench,
  ShieldAlert,
  CalendarClock,
  ArrowUpRight,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

function MetricCard({ label, value, hint, icon: Icon, testid }) {
  return (
    <div className="bg-white border border-slate-200 p-6" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div className="label-mono">{label}</div>
        <Icon className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
      </div>
      <div className="font-display text-3xl font-semibold text-slate-900 mt-3">
        {value}
      </div>
      {hint && <div className="text-xs text-slate-500 mt-2">{hint}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get("/dashboard/stats")
      .then((r) => setStats(r.data))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-8 text-sm text-slate-500" data-testid="dashboard-loading">
        Loading dashboard…
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="dashboard-page">
      <div className="flex items-end justify-between mb-8">
        <div>
          <div className="label-mono mb-2">Overview</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            Asset dashboard
          </h1>
        </div>
        <Link
          to="/assets/new"
          data-testid="dashboard-add-asset"
          className="hidden md:inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white text-sm px-4 py-2"
        >
          Add asset <ArrowUpRight className="w-4 h-4" strokeWidth={1.75} />
        </Link>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-px bg-slate-200 border border-slate-200 mb-8">
        <MetricCard
          testid="kpi-total-assets"
          label="Total assets"
          value={stats.total_assets}
          icon={Boxes}
          hint={`${Object.keys(stats.by_category).length} categories`}
        />
        <MetricCard
          testid="kpi-book-value"
          label="Current book value"
          value={fmtCurrency(stats.current_book_value)}
          icon={CircleDollarSign}
          hint={`Of ${fmtCurrency(stats.total_purchase_value)} purchased`}
        />
        <MetricCard
          testid="kpi-depreciated"
          label="Accumulated depreciation"
          value={fmtCurrency(stats.depreciated_value)}
          icon={TrendingDown}
          hint="Straight-line method"
        />
        <MetricCard
          testid="kpi-open-faults"
          label="Open faults"
          value={stats.open_faults}
          icon={Wrench}
          hint={`${stats.compliance_overdue} compliance overdue`}
        />
      </div>

      {/* Chart + Compliance */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <div className="lg:col-span-2 bg-white border border-slate-200 p-6">
          <div className="flex items-end justify-between mb-6">
            <div>
              <div className="label-mono mb-1">Forecast</div>
              <h2 className="font-display text-xl font-medium text-slate-900">
                Book value, 6-year horizon
              </h2>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats.depreciation_timeline}>
                <defs>
                  <linearGradient id="dep" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#047857" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#047857" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#e2e8f0" vertical={false} />
                <XAxis
                  dataKey="year"
                  stroke="#64748b"
                  fontSize={12}
                  tickLine={false}
                />
                <YAxis
                  stroke="#64748b"
                  fontSize={12}
                  tickLine={false}
                  tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                />
                <Tooltip
                  formatter={(v) => fmtCurrency(v)}
                  contentStyle={{
                    background: "white",
                    border: "1px solid #e2e8f0",
                    borderRadius: 0,
                    fontSize: 12,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#047857"
                  strokeWidth={2}
                  fill="url(#dep)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-white border border-slate-200 p-6">
          <div className="label-mono mb-1">Action required</div>
          <h2 className="font-display text-xl font-medium text-slate-900 mb-5">
            Warranty alerts
          </h2>
          {stats.warranty_alerts.length === 0 ? (
            <div className="text-sm text-slate-500">All warranties in good standing.</div>
          ) : (
            <div className="space-y-3 max-h-72 overflow-y-auto">
              {stats.warranty_alerts.slice(0, 8).map((w) => (
                <Link
                  to={`/assets/${w.id}`}
                  key={w.id}
                  data-testid={`warranty-alert-${w.id}`}
                  className="block border-l-2 border-amber-400 pl-3 py-1 hover:bg-slate-50"
                >
                  <div className="text-sm font-medium text-slate-900 truncate">
                    {w.name}
                  </div>
                  <div className="text-xs text-slate-500 flex items-center gap-2">
                    <span>{w.asset_tag}</span>
                    <span>·</span>
                    <span className={w.expired ? "text-rose-600" : "text-amber-700"}>
                      {w.expired ? "Expired" : "Expires"} {fmtDate(w.warranty_end_date)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent faults + Categories */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-5">
            <div>
              <div className="label-mono mb-1">Recent</div>
              <h2 className="font-display text-xl font-medium text-slate-900">
                Fault reports
              </h2>
            </div>
            <Link to="/faults" className="text-xs text-blue-800 hover:text-blue-900" data-testid="view-all-faults">
              View all →
            </Link>
          </div>
          {stats.recent_faults.length === 0 ? (
            <div className="text-sm text-slate-500">No faults reported.</div>
          ) : (
            <div className="space-y-3">
              {stats.recent_faults.map((f) => (
                <div key={f.id} className="flex items-start gap-3 pb-3 border-b border-slate-100 last:border-0">
                  <div className={`w-2 h-2 mt-1.5 rounded-full ${
                    f.severity === "high" ? "bg-rose-500" :
                    f.severity === "medium" ? "bg-amber-500" : "bg-slate-400"
                  }`} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-900 truncate">{f.title}</div>
                    <div className="text-xs text-slate-500 flex items-center gap-2 mt-0.5">
                      <span>{f.asset_name}</span>
                      <span>·</span>
                      <span className="capitalize">{f.status.replace("_", " ")}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-5">
            <div>
              <div className="label-mono mb-1">Inventory</div>
              <h2 className="font-display text-xl font-medium text-slate-900">By category</h2>
            </div>
            <Link to="/compliance" className="text-xs text-blue-800 hover:text-blue-900" data-testid="view-compliance-link">
              Compliance →
            </Link>
          </div>
          <div className="space-y-3">
            {Object.entries(stats.by_category).map(([cat, count]) => {
              const pct = (count / stats.total_assets) * 100;
              return (
                <div key={cat}>
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="text-slate-700">{cat}</span>
                    <span className="font-mono text-xs text-slate-500">{count}</span>
                  </div>
                  <div className="h-1 bg-slate-100">
                    <div
                      className="h-full bg-blue-800"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          {(stats.compliance_overdue > 0 || stats.compliance_upcoming > 0) && (
            <div className="mt-6 pt-5 border-t border-slate-200 grid grid-cols-2 gap-4">
              <div className="flex items-center gap-3">
                <ShieldAlert className="w-4 h-4 text-rose-600" strokeWidth={1.75} />
                <div>
                  <div className="text-xl font-display font-semibold text-slate-900">{stats.compliance_overdue}</div>
                  <div className="text-xs text-slate-500">Overdue</div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <CalendarClock className="w-4 h-4 text-amber-600" strokeWidth={1.75} />
                <div>
                  <div className="text-xl font-display font-semibold text-slate-900">{stats.compliance_upcoming}</div>
                  <div className="text-xs text-slate-500">Due in 30 days</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
