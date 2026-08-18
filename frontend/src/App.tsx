import React from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './store/AuthContext'
import Sidebar from './components/Sidebar/Sidebar'
import DashboardPage from './pages/DashboardPage'
import InventoryPage from './pages/InventoryPage'
import OrdersPage from './pages/OrdersPage'
import WarehousesPage from './pages/WarehousesPage'
import AuditLogsPage from './pages/AuditLogsPage'
import SettingsPage from './pages/SettingsPage'
import LoginPage from './pages/LoginPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me } = useAuth()
  const location = useLocation()
  if (!me) return <Navigate to="/login" replace state={{ from: location }} />
  return <>{children}</>
}

function AppShell() {
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar />
      <main style={{ padding: 16, flex: 1 }}>
        <Routes>
          <Route path="/" element={<RequireAuth children={<DashboardPage />} />} />
          <Route path="/inventory" element={<RequireAuth children={<InventoryPage />} />} />
          <Route path="/orders" element={<RequireAuth children={<OrdersPage />} />} />
          <Route path="/warehouses" element={<RequireAuth children={<WarehousesPage />} />} />
          <Route path="/audit" element={<RequireAuth children={<AuditLogsPage />} />} />
          <Route path="/settings" element={<RequireAuth children={<SettingsPage />} />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  )
}

