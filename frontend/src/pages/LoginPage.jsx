import { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useLang } from "../context/LangContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Alert, AlertDescription } from "../components/ui/alert";
import { formatErr } from "../lib/api";
import { ArrowRight } from "lucide-react";

export default function LoginPage() {
  const { user, login, register } = useAuth();
  const { t } = useLang();
  const navigate = useNavigate();
  const [tab, setTab] = useState("login");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [loginEmail, setLoginEmail] = useState("admin@school.edu");
  const [loginPassword, setLoginPassword] = useState("admin123");

  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regDept, setRegDept] = useState("");

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

  const handleRegister = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await register({
        email: regEmail,
        password: regPassword,
        name: regName,
        role: "staff",
        department: regDept,
      });
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

          <Tabs value={tab} onValueChange={setTab} className="mt-10">
            <TabsList className="grid grid-cols-2 w-full bg-slate-100 rounded-none">
              <TabsTrigger value="login" data-testid="tab-login" className="rounded-none">
                {t("tab_signin")}
              </TabsTrigger>
              <TabsTrigger value="register" data-testid="tab-register" className="rounded-none">
                {t("tab_register")}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="login" className="pt-6">
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <Label htmlFor="login-email" className="label-mono">{t("email")}</Label>
                  <Input
                    id="login-email"
                    type="email"
                    required
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
                <div className="text-xs text-slate-500 pt-2 border-t border-slate-200 mt-4">
                  <div className="label-mono mb-2">{t("demo_accounts")}</div>
                  <div>Admin — admin@school.edu / admin123</div>
                  <div>Staff — staff@school.edu / staff123</div>
                </div>
              </form>
            </TabsContent>

            <TabsContent value="register" className="pt-6">
              <form onSubmit={handleRegister} className="space-y-4">
                <div>
                  <Label htmlFor="reg-name" className="label-mono">{t("full_name")}</Label>
                  <Input id="reg-name" required value={regName} onChange={(e)=>setRegName(e.target.value)}
                    className="mt-2 rounded-none border-slate-300" data-testid="register-name-input" />
                </div>
                <div>
                  <Label htmlFor="reg-email" className="label-mono">{t("email")}</Label>
                  <Input id="reg-email" type="email" required value={regEmail} onChange={(e)=>setRegEmail(e.target.value)}
                    className="mt-2 rounded-none border-slate-300" data-testid="register-email-input" />
                </div>
                <div>
                  <Label htmlFor="reg-dept" className="label-mono">{t("department")}</Label>
                  <Input id="reg-dept" value={regDept} onChange={(e)=>setRegDept(e.target.value)}
                    placeholder={t("dept_placeholder")}
                    className="mt-2 rounded-none border-slate-300" data-testid="register-dept-input" />
                </div>
                <div>
                  <Label htmlFor="reg-password" className="label-mono">{t("password")}</Label>
                  <Input id="reg-password" type="password" required minLength={6}
                    value={regPassword} onChange={(e)=>setRegPassword(e.target.value)}
                    className="mt-2 rounded-none border-slate-300" data-testid="register-password-input" />
                </div>
                {error && (
                  <Alert variant="destructive" data-testid="register-error">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                <Button type="submit" disabled={submitting} data-testid="register-submit-button"
                  className="w-full rounded-none bg-slate-900 hover:bg-slate-800 h-11">
                  {submitting ? t("creating") : t("create_staff")}
                </Button>
              </form>
            </TabsContent>
          </Tabs>
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
