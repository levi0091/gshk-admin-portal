import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext.jsx'
import LoginPage from './pages/LoginPage.jsx'
import UserManagementPage from './pages/UserManagementPage.jsx'
import RoleManagementPage from './pages/RoleManagementPage.jsx'
import AuditLogPage from './pages/AuditLogPage.jsx'
import AppShell from './components/AppShell.jsx'

function RequireAuth({ children }) {
  const { session } = useAuth()
  if (session === undefined) return null // loading
  if (!session) return <Navigate to="/login" replace />
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
          <Route index element={<Navigate to="/users" replace />} />
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
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
