import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { useAuth } from "../context/AuthContext";
import { canWrite } from "../lib/roles";
import { Button } from "../components/ui/button";
import { toast } from "sonner";
import QrScanner from "../components/loans/QrScanner";
import { fmtDateTime } from "../components/loans/LoanForms";
import { campusLabel } from "../lib/campus";
import { QrCode, X } from "lucide-react";

const STATE_STYLE = {
  available: "text-emerald-700 bg-emerald-50 border-emerald-200", on_loan: "text-amber-700 bg-amber-50 border-amber-200",
  scheduled: "text-amber-700 bg-amber-50 border-amber-200",
  repair: "text-rose-700 bg-rose-50 border-rose-200", lost: "text-rose-700 bg-rose-50 border-rose-200",
};

export default function ScanPage() {
  const { t } = useLang();
  const { user } = useAuth();
  const manager = ["super_admin", "admin", "campus_admin", "ict_admin"].includes(user?.role);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  // several units for one loan: scanned into a basket, then turned into a single loan for the borrower
  const [multi, setMulti] = useState(false);
  const [basket, setBasket] = useState([]);
  const [users, setUsers] = useState([]);
  const [borrower, setBorrower] = useState("");
  const [purpose, setPurpose] = useState("");
  const [className, setClassName] = useState("");
  const [until, setUntil] = useState(() => { const d = new Date(Date.now() + 4 * 3600e3); d.setMinutes(0, 0, 0); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}T${String(d.getHours()).padStart(2, "0")}:00`; });
  useEffect(() => { if (multi && !users.length) api.get("/users").then((r) => setUsers(r.data)).catch(() => {}); }, [multi, users.length]);
  const [userQ, setUserQ] = useState("");
  const [suggestOpen, setSuggestOpen] = useState(false);
  const pickUser = (u) => { setBorrower(u.id); setUserQ(`${u.name} — ${u.email}`); setSuggestOpen(false); };
  const [photo, setPhoto] = useState("");                // one group photo of all the units = hand them over right away
  const [photoBusy, setPhotoBusy] = useState(false);
  const pickPhoto = async (file) => {
    if (!file) return;
    setPhotoBusy(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await api.post("/upload?purpose=loan", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setPhoto(r.data.path);
    } catch (e) { toast.error(formatErr(e)); } finally { setPhotoBusy(false); }
  };
  const shownUsers = useMemo(() => { const q = userQ.trim().toLowerCase(); return q ? users.filter((u) => `${u.name} ${u.email}`.toLowerCase().includes(q)) : []; }, [users, userQ]);
  const createCounterLoan = async () => {
    setBusy(true);
    try {
      const r = await api.post("/loans/counter", { asset_ids: basket.map((x) => x.id), borrower_id: borrower, end_at: until, purpose, class_name: className });
      if (photo) {                                   // all units fine + group photo = checked out in the same step
        try { await api.post(`/loans/${r.data.id}/check-out`, { all_units: true, group_photo: photo, units: [] }); toast.success(t("qr_multi_handed").replace("{n}", r.data.units)); }
        catch (e) { toast.error(formatErr(e)); }
      } else toast.success(t("qr_multi_created").replace("{n}", r.data.units));
      navigate(`/loans/${r.data.id}`);
    } catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
  };
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const openSession = async (sg) => {
    setBusy(true);
    try { const r = await api.post(`/loans/schedules/${sg.schedule_id}/session`, { date: sg.date }); navigate(`/loans/${r.data.id}`); }
    catch (e) { toast.error(formatErr(e)); } finally { setBusy(false); }
  };

  const onScan = useCallback(async (code) => {
    setBusy(true);
    try {
      const r = await api.get("/loans/scan", { params: { code } });
      if (multi) {                                   // basket mode: add the unit, keep scanning
        const a0 = r.data.asset;
        if (r.data.state !== "available" || !r.data.borrowable) toast.error(`${a0.name}: ${t(`ln_state_${r.data.state}`)}`);
        else if (basket.some((x) => x.id === a0.id)) toast.message(`${a0.name}: ${t("qr_multi_dup")}`);
        else { setBasket((b) => [...b, { id: a0.id, name: a0.name, tag: a0.asset_tag, unit: a0.unit }]); toast.success(`+ ${a0.name}`); }
      } else setResult(r.data);
    }
    catch (e) { setResult(null); toast.error(formatErr(e)); }
    finally { setBusy(false); }
  }, [multi, basket, t]);

  // opened from a label with the phone's own camera: /scan?code=<asset tag>
  useEffect(() => { const c = params.get("code"); if (c) onScan(c); }, [params, onScan]);

  const a = result?.asset;
  return (
    <div className="p-6 lg:p-10 max-w-[760px] mx-auto" data-testid="scan-page">
      <div className="label-mono mb-2">{t("ln_kicker")}</div>
      <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">{t("qr_loan_title")}</h1>
      <p className="text-sm text-slate-500 mt-2">{t("qr_loan_subtitle")}</p>
      <div className="mt-6"><QrScanner onScan={onScan} t={t} paused={!multi && !!result} /></div>
      {manager && <label className="mt-3 flex items-center gap-2 text-sm text-slate-700 cursor-pointer"><input type="checkbox" checked={multi} onChange={(e) => { setMulti(e.target.checked); setResult(null); }} data-testid="scan-multi" /> {t("qr_multi_toggle")}</label>}
      {manager && multi && (
        <div className="mt-4 bg-white border border-slate-200 p-5" data-testid="scan-basket">
          <div className="font-semibold text-slate-900">{t("qr_multi_basket")} ({basket.length})</div>
          {basket.length === 0 && <div className="text-sm text-slate-500 mt-1">{t("qr_multi_empty")}</div>}
          <ul className="mt-2 divide-y divide-slate-100">
            {basket.map((x) => (<li key={x.id} className="py-1.5 flex items-center justify-between text-sm"><span>{x.unit ? <b className="text-blue-800 mr-2">{t(`unit_${x.unit}`)}</b> : null}{x.name} <span className="font-mono text-xs text-slate-400">{x.tag}</span></span>
              <button onClick={() => setBasket((b) => b.filter((y) => y.id !== x.id))} className="text-slate-400 hover:text-rose-600" aria-label="remove"><X className="w-4 h-4" /></button></li>))}
          </ul>
          {basket.length > 0 && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2 relative"><div className="label-mono mb-1">{t("qr_multi_borrower")}</div>
                <input className="border border-slate-200 px-3 py-2 text-sm w-full" placeholder={t("qr_multi_search")} value={userQ} autoComplete="off" data-testid="scan-borrower"
                  onChange={(e) => { setUserQ(e.target.value); setBorrower(""); setSuggestOpen(true); }} onFocus={() => setSuggestOpen(true)} onBlur={() => setTimeout(() => setSuggestOpen(false), 150)}
                  onKeyDown={(e) => { if (e.key === "Enter" && suggestOpen && shownUsers[0]) { e.preventDefault(); pickUser(shownUsers[0]); } }} />
                {borrower && <span className="absolute right-3 top-8 text-emerald-600 text-sm">✓</span>}
                {suggestOpen && !borrower && userQ.trim() && (
                  <ul className="absolute z-20 left-0 right-0 mt-1 bg-white border border-slate-200 shadow-lg max-h-60 overflow-y-auto" data-testid="scan-borrower-suggestions">
                    {shownUsers.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">{t("qr_multi_no_user")}</li>}
                    {shownUsers.slice(0, 8).map((u) => (
                      <li key={u.id}><button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => pickUser(u)} className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50">
                        <span className="font-medium text-slate-900">{u.name}</span> <span className="text-slate-500">{u.email}</span></button></li>))}
                  </ul>)}</div>
              <div><div className="label-mono mb-1">{t("qr_multi_until")}</div><input type="datetime-local" className="border border-slate-200 px-3 py-2 text-sm w-full" value={until} onChange={(e) => setUntil(e.target.value)} data-testid="scan-until" /></div>
              <div><div className="label-mono mb-1">{t("qr_multi_class")}</div><input className="border border-slate-200 px-3 py-2 text-sm w-full" value={className} onChange={(e) => setClassName(e.target.value)} /></div>
              <div className="sm:col-span-2"><div className="label-mono mb-1">{t("qr_multi_purpose")}</div><input className="border border-slate-200 px-3 py-2 text-sm w-full" value={purpose} onChange={(e) => setPurpose(e.target.value)} /></div>
              <div className="sm:col-span-2"><div className="label-mono mb-1">{t("qr_multi_photo")}</div>
                <input type="file" accept="image/*" capture="environment" onChange={(e) => pickPhoto(e.target.files[0])} className="text-sm" data-testid="scan-group-photo" />
                {photoBusy && <span className="text-xs text-slate-400 ml-2">…</span>}
                {photo && <span className="text-xs text-emerald-700 ml-2">✓ {t("qr_multi_photo_ok")}</span>}
                <div className="text-xs text-slate-500 mt-1">{t("qr_multi_photo_hint")}</div></div>
              <div className="sm:col-span-2 text-xs text-slate-500">{t("qr_multi_terms")}</div>
              <div className="sm:col-span-2"><Button className="rounded-none" disabled={busy || !borrower || !until} onClick={createCounterLoan} data-testid="scan-create-loan">{t(photo ? "qr_multi_create_out" : "qr_multi_create").replace("{n}", basket.length)}</Button></div>
            </div>)}
        </div>)}
      {result && !multi && <Button variant="outline" className="rounded-none mt-3" onClick={() => setResult(null)} data-testid="scan-next">{t("qr_scan_next")}</Button>}

      {a && !multi && (
        <div className="mt-6 bg-white border border-slate-200 p-5" data-testid="scan-result">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-semibold text-slate-900 text-lg">{a.unit && <span className="text-[11px] font-semibold px-1.5 py-0.5 bg-blue-50 text-blue-800 border border-blue-200 mr-2" data-testid="asset-unit">{t(`unit_${a.unit}`)}</span>}{a.name}</div>
              <div className="text-xs text-slate-500">{[a.brand, a.model].filter(Boolean).join(" ") || a.category} · {campusLabel(a.campus)}</div>
              <div className="font-mono text-xs text-slate-400 mt-1">{a.asset_tag}{a.serial_number ? ` · SN ${a.serial_number}` : ""}</div>
            </div>
            <span className={`text-xs px-2 py-0.5 border ${STATE_STYLE[result.state]}`} data-testid="scan-state">{t(`ln_state_${result.state}`)}</span>
          </div>
          {result.out && <div className="text-sm text-slate-600 mt-3">{t("ln_with")} <b>{result.out.requester_name}</b> · {t("ln_until")} {fmtDateTime(result.out.end_at)}</div>}
          {result.in_use && <div className="text-sm text-slate-600 mt-3">{t("ln_in_use_now")}{result.in_use.requester ? `: ${result.in_use.requester}` : ""}</div>}
          {result.session && <div className="text-sm text-slate-700 mt-3 border border-amber-200 bg-amber-50 px-3 py-2" data-testid="scan-session">
            {t("qr_session")}: <b>{result.session.class_name}</b> · {result.session.teacher_name} · {fmtDateTime(result.session.start)}–{result.session.end.slice(11)} · {result.session.units} unit</div>}
          {result.cart && result.cart.used > 0 && <div className="text-xs text-slate-500 mt-1">{result.cart.name}: {result.cart.used} / {result.cart.capacity} {t("qr_cart_used")}</div>}
          {result.pickup && <div className="text-sm text-slate-600 mt-3">{t("qr_pickup")}: {result.pickup.number} · {result.pickup.requester_name}</div>}
          <div className="flex gap-2 mt-4 flex-wrap">
            {result.suggest?.action === "open_session" && (
              <Button className="rounded-none" disabled={busy} onClick={() => openSession(result.suggest)} data-testid="scan-open-session">{t("qr_handover_session")}</Button>)}
            {result.suggest && result.suggest.action !== "open_session" && (
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
