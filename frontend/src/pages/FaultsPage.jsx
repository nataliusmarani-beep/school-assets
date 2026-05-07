import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { fmtDate, formatErr } from "../lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "../components/ui/dialog";
import { toast } from "sonner";
import { Wrench } from "lucide-react";

const STATUS_BADGE = {
  open: "bg-amber-50 text-amber-700 border-amber-200",
  in_progress: "bg-blue-50 text-blue-700 border-blue-200",
  resolved: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

const SEVERITY_BADGE = {
  high: "text-rose-600",
  medium: "text-amber-600",
  low: "text-slate-500",
};

export default function FaultsPage() {
  const [faults, setFaults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveTarget, setResolveTarget] = useState(null);
  const [resolveNote, setResolveNote] = useState("");

  const load = () => {
    setLoading(true);
    const params = filter !== "all" ? { status: filter } : {};
    api.get("/faults", { params })
      .then((r) => setFaults(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter]);

  const updateStatus = async (f, status, note = null) => {
    try {
      await api.put(`/faults/${f.id}`, {
        status, ...(note ? { resolution_note: note } : {}),
      });
      toast.success("Fault updated");
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const submitResolve = async () => {
    await updateStatus(resolveTarget, "resolved", resolveNote);
    setResolveOpen(false); setResolveNote(""); setResolveTarget(null);
  };

  return (
    <div className="p-6 lg:p-10 max-w-[1600px] mx-auto" data-testid="faults-page">
      <div className="flex items-end justify-between mb-8 flex-wrap gap-4">
        <div>
          <div className="label-mono mb-2">Maintenance</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
            Fault reports
          </h1>
        </div>
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger className="w-48 rounded-none border-slate-300" data-testid="fault-filter">
            <SelectValue/>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All faults</SelectItem>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="in_progress">In progress</SelectItem>
            <SelectItem value="resolved">Resolved</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="text-sm text-slate-500">Loading…</div>
      ) : faults.length === 0 ? (
        <div className="bg-white border border-slate-200 p-12 text-center">
          <Wrench className="w-8 h-8 text-slate-300 mx-auto mb-3" strokeWidth={1.5}/>
          <div className="font-display text-lg text-slate-700">No fault reports</div>
          <div className="text-xs text-slate-500 mt-1">Reports will appear here when staff submit them.</div>
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
                      {f.status.replace("_", " ")}
                    </span>
                    <span className={`text-xs label-mono ${SEVERITY_BADGE[f.severity]}`}>
                      {f.severity} severity
                    </span>
                  </div>
                  <div className="text-sm text-slate-600 mt-2">{f.description}</div>
                  <div className="text-xs text-slate-500 mt-3 flex items-center gap-3 flex-wrap">
                    <Link to={`/assets/${f.asset_id}`} className="hover:text-emerald-700">
                      {f.asset_name} <span className="font-mono">({f.asset_tag})</span>
                    </Link>
                    <span>·</span>
                    <span>Reported by {f.reported_by_name}</span>
                    <span>·</span>
                    <span>{fmtDate(f.created_at)}</span>
                  </div>
                  {f.resolution_note && (
                    <div className="text-sm text-emerald-700 mt-2 bg-emerald-50 border border-emerald-200 p-2">
                      Resolution: {f.resolution_note}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {f.status === "open" && (
                    <Button size="sm" variant="outline" className="rounded-none"
                      onClick={() => updateStatus(f, "in_progress")}
                      data-testid={`fault-progress-${f.id}`}>
                      Mark in progress
                    </Button>
                  )}
                  {f.status !== "resolved" && (
                    <Button size="sm" className="rounded-none bg-emerald-700 hover:bg-emerald-800"
                      onClick={() => { setResolveTarget(f); setResolveOpen(true); }}
                      data-testid={`fault-resolve-${f.id}`}>
                      Resolve
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
          <DialogHeader><DialogTitle>Resolve fault</DialogTitle></DialogHeader>
          <div>
            <Textarea placeholder="Resolution note (optional)…"
              value={resolveNote} onChange={(e) => setResolveNote(e.target.value)}
              rows={3} className="rounded-none" data-testid="resolve-note-input"/>
          </div>
          <DialogFooter>
            <Button onClick={submitResolve} className="rounded-none bg-emerald-700"
              data-testid="confirm-resolve-button">
              Mark resolved
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
