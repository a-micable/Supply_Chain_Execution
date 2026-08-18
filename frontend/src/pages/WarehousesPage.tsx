import React, { useEffect, useState } from 'react'
import { useAuth } from '../store/AuthContext'
import { api } from '../services/apiClient'

export default function WarehousesPage() {
  const { token } = useAuth()
  const [warehouses, setWarehouses] = useState<any[]>([])
  const [transfers, setTransfers] = useState<any[]>([])

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!token) return
      const ws = await api.listWarehouses(token)
      const trs = await api.listTransfers(token, {})
      if (!cancelled) {
        setWarehouses(ws)
        setTransfers(trs)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <div>
      <h2>Warehouses</h2>
      <h3>Active</h3>
      <ul>
        {warehouses.map((w) => (
          <li key={w.id}>
            {w.warehouse_code} - {w.name}
          </li>
        ))}
      </ul>

      <h3 style={{ marginTop: 24 }}>Transfers</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', padding: 8 }}>Transfer</th>
            <th style={{ textAlign: 'left', padding: 8 }}>Status</th>
            <th style={{ textAlign: 'left', padding: 8 }}>SKU</th>
            <th style={{ textAlign: 'left', padding: 8 }}>Qty</th>
          </tr>
        </thead>
        <tbody>
          {transfers.map((t) => (
            <tr key={t.transfer_number}>
              <td style={{ padding: 8 }}>{t.transfer_number}</td>
              <td style={{ padding: 8 }}>{t.status}</td>
              <td style={{ padding: 8 }}>{t.sku_id}</td>
              <td style={{ padding: 8 }}>{t.quantity}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

