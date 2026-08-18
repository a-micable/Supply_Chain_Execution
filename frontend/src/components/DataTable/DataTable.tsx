import React from 'react'

export type DataTableColumn<T> = {
  key: string
  header: string
  width?: number | string
  render: (row: T) => React.ReactNode
}

export type DataTableProps<T extends { id: string }> = {
  columns: DataTableColumn<T>[]
  rows: T[]
  selectedIds: Set<string>
  onSelectedIdsChange: (next: Set<string>) => void
  ariaLabel?: string
}

export default function DataTable<T extends { id: string }>({
  columns,
  rows,
  selectedIds,
  onSelectedIdsChange,
  ariaLabel = 'data table',
}: DataTableProps<T>) {
  function toggleRow(id: string) {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onSelectedIdsChange(next)
  }

  function toggleAllVisible() {
    const visibleIds = rows.map((r) => r.id)
    const allSelected = visibleIds.every((id) => selectedIds.has(id))
    const next = new Set(selectedIds)
    for (const id of visibleIds) {
      if (allSelected) next.delete(id)
      else next.add(id)
    }
    onSelectedIdsChange(next)
  }

  const allVisibleSelected = rows.length > 0 && rows.every((r) => selectedIds.has(r.id))

  return (
    <table aria-label={ariaLabel} style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <th style={{ width: 40, padding: 8 }}>
            <input
              type="checkbox"
              aria-label="select all visible"
              checked={allVisibleSelected}
              onChange={toggleAllVisible}
            />
          </th>
          {columns.map((c) => (
            <th key={c.key} style={{ textAlign: 'left', padding: 8, width: c.width }}>
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const checked = selectedIds.has(row.id)
          return (
            <tr key={row.id}>
              <td style={{ padding: 8 }}>
                <input
                  type="checkbox"
                  aria-label={`select row ${row.id}`}
                  checked={checked}
                  onChange={() => toggleRow(row.id)}
                />
              </td>
              {columns.map((c) => (
                <td key={c.key} style={{ padding: 8, borderTop: '1px solid #f0f0f0' }}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

