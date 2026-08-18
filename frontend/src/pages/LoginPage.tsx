import React, { useState } from 'react'
import { useAuth } from '../store/AuthContext'
import { useNavigate } from 'react-router-dom'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  return (
    <div style={{ maxWidth: 420 }}>
      <h2>Sign in</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          Password
          <input value={password} type="password" onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error ? <div style={{ color: 'crimson' }}>{error}</div> : null}
        <button
          type="button"
          disabled={loading}
          onClick={async () => {
            setLoading(true)
            setError(null)
            try {
              await login(username, password)
              navigate('/')
            } catch (e: any) {
              setError(e?.message || 'Login failed')
            } finally {
              setLoading(false)
            }
          }}
        >
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
        <div style={{ fontSize: 12, color: '#666' }}>
          Demo users: <code>admin/admin123</code>, <code>operator/operator123</code>
        </div>
      </div>
    </div>
  )
}

