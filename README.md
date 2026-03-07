# Maa — Multi-Agent Maternal Health Assistant 🌸

5 AI agents collaborate in a Telegram group to monitor pregnant women daily, track medicine, detect danger signs, notify ASHA workers, and book appointments — autonomously.

## Architecture

```
CheckInAgent  (Mistral)       — Daily morning check-in, conversation, data extraction
SymptomAgent  (Groq/LLaMA)    — 14-day pattern analysis, severity detection
ResourceAgent (Gemini)         — Medicine stock tracking, compliance, runout prediction
NotifyAgent   (NVIDIA NIM)     — Email, Ntfy push, Vapi outbound calls
CareAgent     (Ollama)         — Appointment booking, care plan generation
```

All patient-facing messages pass through **Sarvam AI** for multilingual translation (Hindi, Tamil, Marathi, Telugu).

## Pre-seeded Patients

| Name           | Weeks | Risk     | Language |
|----------------|-------|----------|----------|
| Priya Sharma   | 34    | Moderate | Hindi    |
| Anita Devi     | 28    | Low      | Tamil    |
| Meena Bai      | 38    | High     | Marathi  |
| Sunita Kumari  | 22    | Low      | Telugu   |

## Quick Start

### 1. Setup

```bash
# Clone and enter project
cd Maa

# Copy env and fill in your API keys
cp .env.example .env

# Install backend dependencies
cd backend
pip install -r requirements.txt
cd ..

# Install frontend dependencies
cd frontend
npm install
cd ..
```

### 2. Create Telegram Bots

Create 5 bots via [@BotFather](https://t.me/BotFather):
- MaaCheckIn, MaaSymptom, MaaResource, MaaNotify, MaaCare

Add all 5 to a Telegram group as admins. Disable group privacy for all 5.
Put tokens in `.env`.

### 3. Run

```bash
# Terminal 1 — Backend
cd backend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Dashboard: http://localhost:5173
API: http://localhost:8000/docs

### 4. Demo Mode

With `DEMO_MODE=true`, any registered patient sending **any message** (e.g., "hi") triggers the full 5-agent pipeline immediately. No scheduler needed.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/api/patients` | All patients (sorted RED first) |
| GET    | `/api/patients/:id` | Patient detail + logs |
| GET    | `/api/patients/:id/logs` | 14-day daily logs |
| GET    | `/api/patients/:id/medicines` | Medicine compliance |
| GET    | `/api/patients/:id/care-plans` | Care plans |
| GET    | `/api/events` | Recent agent events |
| GET    | `/api/pipeline-feed` | SSE live agent feed |
| POST   | `/api/trigger/pipeline/:id` | Trigger pipeline for one patient |
| POST   | `/api/trigger/all` | Trigger pipeline for all patients |
| GET    | `/api/status` | System status |

## Pipeline Flow

```
08:00  CheckInAgent → morning message (Sarvam translated)
       Patient replies → Sarvam → English → follow-up (max 4 exchanges)
       Extract structured JSON → SQLite

       SymptomAgent → 14-day analysis → GREEN/YELLOW/RED

       ResourceAgent → medicine stock → flags

       NotifyAgent:
         GREEN  → log only
         YELLOW → email ASHA
         RED    → email + Ntfy push + Vapi call

       CareAgent (on YELLOW/RED):
         → Google Calendar appointment
         → Care plan → Sarvam translated → patient
```

## Key Rotation

Sarvam and Vapi API keys rotate automatically via `KeyRotator`:
- Tracks usage in `state.json`
- On HTTP 429 → marks exhausted, switches to next key
- Exhausted keys retry after 60 minutes
- All keys down → Sarvam falls back to English, Vapi falls back to Ntfy

## Tech Stack

- **Backend:** Python, FastAPI, APScheduler, python-telegram-bot
- **Frontend:** React + Vite, SSE for live feed
- **Database:** SQLite (auto-seeded on first run)
- **AI:** Mistral, Groq, Gemini, NVIDIA NIM, Ollama
- **Translation:** Sarvam AI
- **Calls:** Vapi AI
- **Notifications:** Ntfy.sh, Gmail SMTP
