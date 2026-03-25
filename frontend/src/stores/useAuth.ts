import { create } from 'zustand'
import { API_BASE as API } from '@/lib/utils'

interface User {
  id: number
  email: string
  username: string
  avatar_url: string
  provider: string
  is_verified: boolean
}

interface AuthState {
  token: string | null
  user: User | null
  loading: boolean
  error: string | null

  login: (email: string, password: string) => Promise<boolean>
  register: (email: string, username: string, password: string) => Promise<boolean>
  setToken: (token: string) => Promise<boolean>
  fetchMe: () => Promise<void>
  logout: () => void
  clearError: () => void
  getHeaders: () => Record<string, string>
}

export const useAuth = create<AuthState>((set, get) => ({
  token: localStorage.getItem('token'),
  user: null,
  loading: false,
  error: null,

  login: async (email, password) => {
    set({ loading: true, error: null })
    try {
      const r = await fetch(`${API}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Login failed' }))
        set({ loading: false, error: err.detail || 'Login failed' })
        return false
      }
      const data = await r.json()
      localStorage.setItem('token', data.token)
      set({ token: data.token, user: data.user, loading: false, error: null })
      return true
    } catch {
      set({ loading: false, error: 'Server unreachable' })
      return false
    }
  },

  register: async (email, username, password) => {
    set({ loading: true, error: null })
    try {
      const r = await fetch(`${API}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, username, password }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: 'Registration failed' }))
        set({ loading: false, error: err.detail || 'Registration failed' })
        return false
      }
      const data = await r.json()
      localStorage.setItem('token', data.token)
      set({ token: data.token, user: data.user, loading: false, error: null })
      return true
    } catch {
      set({ loading: false, error: 'Server unreachable' })
      return false
    }
  },

  setToken: async (token) => {
    localStorage.setItem('token', token)
    set({ token, loading: true })
    try {
      const r = await fetch(`${API}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (r.ok) {
        const user = await r.json()
        set({ user, loading: false })
        return true
      }
    } catch {}
    localStorage.removeItem('token')
    set({ token: null, user: null, loading: false })
    return false
  },

  fetchMe: async () => {
    const token = get().token
    if (!token) return
    set({ loading: true })
    try {
      const r = await fetch(`${API}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (r.ok) {
        set({ user: await r.json(), loading: false })
      } else {
        localStorage.removeItem('token')
        set({ token: null, user: null, loading: false })
      }
    } catch {
      set({ loading: false })
    }
  },

  logout: () => {
    localStorage.removeItem('token')
    set({ token: null, user: null })
  },

  clearError: () => set({ error: null }),

  getHeaders: () => {
    const token = get().token
    if (token) return { Authorization: `Bearer ${token}` }
    return {} as Record<string, string>
  },
}))
