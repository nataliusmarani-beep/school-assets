import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { canWrite } from "../lib/roles";
import { Button } from "../components/ui/button";
import { toast } from "sonner";
import QrScanner from "../components/loans/QrScanner";
import { fmtDateTime } from "../components/loans/LoanForms";
import { campusLabel } from "../lib/campus";
import { QrCode } from "lucide-react";

const STATE_STYLE = {
  available: "text-emerald-700 bg-emerald-50 border-emerald-200", on_loan: "text-amber-700 bg-amber-50 border-amber-200",
  repair: "text-rose-700 bg-rose-50 border-rose-200", lost: "text-rose-700 bg-rose-50 border-rose-200",
};

export default function ScanPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const manager = ["super_admin", "admin", "campus_admin", "ict_admin"].includes(user?.role);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [params] = useSearchParams();

  const onScan = useCallback(async (code) => {
    setBusy(true);
    try { const r = await api.get("/loans/scan", { params: { code } }); setResult(r.data); }
    catch (e) { setResult(null); toast.error(formatErr(e)); }
    finally { setBusy(false); }
  }, []);

  // opened from a label with the phone's own camera: /scan?code=<asset tag>
  useEffect(() => { const c = params.get("code"); if (c) onScan(c); }, [params, onScan]);

  const a = result?.asset;
  return (
    <div className="p-6 lg:p-10 max-w-[760px] mx-auto" data-testid="scan-page">
      <div className="label-mono mb-2">{t("ln_kicker")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">{t("qr_title")}</h1>
      <p className="text-sm text-slate-500 mt-2">{t("qr_subtitle")}</p>
      <div className="mt-6"><QrScanner onScan={onScan} t={t} /></div>

      {a && (
        <div className="mt-6 bg-white border border-slate-200 p-5" data-testid="scan-result">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-semibold text-slate-900 text-lg">{a.name}</div>
              <div className="text-xs text-slate-500">{[a.brand, a.model].filter(Boolean).join(" ") || a.category} · {campusLabel(a.campus)}</div>
              <div className="font-mono text-xs text-slate-400 mt-1">{a.asset_tag}{a.serial_number ? ` · SN ${a.serial_number}` : ""}</div>
            </div>
            <span className={`text-xs px-2 py-0.5 border ${STATE_STYLE[result.state]}`} data-testid="scan-state">{t(`ln_state_${result.state}`)}</span>
          </div>
          {result.out && <div className="text-sm text-slate-600 mt-3">{t("ln_with")} <b>{result.out.requester_name}</b> · {t("ln_until")} {fmtDateTime(result.out.end_at)}</div>}
          {result.pickup && <div className="text-sm text-slate-600 mt-3">{t("qr_pickup")}: {result.pickup.number} · {result.pickup.requester_name}</div>}
          <div className="flex gap-2 mt-4 flex-wrap">
            {result.suggest && (
              <Link to={`/loans/${result.suggest.booking_id}`}>
                <Button className="rounded-none" data-testid="scan-action">{t(result.suggest.action === "check_in" ? "ln_act_checkin" : "ln_act_checkout")}</Button></Link>)}
            {canWrite(user?.role) && result.borrowable && result.state === "available" && (
              <Link to={`/loans?asset=${a.id}`}><Button variant={result.suggest ? "outline" : "default"} className="rounded-none" data-testid="scan-borrow">{t("qr_borrow")}</Button></Link>)}
            {!result.borrowable && !result.suggest && <span className="text-xs text-slate-500" data-testid="scan-not-borrowable">{t("qr_not_borrowable")}</span>}
            {manager && !result.suggest && result.borrowable && <span className="text-xs text-slate-500">{t("qr_no_action")}</span>}
            <Link to={`/assets/${a.id}`}><Button variant="outline" className="rounded-none">{t("qr_open_asset")}</Button></Link>
          </div>
        </div>)}
      {busy && <div className="text-xs text-slate-400 mt-2">…</div>}
      {manager && <div className="mt-6"><Link to="/loans/labels" className="text-sm text-blue-700 hover:underline inline-flex items-center gap-1"><QrCode className="w-4 h-4" /> {t("qr_print_labels")}</Link></div>}
    </div>
  );
}
