import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import api, { fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { BookOpen, CheckCircle2, XCircle } from "lucide-react";

const STATUS_META = {
  pending:  { bg: "bg-amber-50 text-amber-700 border-amber-200" },
  approved: { bg: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  rejected: { bg: "bg-rose-50 text-rose-700 border-rose-200" },
};

const FILTERS = (t) => [
  { value: "pending",  label: t("tr_filter_pending") },
  { value: "approved", label: t("tr_filter_approved") },
  { value: "rejected", label: t("tr_filter_rejected") },
  { value: "all",      label: t("tr_filter_all") },
];

function LoanCard({ req, t, isAdmin, onApprove, onReject }) {
  const meta = STATUS_META[req.status] || STATUS_META.pending;
  return (
    <div className="bg-white border border-slate-200 p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap mb-1">
            <Link to={`/assets/${req.asset_id}`}
              className="font-semibold text-slate-900 hover:text-blue-700">
              {req.asset_name}
            </Link>
            <span className="font-mono text-xs text-slate-500">({req.asset_tag})</span>
            <span className={`text-xs px-2 py-0.5 border capitalize ${meta.bg}`}>{req.status}</span>
          </div>

          {req.purpose && (
            <div className="text-xs text-slate-500 italic mb-2">"{req.purpose}"</div>
          )}

          <div className="flex items-center gap-4 text-xs text-slate-500 mb-2 flex-wrap">
            {req.start_date && (
              <span>{t("loan_from")}: <span className="text-slate-700">{fmtDate(req.start_date)}</span></span>
            )}
            {req.end_date && (
              <span>{t("loan_until")}: <span className="text-slate-700">{fmtDate(req.end_date)}</span></span>
            )}
          </div>

          <div className="text-xs text-slate-400 flex items-center gap-2 flex-wrap">
            {isAdmin && (
              <><span>{t("tr_requested_by")} <span className="text-slate-600">{req.requested_by_name}</span></span><span>·</span></>
            )}
            <span>{fmtDate(req.created_at)}</span>
            {req.reviewed_by_name && (
              <>
                <span>·</span>
                <span>
                  {req.status === "approved" ? t("tr_approved_by") : t("tr_rejected_by")}{" "}
                  <span className="text-slate-600">{req.reviewed_by_name}</span>
                </span>
              </>
            )}
          </div>

          {req.reject_reason && (
            <div className="mt-2 text-xs text-rose-700 bg-rose-50 border border-rose-200 px-3 py-2">
              {t("tr_reason")}: {req.reject_reason}
            </div>
          )}
        </div>

        {req.status === "pending" && isAdmin && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button size="sm" variant="outline"
              className="rounded-none border-rose-300 text-rose-600 hover:bg-rose-50"
              onClick={() => onReject(req)}>
              <XCircle className="w-3.5 h-3.5 mr-1.5" strokeWidth={1.75} />
              {t("tr_reject")}
            </Button>
            <Button size="sm"
              className="rounded-none bg-emerald-700 hover:bg-emerald-800"
              onClick={() => onApprove(req)}>
              <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" strokeWidth={1.75} />
              {t("tr_approve")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function LoanRequestsPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("pending");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectTarget, setRejectTarget] = useState(null);
  const [rejectReason, setRejectReason] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    const params = filter !== "all" ? { status: filter } : {};
    api.get("/loan-requests", { params })
      .then((r) => setRequests(r.data))
      .catch((e) => toast.error(formatErr(e)))
      .finally(() => setLoading(false));
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const approve = async (req) => {
    try {
      await api.put(`/loan-requests/${req.id}/approve`);
      toast.success(t("loan_approved"));
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  const openReject = (req) => { setRejectTarget(req); setRejectOpen(true); };

  const confirmReject = async () => {
    try {
      await api.put(`/loan-requests/${rejectTarget.id}/reject`, null, {
        params: { reason: rejectReason || undefined },
      });
      toast.success(t("loan_rejected"));
      setRejectOpen(false); setRejectReason(""); setRejectTarget(null);
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  /* ── Staff view ── */
  if (!isAdmin) {
    return (
      <div className="p-6 lg:p-10 max-w-[800px] mx-auto">
        <div className="label-mono mb-2">{t("assets")}</div>
        <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-1">
          {t("loan_my_requests")}
        </h1>
        <p className="text-sm text-slate-500 mb-6">{t("loan_my_subtitle")}</p>

        <div className="space-y-3">
          {loading ? (
            <div className="text-sm text-slate-400 py-8 text-center">{t("loading")}</div>
          ) : requests.length === 0 ? (
            <div className="bg-white border border-slate-200 p-16 flex flex-col items-center text-center">
              <BookOpen className="w-10 h-10 text-slate-300 mb-4" strokeWidth={1.5} />
              <div className="font-display text-lg text-slate-600 mb-1">{t("loan_my_empty")}</div>
              <div className="text-sm text-slate-400">{t("loan_my_empty_sub")}</div>
            </div>
          ) : requests.map((req) => (
            <LoanCard key={req.id} req={req} t={t} isAdmin={false} />
          ))}
        </div>
      </div>
    );
  }

  /* ── Admin view ── */
  return (
    <div className="p-6 lg:p-10 max-w-[1000px] mx-auto">
      <div className="label-mono mb-2">{t("assets")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 mb-6">
        {t("nav_loan_requests")}
      </h1>

      <div className="flex gap-2 flex-wrap mb-6">
        {FILTERS(t).map((f) => (
          <button key={f.value} onClick={() => setFilter(f.value)}
            className={`text-xs px-3 py-1.5 border transition-colors ${
              filter === f.value
                ? "bg-slate-900 text-white border-slate-900"
                : "bg-white text-slate-600 border-slate-300 hover:border-slate-500"
            }`}>
            {f.label}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {loading ? (
          <div className="text-sm text-slate-400 py-8 text-center">{t("loading")}</div>
        ) : requests.length === 0 ? (
          <div className="bg-white border border-slate-200 p-16 flex flex-col items-center text-center">
            <BookOpen className="w-10 h-10 text-slate-300 mb-4" strokeWidth={1.5} />
            <div className="font-display text-lg text-slate-600 mb-1">{t("loan_empty")}</div>
            <div className="text-sm text-slate-400">{t("loan_empty_sub")}</div>
          </div>
        ) : requests.map((req) => (
          <LoanCard key={req.id} req={req} t={t} isAdmin
            onApprove={approve} onReject={openReject} />
        ))}
      </div>

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent className="rounded-none">
          <DialogHeader>
            <DialogTitle>{t("loan_reject_title")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-600">{t("tr_reject_desc")}</p>
          <Textarea
            placeholder={t("tr_reject_reason_placeholder")}
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            rows={3}
            className="rounded-none mt-2"
          />
          <DialogFooter>
            <Button variant="outline" className="rounded-none" onClick={() => setRejectOpen(false)}>
              {t("cancel")}
            </Button>
            <Button className="rounded-none bg-rose-600 hover:bg-rose-700" onClick={confirmReject}>
              {t("tr_confirm_reject")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
