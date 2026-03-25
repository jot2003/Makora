import { create } from 'zustand'

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

const DEFAULT_URL = 'ws://localhost:8000/ws/meeting'
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 10000]

let _reconnectTimer: ReturnType<typeof setTimeout> | null = null
let _pingInterval: ReturnType<typeof setInterval> | null = null
let _reconnectAttempt = 0
let _intentionalClose = false
let _lastUrl = DEFAULT_URL

export const useWebSocket = create<WebSocketState>((set, get) => ({
  ws: null,
  status: 'disconnected',
  lastMessage: null,

  connect: (url = DEFAULT_URL) => {
    const existing = get().ws
    if (existing && existing.readyState <= WebSocket.OPEN) return

    _intentionalClose = false
    _lastUrl = url
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null }

    set({ status: 'connecting' })
    const ws = new WebSocket(url)

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
          if (!_intentionalClose) get().connect(_lastUrl)
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
