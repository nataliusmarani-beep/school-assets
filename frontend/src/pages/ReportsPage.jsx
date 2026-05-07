import { useState } from "react";
import { useLang } from "../context/LangContext";
import api, { formatErr } from "../lib/api";
import { toast } from "sonner";
import { Package, TrendingDown, Wrench, ShieldCheck, ArrowLeftRight, FileSpreadsheet } from "lucide-react";

const REPORTS = [
  {
    key: "asset_inventory",
    endpoint: "/reports/asset-inventory",
    icon: Package,
    titleKey: "report_asset_inventory",
    descKey: "report_asset_inventory_desc",
  },
  {
    key: "depreciation",
    endpoint: "/reports/depreciation",
    icon: TrendingDown,
    titleKey: "report_depreciation",
    descKey: "report_depreciation_desc",
  },
  {
    key: "faults",
    endpoint: "/reports/faults",
    icon: Wrench,
    titleKey: "report_faults",
    descKey: "report_faults_desc",
  },
  {
    key: "compliance",
    endpoint: "/reports/compliance",
    icon: ShieldCheck,
    titleKey: "report_compliance",
    descKey: "report_compliance_desc",
  },
  {
    key: "ownership",
    endpoint: "/reports/ownership",
    icon: ArrowLeftRight,
    titleKey: "report_ownership",
    descKey: "report_ownership_desc",
  },
];

export default function ReportsPage() {
  const { t } = useLang();
  const [downloading, setDownloading] = useState({});

  const download = async (report) => {
    if (downloading[report.key]) return;
    setDownloading((d) => ({ ...d, [report.key]: true }));
    try {
      const res = await api.get(report.endpoint, { responseType: "blob" });
      const cd = res.headers["content-disposition"] || "";
      const match = cd.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : `${report.key}.xlsx`;
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      setDownloading((d) => ({ ...d, [report.key]: false }));
    }
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto">
      <div className="label-mono mb-2">{t("analytics")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-8">
        {t("reports")}
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {REPORTS.map((report) => {
          const Icon = report.icon;
          const isLoading = downloading[report.key];
          return (
            <div key={report.key} className="bg-white border border-slate-200 p-6 flex flex-col gap-4">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 bg-blue-50 border border-blue-100 flex items-center justify-center flex-shrink-0">
                  <Icon className="w-5 h-5 text-blue-700" strokeWidth={1.5} />
                </div>
                <div>
                  <div className="font-semibold text-slate-900 mb-1">{t(report.titleKey)}</div>
                  <div className="text-sm text-slate-500 leading-relaxed">{t(report.descKey)}</div>
                </div>
              </div>
              <button
                onClick={() => download(report)}
                disabled={isLoading}
                className="self-start inline-flex items-center gap-2 border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <FileSpreadsheet className="w-4 h-4 text-slate-500" strokeWidth={1.5} />
                {isLoading ? t("report_downloading") : t("report_download_xlsx")}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
