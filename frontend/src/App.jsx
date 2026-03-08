import { useState, useEffect } from 'react'
import { Routes, Route, Link, useNavigate, useLocation, Navigate } from 'react-router-dom'
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Patients from './pages/Patients.jsx'

const API = '/api'

function Navbar({ worker, onLogout }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  if (['/login', '/register'].includes(location.pathname)) return null

  const isActive = (path) => location.pathname === path ? 'nav-link active' : 'nav-link'

  return (
    <nav className="navbar">
      <div className="nav-container">
        <Link to="/" className="nav-brand">
          <span className="nav-logo">🌸</span>
          <span className="nav-brand-text">MAA</span>
        </Link>

        <button className="nav-hamburger" onClick={() => setMenuOpen(!menuOpen)}>
          {menuOpen ? '✕' : '☰'}
        </button>

        <div className={`nav-links ${menuOpen ? 'open' : ''}`}>
          <Link to="/" className={isActive('/')} onClick={() => setMenuOpen(false)}>Home</Link>
          {worker && (
            <>
              <Link to="/dashboard" className={isActive('/dashboard')} onClick={() => setMenuOpen(false)}>Dashboard</Link>
              <Link to="/patients" className={isActive('/patients')} onClick={() => setMenuOpen(false)}>Patients</Link>
            </>
          )}
        </div>

        <div className={`nav-actions ${menuOpen ? 'open' : ''}`}>
          {worker ? (
            <div className="nav-user-section">
              <div className="nav-user">
                <span className="nav-avatar">{worker.name?.charAt(0).toUpperCase()}</span>
                <span className="nav-username">{worker.name}</span>
              </div>
              <button className="nav-logout-btn" onClick={onLogout}>Logout</button>
            </div>
          ) : (
            <>
              <Link to="/login" className="nav-btn-outline" onClick={() => setMenuOpen(false)}>Sign In</Link>
              <Link to="/register" className="nav-btn-primary" onClick={() => setMenuOpen(false)}>Get Started</Link>
            </>
          )}
        </div>
      </div>
    </nav>
  )
}

function ProtectedRoute({ worker, children }) {
  if (!worker) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  const [worker, setWorker] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    const token = localStorage.getItem('maa_token')
    if (token) {
      fetch(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => {
          if (r.ok) return r.json()
          throw new Error('Invalid token')
        })
        .then(setWorker)
        .catch(() => {
          localStorage.removeItem('maa_token')
          localStorage.removeItem('maa_worker')
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const handleLogin = (workerData) => {
    setWorker(workerData)
  }

  const handleLogout = () => {
    const token = localStorage.getItem('maa_token')
    if (token) {
      fetch(`${API}/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {})
    }
    localStorage.removeItem('maa_token')
    localStorage.removeItem('maa_worker')
    setWorker(null)
    navigate('/')
  }

  if (loading) {
    return (
      <div className="app-loading">
        <div className="loading-spinner" />
        <p>Loading MAA...</p>
      </div>
    )
  }

  return (
    <div className="app">
      <Navbar worker={worker} onLogout={handleLogout} />
      <Routes>
        <Route path="/" element={<Home isLoggedIn={!!worker} />} />
        <Route path="/login" element={worker ? <Navigate to="/dashboard" /> : <Login onLogin={handleLogin} />} />
        <Route path="/register" element={worker ? <Navigate to="/dashboard" /> : <Register onLogin={handleLogin} />} />
        <Route path="/dashboard" element={<ProtectedRoute worker={worker}><Dashboard /></ProtectedRoute>} />
        <Route path="/patients" element={<ProtectedRoute worker={worker}><Patients /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
