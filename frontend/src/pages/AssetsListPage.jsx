import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtCurrency, fmtDate } from "../lib/api";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Search, Plus, Filter } from "lucide-react";

const CATEGORIES = [
  "IT Equipment", "AV Equipment", "Furniture", "Lab Equipment",
  "Vehicles", "Books", "Sports", "Music Equipment", "Other",
];

const STATUS_LABELS = {
  active: { label: "Active", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  in_repair: { label: "In Repair", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  retired: { label: "Retired", cls: "bg-slate-100 text-slate-600 border-slate-200" },
  lost: { label: "Lost", cls: "bg-rose-50 text-rose-700 border-rose-200" },
};

export default function AssetsListPage() {
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");

  const load = () => {
    setLoading(true);
    const params = {};
    if (search) params.search = search;
    if (category !== "all") params.category = category;
    if (status !== "all") params.status = status;
    api.get("/assets", { params })
      .then((r) => setAssets(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, category, status]);

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="assets-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="label-mono mb-2">Inventory</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            Assets
          </h1>
        </div>
        <Link
          to="/assets/new"
          data-testid="add-asset-button"
          className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white text-sm px-4 py-2.5"
        >
          <Plus className="w-4 h-4" strokeWidth={1.75} /> Add asset
        </Link>
      </div>

      {/* Filters */}
      <div className="bg-white border border-slate-200 p-4 mb-6 grid grid-cols-1 md:grid-cols-12 gap-3">
        <div className="md:col-span-6 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" strokeWidth={1.75} />
          <Input
            placeholder="Search by name, tag or serial number…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 rounded-none border-slate-300"
            data-testid="asset-search-input"
          />
        </div>
        <div className="md:col-span-3">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-category">
              <Filter className="w-3.5 h-3.5 mr-2 text-slate-400" strokeWidth={1.75} />
              <SelectValue placeholder="All categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-3">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-status">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="in_repair">In Repair</SelectItem>
              <SelectItem value="retired">Retired</SelectItem>
              <SelectItem value="lost">Lost</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="assets-table">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left font-medium label-mono py-3 px-4">Tag</th>
                <th className="text-left font-medium label-mono py-3 px-4">Asset</th>
                <th className="text-left font-medium label-mono py-3 px-4">Category</th>
                <th className="text-left font-medium label-mono py-3 px-4">Location</th>
                <th className="text-left font-medium label-mono py-3 px-4">Assigned</th>
                <th className="text-left font-medium label-mono py-3 px-4">Status</th>
                <th className="text-right font-medium label-mono py-3 px-4">Book Value</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="text-center text-slate-500 py-12">Loading…</td>
                </tr>
              ) : assets.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center text-slate-500 py-16">
                    <div className="font-display text-lg text-slate-700 mb-1">No assets found</div>
                    <div className="text-xs">Try adjusting filters or add your first asset.</div>
                  </td>
                </tr>
              ) : assets.map((a) => {
                const st = STATUS_LABELS[a.status] || STATUS_LABELS.active;
                return (
                  <tr
                    key={a.id}
                    className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer"
                    data-testid={`asset-row-${a.id}`}
                  >
                    <td className="py-3 px-4 font-mono text-xs text-slate-600">
                      <Link to={`/assets/${a.id}`} className="hover:text-emerald-700">{a.asset_tag}</Link>
                    </td>
                    <td className="py-3 px-4">
                      <Link to={`/assets/${a.id}`} className="font-medium text-slate-900 hover:text-emerald-700">
                        {a.name}
                      </Link>
                      <div className="text-xs text-slate-500 mt-0.5">{a.serial_number || "—"}</div>
                    </td>
                    <td className="py-3 px-4 text-slate-700">{a.category}</td>
                    <td className="py-3 px-4 text-slate-700">{a.location}</td>
                    <td className="py-3 px-4 text-slate-700">{a.assigned_to_name || "—"}</td>
                    <td className="py-3 px-4">
                      <span className={`inline-flex items-center px-2 py-0.5 text-xs border ${st.cls}`}>
                        {st.label}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right font-mono">
                      {fmtCurrency(a.depreciation?.current_value)}
                      <div className="text-xs text-slate-400">of {fmtCurrency(a.purchase_price)}</div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="text-xs text-slate-500 mt-3 flex items-center justify-between">
        <span>{assets.length} asset{assets.length !== 1 && "s"}</span>
        <span>Last refreshed {fmtDate(new Date().toISOString())}</span>
      </div>
    </div>
  );
}
