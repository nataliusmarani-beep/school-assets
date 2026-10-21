import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fmtCurrency } from "../../lib/api";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

const STATUS_CLS = {
  active: "bg-emerald-50 text-emerald-700 border-emerald-200",
  in_repair: "bg-amber-50 text-amber-700 border-amber-200",
  retired: "bg-slate-100 text-slate-600 border-slate-200",
  lost: "bg-rose-50 text-rose-700 border-rose-200",
};

const SORTERS = {
  asset: (a) => a.name || "",
  location: (a) => a.location || "",
  category: (a) => a.category || "",
  type: (a) => a.assignment_kind || "",
  status: (a) => a.status || "",
  value: (a) => Number(a.depreciation?.current_value) || 0,
};

// Table of the assets a person holds, with tabs for all / class / personal assets. Click a column header to sort.
export default function AssetBundle({ bundle, t, testid = "asset-bundle" }) {
  const [tab, setTab] = useState("all");
  const all = [...bundle.class, ...bundle.personal];
  const base = tab === "class" ? bundle.class : tab === "personal" ? bundle.personal : all;
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  const rows = useMemo(() => {
    if (!sort.key) return base;
    const get = SORTERS[sort.key], m = sort.dir === "asc" ? 1 : -1;
    return [...base].sort((x, y) => {
      const a = get(x), b = get(y);
      const c = typeof a === "number" ? a - b : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
      return m * c || String(x.name).localeCompare(String(y.name), undefined, { numeric: true });
    });
  }, [base, sort]);
  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  const Th = ({ k, label, right }) => {
    const on = sort.key === k;
    const Icon = !on ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
    return (
      <th className={`px-4 py-3 ${right ? "text-right" : ""}`} aria-sort={on ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
        <button type="button" onClick={() => toggleSort(k)} data-testid={`${testid}-sort-${k}`}
          className={`inline-flex items-center gap-1 uppercase hover:text-slate-900 ${on ? "text-slate-900" : ""}`}>
          {label} <Icon className={`w-3 h-3 ${on ? "" : "opacity-40"}`} strokeWidth={2} />
        </button>
      </th>
    );
  };
  const tabs = [
    { v: "all", label: `${t("ma_tab_all")} (${all.length})` },
    { v: "class", label: `${t("ma_kind_class")} (${bundle.class.length})` },
    { v: "personal", label: `${t("ma_kind_personal")} (${bundle.personal.length})` },
  ];
  return (
    <div data-testid={testid}>
      <div className="flex gap-2 flex-wrap mb-4">
        {tabs.map((x) => (
          <button key={x.v} onClick={() => setTab(x.v)} data-testid={`${testid}-tab-${x.v}`}
            className={`text-xs px-3 py-1.5 border transition-colors ${
              tab === x.v ? "bg-slate-900 text-white border-slate-900"
                          : "bg-white text-slate-600 border-slate-300 hover:border-slate-500"}`}>
            {x.label}
          </button>
        ))}
      </div>
      {rows.length === 0 ? (
        <div className="text-sm text-slate-500 py-8 text-center border border-dashed border-slate-200">{t("ma_empty")}</div>
      ) : (
        <div className="overflow-x-auto border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left label-mono bg-slate-50">
                <Th k="asset" label={t("ma_col_asset")} />
                <Th k="location" label={t("ma_col_location")} />
                <Th k="category" label={t("ma_col_category")} />
                <Th k="type" label={t("ma_col_type")} />
                <Th k="status" label={t("ma_col_status")} />
                <Th k="value" label={t("ma_col_value")} right />
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className="border-t border-slate-100" data-testid="bundle-row">
                  <td className="px-4 py-3">
                    <Link to={`/assets/${a.id}`} className="font-medium text-slate-900 hover:text-blue-700">{a.name}</Link>
                    <div className="font-mono text-xs text-slate-500">{a.asset_tag}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{a.location}</td>
                  <td className="px-4 py-3 text-slate-600">{a.category}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 border ${a.assignment_kind === "class"
                      ? "bg-blue-50 text-blue-700 border-blue-200" : "bg-slate-50 text-slate-600 border-slate-200"}`}>
                      {a.assignment_kind === "class" ? t("ma_kind_class") : t("ma_kind_personal")}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 border ${STATUS_CLS[a.status] || STATUS_CLS.active}`}>{a.status}</span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{fmtCurrency(a.depreciation?.current_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
