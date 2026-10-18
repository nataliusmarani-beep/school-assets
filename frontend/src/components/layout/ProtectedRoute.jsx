import { Navigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { isAdminRole } from "../../lib/roles";
import PolicyAgreementModal from "./PolicyAgreementModal";

export default function ProtectedRoute({ children, adminOnly = false }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-500">Loading…</div>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  if (adminOnly && !isAdminRole(user.role)) return <Navigate to="/" replace />;
  // Nobody uses the app before confirming the current policies (re-asked whenever the version changes).
  if (user.policy_required && !user.policy_accepted) return <PolicyAgreementModal />;
  return children;
}
