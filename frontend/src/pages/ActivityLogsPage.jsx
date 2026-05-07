import { useEffect, useState, useCallback } from "react";
import api, { fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { toast } from "sonner";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../components/ui/select";

// Maps event type → display label key + entity label
const EVENT_META = {
  asset_created:      { actionKey: "log_asset_created",     entity: "Asset",      entityKey: "assets" },
  ownership_transfer: { actionKey: "log_ownership_transfer", entity: "Asset",      entityKey: "assets" },
  fault_reported:     { actionKey: "log_fault_reported",    entity: "Fault",      entityKey: "nav_faults" },
  fault_resolved:     { actionKey: "log_fault_resolved",    entity: "Fault",      entityKey: "nav_faults" },
  compliance_added:   { actionKey: "log_compliance_added",  entity: "Compliance", entityKey: "nav_compliance" },
  user_created:       { actionKey: "log_user_created",      entity: "User",       entityKey: "nav_users" },
};

const ACTION_TYPES = [
  { value: "all",                labelKey: "log_all_actions" },
  { value: "asset_created",      labelKey: "log_asset_created" },
  { value: "ownership_transfer", labelKey: "log_ownership_transfer" },
  { value: "fault_reported",     labelKey: "log_fault_reported" },
  { value: "fault_resolved",     labelKey: "log_fault_resolved" },
  { value: "compliance_added",   labelKey: "log_compliance_added" },
  { value: "user_created",       labelKey: "log_user_created" },
];

const ENTITY_TYPES = [
  { value: "all",        labelKey: "log_all_entities" },
  { value: "asset_created,ownership_transfer", labelKey: "assets" },
  { value: "fault_reported,fault_resolved",    labelKey: "nav_faults" },
  { value: "compliance_added",                 labelKey: "nav_compliance" },
  { value: "user_created",                     labelKey: "nav_users" },
];

const PAGE_SIZE = 50;

function getDetails(event, t) {
  switch (event.type) {
    case "asset_created":      return event.detail || "—";
    case "ownership_transfer": return event.detail ? `${t("log_to")} ${event.detail}` : "—";
    case "fault_reported":
    case "fault_resolved":     return event.detail || "—";
    case "compliance_added":   return event.detail || "—";
    case "user_created":       return event.detail ? event.detail.charAt(0).toUpperCase() + event.detail.slice(1) : "—";
    default:                   return "—";
  }
}

export default function ActivityLogsPage() {
  const { t } = useLang();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [actionFilter, setActionFilter] = useState("all");
  const [entityFilter, setEntityFilter] = useState("all");

  const load = useCallback(async (pg, action, entity, append = false) => {
    append ? setLoadingMore(true) : setLoading(true);
    try {
      // Resolve which event_type(s) to pass
      let eventType = "all";
      if (action !== "all") {
        eventType = action;
      } else if (entity !== "all") {
        // entity filter maps to comma-separated types; backend accepts one at a time
        // so we fetch all and filter client-side for multi-type entity groups
        eventType = "all";
      }

      const params = { page: pg, limit: PAGE_SIZE };
      if (eventType !== "all") params.event_type = eventType;

      const res = await api.get("/activity", { params });
      let fetched = res.data.items;

      // Client-side entity filter when action is "all"
      if (action === "all" && entity !== "all") {
        const allowed = entity.split(",");
        fetched = fetched.filter((ev) => allowed.includes(ev.type));
      }

      setTotal(res.data.total);
      setItems((prev) => append ? [...prev, ...fetched] : fetched);
    } catch (err) {
      toast.error(formatErr(err));
    } finally {
      append ? setLoadingMore(false) : setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(1);
    load(1, actionFilter, entityFilter, false);
  }, [actionFilter, entityFilter, load]);

  const loadMore = () => {
    const next = page + 1;
    setPage(next);
    load(next, actionFilter, entityFilter, true);
  };

  const hasMore = items.length < total;

  return (
    <div className="p-6 lg:p-10 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-8 flex-wrap">
        <div>
          <div className="label-mono mb-2">{t("access_control")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-1">
            {t("activity_logs")}
          </h1>
          <p className="text-sm text-slate-500">{t("logs_sub")}</p>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 flex-wrap">
          <Select value={actionFilter} onValueChange={setActionFilter}>
            <SelectTrigger className="w-44 rounded-none border-slate-300 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACTION_TYPES.map((a) => (
                <SelectItem key={a.value} value={a.value}>{t(a.labelKey)}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={entityFilter} onValueChange={setEntityFilter}>
            <SelectTrigger className="w-40 rounded-none border-slate-300 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ENTITY_TYPES.map((e) => (
                <SelectItem key={e.value} value={e.value}>{t(e.labelKey)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left label-mono py-3 px-4 w-36">{t("log_col_when")}</th>
                <th className="text-left label-mono py-3 px-4 w-44">{t("log_col_action")}</th>
                <th className="text-left label-mono py-3 px-4 w-28">{t("log_col_entity")}</th>
                <th className="text-left label-mono py-3 px-4">{t("log_col_target")}</th>
                <th className="text-left label-mono py-3 px-4 w-36">{t("log_col_user")}</th>
                <th className="text-left label-mono py-3 px-4">{t("log_col_details")}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400 py-16 text-sm">{t("loading")}</td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-slate-400 py-16 text-sm">{t("log_no_events")}</td>
                </tr>
              ) : (
                items.map((event, i) => {
                  const meta = EVENT_META[event.type];
                  return (
                    <tr
                      key={`${event.type}-${event.ref_id}-${i}`}
                      className="border-b border-slate-100 hover:bg-slate-50 last:border-0"
                    >
                      <td className="py-3 px-4 text-slate-400 text-xs whitespace-nowrap">
                        {fmtDate(event.at)}
                      </td>
                      <td className="py-3 px-4">
                        <span className="inline-flex items-center text-xs text-slate-700">
                          {meta ? t(meta.actionKey) : event.type}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <span className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 border border-slate-200">
                          {meta ? t(meta.entityKey) : event.type}
                        </span>
                      </td>
                      <td className="py-3 px-4 font-medium text-slate-900">
                        {event.subject || "—"}
                        {event.campus && (
                          <span className="ml-2 inline-flex items-center gap-1 text-xs text-slate-400 font-normal">
                            <span className={`w-1.5 h-1.5 rounded-full ${event.campus === "YPJ Kuala Kencana" ? "bg-amber-400" : "bg-blue-500"}`} />
                            {event.campus}
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-slate-600">{event.actor || "—"}</td>
                      <td className="py-3 px-4 text-slate-500 text-xs">{getDetails(event, t)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Load more */}
        {!loading && hasMore && (
          <div className="px-4 py-3 border-t border-slate-100 bg-slate-50">
            <button
              onClick={loadMore}
              disabled={loadingMore}
              className="text-sm text-blue-700 hover:text-blue-900 disabled:opacity-50"
            >
              {loadingMore ? t("loading") : t("log_load_more")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
