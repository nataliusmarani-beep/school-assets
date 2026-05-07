import { useLang } from "../context/LangContext";

export default function ActivityLogsPage() {
  const { t } = useLang();
  return (
    <div className="p-6 lg:p-10 max-w-[1200px] mx-auto">
      <div className="label-mono mb-2">{t("audit")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-8">
        {t("activity_logs")}
      </h1>
      <div className="bg-white border border-slate-200 p-16 flex flex-col items-center justify-center text-center">
        <div className="w-12 h-12 bg-slate-100 flex items-center justify-center mb-4">
          <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <div className="font-display text-lg text-slate-700 mb-1">{t("logs_soon")}</div>
        <div className="text-sm text-slate-500">{t("logs_sub")}</div>
      </div>
    </div>
  );
}
