import { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { Alert, AlertDescription } from "../components/ui/alert";
import { formatErr } from "../lib/api";
import { School, ArrowRight } from "lucide-react";

export default function LoginPage() {
  const { user, login, register } = useAuth();
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
          <div className="w-9 h-9 bg-emerald-600 flex items-center justify-center">
            <School className="w-5 h-5 text-white" strokeWidth={1.75} />
          </div>
          <div>
            <div className="font-display font-semibold text-slate-900 text-base leading-none">
              Lexicon
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500 mt-1">
              School Asset Registry
            </div>
          </div>
        </div>

        <div className="max-w-md w-full mx-auto -mt-12">
          <div className="label-mono mb-4">Welcome back</div>
          <h1 className="font-display text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 leading-tight">
            Manage every asset, from
            <br />
            <span className="text-emerald-700">classroom to campus.</span>
          </h1>
          <p className="text-sm text-slate-600 mt-4 leading-relaxed">
            One source of truth for inventory, ownership, warranty, faults &
            compliance — with depreciation tracked automatically.
          </p>

          <Tabs value={tab} onValueChange={setTab} className="mt-10">
            <TabsList className="grid grid-cols-2 w-full bg-slate-100 rounded-none">
              <TabsTrigger value="login" data-testid="tab-login" className="rounded-none">
                Sign in
              </TabsTrigger>
              <TabsTrigger value="register" data-testid="tab-register" className="rounded-none">
                Create account
              </TabsTrigger>
            </TabsList>

            <TabsContent value="login" className="pt-6">
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <Label htmlFor="login-email" className="label-mono">Email</Label>
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
                  <Label htmlFor="login-password" className="label-mono">Password</Label>
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
                  {submitting ? "Signing in…" : "Sign in"}
                  <ArrowRight className="w-4 h-4 ml-2" strokeWidth={1.75} />
                </Button>
                <div className="text-xs text-slate-500 pt-2 border-t border-slate-200 mt-4">
                  <div className="label-mono mb-2">Demo accounts</div>
                  <div>Admin — admin@school.edu / admin123</div>
                  <div>Staff — staff@school.edu / staff123</div>
                </div>
              </form>
            </TabsContent>

            <TabsContent value="register" className="pt-6">
              <form onSubmit={handleRegister} className="space-y-4">
                <div>
                  <Label htmlFor="reg-name" className="label-mono">Full name</Label>
                  <Input id="reg-name" required value={regName} onChange={(e)=>setRegName(e.target.value)}
                    className="mt-2 rounded-none border-slate-300" data-testid="register-name-input" />
                </div>
                <div>
                  <Label htmlFor="reg-email" className="label-mono">Email</Label>
                  <Input id="reg-email" type="email" required value={regEmail} onChange={(e)=>setRegEmail(e.target.value)}
                    className="mt-2 rounded-none border-slate-300" data-testid="register-email-input" />
                </div>
                <div>
                  <Label htmlFor="reg-dept" className="label-mono">Department</Label>
                  <Input id="reg-dept" value={regDept} onChange={(e)=>setRegDept(e.target.value)}
                    placeholder="e.g. Science Department"
                    className="mt-2 rounded-none border-slate-300" data-testid="register-dept-input" />
                </div>
                <div>
                  <Label htmlFor="reg-password" className="label-mono">Password</Label>
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
                  {submitting ? "Creating…" : "Create staff account"}
                </Button>
              </form>
            </TabsContent>
          </Tabs>
        </div>

        <div className="text-xs text-slate-400">
          © {new Date().getFullYear()} Lexicon Asset Registry
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
          <div className="label-mono text-emerald-300 mb-3">Built for schools</div>
          <p className="font-display text-2xl leading-tight max-w-md">
            "We replaced four spreadsheets and a clipboard. Inventory now closes
            in hours, not weeks."
          </p>
          <div className="mt-6 text-sm text-slate-300">
            Operations Director — Westwood Preparatory
          </div>
        </div>
      </div>
    </div>
  );
}
