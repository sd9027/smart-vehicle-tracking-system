import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { EmptyState, Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import Dashboard from './pages/Dashboard'
import Drivers from './pages/Drivers'
import Expenses from './pages/Expenses'
import Login from './pages/Login'
import Reports from './pages/Reports'
import Tracking from './pages/Tracking'
import Transactions from './pages/Transactions'
import Trips from './pages/Trips'
import Users from './pages/Users'
import Vehicles from './pages/Vehicles'

/** Sends signed-out visitors to /login and remembers where they were going. */
function RequireAuth({ children }) {
  const { user, checking } = useAuth()
  const location = useLocation()
  if (checking) return <Spinner label="Checking your session" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

/** Hides admin-only pages in the UI. The API enforces the same rule independently. */
function RequireRole({ role, children }) {
  const { can } = useAuth()
  if (!can(role)) {
    return <EmptyState title="You don't have access to this page">Ask an administrator if you need it.</EmptyState>
  }
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Dashboard />} />
        <Route path="tracking" element={<Tracking />} />
        <Route path="vehicles" element={<Vehicles />} />
        <Route path="drivers" element={<Drivers />} />
        <Route path="trips" element={<Trips />} />
        <Route path="expenses" element={<Expenses />} />
        <Route path="reports" element={<Reports />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="users" element={<RequireRole role="ADMIN"><Users /></RequireRole>} />
        <Route path="*" element={<EmptyState title="Page not found">Use the menu to find what you need.</EmptyState>} />
      </Route>
    </Routes>
  )
}
