import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'

const API = '/api'

const RISK_OPTIONS = ['low', 'moderate', 'high']
const LANGUAGE_OPTIONS = [
  { code: 'hi', label: 'Hindi' },
  { code: 'ta', label: 'Tamil' },
  { code: 'mr', label: 'Marathi' },
  { code: 'te', label: 'Telugu' },
  { code: 'en', label: 'English' },
]

const EMPTY_FORM = {
  name: '', weeks: '', trimester: '1', risk_level: 'low',
  language_code: 'hi', pregnancy_number: '1', blood_group: '',
  phone: '', address: '', asha_phone: '',
}

function PatientModal({ patient, onClose, onSaved }) {
  const isEdit = !!patient?.id
  const [form, setForm] = useState(isEdit ? {
    name: patient.name || '',
    weeks: String(patient.weeks || ''),
    trimester: String(patient.trimester || '1'),
    risk_level: patient.risk_level || 'low',
    language_code: patient.language_code || 'hi',
    pregnancy_number: String(patient.pregnancy_number || '1'),
    blood_group: patient.blood_group || '',
    phone: patient.phone || '',
    address: patient.address || '',
    asha_phone: patient.asha_phone || '',
  } : { ...EMPTY_FORM })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const update = (field, value) => setForm((f) => ({ ...f, [field]: value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!form.name.trim()) { setError('Name is required'); return }
    if (!form.weeks || isNaN(form.weeks) || +form.weeks < 1 || +form.weeks > 42) {
      setError('Gestational weeks must be 1-42'); return
    }
    setLoading(true)
    const body = {
      ...form,
      weeks: parseInt(form.weeks),
      trimester: parseInt(form.trimester),
      pregnancy_number: parseInt(form.pregnancy_number),
    }
    try {
      const url = isEdit ? `${API}/patients/${patient.id}` : `${API}/patients`
      const res = await fetch(url, {
        method: isEdit ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed to save')
      onSaved(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{isEdit ? 'Edit Patient' : 'Add New Patient'}</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit} className="patient-form">
          {error && <div className="auth-error">{error}</div>}

          <div className="form-grid">
            <div className="form-group full-width">
              <label>Full Name *</label>
              <input type="text" value={form.name} onChange={(e) => update('name', e.target.value)} placeholder="Patient's full name" required />
            </div>

            <div className="form-group">
              <label>Gestational Weeks *</label>
              <input type="number" value={form.weeks} onChange={(e) => update('weeks', e.target.value)} min="1" max="42" placeholder="e.g. 28" required />
            </div>

            <div className="form-group">
              <label>Trimester</label>
              <select value={form.trimester} onChange={(e) => update('trimester', e.target.value)}>
                <option value="1">1st Trimester</option>
                <option value="2">2nd Trimester</option>
                <option value="3">3rd Trimester</option>
              </select>
            </div>

            <div className="form-group">
              <label>Risk Level</label>
              <select value={form.risk_level} onChange={(e) => update('risk_level', e.target.value)}>
                {RISK_OPTIONS.map((r) => (
                  <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Language</label>
              <select value={form.language_code} onChange={(e) => update('language_code', e.target.value)}>
                {LANGUAGE_OPTIONS.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Pregnancy Number</label>
              <input type="number" value={form.pregnancy_number} onChange={(e) => update('pregnancy_number', e.target.value)} min="1" max="10" />
            </div>

            <div className="form-group">
              <label>Blood Group</label>
              <select value={form.blood_group} onChange={(e) => update('blood_group', e.target.value)}>
                <option value="">Not specified</option>
                {['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'].map((bg) => (
                  <option key={bg} value={bg}>{bg}</option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>Phone Number</label>
              <input type="tel" value={form.phone} onChange={(e) => update('phone', e.target.value)} placeholder="+91 98765 43210" />
            </div>

            <div className="form-group">
              <label>ASHA Worker Phone</label>
              <input type="tel" value={form.asha_phone} onChange={(e) => update('asha_phone', e.target.value)} placeholder="+91 98765 43210" />
            </div>

            <div className="form-group full-width">
              <label>Address</label>
              <input type="text" value={form.address} onChange={(e) => update('address', e.target.value)} placeholder="Village, district, state" />
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? 'Saving...' : (isEdit ? 'Update Patient' : 'Add Patient')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function DeleteConfirmModal({ patient, onClose, onConfirm }) {
  const [loading, setLoading] = useState(false)

  const handleDelete = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/patients/${patient.id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed to delete')
      onConfirm()
    } catch {
      alert('Failed to delete patient')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-small" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Delete Patient</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="delete-body">
          <div className="delete-icon">⚠️</div>
          <p>Are you sure you want to delete <strong>{patient.name}</strong>?</p>
          <p className="delete-warning">This will permanently remove all their records, logs, prescriptions, and care plans. This action cannot be undone.</p>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn-cancel" onClick={onClose}>Cancel</button>
          <button type="button" className="btn-danger" onClick={handleDelete} disabled={loading}>
            {loading ? 'Deleting...' : 'Delete Patient'}
          </button>
        </div>
      </div>
    </div>
  )
}

const SEVERITY_COLORS = {
  RED: '#dc2626', YELLOW: '#f59e0b', GREEN: '#16a34a', NONE: '#94a3b8', PENDING: '#94a3b8',
}

export default function Patients() {
  const [patients, setPatients] = useState([])
  const [search, setSearch] = useState('')
  const [filterRisk, setFilterRisk] = useState('all')
  const [showModal, setShowModal] = useState(false)
  const [editPatient, setEditPatient] = useState(null)
  const [deletePatient, setDeletePatient] = useState(null)

  const fetchPatients = useCallback(() => {
    fetch(`${API}/patients`)
      .then((r) => r.json())
      .then(setPatients)
      .catch(console.error)
  }, [])

  useEffect(() => { fetchPatients() }, [fetchPatients])

  const filtered = patients.filter((p) => {
    const matchesSearch = p.name.toLowerCase().includes(search.toLowerCase())
    const matchesRisk = filterRisk === 'all' || p.risk_level === filterRisk
    return matchesSearch && matchesRisk
  })

  const handleSaved = () => {
    setShowModal(false)
    setEditPatient(null)
    fetchPatients()
  }

  const handleDeleted = () => {
    setDeletePatient(null)
    fetchPatients()
  }

  const riskCount = (level) => patients.filter((p) => p.risk_level === level).length

  return (
    <div className="patients-page">
      <div className="patients-header">
        <div>
          <h1>Patient Management</h1>
          <p className="patients-subtitle">{patients.length} patients registered</p>
        </div>
        <button className="btn-primary" onClick={() => { setEditPatient(null); setShowModal(true) }}>
          + Add New Patient
        </button>
      </div>

      {/* Summary Cards */}
      <div className="patients-summary">
        <div className="summary-card" onClick={() => setFilterRisk('all')}>
          <div className="summary-num">{patients.length}</div>
          <div className="summary-label">Total Patients</div>
        </div>
        <div className="summary-card risk-high" onClick={() => setFilterRisk('high')}>
          <div className="summary-num">{riskCount('high')}</div>
          <div className="summary-label">High Risk</div>
        </div>
        <div className="summary-card risk-moderate" onClick={() => setFilterRisk('moderate')}>
          <div className="summary-num">{riskCount('moderate')}</div>
          <div className="summary-label">Moderate Risk</div>
        </div>
        <div className="summary-card risk-low" onClick={() => setFilterRisk('low')}>
          <div className="summary-num">{riskCount('low')}</div>
          <div className="summary-label">Low Risk</div>
        </div>
      </div>

      {/* Filters */}
      <div className="patients-toolbar">
        <input
          type="text"
          className="search-input"
          placeholder="Search patients by name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="risk-filters">
          {['all', 'high', 'moderate', 'low'].map((r) => (
            <button
              key={r}
              className={`filter-chip ${filterRisk === r ? 'active' : ''}`}
              onClick={() => setFilterRisk(r)}
            >
              {r === 'all' ? 'All' : r.charAt(0).toUpperCase() + r.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Patient Table */}
      <div className="patients-table-wrap">
        <table className="patients-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Name</th>
              <th>Weeks</th>
              <th>Trimester</th>
              <th>Risk</th>
              <th>Today</th>
              <th>Language</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => (
              <tr key={p.id}>
                <td className="td-id">#MAA-{String(p.id).padStart(4, '0')}</td>
                <td className="td-name">
                  <Link to={`/dashboard?patient=${p.id}`}>{p.name}</Link>
                </td>
                <td>{p.weeks}w</td>
                <td>T{p.trimester}</td>
                <td>
                  <span className={`risk-badge risk-${p.risk_level}`}>
                    {p.risk_level.toUpperCase()}
                  </span>
                </td>
                <td>
                  <span className="severity-dot" style={{ backgroundColor: SEVERITY_COLORS[p.today_severity] || SEVERITY_COLORS.NONE }} />
                  {p.today_severity || 'N/A'}
                </td>
                <td>{LANGUAGE_OPTIONS.find((l) => l.code === p.language_code)?.label || p.language_code}</td>
                <td className="td-actions">
                  <button className="action-btn edit" onClick={() => { setEditPatient(p); setShowModal(true) }} title="Edit">✏️</button>
                  <button className="action-btn delete" onClick={() => setDeletePatient(p)} title="Delete">🗑️</button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan="8" className="empty-row">No patients found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Modals */}
      {showModal && (
        <PatientModal
          patient={editPatient}
          onClose={() => { setShowModal(false); setEditPatient(null) }}
          onSaved={handleSaved}
        />
      )}
      {deletePatient && (
        <DeleteConfirmModal
          patient={deletePatient}
          onClose={() => setDeletePatient(null)}
          onConfirm={handleDeleted}
        />
      )}
    </div>
  )
}
