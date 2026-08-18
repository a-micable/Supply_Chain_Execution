import React from 'react'
import { useAuth } from '../store/AuthContext'

export default function SettingsPage() {
  const { me } = useAuth()
  return (
    <div>
      <h2>Settings</h2>
      <div style={{ fontSize: 12, color: '#666' }}>
        Tenant/user preferences are UI-only in this MVP.
      </div>
      <div style={{ marginTop: 16 }}>
        <div>
          User: <b>{me?.username}</b>
        </div>
      </div>
    </div>
  )
}

