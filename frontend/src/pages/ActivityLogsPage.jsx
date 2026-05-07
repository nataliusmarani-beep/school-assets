import { useEffect, useState, useCallback } from "react";
import api, { fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { toast } from "sonner";
import {
  PackagePlus, ArrowLeftRight, Wrench, CheckCircle2,
  ShieldCheck, UserPlus, Activity,
} from "lucide-react";

const EVENT_TYPES = [
  { value: "all", labelKey: "log_all" },
  { value: "asset_created", labelKey: "log_asset_created" },
  { value: "ownership_transfer", labelKey: "log_ownership_transfer" },
  { value: "fault_reported", labelKey: "log_fault_reported" },
  { value: "fault_resolved", labelKey: "log_fault_resolved" },
  { value: "compliance_added", labelKey: "log_compliance_added" },
  { value: "user_created", labelKey: "log_user_created" },
];

const EVENT_META = {
  asset_created:       { Icon: PackagePlus,    color: "text-blue-600",   bg: "bg-blue-50 border-blue-100" },
  ownership_transfer:  { Icon: ArrowLeftRight, color: "text-violet-600", bg: "bg-violet-50 border-violet-100" },
  fault_reported:      { Icon: Wrench,         color: "text-rose-600",   bg: "bg-rose-50 border-rose-100" },
  fault_resolved:      { Icon: CheckCircle2,   color: "text-emerald-600",bg: "bg-emerald-50 border-emerald-100" },
  compliance_added:    { Icon: ShieldCheck,    color: "text-amber-600",  bg: "bg-amber-50 border-amber-100" },
  user_created:        { Icon: UserPlus,       color: "text-slate-600",  bg: "bg-slate-100 border-slate-200" },
};

const CAMPUS_DOT = {
  "YPJ Kuala Kencana": "bg-amber-400",
  "YPJ Tembagapura": "bg-blue-500",
};

const PAGE_SIZE = 30;

function EventRow({ event, t }) {
  const meta = EVENT_META[event.type] || EVENT_META.asset_created;
  const { Icon, color, bg } = meta;

  const renderDetail = () => {
    switch (event.type) {
      case "asset_created":
        return (
          <span>
            <span className="font-medium text-slate-900">{event.subject}</span>
            {" "}
            <span className="text-slate-400">·</span>
            {" "}{event.detail}
            {event.actor && <> <span className="text-slate-400">{t("log_by")}</span> <span className="font-medium">{event.actor}</span></>}
          </span>
        );
      case "ownership_transfer":
        return (
          <span>
            <span className="font-medium text-slate-900">{event.subject}</span>
            {" "}<span className="text-slate-400">{t("log_to")}</span>{" "}
            <span className="font-medium">{event.detail}</span>
            {event.actor && <> <span className="text-slate-400">{t("log_by")}</span> <span className="font-medium">{event.actor}</span></>}
          </span>
        );
      case "fault_reported":
      case "fault_resolved":
        return (
          <span>
            <span className="font-medium text-slate-900">{event.detail}</span>
            {" "}<span className="text-slate-400">·</span>{" "}
            {event.subject}
            {event.actor && <> <span className="text-slate-400">{t("log_by")}</span> <span className="font-medium">{event.actor}</span></>}
          </span>
        );
      case "compliance_added":
        return (
          <span>
            <span className="font-medium text-slate-900">{event.subject}</span>
            {" "}<span className="text-slate-400">·</span>{" "}
            {event.detail}
          </span>
        );
      case "user_created":
        return (
          <span>
            <span className="font-medium text-slate-900">{event.subject}</span>
            {" "}<span className="text-slate-400">·</span>{" "}
            <span className="capitalize">{event.detail}</span>
          </span>
        );
      default:
        return <span className="font-medium text-slate-900">{event.subject}</span>;
    }
  };

  return (
    <div className="flex items-start gap-4 py-3.5 px-5 border-b border-slate-100 last:border-0 hover:bg-slate-50/60 transition-colors">
      <div className={`mt-0.5 w-8 h-8 flex-shrink-0 flex items-center justify-center border rounded-sm ${bg}`}>
        <Icon className={`w-4 h-4 ${color}`} strokeWidth={1.75} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className={`label-mono text-[10px] ${color}`}>{t(`log_${event.type}`)}</span>
          {event.campus && (
            <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
              <span className={`w-1.5 h-1.5 rounded-full ${CAMPUS_DOT[event.campus] || "bg-slate-400"}`} />
              {event.campus}
            </span>
          )}
        </div>
        <div className="text-sm text-slate-600 leading-snug">{renderDetail()}</div>
      </div>
      <div className="flex-shrink-0 text-xs text-slate-400 whitespace-nowrap pt-0.5">{fmtDate(event.at)}</div>
    </div>
  );
}

export default function ActivityLogsPage() {
  const { t } = useLang();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [filter, setFilter] = useState("all");

  const load = useCallback(async (pg, type, append = false) => {
    append ? setLoadingMore(true) : setLoading(true);
    try {
      const params = { page: pg, limit: PAGE_SIZE };
      if (type && type !== "all") params.event_type = type;
      const res = await api.get("/activity", { params });
      setTotal(res.data.total);
      setItems((prev) => append ? [...prev, ...res.data.items] : res.data.items);
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      append ? setLoadingMore(false) : setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(1);
    load(1, filter, false);
  }, [filter, load]);

  const loadMore = () => {
    const next = page + 1;
    setPage(next);
    load(next, filter, true);
  };

  const hasMore = items.length < total;

  return (
    <div className="p-6 lg:p-10 max-w-[1000px] mx-auto">
      <div className="label-mono mb-2">{t("audit")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-6">
        {t("activity_logs")}
      </h1>

      {/* Filter tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        {EVENT_TYPES.map((et) => (
          <button
            key={et.value}
            onClick={() => setFilter(et.value)}
            className={`text-xs px-3 py-1.5 border transition-colors ${
              filter === et.value
                ? "bg-slate-900 text-white border-slate-900"
                : "bg-white text-slate-600 border-slate-300 hover:border-slate-500"
            }`}
          >
            {t(et.labelKey)}
          </button>
        ))}
      </div>

      <div className="bg-white border border-slate-200">
        {/* Header */}
        <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-slate-400" strokeWidth={1.5} />
            <span className="label-mono text-slate-500">
              {loading ? t("loading") : `${total} ${t("activity_logs").toLowerCase()}`}
            </span>
          </div>
        </div>

        {/* Events */}
        {loading ? (
          <div className="text-center text-slate-400 py-16 text-sm">{t("loading")}</div>
        ) : items.length === 0 ? (
          <div className="text-center text-slate-400 py-16 text-sm">{t("log_no_events")}</div>
        ) : (
          <>
            {items.map((event, i) => (
              <EventRow key={`${event.type}-${event.ref_id}-${event.at}-${i}`} event={event} t={t} />
            ))}
            {hasMore && (
              <div className="px-5 py-4 border-t border-slate-100">
                <button
                  onClick={loadMore}
                  disabled={loadingMore}
                  className="text-sm text-blue-700 hover:text-blue-900 disabled:opacity-50"
                >
                  {loadingMore ? t("loading") : t("log_load_more")}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
