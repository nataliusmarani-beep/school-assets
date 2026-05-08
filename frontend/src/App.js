import "./App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
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
import TransferRequestsPage from "./pages/TransferRequestsPage";
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
              <ProtectedRoute adminOnly><Layout><TransferRequestsPage /></Layout></ProtectedRoute>
            }/>
            <Route path="/help" element={
              <ProtectedRoute><Layout><HelpPage /></Layout></ProtectedRoute>
            }/>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      </LangProvider>
    </div>
  );
}

export default App;
