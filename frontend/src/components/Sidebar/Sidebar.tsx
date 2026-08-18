import React from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useAuth } from '../../store/AuthContext'

export default function Sidebar() {
  const { me, logout } = useAuth()
  const roleLabel = me?.roles?.[0] ? `(${me.roles[0]})` : ''

  return (
    <aside style={{ width: 220, borderRight: '1px solid #eee', padding: 16 }}>
      <div style={{ fontWeight: 700, marginBottom: 16 }}>
        NexusOps <span style={{ color: '#666' }}>{roleLabel}</span>
      </div>
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <NavLink to="/" end style={({ isActive }) => ({ textDecoration: 'none', color: isActive ? '#000' : '#444' })}>
          Dashboard
        </NavLink>
        <NavLink to="/inventory" style={({ isActive }) => ({ textDecoration: 'none', color: isActive ? '#000' : '#444' })}>
          Inventory
        </NavLink>
        <NavLink to="/orders" style={({ isActive }) => ({ textDecoration: 'none', color: isActive ? '#000' : '#444' })}>
          Orders
        </NavLink>
        <NavLink to="/warehouses" style={({ isActive }) => ({ textDecoration: 'none', color: isActive ? '#000' : '#444' })}>
          Warehouses
        </NavLink>
        <NavLink to="/audit" style={({ isActive }) => ({ textDecoration: 'none', color: isActive ? '#000' : '#444' })}>
          Audit Logs
        </NavLink>
        <NavLink to="/settings" style={({ isActive }) => ({ textDecoration: 'none', color: isActive ? '#000' : '#444' })}>
          Settings
        </NavLink>
      </nav>
      <div style={{ marginTop: 24, fontSize: 12, color: '#666' }}>
        {me ? (
          <>
            Signed in as <b>{me.username}</b>
            <div style={{ marginTop: 12 }}>
              <button onClick={logout} type="button">
                Logout
              </button>
            </div>
          </>
        ) : (
          <Link to="/login">Login</Link>
        )}
      </div>
    </aside>
  )
}

