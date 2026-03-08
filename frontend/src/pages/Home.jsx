import { Link } from 'react-router-dom'

const NEWS_ITEMS = [
  {
    title: "India's Maternal Mortality Ratio Drops to 97 per 100,000 Live Births",
    summary: "India has made significant progress in reducing maternal mortality, with the MMR declining from 130 in 2014-16 to 97 in 2018-20. However, rural areas still lag behind urban centres, emphasizing the need for ground-level healthcare workers.",
    source: "Ministry of Health & Family Welfare",
    date: "2025",
    tag: "Progress",
    tagColor: "#16a34a",
  },
  {
    title: "ASHA Workers: The Backbone of India's Maternal Health Revolution",
    summary: "Over 10 lakh ASHA workers across India serve as the critical link between pregnant women in rural communities and the healthcare system. Their tireless efforts have been instrumental in reducing maternal and neonatal mortality.",
    source: "National Health Mission",
    date: "2025",
    tag: "ASHA Impact",
    tagColor: "#3b82f6",
  },
  {
    title: "Pre-eclampsia & Eclampsia: Leading Cause of Maternal Deaths in India",
    summary: "Hypertensive disorders during pregnancy account for nearly 14% of all maternal deaths in India. Early detection through regular monitoring and timely intervention by ASHA workers can prevent most of these deaths.",
    source: "Indian Journal of Medical Research",
    date: "2025",
    tag: "Awareness",
    tagColor: "#f59e0b",
  },
  {
    title: "AI-Powered Healthcare: The Future of Maternal Monitoring in Rural India",
    summary: "Artificial intelligence systems like MAA are being deployed to assist ASHA workers with real-time symptom analysis, risk assessment, and automated follow-ups in regional languages, bridging the gap in rural healthcare delivery.",
    source: "Digital India Health Initiative",
    date: "2026",
    tag: "Technology",
    tagColor: "#8b5cf6",
  },
  {
    title: "Anaemia Affects 50% of Pregnant Women in India — Prevention is Key",
    summary: "Iron deficiency anaemia remains a critical concern, affecting every second pregnant woman in India. Regular iron supplementation tracking and dietary counselling through ASHA workers is vital for prevention.",
    source: "NFHS-5 Survey",
    date: "2025",
    tag: "Health Crisis",
    tagColor: "#dc2626",
  },
  {
    title: "Pradhan Mantri Surakshit Matritva Abhiyan Expands to All Districts",
    summary: "The PMSMA initiative now covers all 780+ districts, providing free antenatal check-ups on the 9th of every month. Integration with digital tools helps ASHA workers track and ensure complete coverage of pregnant women.",
    source: "Government of India",
    date: "2025",
    tag: "Policy",
    tagColor: "#0ea5e9",
  },
]

const STATS = [
  { number: "44,000", label: "Maternal deaths annually in India", icon: "💔" },
  { number: "97", label: "MMR per 100K live births", icon: "📊" },
  { number: "70%", label: "Deaths preventable with timely care", icon: "🛡️" },
  { number: "10L+", label: "ASHA workers serving rural India", icon: "🤝" },
]

const STEPS = [
  {
    icon: "🤖",
    title: "AI Daily Check-ins",
    desc: "MAA automatically contacts each pregnant woman daily via Telegram in her local language, asking about symptoms, fetal movement, and medicine compliance.",
  },
  {
    icon: "🔍",
    title: "Smart Risk Analysis",
    desc: "Multi-agent AI pipeline analyses responses in real-time, detecting danger signs like pre-eclampsia, anaemia, and reduced fetal movement with medical-grade accuracy.",
  },
  {
    icon: "🚨",
    title: "Instant ASHA Alerts",
    desc: "High-risk cases trigger immediate alerts to the assigned ASHA worker with personalized care plans, ensuring no critical case goes unnoticed.",
  },
  {
    icon: "📋",
    title: "Comprehensive Dashboard",
    desc: "ASHA workers get a full admin panel to manage patients, track vitals, monitor medicine compliance, and generate care plans — all in one place.",
  },
]

export default function Home({ isLoggedIn }) {
  return (
    <div className="home-page">
      {/* Hero Section */}
      <section className="hero">
        <div className="hero-bg-shapes">
          <div className="hero-shape hero-shape-1" />
          <div className="hero-shape hero-shape-2" />
          <div className="hero-shape hero-shape-3" />
        </div>
        <div className="hero-content">
          <div className="hero-badge">🇮🇳 Protecting Every Mother in India</div>
          <h1 className="hero-title">
            <span className="hero-flower">🌸</span> MAA
          </h1>
          <p className="hero-subtitle">Maternal Agentic Assistant</p>
          <p className="hero-desc">
            An AI-powered multi-agent system that partners with ASHA workers to monitor
            high-risk pregnancies, detect danger signs early, and save mothers' lives
            across rural India — in every regional language.
          </p>
          <div className="hero-actions">
            {isLoggedIn ? (
              <Link to="/dashboard" className="hero-btn primary">Open Dashboard →</Link>
            ) : (
              <>
                <Link to="/register" className="hero-btn primary">Get Started — It's Free</Link>
                <Link to="/login" className="hero-btn secondary">Sign In</Link>
              </>
            )}
          </div>
          <div className="hero-languages">
            Supports: <strong>Hindi</strong> • <strong>Tamil</strong> • <strong>Telugu</strong> • <strong>Marathi</strong> • <strong>English</strong> + more
          </div>
        </div>
      </section>

      {/* Stats Section */}
      <section className="stats-section">
        <div className="section-container">
          <h2 className="section-title">The Maternal Health Crisis in India</h2>
          <p className="section-subtitle">
            Despite significant progress, India still accounts for 12% of global maternal deaths.
            Most of these deaths are preventable with timely intervention.
          </p>
          <div className="stats-grid">
            {STATS.map((stat, i) => (
              <div key={i} className="stat-card">
                <span className="stat-icon">{stat.icon}</span>
                <div className="stat-number">{stat.number}</div>
                <div className="stat-label">{stat.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="how-section">
        <div className="section-container">
          <h2 className="section-title">How MAA Saves Lives</h2>
          <p className="section-subtitle">
            A 5-agent AI pipeline that works 24/7 alongside ASHA workers
          </p>
          <div className="steps-grid">
            {STEPS.map((step, i) => (
              <div key={i} className="step-card">
                <div className="step-number">{String(i + 1).padStart(2, '0')}</div>
                <div className="step-icon">{step.icon}</div>
                <h3>{step.title}</h3>
                <p>{step.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="features-section">
        <div className="section-container">
          <h2 className="section-title">Built for ASHA Workers</h2>
          <p className="section-subtitle">Everything you need to manage maternal healthcare in your area</p>
          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-icon">👩‍⚕️</div>
              <h3>Patient Management</h3>
              <p>Add, edit, and manage all pregnant women under your care. Track gestational age, risk levels, and contact information.</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">💊</div>
              <h3>Medicine Tracking</h3>
              <p>Monitor iron, calcium, and folic acid compliance. Get alerts when patients miss doses or run low on medicines.</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">📱</div>
              <h3>Telegram Integration</h3>
              <p>Automated daily check-ins via Telegram bots in the patient's own language. No app installation required.</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">📊</div>
              <h3>Risk Dashboard</h3>
              <p>Visual severity timelines, symptom logs, and care plans. See your entire patient queue prioritized by risk level.</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🔔</div>
              <h3>Smart Notifications</h3>
              <p>Instant alerts via Telegram, email, and push notifications when a patient reports danger signs.</p>
            </div>
            <div className="feature-card">
              <div className="feature-icon">🗓️</div>
              <h3>Appointment Scheduling</h3>
              <p>Automated reminders for PMSMA check-ups, vaccination schedules, and hospital visits.</p>
            </div>
          </div>
        </div>
      </section>

      {/* News Section */}
      <section className="news-section">
        <div className="section-container">
          <h2 className="section-title">Maternal Health News Across India</h2>
          <p className="section-subtitle">
            Stay informed about the latest developments in maternal healthcare
          </p>
          <div className="news-grid">
            {NEWS_ITEMS.map((item, i) => (
              <article key={i} className="news-card">
                <div className="news-tag" style={{ backgroundColor: `${item.tagColor}15`, color: item.tagColor }}>
                  {item.tag}
                </div>
                <h3>{item.title}</h3>
                <p>{item.summary}</p>
                <div className="news-meta">
                  <span>{item.source}</span>
                  <span>{item.date}</span>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <div className="section-container">
          <div className="cta-card">
            <h2>Ready to Save Lives?</h2>
            <p>
              Join the network of ASHA workers using MAA to provide better maternal
              healthcare in rural India. Setup takes less than 5 minutes.
            </p>
            <div className="cta-actions">
              {isLoggedIn ? (
                <Link to="/dashboard" className="hero-btn primary">Go to Dashboard</Link>
              ) : (
                <>
                  <Link to="/register" className="hero-btn primary">Create Free Account</Link>
                  <Link to="/login" className="hero-btn secondary">Sign In</Link>
                </>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="site-footer">
        <div className="section-container">
          <div className="footer-grid">
            <div className="footer-brand">
              <h3>🌸 MAA</h3>
              <p>AI-powered Maternal Agentic Assistant for ASHA workers across India.</p>
            </div>
            <div className="footer-links">
              <h4>Platform</h4>
              <Link to="/dashboard">Dashboard</Link>
              <Link to="/patients">Patient Management</Link>
            </div>
            <div className="footer-links">
              <h4>Resources</h4>
              <span>ASHA Worker Guide</span>
              <span>Maternal Health Tips</span>
              <span>Emergency Contacts</span>
            </div>
            <div className="footer-links">
              <h4>Emergency</h4>
              <span>Ambulance: 108</span>
              <span>Health Helpline: 104</span>
              <span>Women's Helpline: 181</span>
            </div>
          </div>
          <div className="footer-bottom">
            <p>© 2026 MAA — Maternal Agentic Assistant. Built with ❤️ for India's mothers.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
