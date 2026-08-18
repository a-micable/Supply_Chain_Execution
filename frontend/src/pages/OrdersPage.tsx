import React, { useEffect, useState } from 'react'
import { useAuth } from '../store/AuthContext'
import { api } from '../services/apiClient'

export default function OrdersPage() {
  const { token } = useAuth()
  const [orders, setOrders] = useState<any[]>([])

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!token) return
      const res = await api.listOrders(token, { page: 1, page_size: 25 })
      if (!cancelled) setOrders(res)
    }
    load()
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <div>
      <h2>Orders</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', padding: 8 }}>Order</th>
            <th style={{ textAlign: 'left', padding: 8 }}>Customer</th>
            <th style={{ textAlign: 'left', padding: 8 }}>Status</th>
            <th style={{ textAlign: 'left', padding: 8 }}>Priority</th>
            <th style={{ textAlign: 'left', padding: 8 }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td style={{ padding: 8 }}>{o.external_order_id}</td>
              <td style={{ padding: 8 }}>{o.customer_id}</td>
              <td style={{ padding: 8 }}>{o.status}</td>
              <td style={{ padding: 8 }}>{o.priority}</td>
              <td style={{ padding: 8, display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  onClick={async () => {
                    await api.reserveOrder(token!, o.id)
                    const res = await api.listOrders(token!, { page: 1, page_size: 25 })
                    setOrders(res)
                  }}
                >
                  Reserve
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    await api.cancelOrder(token!, o.id)
                    const res = await api.listOrders(token!, { page: 1, page_size: 25 })
                    setOrders(res)
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    await api.fulfillOrder(token!, o.id)
                    const res = await api.listOrders(token!, { page: 1, page_size: 25 })
                    setOrders(res)
                  }}
                >
                  Fulfill
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

