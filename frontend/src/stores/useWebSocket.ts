import { create } from 'zustand'
import { WS_BASE } from '@/lib/utils'

export type WSStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface WSMessage {
  type: string
  [key: string]: unknown
}

interface WebSocketState {
  ws: WebSocket | null
  status: WSStatus
  lastMessage: WSMessage | null
  connect: (url?: string) => void
  disconnect: () => void
  send: (msg: WSMessage) => void
}

function buildWsUrl(base?: string): string {
  const url = base || `${WS_BASE || `ws://${window.location.host}`}/ws/meeting`
  const token = localStorage.getItem('token')
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 10000]

let _reconnectTimer: ReturnType<typeof setTimeout> | null = null
let _pingInterval: ReturnType<typeof setInterval> | null = null
let _reconnectAttempt = 0
let _intentionalClose = false
let _lastBaseUrl = ''

export const useWebSocket = create<WebSocketState>((set, get) => ({
  ws: null,
  status: 'disconnected',
  lastMessage: null,

  connect: (url?: string) => {
    const existing = get().ws
    if (existing && existing.readyState <= WebSocket.OPEN) return

    _intentionalClose = false
    _lastBaseUrl = url || ''
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null }

    set({ status: 'connecting' })
    const ws = new WebSocket(buildWsUrl(url))

    ws.onopen = () => {
      _reconnectAttempt = 0
      if (_pingInterval) clearInterval(_pingInterval)
      _pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, 15000)
      set({ status: 'connected', ws })
    }
    ws.onclose = () => {
      if (_pingInterval) { clearInterval(_pingInterval); _pingInterval = null }
      set({ status: 'disconnected', ws: null })
      if (!_intentionalClose) {
        const delay = RECONNECT_DELAYS[Math.min(_reconnectAttempt, RECONNECT_DELAYS.length - 1)]
        _reconnectAttempt++
        _reconnectTimer = setTimeout(() => {
          _reconnectTimer = null
          if (!_intentionalClose) get().connect(_lastBaseUrl || undefined)
        }, delay)
      }
    }
    ws.onerror = () => set({ status: 'error' })
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data)
        set({ lastMessage: data })
      } catch {
        /* ignore non-JSON */
      }
    }

    set({ ws })
  },

  disconnect: () => {
    _intentionalClose = true
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null }
    if (_pingInterval) { clearInterval(_pingInterval); _pingInterval = null }
    _reconnectAttempt = 0
    const ws = get().ws
    if (ws) ws.close()
    set({ ws: null, status: 'disconnected' })
  },

  send: (msg) => {
    const ws = get().ws
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    }
  },
}))
