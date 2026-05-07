import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import {
  LayoutDashboard,
  Boxes,
  Wrench,
  ShieldCheck,
  Users,
  LogOut,
  Menu,
  BarChart3,
  History,
  HelpCircle,
  DatabaseBackup,
} from "lucide-react";
import { useState, useCallback } from "react";
import api from "../../lib/api";
import { toast } from "sonner";

const links = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
  { to: "/assets", label: "Assets", icon: Boxes, testid: "nav-assets" },
  { to: "/faults", label: "Faults", icon: Wrench, testid: "nav-faults" },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck, testid: "nav-compliance" },
  { to: "/users", label: "Users", icon: Users, testid: "nav-users", adminOnly: true },
  { to: "/reports", label: "Reports", icon: BarChart3, testid: "nav-reports" },
  { to: "/activity-logs", label: "Activity logs", icon: History, testid: "nav-activity", adminOnly: true },
  { to: "/help", label: "Help & Guide", icon: HelpCircle, testid: "nav-help" },
];

function useLang() {
  const [lang, setLangState] = useState(() => localStorage.getItem("lang") || "EN");
  const setLang = useCallback((l) => {
    localStorage.setItem("lang", l);
    setLangState(l);
  }, []);
  return [lang, setLang];
}

export default function AppLayout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [lang, setLang] = useLang();
  const [backing, setBacking] = useState(false);

  const visibleLinks = links.filter((l) => !l.adminOnly || user?.role === "admin");

  const handleBackup = async () => {
    setBacking(true);
    try {
      const res = await api.get("/backup", { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ypj-backup-${new Date().toISOString().split("T")[0]}.db`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Backup downloaded");
    } catch {
      toast.error("Backup not available yet");
    } finally {
      setBacking(false);
    }
  };

  const LangToggle = ({ compact }) => (
    <div className={compact ? "flex items-center gap-1" : "flex gap-1"}>
      {["EN", "ID"].map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className={`px-2.5 py-1 text-xs font-mono font-medium transition-colors ${
            lang === l
              ? "bg-white text-slate-900"
              : "text-slate-400 hover:text-white"
          }`}
        >
          {l}
        </button>
      ))}
    </div>
  );

  const SidebarContent = () => (
    <>
      <div className="px-6 pt-8 pb-6 border-b border-slate-800">
        <Link to="/" className="flex items-center gap-3 group" data-testid="brand-logo">
          <img src={require("../../ypj-logo.png")} alt="YPJ Logo" className="w-9 h-9 object-contain" />
          <div>
            <div className="font-display font-semibold text-white text-base leading-none">
              YPJ School
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400 mt-1">
              Asset Registry
            </div>
          </div>
        </Link>
      </div>

      <nav className="flex-1 px-3 py-6 overflow-y-auto">
        <div className="label-mono px-3 mb-3 text-slate-500">Navigation</div>
        <div className="space-y-1">
          {visibleLinks.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.to === "/"}
              data-testid={l.testid}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                `sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm border-l-2 transition-colors ${
                  isActive
                    ? "border-blue-500 bg-white/5 text-white"
                    : "border-transparent text-slate-400 hover:text-white hover:bg-white/5"
                }`
              }
            >
              <l.icon className="w-4 h-4" strokeWidth={1.75} />
              <span>{l.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>

      <div className="px-3 pb-6 border-t border-slate-800 pt-4 space-y-4">
        {/* Backup */}
        <button
          onClick={handleBackup}
          disabled={backing}
          className="w-full flex items-center justify-center gap-2 bg-amber-400 hover:bg-amber-300 text-slate-900 font-semibold text-sm px-3 py-2.5 transition-colors disabled:opacity-60"
        >
          <DatabaseBackup className="w-4 h-4" strokeWidth={1.75} />
          {backing ? "Backing up…" : "Backup"}
        </button>

        {/* Language */}
        <div className="px-1">
          <div className="label-mono text-slate-500 mb-2">Language</div>
          <LangToggle />
        </div>

        {/* User */}
        <div className="border-t border-slate-800 pt-4">
          <div className="px-2 py-1">
            <div className="label-mono text-slate-500 mb-1">Signed in as</div>
            <div className="text-sm text-white truncate" data-testid="current-user-name">
              {user?.name}
            </div>
            <div className="text-xs text-slate-500 capitalize">{user?.role}</div>
          </div>
          <button
            data-testid="logout-button"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
            className="w-full mt-2 flex items-center gap-2 px-2 py-2 text-sm text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <LogOut className="w-4 h-4" strokeWidth={1.75} />
            Sign out
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-screen flex bg-slate-50">
      {/* Desktop Sidebar */}
      <aside className="hidden md:flex w-64 bg-slate-950 text-white flex-col fixed inset-y-0 left-0 z-40">
        <SidebarContent />
      </aside>

      {/* Mobile Sidebar */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-black/50"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="relative w-64 bg-slate-950 text-white flex flex-col">
            <SidebarContent />
          </aside>
        </div>
      )}

      {/* Main */}
      <div className="flex-1 md:ml-64 flex flex-col min-w-0">
        <header className="h-14 bg-white border-b border-slate-200 px-4 md:px-8 flex items-center justify-between sticky top-0 z-30">
          <button
            className="md:hidden p-2 -ml-2"
            onClick={() => setMobileOpen(true)}
            data-testid="mobile-menu-button"
          >
            <Menu className="w-5 h-5" strokeWidth={1.75} />
          </button>
          <div className="hidden md:block label-mono">School Assets Management</div>
          <div className="flex items-center gap-3">
            {/* Language toggle in topbar */}
            <div className="hidden sm:flex items-center gap-0.5 border border-slate-200 p-0.5">
              {["EN", "ID"].map((l) => (
                <button
                  key={l}
                  onClick={() => setLang(l)}
                  className={`px-2.5 py-1 text-xs font-mono font-medium transition-colors ${
                    lang === l
                      ? "bg-slate-900 text-white"
                      : "text-slate-500 hover:text-slate-900"
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
            <div className="hidden sm:block text-right">
              <div className="text-xs text-slate-500">{user?.department || "—"}</div>
            </div>
            <div className="w-8 h-8 bg-slate-900 text-white flex items-center justify-center text-xs font-medium">
              {user?.name?.[0]?.toUpperCase()}
            </div>
          </div>
        </header>
        <main className="flex-1 overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}
