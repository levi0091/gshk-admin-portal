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
import HomePage from './pages/HomePage.jsx'
import AppShell from './components/AppShell.jsx'
import RequirePermission, { NoAccess } from './components/RequirePermission.jsx'

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
  // NOT `<Navigate to="/login">`. Bouncing a signed-in user to the sign-in
  // screen says "you are not logged in" about somebody who is, and the login
  // page then either sits there or bounces them straight back. The honest
  // answer to "you may not open this" is to say so.
  if (!isSuperAdmin) return <NoAccess title="Super Admins only" />
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
          {/* NOT a bare redirect to /dashboard any more. That screen needs
              `nar1:read`, and sending every signed-in user to it dropped roles
              without that permission onto a page that answered 403 — while the
              sidebar, which IS gated, showed nothing at all. HomePage sends
              each role to the first screen its own menu offers. */}
          <Route index element={<HomePage />} />
          <Route path="dashboard" element={
            <RequirePermission module="nar1" permission="read">
              <DashboardPage />
            </RequirePermission>
          } />
          <Route path="registry" element={
            <RequirePermission module="companies" permission="read">
              <CompanyRegistryPage />
            </RequirePermission>
          } />
          <Route path="companies/:companyId" element={
            <RequirePermission module="companies" permission="read">
              <CompanyProfilePage />
            </RequirePermission>
          } />
          {/* The case dashboard opens a case directly, not the company. */}
          <Route path="cases/:caseId" element={
            <RequirePermission module="nar1" permission="read">
              <CaseWorkflowPage />
            </RequirePermission>
          } />
          <Route path="persons" element={
            <RequirePermission module="persons" permission="read">
              <PersonsRegistryPage />
            </RequirePermission>
          } />
          <Route path="persons/:personId" element={
            <RequirePermission module="persons" permission="read">
              <PersonProfilePage />
            </RequirePermission>
          } />
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
          <Route path="audit-log" element={
            <RequirePermission module="audit_trail" permission="read">
              <AuditLogPage />
            </RequirePermission>
          } />
          {/* The one screen every signed-in user may open, whatever their role
              holds — it is where they read what their role holds. */}
          <Route path="settings" element={<SettingsPage />} />
          {/* tpsi:read views the credential metadata; the page gates saving on
              tpsi:write itself. */}
          <Route path="cr-credentials" element={
            <RequirePermission module="tpsi" permission="read">
              <CrCredentialsPage />
            </RequirePermission>
          } />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
