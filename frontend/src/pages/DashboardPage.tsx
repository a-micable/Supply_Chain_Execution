import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../services/apiClient'
import { useAuth } from '../store/AuthContext'

type Kpis = {
  total_on_hand: number
  active_orders: number
  low_stock_count: number
  recent_activity: any[]
}

export default function DashboardPage() {
  const { token } = useAuth()
  const [kpis, setKpis] = useState<Kpis | null>(null)
  const [error, setError] = useState<string | null>(null)

  const wsUrl = useMemo(() => {
    const base = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000/api/v2'
    // Convert http base to ws base and drop /api/v2.
    const host = base.replace(/^http/, 'ws').replace(/\/api\/v2$/, '')
    return `${host}/api/v2/dashboard/stream?access_token=${token || ''}`
  }, [token])

  async function load() {
    if (!token) return
    setError(null)
    try {
      const res = await api.getDashboardKpis(token)
      setKpis(res as Kpis)
    } catch (e: any) {
      setError(e?.message || 'Failed to load KPIs')
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => {
    if (!token) return
    let ws: WebSocket | null = null
    try {
      ws = new WebSocket(wsUrl)
      ws.onmessage = () => {
        // Keep it simple: refetch KPIs when events arrive.
        load()
      }
      ws.onerror = () => {}
    } catch {
      return
    }
    return () => {
      ws?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsUrl])

  return (
    <div>
      <h2>Dashboard</h2>
      {error ? <div style={{ color: 'crimson' }}>{error}</div> : null}
      {kpis ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          <div style={{ border: '1px solid #eee', padding: 12 }}>
            <div style={{ color: '#666' }}>Total on hand</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{kpis.total_on_hand}</div>
          </div>
          <div style={{ border: '1px solid #eee', padding: 12 }}>
            <div style={{ color: '#666' }}>Active orders</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{kpis.active_orders}</div>
          </div>
          <div style={{ border: '1px solid #eee', padding: 12 }}>
            <div style={{ color: '#666' }}>Low stock alerts</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{kpis.low_stock_count}</div>
          </div>
        </div>
      ) : (
        <div>Loading…</div>
      )}

      <h3 style={{ marginTop: 24 }}>Recent activity</h3>
      <div style={{ border: '1px solid #eee', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead style={{ background: '#fafafa' }}>
            <tr>
              <th style={{ textAlign: 'left', padding: 10 }}>Time</th>
              <th style={{ textAlign: 'left', padding: 10 }}>Entity</th>
              <th style={{ textAlign: 'left', padding: 10 }}>Action</th>
              <th style={{ textAlign: 'left', padding: 10 }}>Actor</th>
            </tr>
          </thead>
          <tbody>
            {(kpis?.recent_activity || []).map((a, idx) => (
              <tr key={a.id || idx}>
                <td style={{ padding: 10, fontSize: 12 }}>{new Date(a.event_timestamp).toLocaleString()}</td>
                <td style={{ padding: 10, fontSize: 12 }}>
                  {a.entity_type} / {a.entity_id}
                </td>
                <td style={{ padding: 10, fontSize: 12 }}>{a.action}</td>
                <td style={{ padding: 10, fontSize: 12 }}>{a.actor_id || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

