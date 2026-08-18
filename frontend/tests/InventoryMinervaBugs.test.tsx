import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import DataTable from '../src/components/DataTable/DataTable'

type TableRow = { id: string; label: string }

function DataTableWrapper() {
  const [rows, setRows] = React.useState<TableRow[]>([
    { id: 'w:s1', label: 'SKU1' },
    { id: 'w:s2', label: 'SKU2' },
  ])
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set())

  return (
    <div>
      <button type="button" onClick={() => setRows([{ id: 'w:s2', label: 'SKU2' }, { id: 'w:s3', label: 'SKU3' }])}>
        Apply filter
      </button>
      <button type="button" onClick={() => setRows([{ id: 'w:s1', label: 'SKU1' }, { id: 'w:s2', label: 'SKU2' }])}>
        Clear filter
      </button>
      <DataTable<TableRow>
        ariaLabel="inventory"
        columns={[
          { key: 'label', header: 'Label', render: (r) => r.label },
        ]}
        rows={rows}
        selectedIds={selectedIds}
        onSelectedIdsChange={setSelectedIds}
      />
    </div>
  )
}

describe('Minerva bug examples', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.resetModules()
  })

  it('preserves selected rows across filtering', async () => {
    const user = userEvent.setup()
    render(<DataTableWrapper />)

    const sku1Checkbox = screen.getByRole('checkbox', { name: 'select row w:s1' })
    await user.click(sku1Checkbox)
    expect(sku1Checkbox).toBeChecked()

    await user.click(screen.getByText('Apply filter'))
    // SKU1 checkbox disappears from DOM, but selection should persist.
    await user.click(screen.getByText('Clear filter'))
    const sku1CheckboxAgain = screen.getByRole('checkbox', { name: 'select row w:s1' })
    expect(sku1CheckboxAgain).toBeChecked()
  })

  it('inventory modal updates product identity and closes with Escape', async () => {
    const listWarehouses = vi.fn().mockResolvedValue([{ id: 'wh1', warehouse_code: 'WH1', name: 'Warehouse 1' }])
    const listInventoryBalances = vi
      .fn()
      .mockResolvedValueOnce([
        { warehouse_id: 'wh1', sku_id: 's1', sku_code: 'SKU1', description: 'D1', uom: 'EA', on_hand: 10, reserved: 0, allocated: 0, available: 10 },
        { warehouse_id: 'wh1', sku_id: 's2', sku_code: 'SKU2', description: 'D2', uom: 'EA', on_hand: 20, reserved: 0, allocated: 0, available: 20 },
      ])
      .mockResolvedValue([
        { warehouse_id: 'wh1', sku_id: 's1', sku_code: 'SKU1', description: 'D1', uom: 'EA', on_hand: 10, reserved: 0, allocated: 0, available: 10 },
        { warehouse_id: 'wh1', sku_id: 's2', sku_code: 'SKU2', description: 'D2', uom: 'EA', on_hand: 20, reserved: 0, allocated: 0, available: 20 },
      ])

    const adjustInventoryBalance = vi.fn()
    vi.doMock('../src/services/apiClient', () => ({
      api: {
        listWarehouses,
        listInventoryBalances,
        adjustInventoryBalance,
        listOrders: vi.fn(),
        getDashboardKpis: vi.fn(),
        listTransfers: vi.fn(),
        loginForm: vi.fn(),
        getMe: vi.fn(),
      },
    }))

    vi.doMock('../src/store/AuthContext', () => ({
      useAuth: () => ({
        token: 't',
        me: { user_id: 'u', username: 'admin', roles: ['admin'] },
        login: vi.fn(),
        logout: vi.fn(),
      }),
    }))

    const InventoryPage = (await import('../src/pages/InventoryPage')).default
    render(<InventoryPage />)

    // Click edit for SKU1, modal title should match.
    const editButtonsInitial = screen.getAllByText('Edit')
    await userEvent.click(editButtonsInitial[0])
    expect(screen.getByRole('dialog', { name: /Edit SKU1/i })).toBeInTheDocument()

    // Click edit for SKU2 while modal is open.
    const editButtons = screen.getAllByText('Edit')
    await userEvent.click(editButtons[1])
    expect(screen.getByRole('dialog', { name: /Edit SKU2/i })).toBeInTheDocument()

    // Escape closes.
    await userEvent.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})

