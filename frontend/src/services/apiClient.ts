const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000/api/v2'

export async function apiFetch<T>(path: string, token: string | null, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return (await res.json()) as T
}

export const api = {
  login: (username: string, password: string) =>
    apiFetch<{ access_token: string }>(
      '/auth/token',
      null,
      { method: 'POST', body: JSON.stringify({ username, password }) },
    ),

  getMe: (token: string) =>
    apiFetch<{ user_id: string; username: string; roles: string[] }>('/auth/me', token, { method: 'GET' }),

  getDashboardKpis: (token: string) => apiFetch<any>('/dashboard/kpis', token, { method: 'GET' }),

  listWarehouses: (token: string) => apiFetch<any[]>('/warehouses', token, { method: 'GET' }),

  listInventoryBalances: (token: string, params: Record<string, string | number | undefined>) => {
    const usp = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === '') return
      usp.set(k, String(v))
    })
    return apiFetch<any[]>(`/inventory/balances?${usp.toString()}`, token, { method: 'GET' })
  },

  adjustInventoryBalance: (token: string, warehouseId: string, skuId: string, onHand: number, reason: string) =>
    apiFetch<any>(`/inventory/balances/${warehouseId}/${skuId}`, token, {
      method: 'POST',
      body: JSON.stringify({ on_hand: onHand, reason }),
    }),

  listOrders: (token: string, params: Record<string, string | number | undefined>) => {
    const usp = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === '') return
      usp.set(k, String(v))
    })
    return apiFetch<any[]>(`/orders?${usp.toString()}`, token, { method: 'GET' })
  },

  reserveOrder: (token: string, orderId: string) =>
    apiFetch<any>(`/orders/${orderId}/reserve`, token, { method: 'POST' }),

  cancelOrder: (token: string, orderId: string) =>
    apiFetch<any>(`/orders/${orderId}/cancel`, token, { method: 'POST' }),

  fulfillOrder: (token: string, orderId: string) =>
    apiFetch<any>(`/orders/${orderId}/fulfill`, token, { method: 'POST' }),

  listTransfers: (token: string, params: Record<string, string | number | undefined>) => {
    const usp = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === '') return
      usp.set(k, String(v))
    })
    return apiFetch<any[]>(`/warehouse/transfers?${usp.toString()}`, token, { method: 'GET' })
  },

  loginForm: (username: string, password: string) => apiFetch<any>('/auth/token', null, {
    method: 'POST',
    body: JSON.stringify({ username, password })
  }),

  listPurchaseOrders: (token: string) => apiFetch<any[]>('/purchase-orders', token, { method: 'GET' }),

  createPurchaseOrder: (token: string, body: any) => apiFetch<any>('/purchase-orders', token, {
    method: 'POST',
    body: JSON.stringify(body),
  }),

  getAudit: (token: string, entityType: string, entityId: string) =>
    apiFetch<any[]>(`/audit/${entityType}/${entityId}`, token, { method: 'GET' }),
}

export default api

