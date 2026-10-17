import { useState } from "react";
import { Link } from "react-router-dom";
import { fmtCurrency } from "../../lib/api";

const STATUS_CLS = {
  active: "bg-emerald-50 text-emerald-700 border-emerald-200",
  in_repair: "bg-amber-50 text-amber-700 border-amber-200",
  retired: "bg-slate-100 text-slate-600 border-slate-200",
  lost: "bg-rose-50 text-rose-700 border-rose-200",
};

// Table of the assets a person holds, with tabs for all / class / personal assets.
export default function AssetBundle({ bundle, t, testid = "asset-bundle" }) {
  const [tab, setTab] = useState("all");
  const all = [...bundle.class, ...bundle.personal];
  const rows = tab === "class" ? bundle.class : tab === "personal" ? bundle.personal : all;
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
                <th className="px-4 py-3">{t("ma_col_asset")}</th>
                <th className="px-4 py-3">{t("ma_col_location")}</th>
                <th className="px-4 py-3">{t("ma_col_category")}</th>
                <th className="px-4 py-3">{t("ma_col_type")}</th>
                <th className="px-4 py-3">{t("ma_col_status")}</th>
                <th className="px-4 py-3 text-right">{t("ma_col_value")}</th>
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
