import { useState, useEffect, useCallback } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar, Legend,
} from 'recharts'
import {
  Coins, Zap, Clock, Hash, ChevronDown, RefreshCw,
} from 'lucide-react'
import { cn, API_BASE as API } from '@/lib/utils'
import { useAuth } from '@/stores/useAuth'

interface SummaryData {
  totals: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    total_cost: number
    request_count: number
    avg_latency_ms: number
  }
  by_model: {
    model: string
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    total_cost: number
    request_count: number
    avg_latency_ms: number
  }[]
}

interface DailyEntry {
  date: string
  total_tokens: number
  total_cost: number
  requests: number
  models: Record<string, { tokens: number; cost: number; requests: number }>
}

interface RecentItem {
  id: number
  meeting_id: string | null
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated_cost: number
  request_type: string
  latency_ms: number
  created_at: string | null
}

const COLORS = ['#6366f1', '#06b6d4', '#f59e0b', '#ef4444', '#10b981', '#8b5cf6', '#ec4899']
const RANGE_OPTIONS = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
]

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toString()
}

function formatCost(n: number): string {
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms}ms`
}

function SummaryCard({ icon: Icon, label, value, sub, color }: {
  icon: typeof Coins; label: string; value: string; sub?: string; color: string
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex items-start gap-3">
      <div className={cn('w-10 h-10 rounded-lg flex items-center justify-center shrink-0', color)}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <p className="text-[12px] text-muted-foreground font-medium">{label}</p>
        <p className="text-xl font-semibold tracking-tight mt-0.5">{value}</p>
        {sub && <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

export default function UsageDashboard() {
  const { getHeaders } = useAuth()
  const [days, setDays] = useState('30')
  const [summary, setSummary] = useState<SummaryData | null>(null)
  const [daily, setDaily] = useState<DailyEntry[]>([])
  const [recent, setRecent] = useState<RecentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [rangeOpen, setRangeOpen] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    const h = getHeaders()
    try {
      const [summaryRes, dailyRes, recentRes] = await Promise.all([
        fetch(`${API}/api/usage/summary?days=${days}`, { headers: h }),
        fetch(`${API}/api/usage/daily?days=${days}`, { headers: h }),
        fetch(`${API}/api/usage/recent?limit=30`, { headers: h }),
      ])
      if (summaryRes.ok) setSummary(await summaryRes.json())
      if (dailyRes.ok) {
        const d = await dailyRes.json()
        setDaily(d.daily || [])
      }
      if (recentRes.ok) {
        const r = await recentRes.json()
        setRecent(r.items || [])
      }
    } catch { /* ignore */ }
    setLoading(false)
  }, [days])

  useEffect(() => { fetchData() }, [fetchData])

  const modelNames = summary?.by_model.map(m => m.model) || []

  const areaData = daily.map(d => {
    const row: Record<string, any> = { date: d.date.slice(5) }
    for (const name of modelNames) {
      row[name] = d.models[name]?.tokens || 0
    }
    return row
  })

  const pieData = (summary?.by_model || []).map(m => ({
    name: m.model,
    value: m.total_cost,
  }))

  const barData = (summary?.by_model || []).map(m => ({
    name: m.model,
    latency: m.avg_latency_ms,
  }))

  const totals = summary?.totals

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Usage Dashboard</h1>
            <p className="text-[13px] text-muted-foreground mt-0.5">LLM token usage and cost analytics</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Range selector */}
            <div className="relative">
              <button
                onClick={() => setRangeOpen(!rangeOpen)}
                className="h-8 px-3 rounded-lg border border-border bg-background text-[13px] flex items-center gap-1.5 hover:border-foreground/20 transition-colors"
              >
                {RANGE_OPTIONS.find(o => o.value === days)?.label}
                <ChevronDown className={cn('w-3.5 h-3.5 text-muted-foreground transition-transform', rangeOpen && 'rotate-180')} />
              </button>
              {rangeOpen && (
                <div className="absolute right-0 z-50 mt-1 w-28 rounded-lg border border-border bg-card shadow-lg overflow-hidden animate-scale-in origin-top">
                  {RANGE_OPTIONS.map(o => (
                    <button
                      key={o.value}
                      onClick={() => { setDays(o.value); setRangeOpen(false) }}
                      className={cn(
                        'w-full px-3 py-1.5 text-[12px] text-left transition-colors',
                        o.value === days ? 'bg-primary/10 text-primary font-medium' : 'text-foreground hover:bg-muted',
                      )}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={fetchData}
              disabled={loading}
              className="h-8 w-8 rounded-lg border border-border bg-background flex items-center justify-center hover:bg-accent transition-colors"
            >
              <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
            </button>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <SummaryCard
            icon={Hash}
            label="Total Tokens"
            value={formatNumber(totals?.total_tokens || 0)}
            sub={`${formatNumber(totals?.prompt_tokens || 0)} in / ${formatNumber(totals?.completion_tokens || 0)} out`}
            color="bg-indigo-500/10 text-indigo-500"
          />
          <SummaryCard
            icon={Coins}
            label="Total Cost"
            value={formatCost(totals?.total_cost || 0)}
            color="bg-emerald-500/10 text-emerald-500"
          />
          <SummaryCard
            icon={Zap}
            label="Requests"
            value={formatNumber(totals?.request_count || 0)}
            color="bg-amber-500/10 text-amber-500"
          />
          <SummaryCard
            icon={Clock}
            label="Avg Latency"
            value={formatMs(totals?.avg_latency_ms || 0)}
            color="bg-cyan-500/10 text-cyan-500"
          />
        </div>

        {/* Daily usage chart */}
        <div className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-[14px] font-semibold mb-4">Daily Token Usage</h2>
          <div className="h-[260px]">
            {areaData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={areaData}>
                  <defs>
                    {modelNames.map((name, i) => (
                      <linearGradient key={name} id={`gradient-${i}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={COLORS[i % COLORS.length]} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={COLORS[i % COLORS.length]} stopOpacity={0} />
                      </linearGradient>
                    ))}
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                  <YAxis tick={{ fontSize: 11 }} className="text-muted-foreground" tickFormatter={formatNumber} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                    labelStyle={{ fontWeight: 600 }}
                    formatter={(value: any) => [formatNumber(Number(value ?? 0)), '']}
                  />
                  <Legend wrapperStyle={{ fontSize: '12px' }} />
                  {modelNames.map((name, i) => (
                    <Area
                      key={name}
                      type="monotone"
                      dataKey={name}
                      stackId="1"
                      stroke={COLORS[i % COLORS.length]}
                      fill={`url(#gradient-${i})`}
                      strokeWidth={2}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-muted-foreground text-[13px]">
                No usage data yet
              </div>
            )}
          </div>
        </div>

        {/* Pie + Bar charts side by side */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Cost by model */}
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="text-[14px] font-semibold mb-4">Cost by Model</h2>
            <div className="h-[220px]">
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      paddingAngle={3}
                      dataKey="value"
                      label={({ name, percent }: any) => `${name} (${((percent ?? 0) * 100).toFixed(0)}%)`}
                      labelLine={false}
                    >
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                      formatter={(value: any) => [formatCost(Number(value ?? 0)), 'Cost']}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-muted-foreground text-[13px]">
                  No data
                </div>
              )}
            </div>
          </div>

          {/* Latency by model */}
          <div className="rounded-xl border border-border bg-card p-4">
            <h2 className="text-[14px] font-semibold mb-4">Avg Latency by Model</h2>
            <div className="h-[220px]">
              {barData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                    <YAxis tick={{ fontSize: 11 }} className="text-muted-foreground" tickFormatter={(v: number) => formatMs(v)} />
                    <Tooltip
                      contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '8px', fontSize: '12px' }}
                      formatter={(value: any) => [formatMs(Number(value ?? 0)), 'Latency']}
                    />
                    <Bar dataKey="latency" radius={[6, 6, 0, 0]}>
                      {barData.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-muted-foreground text-[13px]">
                  No data
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Recent requests table */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h2 className="text-[14px] font-semibold">Recent Requests</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Model</th>
                  <th className="text-right px-4 py-2 font-medium text-muted-foreground">Tokens</th>
                  <th className="text-right px-4 py-2 font-medium text-muted-foreground">Cost</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Type</th>
                  <th className="text-right px-4 py-2 font-medium text-muted-foreground">Latency</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Time</th>
                </tr>
              </thead>
              <tbody>
                {recent.length > 0 ? recent.map((item) => (
                  <tr key={item.id} className="border-b border-border/50 hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-2 font-medium">{item.model}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatNumber(item.total_tokens)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatCost(item.estimated_cost)}</td>
                    <td className="px-4 py-2">
                      <span className={cn(
                        'inline-flex px-1.5 py-0.5 rounded text-[11px] font-medium',
                        item.request_type === 'manual' ? 'bg-blue-500/10 text-blue-500' : 'bg-violet-500/10 text-violet-500',
                      )}>
                        {item.request_type}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatMs(item.latency_ms)}</td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {item.created_at ? new Date(item.created_at).toLocaleTimeString() : '—'}
                    </td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                      No usage data yet. Start a meeting to generate usage logs.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
