import React, { useEffect, useMemo, useState } from 'react'
import DataTable, { DataTableColumn } from '../components/DataTable/DataTable'
import ConfirmDialog from '../components/ConfirmDialog/ConfirmDialog'
import StockBadge from '../components/StockBadge/StockBadge'
import { api } from '../services/apiClient'
import { useAuth } from '../store/AuthContext'

type Warehouse = { id: string; warehouse_code: string; name: string }

type InventoryRow = {
  warehouse_id: string
  sku_id: string
  sku_code: string
  description: string
  uom: string
  on_hand: number
  reserved: number
  allocated: number
  available: number
}

type RowForTable = InventoryRow & { id: string }

export default function InventoryPage() {
  const { token } = useAuth()
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [warehouseId, setWarehouseId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [rows, setRows] = useState<RowForTable[]>([])
  const [page, setPage] = useState(1)
  const pageSize = 20
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())

  const [edit, setEdit] = useState<{ key: string; row: RowForTable; onHand: string } | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const columns: DataTableColumn<RowForTable>[] = useMemo(
    () => [
      { key: 'sku', header: 'SKU', render: (r) => <b>{r.sku_code}</b> },
      { key: 'desc', header: 'Description', render: (r) => <span>{r.description}</span> },
      {
        key: 'badge',
        header: 'Availability',
        render: (r) => <StockBadge available={r.available} isLow={r.available < 10} />,
      },
      { key: 'on_hand', header: 'On hand', render: (r) => r.on_hand },
      { key: 'reserved', header: 'Reserved', render: (r) => r.reserved },
      { key: 'allocated', header: 'Allocated', render: (r) => r.allocated },
      {
        key: 'actions',
        header: 'Actions',
        render: (r) => (
          <button
            type="button"
            onClick={() => {
              setEdit({ key: r.id, row: r, onHand: String(r.on_hand) })
              setConfirmOpen(true)
            }}
          >
            Edit
          </button>
        ),
      },
    ],
    [],
  )

  // Load warehouses once.
  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!token) return
      const ws = await api.listWarehouses(token)
      if (cancelled) return
      setWarehouses(ws as Warehouse[])
      if (!warehouseId && (ws as Warehouse[]).length) {
        setWarehouseId((ws as Warehouse[])[0].id)
      }
    }
    load()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  // Fetch balances.
  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!token || !warehouseId) return
      setLoading(true)
      try {
        const res = await api.listInventoryBalances(token, {
          warehouse_id: warehouseId,
          search: search || undefined,
          sort_by: 'sku_code',
          sort_dir: 'asc',
          page,
          page_size: pageSize,
        })
        if (cancelled) return
        const typed = (res as InventoryRow[]).map((r) => ({ ...r, id: `${r.warehouse_id}:${r.sku_id}` }))
        setRows(typed)

        // Minerva bug fix: keep current page on search changes; if results are empty and page>1, fall back.
        if (typed.length === 0 && page > 1) setPage(1)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [token, warehouseId, search, page])

  async function saveEdit() {
    if (!token || !edit) return
    const onHand = Number(edit.onHand)
    await api.adjustInventoryBalance(token, edit.row.warehouse_id, edit.row.sku_id, onHand, 'manual adjustment')
    setConfirmOpen(false)
    setEdit(null)
    // Update badges and available values by refetching current page.
    const res = await api.listInventoryBalances(token, {
      warehouse_id: warehouseId || undefined,
      search: search || undefined,
      sort_by: 'sku_code',
      sort_dir: 'asc',
      page,
      page_size: pageSize,
    })
    const typed = (res as InventoryRow[]).map((r) => ({ ...r, id: `${r.warehouse_id}:${r.sku_id}` }))
    setRows(typed)
  }

  return (
    <div>
      <h2>Inventory</h2>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <select
          aria-label="warehouse filter"
          value={warehouseId || ''}
          onChange={(e) => {
            setWarehouseId(e.target.value)
            setPage(1)
          }}
        >
          {warehouses.map((w) => (
            <option value={w.id} key={w.id}>
              {w.warehouse_code} - {w.name}
            </option>
          ))}
        </select>

        <input
          aria-label="search inventory"
          placeholder="Search SKU or description"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
          }}
        />
      </div>

      <div style={{ marginBottom: 12 }}>
        {loading ? 'Loading…' : `${rows.length} rows`} Selected: {selectedIds.size}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button
          type="button"
          onClick={() => {
            const selected = rows.filter((r) => selectedIds.has(r.id))
            const exportRows = selected.length ? selected : rows
            const header = ['sku_code', 'description', 'on_hand', 'reserved', 'allocated', 'available']
            const csv = [
              header.join(','),
              ...exportRows.map((r) =>
                [
                  r.sku_code,
                  r.description.replace(/"/g, '""'),
                  r.on_hand,
                  r.reserved,
                  r.allocated,
                  r.available,
                ]
                  .map((v) => `"${String(v)}"`)
                  .join(','),
              ),
            ].join('\n')
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `inventory_export_${new Date().toISOString().slice(0, 10)}.csv`
            a.click()
            URL.revokeObjectURL(url)
          }}
        >
          Export CSV
        </button>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        selectedIds={selectedIds}
        onSelectedIdsChange={setSelectedIds}
      />

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
          Prev
        </button>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          Page <b>{page}</b>
        </div>
        <button
          type="button"
          onClick={() => setPage((p) => p + 1)}
          disabled={rows.length < pageSize}
        >
          Next
        </button>
      </div>

      {/* Edit modal: component identity is driven by `edit.key` + key prop on ConfirmDialog */}
      <ConfirmDialog
        open={confirmOpen}
        title={edit ? `Edit ${edit.row.sku_code}` : 'Edit'}
        description={edit ? `Update on-hand quantity for ${edit.row.sku_code}.` : undefined}
        confirmLabel="Save"
        cancelLabel="Close"
        onCancel={() => {
          setConfirmOpen(false)
          setEdit(null)
        }}
        onConfirm={saveEdit}
      >
        {edit ? (
          <div key={edit.key} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label>
              On hand
              <input
                aria-label="on hand input"
                value={edit.onHand}
                onChange={(e) => setEdit((prev) => (prev ? { ...prev, onHand: e.target.value } : prev))}
              />
            </label>
            <div style={{ fontSize: 12, color: '#666' }}>
              Available badge updates after save.
            </div>
          </div>
        ) : null}
      </ConfirmDialog>
    </div>
  )
}

