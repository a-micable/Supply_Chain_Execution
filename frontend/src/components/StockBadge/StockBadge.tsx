import React from 'react'

export default function StockBadge({
  available,
  isLow,
}: {
  available: number
  isLow?: boolean
}) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: 999,
        background: isLow ? '#ffe8e8' : '#eef6ff',
        border: `1px solid ${isLow ? '#ffb3b3' : '#b8d7ff'}`,
        color: isLow ? '#b00020' : '#0b4a6f',
        fontSize: 12,
        fontWeight: 700,
      }}
      aria-label={isLow ? 'low stock' : 'stock'}
    >
      Available: {available}
    </span>
  )
}

