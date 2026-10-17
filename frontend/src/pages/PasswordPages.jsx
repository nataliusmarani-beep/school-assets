import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api, { formatErr } from "../lib/api";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Alert, AlertDescription } from "../components/ui/alert";

function Shell({ title, sub, children }) {
  const { t } = useLang();
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md bg-white border border-slate-200 p-8">
        <div className="flex items-center gap-3 mb-8">
          <img src={require("../ypj-logo.png")} alt="YPJ" className="w-9 h-9 object-contain" />
          <div>
            <div className="font-display font-semibold text-slate-900 leading-none">Yayasan Pendidikan Jayawijaya</div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">{t("brand_subtitle")}</div>
          </div>
        </div>
        <h1 className="font-display text-2xl font-semibold text-slate-900">{title}</h1>
        {sub && <p className="text-sm text-slate-600 mt-2 leading-relaxed">{sub}</p>}
        <div className="mt-6">{children}</div>
      </div>
    </div>
  );
}

/* Public page opened from the invitation / reset e-mail: /set-password?token=… */
export function SetPasswordPage() {
  const { t } = useLang();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [info, setInfo] = useState(null); // null = checking
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    api.get(`/auth/password-token/${encodeURIComponent(token)}`)
      .then((r) => setInfo(r.data)).catch(() => setInfo({ valid: false }));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (pw.length < 6) return setError(t("sp_too_short"));
    if (pw !== pw2) return setError(t("sp_mismatch"));
    setBusy(true);
    try { await api.post("/auth/set-password", { token, password: pw }); setDone(true); setTimeout(() => navigate("/login"), 2500); }
    catch (err) { setError(formatErr(err)); }
    finally { setBusy(false); }
  };

  if (!info) return <Shell title={t("loading")} />;
  if (!info.valid) return (
    <Shell title={t("sp_invalid_title")} sub={t("sp_invalid_sub")}>
      <Link to="/forgot-password" className="text-sm text-blue-800 underline" data-testid="sp-request-new">{t("sp_request_new")}</Link>
    </Shell>
  );
  if (done) return (
    <Shell title={t("sp_done_title")} sub={t("sp_done_sub")}>
      <Link to="/login" className="text-sm text-blue-800 underline">{t("tab_signin")}</Link>
    </Shell>
  );
  return (
    <Shell title={info.kind === "invite" ? t("sp_title_invite") : t("sp_title_reset")}
      sub={`${info.name} · ${info.email}`}>
      <form onSubmit={submit} className="space-y-4" data-testid="set-password-form">
        <div><Label className="label-mono">{t("sp_new")}</Label>
          <Input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className="mt-2 rounded-none" data-testid="sp-new" autoComplete="new-password" /></div>
        <div><Label className="label-mono">{t("sp_confirm")}</Label>
          <Input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} className="mt-2 rounded-none" data-testid="sp-confirm" autoComplete="new-password" /></div>
        {error && <Alert variant="destructive"><AlertDescription data-testid="sp-error">{error}</AlertDescription></Alert>}
        <Button type="submit" disabled={busy} className="w-full rounded-none bg-slate-900 hover:bg-slate-800 h-11" data-testid="sp-submit">
          {busy ? t("loading") : t("sp_save")}
        </Button>
      </form>
    </Shell>
  );
}

/* Public page: asks for the e-mail and sends a reset link (answer is always the same). */
export function ForgotPasswordPage() {
  const { t } = useLang();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { await api.post("/auth/forgot-password", { email }); setSent(true); }
    catch (err) { setError(formatErr(err)); }
    finally { setBusy(false); }
  };

  return (
    <Shell title={t("fp_title")} sub={sent ? t("fp_sent") : t("fp_sub")}>
      {!sent && (
        <form onSubmit={submit} className="space-y-4" data-testid="forgot-form">
          <div><Label className="label-mono">{t("email")}</Label>
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-2 rounded-none" data-testid="fp-email" /></div>
          {error && <div className="text-sm text-red-600">{error}</div>}
          <Button type="submit" disabled={busy} className="w-full rounded-none bg-slate-900 hover:bg-slate-800 h-11" data-testid="fp-submit">
            {busy ? t("loading") : t("fp_send")}
          </Button>
        </form>
      )}
      <div className="mt-6"><Link to="/login" className="text-sm text-blue-800 underline">{t("fp_back")}</Link></div>
    </Shell>
  );
}
