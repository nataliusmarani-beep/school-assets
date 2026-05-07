import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../components/ui/select";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { Wrench } from "lucide-react";

const STATUS_BADGE = {
  open: "bg-amber-50 text-amber-700 border-amber-200",
  in_progress: "bg-blue-50 text-blue-700 border-blue-200",
  resolved: "bg-blue-50 text-blue-800 border-blue-200",
};

const SEVERITY_BADGE = {
  high: "text-rose-600",
  medium: "text-amber-600",
  low: "text-slate-500",
};

export default function FaultsPage() {
  const { t } = useLang();
  const [faults, setFaults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveTarget, setResolveTarget] = useState(null);
  const [resolveNote, setResolveNote] = useState("");

  const load = () => {
    setLoading(true);
    const params = filter !== "all" ? { status: filter } : {};
    api.get("/faults", { params }).then((r) => setFaults(r.data)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter]);

  const updateStatus = async (f, status, note = null) => {
    try {
      await api.put(`/faults/${f.id}`, { status, ...(note ? { resolution_note: note } : {}) });
      toast.success("Fault updated");
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const submitResolve = async () => {
    await updateStatus(resolveTarget, "resolved", resolveNote);
    setResolveOpen(false); setResolveNote(""); setResolveTarget(null);
  };

  const STATUS_LABEL = {
    open: t("filter_open"),
    in_progress: t("filter_in_progress"),
    resolved: t("filter_resolved"),
  };

  const SEV_LABEL = {
    high: t("sev_high"),
    medium: t("sev_medium"),
    low: t("sev_low"),
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="faults-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="label-mono mb-2">{t("maintenance")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            {t("fault_reports")}
          </h1>
        </div>
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="w-48 rounded-none border-slate-300" data-testid="fault-filter">
            <SelectValue/>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("all_faults")}</SelectItem>
            <SelectItem value="open">{t("filter_open")}</SelectItem>
            <SelectItem value="in_progress">{t("filter_in_progress")}</SelectItem>
            <SelectItem value="resolved">{t("filter_resolved")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="text-sm text-slate-500">{t("loading")}</div>
      ) : faults.length === 0 ? (
        <div className="bg-white border border-slate-200 p-12 text-center">
          <Wrench className="w-8 h-8 text-slate-300 mx-auto mb-3" strokeWidth={1.5}/>
          <div className="font-display text-lg text-slate-700">{t("no_fault_reports")}</div>
          <div className="text-xs text-slate-500 mt-1">{t("faults_sub")}</div>
        </div>
      ) : (
        <div className="space-y-3">
          {faults.map((f) => (
            <div key={f.id} className="bg-white border border-slate-200 p-5" data-testid={`fault-row-${f.id}`}>
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 flex-wrap">
                    <h3 className="font-display text-lg font-medium text-slate-900">{f.title}</h3>
                    <span className={`text-xs px-2 py-0.5 border ${STATUS_BADGE[f.status]}`}>
                      {STATUS_LABEL[f.status] || f.status}
                    </span>
                    <span className={`text-xs label-mono ${SEVERITY_BADGE[f.severity]}`}>
                      {SEV_LABEL[f.severity] || f.severity}
                    </span>
                  </div>
                  <div className="text-sm text-slate-600 mt-2">{f.description}</div>
                  <div className="text-xs text-slate-500 mt-3 flex items-center gap-3 flex-wrap">
                    <Link to={`/assets/${f.asset_id}`} className="hover:text-blue-800">
                      {f.asset_name} <span className="font-mono">({f.asset_tag})</span>
                    </Link>
                    <span>·</span>
                    <span>{f.reported_by_name}</span>
                    <span>·</span>
                    <span>{fmtDate(f.created_at)}</span>
                  </div>
                  {f.resolution_note && (
                    <div className="text-sm text-blue-800 mt-2 bg-blue-50 border border-blue-200 p-2">
                      {f.resolution_note}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {f.status === "open" && (
                    <Button size="sm" variant="outline" className="rounded-none"
                      onClick={() => updateStatus(f, "in_progress")} data-testid={`fault-progress-${f.id}`}>
                      {t("mark_in_progress")}
                    </Button>
                  )}
                  {f.status !== "resolved" && (
                    <Button size="sm" className="rounded-none bg-blue-800 hover:bg-blue-900"
                      onClick={() => { setResolveTarget(f); setResolveOpen(true); }} data-testid={`fault-resolve-${f.id}`}>
                      {t("resolve")}
                    </Button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={resolveOpen} onOpenChange={setResolveOpen}>
        <DialogContent className="rounded-none">
          <DialogHeader><DialogTitle>{t("resolve_fault")}</DialogTitle></DialogHeader>
          <Textarea placeholder={t("resolution_note")} value={resolveNote}
            onChange={(e) => setResolveNote(e.target.value)} rows={3}
            className="rounded-none" data-testid="resolve-note-input"/>
          <DialogFooter>
            <Button onClick={submitResolve} className="rounded-none bg-blue-800" data-testid="confirm-resolve-button">
              {t("mark_resolved")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
