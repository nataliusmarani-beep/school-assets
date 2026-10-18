import "./App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { LangProvider } from "./context/LangContext";
import ProtectedRoute from "./components/layout/ProtectedRoute";
import AppLayout from "./components/layout/AppLayout";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import AssetsListPage from "./pages/AssetsListPage";
import AssetFormPage from "./pages/AssetFormPage";
import AssetDetailPage from "./pages/AssetDetailPage";
import FaultsPage from "./pages/FaultsPage";
import CompliancePage from "./pages/CompliancePage";
import UsersPage from "./pages/UsersPage";
import ReportsPage from "./pages/ReportsPage";
import ActivityLogsPage from "./pages/ActivityLogsPage";
import HelpPage from "./pages/HelpPage";
import PoliciesPage from "./pages/PoliciesPage";
import TransferRequestsPage from "./pages/TransferRequestsPage";
import LoansPage from "./pages/LoansPage";
import LoanDetailPage from "./pages/LoanDetailPage";
import SchedulePage from "./pages/SchedulePage";
import LoanSetupPage from "./pages/LoanSetupPage";
import MyAssetsPage from "./pages/MyAssetsPage";
import UserAssetsPage from "./pages/UserAssetsPage";
import ClassroomsPage from "./pages/ClassroomsPage";
import ClassroomDetailPage from "./pages/ClassroomDetailPage";
import { SetPasswordPage, ForgotPasswordPage } from "./pages/PasswordPages";
import { Toaster } from "./components/ui/sonner";

function Layout({ children }) {
  return <AppLayout>{children}</AppLayout>;
}

function App() {
  return (
    <div className="App">
      <LangProvider>
      <AuthProvider>
        <BrowserRouter>
          <Toaster richColors position="top-right" />
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/set-password" element={<SetPasswordPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/" element={
              <ProtectedRoute><Layout><DashboardPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/assets" element={
              <ProtectedRoute><Layout><AssetsListPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/assets/new" element={
              <ProtectedRoute><Layout><AssetFormPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/assets/:id" element={
              <ProtectedRoute><Layout><AssetDetailPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/assets/:id/edit" element={
              <ProtectedRoute><Layout><AssetFormPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/my-assets" element={
              <ProtectedRoute><Layout><MyAssetsPage /></Layout></ProtectedRoute>
            } />
            <Route path="/user-assets" element={
              <ProtectedRoute adminOnly><Layout><UserAssetsPage /></Layout></ProtectedRoute>
            } />
            <Route path="/classrooms" element={
              <ProtectedRoute><Layout><ClassroomsPage /></Layout></ProtectedRoute>
            } />
            <Route path="/classrooms/:id" element={
              <ProtectedRoute><Layout><ClassroomDetailPage /></Layout></ProtectedRoute>
            } />
            <Route path="/faults" element={
              <ProtectedRoute><Layout><FaultsPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/compliance" element={
              <ProtectedRoute><Layout><CompliancePage /></Layout></ProtectedRoute>
            }/>
            <Route path="/users" element={
              <ProtectedRoute adminOnly><Layout><UsersPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/reports" element={
              <ProtectedRoute><Layout><ReportsPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/activity-logs" element={
              <ProtectedRoute adminOnly><Layout><ActivityLogsPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/transfer-requests" element={
              <ProtectedRoute><Layout><TransferRequestsPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/loans" element={
              <ProtectedRoute><Layout><LoansPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/schedule" element={
              <ProtectedRoute><Layout><SchedulePage /></Layout></ProtectedRoute>
            }/>
            <Route path="/loans/setup" element={
              <ProtectedRoute><Layout><LoanSetupPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/loans/:id" element={
              <ProtectedRoute><Layout><LoanDetailPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/loan-requests" element={<Navigate to="/loans" replace />} />
            <Route path="/help" element={
              <ProtectedRoute><Layout><HelpPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/policies" element={
              <ProtectedRoute><Layout><PoliciesPage /></Layout></ProtectedRoute>
            }/>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      </LangProvider>
    </div>
  );
}

export default App;
