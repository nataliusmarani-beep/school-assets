import { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Alert, AlertDescription } from "../components/ui/alert";
import { formatErr } from "../lib/api";
import { ArrowRight } from "lucide-react";

export default function LoginPage() {
  const { user, login } = useAuth();
  const { t } = useLang();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  if (user) return <Navigate to="/" replace />;

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(loginEmail, loginPassword);
      navigate("/");
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* Left: Form */}
      <div className="flex flex-col justify-between bg-white px-8 py-10 sm:px-16">
        <div className="flex items-center gap-3">
          <img src={require("../ypj-logo.png")} alt="YPJ Logo" className="w-9 h-9 object-contain" />
          <div>
            <div className="font-display font-semibold text-slate-900 text-base leading-none">
              YPJ School
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">
              {t("brand_subtitle")}
            </div>
          </div>
        </div>

        <div className="max-w-md w-full mx-auto -mt-12">
          <div className="label-mono mb-4">{t("welcome_back")}</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 leading-tight">
            {t("login_tagline").split("classroom to campus.")[0]}
            <br />
            <span className="text-blue-800">classroom to campus.</span>
          </h1>
          <p className="text-sm text-slate-600 mt-4 leading-relaxed">
            {t("login_sub")}
          </p>

          <form onSubmit={handleLogin} className="mt-10 space-y-4">
            <div>
              <Label htmlFor="login-email" className="label-mono">{t("email")}</Label>
              <Input
                id="login-email"
                type="email"
                required
                placeholder="you@fmi.com"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                className="mt-2 rounded-none border-slate-300"
                data-testid="login-email-input"
              />
            </div>
            <div>
              <Label htmlFor="login-password" className="label-mono">{t("password")}</Label>
              <Input
                id="login-password"
                type="password"
                required
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                className="mt-2 rounded-none border-slate-300"
                data-testid="login-password-input"
              />
            </div>
            {error && (
              <Alert variant="destructive" data-testid="login-error">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Button
              type="submit"
              disabled={submitting}
              data-testid="login-submit-button"
              className="w-full rounded-none bg-slate-900 hover:bg-slate-800 h-11"
            >
              {submitting ? t("signing_in") : t("tab_signin")}
              <ArrowRight className="w-4 h-4 ml-2" strokeWidth={1.75} />
            </Button>
          </form>
        </div>

        <div className="text-xs text-slate-400">
          © {new Date().getFullYear()} {t("footer_copy")}
        </div>
      </div>

      {/* Right: Hero */}
      <div className="hidden lg:block relative overflow-hidden">
        <img
          src="https://images.unsplash.com/photo-1759299615947-bc798076b479?crop=entropy&cs=srgb&fm=jpg&q=85"
          alt="School campus"
          className="absolute inset-0 w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-slate-900/60" />
        <div className="relative h-full flex flex-col justify-end p-12 text-white">
          <div className="label-mono text-blue-300 mb-3">{t("login_hero_label")}</div>
          <p className="font-display text-2xl leading-tight max-w-md">
            {t("login_hero_quote")}
          </p>
          <div className="mt-6 text-sm text-slate-300">
            {t("login_hero_attr")}
          </div>
        </div>
      </div>
    </div>
  );
}
