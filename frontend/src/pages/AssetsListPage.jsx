import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtCurrency, fmtDate } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { CATEGORY_VALUES, CATEGORY_KEYS, STATUS_KEYS } from "../i18n";
import { Input } from "../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Search, Plus, Filter } from "lucide-react";

const CAMPUSES = ["YPJ Kuala Kencana", "YPJ Tembagapura"];

const CAMPUS_DOT = {
  "YPJ Kuala Kencana": "bg-amber-400",
  "YPJ Tembagapura": "bg-blue-500",
};

const STATUS_CLS = {
  active: "bg-blue-50 text-blue-800 border-blue-200",
  in_repair: "bg-amber-50 text-amber-700 border-amber-200",
  retired: "bg-slate-100 text-slate-600 border-slate-200",
  lost: "bg-rose-50 text-rose-700 border-rose-200",
};

export default function AssetsListPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [campus, setCampus] = useState("all");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");

  const load = () => {
    setLoading(true);
    const params = {};
    if (search) params.search = search;
    if (campus !== "all") params.campus = campus;
    if (category !== "all") params.category = category;
    if (status !== "all") params.status = status;
    api.get("/assets", { params })
      .then((r) => setAssets(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
    /* eslint-disable-next-line */
  }, [search, campus, category, status]);

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="assets-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="label-mono mb-2">{t("inventory")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            {t("assets")}
          </h1>
        </div>
        {isAdmin && (
          <Link
            to="/assets/new"
            data-testid="add-asset-button"
            className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white text-sm px-4 py-2.5"
          >
            <Plus className="w-4 h-4" strokeWidth={1.75} /> {t("add_asset")}
          </Link>
        )}
      </div>

      {/* Filters */}
      <div className="bg-white border border-slate-200 p-4 mb-6 grid grid-cols-1 md:grid-cols-12 gap-3">
        <div className="md:col-span-4 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" strokeWidth={1.75} />
          <Input
            placeholder={t("search_placeholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 rounded-none border-slate-300"
            data-testid="asset-search-input"
          />
        </div>
        <div className="md:col-span-3">
          <Select value={campus} onValueChange={setCampus}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-campus">
              <SelectValue placeholder={t("all_campuses")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("all_campuses")}</SelectItem>
              {CAMPUSES.map((c) => (
                <SelectItem key={c} value={c}>
                  <span className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${CAMPUS_DOT[c] || "bg-slate-400"}`} />
                    {c}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-3">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-category">
              <Filter className="w-3.5 h-3.5 mr-2 text-slate-400" strokeWidth={1.75} />
              <SelectValue placeholder={t("all_categories")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("all_categories")}</SelectItem>
              {CATEGORY_VALUES.map((c, i) => (
                <SelectItem key={c} value={c}>{t(CATEGORY_KEYS[i])}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="md:col-span-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="rounded-none border-slate-300" data-testid="filter-status">
              <SelectValue placeholder={t("all_statuses")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("all_statuses")}</SelectItem>
              {Object.entries(STATUS_KEYS).map(([val, key]) => (
                <SelectItem key={val} value={val}>{t(key)}</SelectItem>
              ))}
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
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_tag")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_asset")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_category")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_campus")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_room")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_assigned")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_status")}</th>
                <th className="text-left font-medium label-mono py-3 px-4">{t("col_asset_property_of")}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="text-center text-slate-500 py-12">{t("loading")}</td></tr>
              ) : assets.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center text-slate-500 py-16">
                    <div className="font-display text-lg text-slate-700 mb-1">{t("no_assets")}</div>
                    <div className="text-xs">{t("no_assets_sub")}</div>
                  </td>
                </tr>
              ) : assets.map((a) => {
                const cls = STATUS_CLS[a.status] || STATUS_CLS.active;
                const dot = CAMPUS_DOT[a.campus];
                return (
                  <tr key={a.id} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" data-testid={`asset-row-${a.id}`}>
                    <td className="py-3 px-4 font-mono text-xs text-slate-600">
                      <Link to={`/assets/${a.id}`} className="hover:text-blue-800">{a.asset_tag}</Link>
                    </td>
                    <td className="py-3 px-4">
                      <Link to={`/assets/${a.id}`} className="font-medium text-slate-900 hover:text-blue-800">{a.name}</Link>
                      <div className="text-xs text-slate-500 mt-0.5">{a.serial_number || "—"}</div>
                    </td>
                    <td className="py-3 px-4 text-slate-700">{a.category}</td>
                    <td className="py-3 px-4 text-slate-700">
                      {a.campus ? (
                        <span className="flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dot || "bg-slate-400"}`} />
                          {a.campus}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="py-3 px-4 text-slate-700">{a.location}</td>
                    <td className="py-3 px-4 text-slate-700">{a.assigned_to_name || "—"}</td>
                    <td className="py-3 px-4">
                      <span className={`inline-flex items-center px-2 py-0.5 text-xs border ${cls}`}>
                        {t(STATUS_KEYS[a.status] || "status_active")}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-700 text-sm">{a.asset_type || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="text-xs text-slate-500 mt-3 flex items-center justify-between">
        <span>{assets.length} {assets.length !== 1 ? t("count_assets") : t("count_asset")}</span>
        <span>{t("last_refreshed")} {fmtDate(new Date().toISOString())}</span>
      </div>
    </div>
  );
}
