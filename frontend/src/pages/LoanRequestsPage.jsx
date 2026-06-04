import { useEffect, useState, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import api, { fmtDate, formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { BookOpen, CheckCircle2, XCircle, Truck, RotateCcw, Camera, ImageIcon } from "lucide-react";

const STATUS_META = {
  pending:  { bg: "bg-amber-50 text-amber-700 border-amber-200",   dot: "bg-amber-400" },
  approved: { bg: "bg-blue-50 text-blue-700 border-blue-200",      dot: "bg-blue-400" },
  active:   { bg: "bg-emerald-50 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
  returned: { bg: "bg-slate-100 text-slate-600 border-slate-200",  dot: "bg-slate-400" },
  rejected: { bg: "bg-rose-50 text-rose-700 border-rose-200",      dot: "bg-rose-400" },
};

const CONDITION_COLORS = {
  good:    "bg-emerald-50 text-emerald-700 border-emerald-200",
  trouble: "bg-amber-50 text-amber-700 border-amber-200",
  broken:  "bg-rose-50 text-rose-700 border-rose-200",
  missing: "bg-slate-100 text-slate-600 border-slate-300",
};

const EMPTY_CHECK = { condition: "good", note: "", image: null, preview: null };

/* ── Condition image thumbnail ── */
function ConditionThumb({ path, label }) {
  if (!path) return null;
  const src = `/api/files/${path}`;
  return (
    <div className="mt-2">
      <div className="text-xs text-slate-400 mb-1">{label}</div>
      <a href={src} target="_blank" rel="noreferrer">
        <img src={src} alt={label}
          className="h-20 w-auto max-w-[140px] object-cover border border-slate-200 rounded hover:opacity-80 transition-opacity" />
      </a>
    </div>
  );
}

/* ── Condition badge ── */
function CondBadge({ value, t }) {
  const keys = { good: "loan_cond_good", trouble: "loan_cond_trouble", broken: "loan_cond_broken", missing: "loan_cond_missing" };
  if (!value) return null;
  return (
    <span className={`text-xs px-2 py-0.5 border capitalize ${CONDITION_COLORS[value] || CONDITION_COLORS.good}`}>
      {t(keys[value] || value)}
    </span>
  );
}

/* ── Check form (shared for deliver + return modals) ── */
function CheckForm({ values, onChange, t }) {
  const fileRef = useRef(null);
  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const preview = URL.createObjectURL(file);
    onChange({ ...values, image: file, preview });
  };
  return (
    <div className="space-y-4 mt-2">
      <div>
        <Label className="label-mono">{t("loan_condition")}</Label>
        <Select value={values.condition} onValueChange={(v) => onChange({ ...values, condition: v })}>
          <SelectTrigger className="mt-2 rounded-none"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="good">{t("loan_cond_good")}</SelectItem>
            <SelectItem value="trouble">{t("loan_cond_trouble")}</SelectItem>
            <SelectItem value="broken">{t("loan_cond_broken")}</SelectItem>
            <SelectItem value="missing">{t("loan_cond_missing")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label className="label-mono">{t("loan_condition_note")}</Label>
        <Textarea
          value={values.note}
          onChange={(e) => onChange({ ...values, note: e.target.value })}
          placeholder={t("loan_condition_note_placeholder")}
          rows={3}
          className="mt-2 rounded-none"
        />
      </div>
      <div>
        <Label className="label-mono">{t("loan_condition_photo")}</Label>
        <div
          className="mt-2 border-2 border-dashed border-slate-200 rounded p-4 flex flex-col items-center cursor-pointer hover:border-slate-400 transition-colors"
          onClick={() => fileRef.current?.click()}
        >
          {values.preview ? (
            <img src={values.preview} alt="preview" className="h-32 object-contain mb-2 rounded" />
          ) : (
            <Camera className="w-8 h-8 text-slate-300 mb-2" strokeWidth={1.5} />
          )}
          <span className="text-xs text-slate-400">{t("loan_condition_photo_hint")}</span>
          <input ref={fileRef} type="file" accept="image/*" className="sr-only" onChange={handleFile} />
        </div>
      </div>
    </div>
  );
}

/* ── Single loan card ── */
function LoanCard({ req, t, isAdmin, onApprove, onReject, onDeliver, onReturn }) {
  const meta = STATUS_META[req.status] || STATUS_META.pending;
  const hasPreCheck  = req.pre_condition  || req.pre_image_path;
  const hasPostCheck = req.post_condition || req.post_image_path;

  return (
    <div className="bg-white border border-slate-200 p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-center gap-3 flex-wrap mb-1">
            <Link to={`/assets/${req.asset_id}`}
              className="font-semibold text-slate-900 hover:text-blue-700">
              {req.asset_name}
            </Link>
            <span className="font-mono text-xs text-slate-500">({req.asset_tag})</span>
            <span className={`text-xs px-2 py-0.5 border capitalize ${meta.bg}`}>
              <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${meta.dot}`} />
              {req.status}
            </span>
          </div>

          {req.purpose && (
            <div className="text-xs text-slate-500 italic mb-2">"{req.purpose}"</div>
          )}

          {/* Dates */}
          <div className="flex items-center gap-4 text-xs text-slate-500 mb-2 flex-wrap">
            {req.start_date && (
              <span>{t("loan_from")}: <span className="text-slate-700">{fmtDate(req.start_date)}</span></span>
            )}
            {req.end_date && (
              <span>{t("loan_until")}: <span className="text-slate-700 font-medium">{fmtDate(req.end_date)}</span></span>
            )}
            {req.delivered_at && (
              <span>{t("loan_delivered_at")}: <span className="text-slate-700">{fmtDate(req.delivered_at)}</span></span>
            )}
            {req.returned_at && (
              <span>{t("loan_returned_at")}: <span className="text-slate-700">{fmtDate(req.returned_at)}</span></span>
            )}
          </div>

          {/* Meta */}
          <div className="text-xs text-slate-400 flex items-center gap-2 flex-wrap">
            {isAdmin && (
              <><span>{t("tr_requested_by")} <span className="text-slate-600">{req.requested_by_name}</span></span><span>·</span></>
            )}
            <span>{fmtDate(req.created_at)}</span>
            {req.reviewed_by_name && (
              <>
                <span>·</span>
                <span>
                  {req.status === "rejected" ? t("tr_rejected_by") : t("tr_approved_by")}{" "}
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

          {/* Pre-check */}
          {hasPreCheck && (
            <div className="mt-3 pt-3 border-t border-slate-100">
              <div className="text-xs label-mono text-slate-400 mb-1">{t("loan_pre_check")}</div>
              <div className="flex items-center gap-2 flex-wrap">
                <CondBadge value={req.pre_condition} t={t} />
                {req.pre_condition_note && (
                  <span className="text-xs text-slate-600 italic">"{req.pre_condition_note}"</span>
                )}
              </div>
              {req.pre_image_path && (
                <ConditionThumb path={req.pre_image_path} label={t("loan_pre_check")} />
              )}
            </div>
          )}

          {/* Post-check */}
          {hasPostCheck && (
            <div className="mt-3 pt-3 border-t border-slate-100">
              <div className="text-xs label-mono text-slate-400 mb-1">{t("loan_post_check")}</div>
              <div className="flex items-center gap-2 flex-wrap">
                <CondBadge value={req.post_condition} t={t} />
                {req.post_condition_note && (
                  <span className="text-xs text-slate-600 italic">"{req.post_condition_note}"</span>
                )}
              </div>
              {req.post_image_path && (
                <ConditionThumb path={req.post_image_path} label={t("loan_post_check")} />
              )}
            </div>
          )}
        </div>

        {/* Action buttons */}
        {isAdmin && (
          <div className="flex flex-col items-end gap-2 flex-shrink-0">
            {req.status === "pending" && (
              <div className="flex items-center gap-2">
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
            {req.status === "approved" && (
              <Button size="sm"
                className="rounded-none bg-blue-700 hover:bg-blue-800"
                onClick={() => onDeliver(req)}>
                <Truck className="w-3.5 h-3.5 mr-1.5" strokeWidth={1.75} />
                {t("loan_deliver")}
              </Button>
            )}
            {req.status === "active" && (
              <Button size="sm"
                className="rounded-none bg-slate-700 hover:bg-slate-800"
                onClick={() => onReturn(req)}>
                <RotateCcw className="w-3.5 h-3.5 mr-1.5" strokeWidth={1.75} />
                {t("loan_return")}
              </Button>
            )}
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

  // reject modal
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectTarget, setRejectTarget] = useState(null);
  const [rejectReason, setRejectReason] = useState("");

  // deliver modal
  const [deliverOpen, setDeliverOpen] = useState(false);
  const [deliverTarget, setDeliverTarget] = useState(null);
  const [deliverCheck, setDeliverCheck] = useState(EMPTY_CHECK);
  const [delivering, setDelivering] = useState(false);

  // return modal
  const [returnOpen, setReturnOpen] = useState(false);
  const [returnTarget, setReturnTarget] = useState(null);
  const [returnCheck, setReturnCheck] = useState(EMPTY_CHECK);
  const [returning, setReturning] = useState(false);

  const FILTERS = [
    { value: "pending",  label: t("tr_filter_pending") },
    { value: "approved", label: t("tr_filter_approved") },
    { value: "active",   label: t("loan_filter_active") },
    { value: "returned", label: t("loan_filter_returned") },
    { value: "rejected", label: t("tr_filter_rejected") },
    { value: "all",      label: t("tr_filter_all") },
  ];

  const load = useCallback(() => {
    setLoading(true);
    const params = filter !== "all" ? { status: filter } : {};
    api.get("/loan-requests", { params })
      .then((r) => setRequests(r.data))
      .catch((e) => toast.error(formatErr(e)))
      .finally(() => setLoading(false));
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  /* ── Approve ── */
  const approve = async (req) => {
    try {
      await api.put(`/loan-requests/${req.id}/approve`);
      toast.success(t("loan_approved"));
      load();
    } catch (e) { toast.error(formatErr(e)); }
  };

  /* ── Reject ── */
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

  /* ── Deliver ── */
  const openDeliver = (req) => { setDeliverTarget(req); setDeliverCheck(EMPTY_CHECK); setDeliverOpen(true); };
  const confirmDeliver = async () => {
    setDelivering(true);
    try {
      const fd = new FormData();
      fd.append("condition", deliverCheck.condition);
      fd.append("note", deliverCheck.note || "");
      if (deliverCheck.image) fd.append("image", deliverCheck.image);
      await api.put(`/loan-requests/${deliverTarget.id}/deliver`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(t("loan_delivered_ok"));
      setDeliverOpen(false);
      load();
    } catch (e) { toast.error(formatErr(e)); }
    finally { setDelivering(false); }
  };

  /* ── Return ── */
  const openReturn = (req) => { setReturnTarget(req); setReturnCheck(EMPTY_CHECK); setReturnOpen(true); };
  const confirmReturn = async () => {
    setReturning(true);
    try {
      const fd = new FormData();
      fd.append("condition", returnCheck.condition);
      fd.append("note", returnCheck.note || "");
      if (returnCheck.image) fd.append("image", returnCheck.image);
      await api.put(`/loan-requests/${returnTarget.id}/return`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(t("loan_returned_ok"));
      setReturnOpen(false);
      load();
    } catch (e) { toast.error(formatErr(e)); }
    finally { setReturning(false); }
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
        {FILTERS.map((f) => (
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
            onApprove={approve}
            onReject={openReject}
            onDeliver={openDeliver}
            onReturn={openReturn}
          />
        ))}
      </div>

      {/* ── Reject dialog ── */}
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

      {/* ── Deliver dialog ── */}
      <Dialog open={deliverOpen} onOpenChange={setDeliverOpen}>
        <DialogContent className="rounded-none max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("loan_deliver_title")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-600">{t("loan_deliver_hint")}</p>
          {deliverTarget && (
            <div className="text-xs font-mono text-slate-500 mb-1">
              {deliverTarget.asset_name} · {deliverTarget.asset_tag} · {deliverTarget.requested_by_name}
            </div>
          )}
          <CheckForm values={deliverCheck} onChange={setDeliverCheck} t={t} />
          <DialogFooter className="mt-4">
            <Button variant="outline" className="rounded-none" onClick={() => setDeliverOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              className="rounded-none bg-blue-700 hover:bg-blue-800"
              onClick={confirmDeliver}
              disabled={delivering}
            >
              <Truck className="w-4 h-4 mr-2" strokeWidth={1.75} />
              {delivering ? t("saving") : t("loan_confirm_deliver")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Return dialog ── */}
      <Dialog open={returnOpen} onOpenChange={setReturnOpen}>
        <DialogContent className="rounded-none max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("loan_return_title")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-600">{t("loan_return_hint")}</p>
          {returnTarget && (
            <div className="text-xs font-mono text-slate-500 mb-1">
              {returnTarget.asset_name} · {returnTarget.asset_tag} · {returnTarget.requested_by_name}
            </div>
          )}
          <CheckForm values={returnCheck} onChange={setReturnCheck} t={t} />
          <DialogFooter className="mt-4">
            <Button variant="outline" className="rounded-none" onClick={() => setReturnOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              className="rounded-none bg-slate-800 hover:bg-slate-900"
              onClick={confirmReturn}
              disabled={returning}
            >
              <RotateCcw className="w-4 h-4 mr-2" strokeWidth={1.75} />
              {returning ? t("saving") : t("loan_confirm_return")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
