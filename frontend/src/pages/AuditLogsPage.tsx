import React, { useEffect, useState } from 'react'
import { useAuth } from '../store/AuthContext'
import { api } from '../services/apiClient'

export default function AuditLogsPage() {
  const { token, me } = useAuth()
  const [entityType, setEntityType] = useState('order')
  const [entityId, setEntityId] = useState('')
  const [entries, setEntries] = useState<any[]>([])

  useEffect(() => {
    async function load() {
      if (!token || !entityId) return
      const res = await api.getAudit(token!, entityType, entityId)
      setEntries(res)
    }
    load()
  }, [token, entityType, entityId])

  return (
    <div>
      <h2>Audit Logs</h2>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <label>
          Entity type
          <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
            <option value="order">order</option>
            <option value="inventory_balance">inventory_balance</option>
            <option value="transfer">transfer</option>
            <option value="purchase_order">purchase_order</option>
          </select>
        </label>
        <label style={{ flex: 1 }}>
          Entity id (UUID)
          <input value={entityId} onChange={(e) => setEntityId(e.target.value)} placeholder="e.g. 00000000-0000-0000-0000-000000000000" />
        </label>
      </div>

      <div style={{ fontSize: 12, color: '#666' }}>
        {me ? `Signed in as ${me.username}` : ''}
      </div>

      <div style={{ marginTop: 16, border: '1px solid #eee', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead style={{ background: '#fafafa' }}>
            <tr>
              <th style={{ textAlign: 'left', padding: 10 }}>Time</th>
              <th style={{ textAlign: 'left', padding: 10 }}>Action</th>
              <th style={{ textAlign: 'left', padding: 10 }}>Actor</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, idx) => (
              <tr key={e.id || idx}>
                <td style={{ padding: 10, fontSize: 12 }}>{new Date(e.event_timestamp).toLocaleString()}</td>
                <td style={{ padding: 10, fontSize: 12 }}>{e.action}</td>
                <td style={{ padding: 10, fontSize: 12 }}>{e.is_manual_override ? 'Manual' : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

