import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { useLang } from "../../context/LangContext";
import {
  LayoutDashboard,
  CalendarDays,
  ScanLine,
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
  ArrowRightLeft,
  BookOpen,
  ScrollText,
  UserCheck,
  ListChecks,
  School,
  Laptop,
} from "lucide-react";
import { useState, useEffect } from "react";
import api from "../../lib/api";
import { toast } from "sonner";
import { isManagerRole } from "../../lib/roles";

const NAV_LINKS = [
  { to: "/", labelKey: "nav_dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
  { to: "/assets", labelKey: "nav_assets", icon: Boxes, testid: "nav-assets" },
  { to: "/my-assets", labelKey: "nav_my_assets", icon: UserCheck, testid: "nav-my-assets", badge: "pendingMine" },
  { to: "/user-assets", labelKey: "nav_user_assets", icon: ListChecks, testid: "nav-user-assets", adminOnly: true },
  { to: "/classrooms", labelKey: "nav_classrooms", icon: School, testid: "nav-classrooms" },
  { to: "/faults", labelKey: "nav_faults", icon: Wrench, testid: "nav-faults" },
  { to: "/compliance", labelKey: "nav_compliance", icon: ShieldCheck, testid: "nav-compliance" },
  { to: "/transfer-requests", labelKey: "nav_transfer_requests", icon: ArrowRightLeft, testid: "nav-transfers", badge: "pendingTransfers" },
  { to: "/loans", labelKey: "nav_loan_requests", icon: BookOpen, testid: "nav-loans", badge: "pendingLoans" },
  { to: "/schedule", labelKey: "nav_schedule", icon: CalendarDays, testid: "nav-schedule" },
  { to: "/byod", labelKey: "nav_byod", icon: Laptop, testid: "nav-byod" },
  { to: "/scan", labelKey: "nav_scan", icon: ScanLine, testid: "nav-scan", roles: ["super_admin", "admin", "campus_admin", "ict_admin"] },
  { to: "/users", labelKey: "nav_users", icon: Users, testid: "nav-users", roles: ["super_admin", "admin", "campus_admin"] },
  { to: "/reports", labelKey: "nav_reports", icon: BarChart3, testid: "nav-reports", roles: ["super_admin", "admin", "campus_admin", "leader", "ict_admin"] },
  { to: "/activity-logs", labelKey: "nav_activity", icon: History, testid: "nav-activity", adminOnly: true },
  { to: "/policies", labelKey: "nav_policies", icon: ScrollText, testid: "nav-policies" },
  { to: "/help", labelKey: "nav_help", icon: HelpCircle, testid: "nav-help" },
];

export default function AppLayout({ children }) {
  const { user, logout } = useAuth();
  const { lang, setLang, t } = useLang();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [backing, setBacking] = useState(false);
  const [pendingTransfers, setPendingTransfers] = useState(0);
  const [pendingLoans, setPendingLoans] = useState(0);
  const [pendingMine, setPendingMine] = useState(0);

  // hand-overs waiting for MY confirmation (every user)
  useEffect(() => {
    if (!user) return;
    const fetchMine = () => api.get("/assignments/pending-count").then((r) => setPendingMine(r.data.mine)).catch(() => {});
    fetchMine();
    const interval = setInterval(fetchMine, 60000);
    window.addEventListener("assignments-changed", fetchMine);
    return () => { clearInterval(interval); window.removeEventListener("assignments-changed", fetchMine); };
  }, [user]);

  useEffect(() => {
    if (!user) return;
    const fetchCounts = () => {
      if (isManagerRole(user.role)) api.get("/transfer-requests/pending-count").then((r) => setPendingTransfers(r.data.count)).catch(() => {});
      // loan badge: requests waiting for me as ICT / supervisor
      api.get("/loans/pending-count").then((r) => setPendingLoans(r.data.count)).catch(() => {});
    };
    fetchCounts();
    const interval = setInterval(fetchCounts, 60000);
    return () => clearInterval(interval);
  }, [user]);

  const canBackup = user?.role === "super_admin" || user?.role === "campus_admin";   // Campus Admin gets a copy of their own campus only
  const visibleLinks = NAV_LINKS.filter((l) => (l.roles ? l.roles.includes(user?.role) : !l.adminOnly || isManagerRole(user?.role)));

  const handleBackup = async () => {
    setBacking(true);
    try {
      const res = await api.get("/backup", { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      const slug = user?.role === "campus_admin" && user?.campus ? "-" + user.campus.toLowerCase().replace(/[^a-z0-9]+/g, "-") : "";
      a.download = `ypj-backup${slug}-${new Date().toISOString().split("T")[0]}.db`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(t("backup_ok"));
    } catch {
      toast.error(t("backup_err"));
    } finally {
      setBacking(false);
    }
  };

  const LangToggle = ({ dark, amber }) => (
    <div className={`flex items-center gap-0.5 ${dark ? "" : "border border-slate-200 p-0.5"}`}>
      {["EN", "ID"].map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className={`px-2.5 py-1 text-xs font-mono font-medium transition-colors ${
            lang === l
              ? amber ? "bg-slate-900 text-white" : dark ? "bg-white text-slate-900" : "bg-slate-900 text-white"
              : amber ? "text-slate-900/70 hover:text-slate-900" : dark ? "text-slate-400 hover:text-white" : "text-slate-500 hover:text-slate-900"
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
              Yayasan Pendidikan Jayawijaya
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-slate-400 mt-1">
              {t("brand_subtitle")}
            </div>
          </div>
        </Link>
      </div>

      <nav className="flex-1 px-3 py-6 overflow-y-auto">
        <div className="label-mono px-3 mb-3 text-slate-500">{t("nav_section")}</div>
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
              <span className="flex-1">{t(l.labelKey)}</span>
              {l.badge === "pendingTransfers" && pendingTransfers > 0 && (
                <span className="text-[10px] font-bold bg-amber-400 text-slate-900 rounded-full w-4 h-4 flex items-center justify-center flex-shrink-0">
                  {pendingTransfers > 9 ? "9+" : pendingTransfers}
                </span>
              )}
              {l.badge === "pendingMine" && pendingMine > 0 && (
                <span data-testid="badge-my-assets" className="text-[10px] font-bold bg-amber-400 text-slate-900 rounded-full w-4 h-4 flex items-center justify-center flex-shrink-0">
                  {pendingMine > 9 ? "9+" : pendingMine}
                </span>
              )}
              {l.badge === "pendingLoans" && pendingLoans > 0 && (
                <span className="text-[10px] font-bold bg-amber-400 text-slate-900 rounded-full w-4 h-4 flex items-center justify-center flex-shrink-0">
                  {pendingLoans > 9 ? "9+" : pendingLoans}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      <div className="px-3 pb-6 border-t border-slate-800 pt-4 space-y-4">
        {canBackup && (
          <button
            onClick={handleBackup}
            disabled={backing}
            className="w-full flex items-center justify-center gap-2 bg-amber-400 hover:bg-amber-300 text-slate-900 font-semibold text-sm px-3 py-2.5 transition-colors disabled:opacity-60"
          >
            <DatabaseBackup className="w-4 h-4" strokeWidth={1.75} />
            {backing ? t("backing_up") : t("backup")}
          </button>
        )}

        {/* Staff have no Backup button, so the language area takes the same amber highlight */}
        <div className={canBackup ? "px-1" : "bg-amber-400 px-3 py-3"} data-testid="sidebar-language">
          <div className={`label-mono mb-2 ${canBackup ? "text-slate-500" : "text-slate-800"}`}>{t("lang_label")}</div>
          <LangToggle dark amber={!canBackup} />
        </div>

        <div className="border-t border-slate-800 pt-4">
          <div className="px-2 py-1">
            <div className="label-mono text-slate-500 mb-1">{t("signed_in_as")}</div>
            <div className="text-sm text-white truncate" data-testid="current-user-name">
              {user?.name}
            </div>
            <div className="text-xs text-slate-500 capitalize">{user?.role === "super_admin" ? t("super_admin") : user?.role}</div>
          </div>
          <button
            data-testid="logout-button"
            onClick={async () => { await logout(); navigate("/login"); }}
            className="w-full mt-2 flex items-center gap-2 px-2 py-2 text-sm text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <LogOut className="w-4 h-4" strokeWidth={1.75} />
            {t("sign_out")}
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="hidden md:flex w-64 bg-slate-950 text-white flex-col fixed inset-y-0 left-0 z-40">
        <SidebarContent />
      </aside>

      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div className="fixed inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="relative w-64 bg-slate-950 text-white flex flex-col">
            <SidebarContent />
          </aside>
        </div>
      )}

      <div className="flex-1 md:ml-64 flex flex-col min-w-0">
        <header className="h-14 bg-white border-b border-slate-200 px-4 md:px-8 flex items-center justify-between sticky top-0 z-30">
          <button
            className="md:hidden p-2 -ml-2"
            onClick={() => setMobileOpen(true)}
            data-testid="mobile-menu-button"
          >
            <Menu className="w-5 h-5" strokeWidth={1.75} />
          </button>
          <div className="hidden md:block label-mono">{t("topbar_title")}</div>
          <div className="flex items-center gap-3">
            <div className="hidden sm:block">
              <LangToggle />
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
