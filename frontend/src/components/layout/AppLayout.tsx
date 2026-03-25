import { useState, useEffect, useCallback } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar, type Meeting } from './Sidebar'
import { useAuth } from '@/stores/useAuth'

const API = 'http://localhost:8000'

export function AppLayout() {
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const { getHeaders } = useAuth()

  const fetchMeetings = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/meetings`, { headers: getHeaders() })
      if (r.ok) setMeetings(await r.json())
    } catch {}
  }, [getHeaders])

  useEffect(() => {
    fetchMeetings()
    const interval = setInterval(fetchMeetings, 10000)
    return () => clearInterval(interval)
  }, [fetchMeetings])

  return (
    <div className="h-screen flex bg-background transition-colors duration-300">
      <Sidebar meetings={meetings} onRefresh={fetchMeetings} />
      <main className="flex-1 flex flex-col overflow-hidden">
        <Outlet context={{ meetings, refreshMeetings: fetchMeetings }} />
      </main>
    </div>
  )
}
