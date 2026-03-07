import { useState, useEffect, useRef, useCallback } from 'react'

const API = '/api'

const SEVERITY_COLORS = {
  RED: '#dc2626',
  YELLOW: '#f59e0b',
  GREEN: '#16a34a',
  NONE: '#94a3b8',
  PENDING: '#94a3b8',
}

const SEVERITY_EMOJI = { RED: '🚨', YELLOW: '⚠️', GREEN: '✅', NONE: '—', PENDING: '⏳' }

const AGENT_COLORS = {
  CheckInAgent: '#e879a0',
  SymptomAgent: '#f59e0b',
  ResourceAgent: '#3b82f6',
  NotifyAgent: '#dc2626',
  CareAgent: '#16a34a',
  Pipeline: '#8b5cf6',
  System: '#94a3b8',
}

const LANG_LABELS = { hi: 'Hindi', ta: 'Tamil', mr: 'Marathi', te: 'Telugu', en: 'English' }

// ── SSE Hook ──
function useSSE(url) {
  const [events, setEvents] = useState([])
  const esRef = useRef(null)

  useEffect(() => {
    const es = new EventSource(url)
    esRef.current = es

    es.addEventListener('agent_event', (e) => {
      try {
        const data = JSON.parse(e.data)
        setEvents((prev) => [data, ...prev].slice(0, 200))
      } catch {}
    })

    es.onerror = () => {
      es.close()
      setTimeout(() => {
        esRef.current = new EventSource(url)
      }, 3000)
    }

    return () => es.close()
  }, [url])

  return events
}

// ── Helper: Parse conversation from raw_response ──
function parseConversation(rawResponse) {
  if (!rawResponse) return null
  try {
    const parsed = JSON.parse(rawResponse)
    if (Array.isArray(parsed)) return parsed
    return null
  } catch {
    // Not JSON — return as plain text
    return null
  }
}

// ── AlertBanner ──
function AlertBanner({ patients }) {
  const critical = patients.filter((p) => p.today_severity === 'RED')
  if (critical.length === 0) return null

  return (
    <div className="alert-banner">
      <span className="alert-icon">⚠</span>
      <div>
        <strong>Critical alert</strong> —{' '}
        {critical.map((p) => p.name).join(', ')}{' '}
        {critical.length === 1 ? 'requires' : 'require'} immediate attention
      </div>
      <button className="alert-action" onClick={() => {}}>
        Take Action
      </button>
    </div>
  )
}

// ── PatientCard ──
function PatientCard({ patient, selected, onClick }) {
  const sevColor = SEVERITY_COLORS[patient.today_severity] || SEVERITY_COLORS.NONE

  const minMedDays = patient.medicine_days_remaining
    ? Math.min(...Object.values(patient.medicine_days_remaining))
    : null

  return (
    <div
      className={`patient-card ${selected ? 'selected' : ''}`}
      onClick={onClick}
      style={{ borderLeftColor: sevColor }}
    >
      <div className="pc-header">
        <div className="pc-name">{patient.name}</div>
        <div className="pc-severity-dot" style={{ backgroundColor: sevColor }} />
      </div>
      <div className="pc-meta">
        {patient.weeks} Weeks • {patient.risk_level.charAt(0).toUpperCase() + patient.risk_level.slice(1)} Risk
      </div>
      {patient.last_message && (
        <div className="pc-message">"{patient.last_message}"</div>
      )}
      <div className="pc-footer">
        {minMedDays !== null && (
          <span className={`pc-meds ${minMedDays <= 5 ? 'low' : ''}`}>
            MEDS: {String(minMedDays).padStart(2, '0')} REMAINING
          </span>
        )}
        {selected && <span className="pc-selected-tag">SELECTED</span>}
      </div>
    </div>
  )
}

// ── PatientList ──
function PatientList({ patients, selectedId, onSelect }) {
  const [filter, setFilter] = useState('All')

  const filtered = patients.filter((p) => {
    if (filter === 'All') return true
    if (filter === 'High Risk') return p.risk_level === 'high' || p.today_severity === 'RED'
    if (filter === 'Follow-up') return p.today_severity === 'YELLOW'
    return true
  })

  return (
    <div className="patient-list">
      <div className="pl-header">
        <h2>Patient Queue</h2>
        <span className="pl-count">{patients.length} Active Cases</span>
      </div>
      <div className="pl-filters">
        {['All', 'High Risk', 'Follow-up'].map((f) => (
          <button
            key={f}
            className={`filter-btn ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}
          >
            {f}
          </button>
        ))}
      </div>
      <div className="pl-cards">
        {filtered.map((p) => (
          <PatientCard
            key={p.id}
            patient={p}
            selected={p.id === selectedId}
            onClick={() => onSelect(p.id)}
          />
        ))}
      </div>
    </div>
  )
}

// ── ChatBubbles — renders a parsed conversation array ──
function ChatBubbles({ messages }) {
  if (!messages || messages.length === 0) return null
  return (
    <div className="chat-bubbles">
      {messages.map((msg, i) => (
        <div key={i} className={`chat-bubble ${msg.role === 'assistant' ? 'bot' : 'user'}`}>
          <div className="bubble-label">
            {msg.role === 'assistant' ? '🌸 Maa' : '👤 Patient'}
          </div>
          <div className="bubble-content">{msg.content}</div>
        </div>
      ))}
    </div>
  )
}

// ── ConversationView (Care Plan tab — shows recent conversations + severity) ──
function ConversationView({ logs }) {
  if (!logs || logs.length === 0) return <div className="conv-empty">No conversation data</div>

  return (
    <div className="conversation-view">
      <h3>This Week's Conversations</h3>
      {logs.slice(0, 7).map((log, i) => {
        const messages = parseConversation(log.raw_response)
        return (
          <div key={i} className="conv-entry">
            <div className="conv-date">{log.date}</div>
            {messages ? (
              <ChatBubbles messages={messages} />
            ) : (
              log.raw_response && <div className="conv-text-plain">{log.raw_response}</div>
            )}
            <div className="conv-severity">
              <span style={{ color: SEVERITY_COLORS[log.severity] }}>
                {SEVERITY_EMOJI[log.severity]} {log.severity}
              </span>
              {log.reason && <span className="conv-reason"> — {log.reason}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── SymptomTimeline ──
function SymptomTimeline({ logs }) {
  const sorted = [...logs].sort((a, b) => a.date.localeCompare(b.date))
  return (
    <div className="symptom-timeline">
      <h3>14-DAY SYMPTOM TIMELINE</h3>
      <div className="st-dots">
        {sorted.map((log, i) => (
          <div key={i} className="st-dot-wrapper" title={`${log.date}: ${log.severity} — ${log.reason || 'OK'}`}>
            <div
              className="st-dot"
              style={{ backgroundColor: SEVERITY_COLORS[log.severity] || '#94a3b8' }}
            />
            <span className="st-day">{i + 1}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── MedicineBar ──
function MedicineBar({ medicines }) {
  if (!medicines) return null
  return (
    <div className="medicine-bar">
      <h3>7-DAY MED COMPLIANCE</h3>
      {Object.entries(medicines).map(([name, data]) => (
        <div key={name} className="mb-item">
          <div className="mb-name">{name}</div>
          <div className="mb-bar-track">
            <div
              className="mb-bar-fill"
              style={{ width: `${data.rate}%`, backgroundColor: data.rate >= 80 ? '#16a34a' : data.rate >= 50 ? '#f59e0b' : '#dc2626' }}
            />
          </div>
          <span className="mb-rate">{data.rate}%</span>
        </div>
      ))}
    </div>
  )
}

// ── CarePlans ──
function CarePlans({ plans }) {
  if (!plans || plans.length === 0) return null
  return (
    <div className="care-plans">
      <h3>Recent Care Plans</h3>
      {plans.map((plan, i) => (
        <div key={i} className="cp-item">
          <div className="cp-date">{plan.date}</div>
          <pre className="cp-content">{plan.content_english}</pre>
        </div>
      ))}
    </div>
  )
}

// ── ChatHistoryTab — dedicated chat history view ──
function ChatHistoryTab({ logs }) {
  if (!logs || logs.length === 0) {
    return <div className="conv-empty">No chat history available</div>
  }

  // Group and show all conversations with full chat bubbles
  const logsWithConvo = logs.filter((l) => l.raw_response)

  if (logsWithConvo.length === 0) {
    return <div className="conv-empty">No chat history recorded yet</div>
  }

  return (
    <div className="chat-history-tab">
      {logsWithConvo.map((log, i) => {
        const messages = parseConversation(log.raw_response)
        return (
          <div key={i} className="chat-history-day">
            <div className="chd-header">
              <span className="chd-date">{log.date}</span>
              <span
                className="chd-severity-badge"
                style={{
                  backgroundColor: `${SEVERITY_COLORS[log.severity] || '#94a3b8'}18`,
                  color: SEVERITY_COLORS[log.severity] || '#94a3b8',
                }}
              >
                {SEVERITY_EMOJI[log.severity]} {log.severity}
              </span>
            </div>
            {messages ? (
              <ChatBubbles messages={messages} />
            ) : (
              <div className="conv-text-plain">{log.raw_response}</div>
            )}
            {log.reason && (
              <div className="chd-reason">
                <strong>Assessment:</strong> {log.reason}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── VitalsTab — symptom tracking, fetal movement, medicines ──
function VitalsTab({ data, medicines }) {
  const logs = data?.daily_logs || []
  const prescriptions = data?.prescriptions || []

  return (
    <div className="vitals-tab">
      {/* Symptom Timeline */}
      <SymptomTimeline logs={logs} />

      {/* Severity History Table */}
      <div className="vitals-section">
        <h3>Symptom Log</h3>
        {logs.length > 0 ? (
          <div className="vitals-table-wrap">
            <table className="vitals-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Severity</th>
                  <th>Symptoms</th>
                  <th>Fetal Movement</th>
                  <th>Assessment</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log, i) => {
                  let symptoms = '—'
                  try {
                    const parsed = JSON.parse(log.symptoms || '[]')
                    symptoms = Array.isArray(parsed) && parsed.length > 0 ? parsed.join(', ') : '—'
                  } catch {
                    symptoms = log.symptoms || '—'
                  }
                  return (
                    <tr key={i}>
                      <td className="vt-date">{log.date}</td>
                      <td>
                        <span
                          className="vt-severity-badge"
                          style={{
                            backgroundColor: `${SEVERITY_COLORS[log.severity] || '#94a3b8'}18`,
                            color: SEVERITY_COLORS[log.severity] || '#94a3b8',
                          }}
                        >
                          {SEVERITY_EMOJI[log.severity]} {log.severity}
                        </span>
                      </td>
                      <td>{symptoms}</td>
                      <td>{log.fetal_movement || '—'}</td>
                      <td className="vt-reason">{log.reason || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="conv-empty">No vitals recorded yet</div>
        )}
      </div>

      {/* Medicine Compliance */}
      <MedicineBar medicines={medicines} />

      {/* Prescriptions */}
      {prescriptions.length > 0 && (
        <div className="vitals-section">
          <h3>Active Prescriptions</h3>
          <div className="prescriptions-grid">
            {prescriptions.map((rx, i) => (
              <div key={i} className="rx-card">
                <div className="rx-name">💊 {rx.medicine_name}</div>
                <div className="rx-details">
                  <span>Frequency: {rx.frequency}</span>
                  <span>Supply: {rx.quantity_supplied} days</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Patient Info Card */}
      <div className="vitals-section">
        <h3>Patient Profile</h3>
        <div className="patient-info-grid">
          <div className="pi-item">
            <span className="pi-label">Gestational Age</span>
            <span className="pi-value">{data?.weeks || '—'} weeks</span>
          </div>
          <div className="pi-item">
            <span className="pi-label">Trimester</span>
            <span className="pi-value">{data?.trimester || '—'}</span>
          </div>
          <div className="pi-item">
            <span className="pi-label">Risk Level</span>
            <span className="pi-value" style={{
              color: data?.risk_level === 'high' ? '#dc2626' : data?.risk_level === 'moderate' ? '#f59e0b' : '#16a34a',
              fontWeight: 700,
            }}>
              {data?.risk_level?.toUpperCase() || '—'}
            </span>
          </div>
          <div className="pi-item">
            <span className="pi-label">Language</span>
            <span className="pi-value">{LANG_LABELS[data?.language_code] || data?.language_code || '—'}</span>
          </div>
          <div className="pi-item">
            <span className="pi-label">Pregnancy #</span>
            <span className="pi-value">{data?.pregnancy_number || '—'}</span>
          </div>
          <div className="pi-item">
            <span className="pi-label">Blood Group</span>
            <span className="pi-value">{data?.blood_group || '—'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── PatientDetail ──
function PatientDetail({ patientId }) {
  const [data, setData] = useState(null)
  const [medicines, setMedicines] = useState(null)
  const [activeTab, setActiveTab] = useState('care')

  useEffect(() => {
    if (!patientId) return
    fetch(`${API}/patients/${patientId}`)
      .then((r) => r.json())
      .then(setData)
    fetch(`${API}/patients/${patientId}/medicines`)
      .then((r) => r.json())
      .then(setMedicines)
    // Reset tab on patient change
    setActiveTab('care')
  }, [patientId])

  if (!patientId) return <div className="detail-empty">Select a patient</div>
  if (!data) return <div className="detail-loading">Loading...</div>

  const tabs = [
    { id: 'care', label: 'Care Plan', icon: '📋' },
    { id: 'chat', label: 'Chat History', icon: '💬' },
    { id: 'vitals', label: 'Vitals', icon: '❤️' },
  ]

  return (
    <div className="patient-detail">
      <div className="pd-header">
        <div>
          <h2>{data.name}</h2>
          <div className="pd-meta">
            PATIENT ID: #MAA-{String(data.id).padStart(4, '0')} •{' '}
            {data.weeks}w • Trimester {data.trimester} •{' '}
            {LANG_LABELS[data.language_code] || data.language_code}
          </div>
        </div>
        <div
          className="pd-risk-badge"
          style={{
            backgroundColor:
              data.risk_level === 'high'
                ? '#fecaca'
                : data.risk_level === 'moderate'
                ? '#fef3c7'
                : '#dcfce7',
            color:
              data.risk_level === 'high'
                ? '#dc2626'
                : data.risk_level === 'moderate'
                ? '#d97706'
                : '#16a34a',
          }}
        >
          {data.risk_level.toUpperCase()} RISK
        </div>
      </div>

      <div className="pd-tabs">
        {tabs.map((tab) => (
          <span
            key={tab.id}
            className={`pd-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.icon} {tab.label}
          </span>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'care' && (
        <>
          <ConversationView logs={data.daily_logs} />
          <SymptomTimeline logs={data.daily_logs} />
          <MedicineBar medicines={medicines} />
          <CarePlans plans={data.care_plans} />
        </>
      )}

      {activeTab === 'chat' && (
        <ChatHistoryTab logs={data.daily_logs} />
      )}

      {activeTab === 'vitals' && (
        <VitalsTab data={data} medicines={medicines} />
      )}
    </div>
  )
}

// ── AgentFeed ──
function AgentFeed({ events, storedEvents, selectedPatientId }) {
  const allEvents = [
    ...events,
    ...storedEvents.map((e) => ({
      agent: e.agent_name,
      patient_id: e.patient_id,
      message: e.message,
      timestamp: e.created_at,
    })),
  ].filter((e) => !selectedPatientId || e.patient_id === selectedPatientId)

  return (
    <div className="agent-feed">
      <h2>Activity Feed</h2>
      <div className="af-items">
        {allEvents.slice(0, 100).map((event, i) => (
          <div
            key={i}
            className="af-item"
            style={{ borderLeftColor: AGENT_COLORS[event.agent] || '#94a3b8' }}
          >
            <div className="af-agent">{event.agent}</div>
            <div className="af-message">{event.message}</div>
            <div className="af-time">
              {event.timestamp
                ? new Date(event.timestamp).toLocaleTimeString()
                : ''}
            </div>
          </div>
        ))}
        {allEvents.length === 0 && (
          <div className="af-empty">No events yet. Trigger a pipeline to see agent activity.</div>
        )}
      </div>
    </div>
  )
}

// ── App ──
export default function App() {
  const [patients, setPatients] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [storedEvents, setStoredEvents] = useState([])
  const liveEvents = useSSE(`${API}/pipeline-feed`)

  const fetchPatients = useCallback(() => {
    fetch(`${API}/patients`)
      .then((r) => r.json())
      .then((data) => {
        setPatients(data)
        if (!selectedId && data.length > 0) setSelectedId(data[0].id)
      })
      .catch(console.error)
  }, [selectedId])

  useEffect(() => {
    fetchPatients()
    fetch(`${API}/events?limit=50`)
      .then((r) => r.json())
      .then(setStoredEvents)
      .catch(console.error)

    const interval = setInterval(fetchPatients, 15000)
    return () => clearInterval(interval)
  }, [fetchPatients])

  const triggerPipeline = async (patientId) => {
    await fetch(`${API}/trigger/pipeline/${patientId}`, { method: 'POST' })
    setTimeout(fetchPatients, 2000)
  }

  return (
    <div className="app">
      <AlertBanner patients={patients} />
      <header className="app-header">
        <div className="header-left">
          <span className="header-icon">☰</span>
          <h1 className="header-title">
            <span className="logo-flower">🌸</span> Maa Dashboard
          </h1>
        </div>
        <div className="header-right">
          <button className="trigger-btn" onClick={() => selectedId && triggerPipeline(selectedId)}>
            ▶ Run Pipeline
          </button>
          <span className="header-bell">🔔</span>
          <span className="header-avatar">A</span>
        </div>
      </header>

      <div className="main-layout">
        <aside className="sidebar-left">
          <PatientList
            patients={patients}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </aside>

        <main className="center-panel">
          <PatientDetail patientId={selectedId} />
        </main>

        <aside className="sidebar-right">
          <AgentFeed events={liveEvents} storedEvents={storedEvents} selectedPatientId={selectedId} />
        </aside>
      </div>
    </div>
  )
}
