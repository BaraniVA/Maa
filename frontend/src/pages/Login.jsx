import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

const API = '/api'

export default function Login({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Login failed')
      localStorage.setItem('maa_token', data.token)
      localStorage.setItem('maa_worker', JSON.stringify(data.worker))
      onLogin(data.worker)
      navigate('/dashboard')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-left">
        <div className="auth-brand">
          <div className="auth-logo">🌸</div>
          <h1>MAA</h1>
          <p>Maternal Agentic Assistant</p>
          <div className="auth-tagline">
            Empowering ASHA workers with AI-driven maternal healthcare monitoring across India
          </div>
        </div>
        <div className="auth-stats-row">
          <div className="auth-stat">
            <span className="auth-stat-num">97</span>
            <span className="auth-stat-label">MMR per 100K</span>
          </div>
          <div className="auth-stat">
            <span className="auth-stat-num">10L+</span>
            <span className="auth-stat-label">ASHA Workers</span>
          </div>
          <div className="auth-stat">
            <span className="auth-stat-num">24/7</span>
            <span className="auth-stat-label">AI Monitoring</span>
          </div>
        </div>
      </div>
      <div className="auth-right">
        <form className="auth-form" onSubmit={handleSubmit}>
          <h2>Welcome Back</h2>
          <p className="auth-subtitle">Sign in to your ASHA worker dashboard</p>
          {error && <div className="auth-error">{error}</div>}
          <div className="form-group">
            <label>Email Address</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="asha@example.com"
              required
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </div>
          <button type="submit" className="auth-btn" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
          <p className="auth-switch">
            Don't have an account? <Link to="/register">Register here</Link>
          </p>
        </form>
      </div>
    </div>
  )
}
