import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext.jsx'
import LoginPage from './pages/LoginPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import CompanyRegistryPage from './pages/CompanyRegistryPage.jsx'
import CompanyProfilePage from './pages/CompanyProfilePage.jsx'
import CaseWorkflowPage from './pages/CaseWorkflowPage.jsx'
import PersonsRegistryPage from './pages/PersonsRegistryPage.jsx'
import PersonProfilePage from './pages/PersonProfilePage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import CrCredentialsPage from './pages/CrCredentialsPage.jsx'
import UserManagementPage from './pages/UserManagementPage.jsx'
import SetPasswordPage from './pages/SetPasswordPage.jsx'
import RoleManagementPage from './pages/RoleManagementPage.jsx'
import AuditLogPage from './pages/AuditLogPage.jsx'
import AppShell from './components/AppShell.jsx'

function RequireAuth({ children }) {
  const { session, mustChangePassword, profileLoading } = useAuth()
  if (session === undefined) return null // loading
  if (!session) return <Navigate to="/login" replace />
  // Spec §7. Rendered IN PLACE rather than redirected to a route, so there is
  // no URL a new user can navigate back out to. This is the courtesy layer:
  // `middleware/auth` refuses every API route while the flag is set, so
  // someone who defeats this gets 409s rather than a working portal.
  //
  // Waits for /auth/me, like RequireSuperAdmin does — deciding before the
  // profile resolves would flash this screen at every signed-in user on every
  // reload.
  if (!profileLoading && mustChangePassword) return <SetPasswordPage />
  return children
}

function RequireSuperAdmin({ children }) {
  const { isSuperAdmin, profileLoading } = useAuth()
  // Wait for /auth/me to resolve before deciding — prevents redirect loop on slow/failing backend
  if (profileLoading) return null
  if (!isSuperAdmin) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="registry" element={<CompanyRegistryPage />} />
          <Route path="companies/:companyId" element={<CompanyProfilePage />} />
          {/* The case dashboard opens a case directly, not the company. */}
          <Route path="cases/:caseId" element={<CaseWorkflowPage />} />
          <Route path="persons" element={<PersonsRegistryPage />} />
          <Route path="persons/:personId" element={<PersonProfilePage />} />
          <Route
            path="users"
            element={
              <RequireSuperAdmin>
                <UserManagementPage />
              </RequireSuperAdmin>
            }
          />
          <Route
            path="roles"
            element={
              <RequireSuperAdmin>
                <RoleManagementPage />
              </RequireSuperAdmin>
            }
          />
          <Route path="audit-log" element={<AuditLogPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="cr-credentials" element={<CrCredentialsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
