import './i18n'
import { useEffect } from 'react'
import { HashRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { useAuth } from './stores/useAuth'
import Dashboard from './pages/Dashboard'
import UsageDashboard from './pages/UsageDashboard'
import MeetingRoom from './pages/MeetingRoom'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import AuthCallback from './pages/AuthCallback'
import OverlayWindow from './components/overlay/OverlayWindow'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  const location = useLocation()
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />
  return <>{children}</>
}

function RedirectIfAuth({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  if (token) return <Navigate to="/" replace />
  return <>{children}</>
}

function AuthInit({ children }: { children: React.ReactNode }) {
  const { token, user, fetchMe } = useAuth()
  useEffect(() => {
    if (token && !user) fetchMe()
  }, [token])
  return <>{children}</>
}

export default function App() {
  return (
    <HashRouter>
      <AuthInit>
        <Routes>
          <Route path="/overlay" element={<OverlayWindow />} />
          <Route path="/login" element={<RedirectIfAuth><LoginPage /></RedirectIfAuth>} />
          <Route path="/register" element={<RedirectIfAuth><RegisterPage /></RedirectIfAuth>} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/usage" element={<UsageDashboard />} />
            <Route path="/meeting/:id" element={<MeetingRoom />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/settings" element={<SettingsPage />} />
        </Route>
        </Routes>
      </AuthInit>
    </HashRouter>
  )
}
