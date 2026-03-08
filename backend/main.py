"""
Maa — FastAPI backend entry point.
Exposes REST API + SSE pipeline feed for the dashboard.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.config import DEMO_MODE
from backend.database import (
    init_db, get_all_patients, get_patient_by_id,
    get_daily_logs, get_medicine_logs, get_prescriptions,
    get_care_plans, get_notifications, get_agent_events,
    get_conversation_state, create_asha_worker, authenticate_worker,
    get_worker_by_token, delete_session, create_patient_record,
    update_patient, delete_patient, add_prescription,
)
from backend.pipeline import pipeline_events, run_full_pipeline, run_morning_pipeline
from backend.scheduler import setup_scheduler
from backend.telegram_bots import start_polling, stop_polling, bots

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("maa")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    logger.info("🌸 Maa is starting up...")

    # Initialize database and seed data
    init_db()
    logger.info("Database initialized")

    # Start scheduler
    sched = setup_scheduler()
    sched.start()
    logger.info("Scheduler started")

    # Start Telegram bots
    try:
        await start_polling()
        logger.info("Telegram bots started")
    except Exception as e:
        logger.warning(f"Telegram bots not started: {type(e).__name__}: {e}", exc_info=True)

    logger.info(f"Maa is ready! DEMO_MODE={'ON' if DEMO_MODE else 'OFF'}")

    yield

    # Shutdown
    logger.info("Maa shutting down...")
    sched.shutdown(wait=False)
    await stop_polling()


app = FastAPI(title="Maa — Maternal Health Assistant", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ──

@app.get("/api/patients")
async def list_patients():
    """Get all patients sorted by risk (RED first)."""
    patients = get_all_patients()
    result = []
    for p in patients:
        today = date.today().isoformat()
        logs = get_daily_logs(p["id"], days=1)
        meds = get_medicine_logs(p["id"], days=14)
        prescriptions = get_prescriptions(p["id"])

        # Calculate medicine days remaining
        med_days = {}
        for rx in prescriptions:
            taken = sum(1 for m in meds if m["medicine_name"] == rx["medicine_name"] and m["taken"])
            remaining = max(0, rx["quantity_supplied"] - taken)
            med_days[rx["medicine_name"]] = remaining

        latest_log = logs[0] if logs else None

        result.append({
            **p,
            "today_severity": latest_log["severity"] if latest_log else "NONE",
            "last_message": latest_log["raw_response"][:80] if latest_log and latest_log.get("raw_response") else "",
            "medicine_days_remaining": med_days,
        })

    return result


@app.get("/api/patients/{patient_id}")
async def get_patient(patient_id: int):
    """Get detailed patient info."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    today = date.today().isoformat()
    return {
        **patient,
        "daily_logs": get_daily_logs(patient_id, days=14),
        "medicine_logs": get_medicine_logs(patient_id, days=14),
        "prescriptions": get_prescriptions(patient_id),
        "care_plans": get_care_plans(patient_id, limit=3),
        "notifications": get_notifications(patient_id, limit=10),
        "conversation_state": get_conversation_state(patient_id, today),
    }


@app.get("/api/patients/{patient_id}/logs")
async def get_patient_logs(patient_id: int, days: int = 14):
    """Get daily logs for a patient."""
    return get_daily_logs(patient_id, days)


@app.get("/api/patients/{patient_id}/medicines")
async def get_patient_medicines(patient_id: int, days: int = 14):
    """Get medicine compliance data."""
    logs = get_medicine_logs(patient_id, days)
    prescriptions = get_prescriptions(patient_id)

    compliance = {}
    for rx in prescriptions:
        med_logs = [l for l in logs if l["medicine_name"] == rx["medicine_name"]]
        taken = sum(1 for l in med_logs if l["taken"])
        total = len(med_logs)
        compliance[rx["medicine_name"]] = {
            "taken": taken,
            "missed": total - taken,
            "total": total,
            "rate": round(taken / total * 100, 1) if total > 0 else 0,
            "frequency": rx["frequency"],
            "quantity_supplied": rx["quantity_supplied"],
            "remaining": max(0, rx["quantity_supplied"] - taken),
        }

    return compliance


@app.get("/api/patients/{patient_id}/care-plans")
async def get_patient_care_plans(patient_id: int):
    """Get care plans for a patient."""
    return get_care_plans(patient_id)


@app.get("/api/events")
async def get_events(limit: int = 50):
    """Get recent agent events."""
    return get_agent_events(limit)


@app.get("/api/pipeline-feed")
async def pipeline_feed():
    """SSE endpoint — streams agent events in real time."""
    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(pipeline_events.get(), timeout=30.0)
                yield {
                    "event": "agent_event",
                    "data": json.dumps({
                        **event,
                        "timestamp": datetime.now().isoformat(),
                    }),
                }
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": "{}"}

    return EventSourceResponse(event_generator())


# ── Demo/Manual Triggers ──

@app.post("/api/trigger/pipeline/{patient_id}")
async def trigger_pipeline(patient_id: int):
    """Manually trigger the full pipeline for a patient."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Run morning message + pipeline
    asyncio.create_task(run_morning_pipeline(patient_id, bots))
    return {"status": "triggered", "patient": patient["name"]}


@app.post("/api/trigger/all")
async def trigger_all():
    """Trigger pipeline for all patients."""
    patients = get_all_patients()
    for p in patients:
        asyncio.create_task(run_morning_pipeline(p["id"], bots))
    return {"status": "triggered", "count": len(patients)}


@app.get("/api/status")
async def get_status():
    """System status."""
    return {
        "status": "running",
        "demo_mode": DEMO_MODE,
        "patients": len(get_all_patients()),
        "bots_active": list(bots.keys()),
    }


@app.get("/api/audio/{filename}")
async def serve_audio(filename: str):
    """Serve TTS audio files for Twilio playback."""
    audio_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audio_cache")
    filepath = os.path.join(audio_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(filepath, media_type="audio/wav")


# ── Auth Models & Endpoints ──

class RegisterRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class PatientCreate(BaseModel):
    name: str
    weeks: int
    trimester: int
    risk_level: str = "low"
    language_code: str = "hi"
    pregnancy_number: int = 1
    blood_group: str = ""
    phone: str = ""
    address: str = ""
    asha_phone: str = ""

class PatientUpdate(BaseModel):
    name: str | None = None
    weeks: int | None = None
    trimester: int | None = None
    risk_level: str | None = None
    language_code: str | None = None
    pregnancy_number: int | None = None
    blood_group: str | None = None
    phone: str | None = None
    address: str | None = None
    asha_phone: str | None = None

class PrescriptionCreate(BaseModel):
    medicine_name: str
    frequency: str = "daily"
    quantity_supplied: int = 30


@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    worker = create_asha_worker(req.name, req.email, req.phone, req.password)
    if not worker:
        raise HTTPException(status_code=400, detail="Email already registered")
    token = authenticate_worker(req.email, req.password)
    return {"token": token, "worker": worker}


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    token = authenticate_worker(req.email, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    worker = get_worker_by_token(token)
    return {"token": token, "worker": worker}


@app.get("/api/auth/me")
async def get_me(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth[7:]
    worker = get_worker_by_token(token)
    if not worker:
        raise HTTPException(status_code=401, detail="Invalid token")
    return worker


@app.post("/api/auth/logout")
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        delete_session(auth[7:])
    return {"status": "logged_out"}


# ── Patient CRUD ──

@app.post("/api/patients")
async def create_patient_endpoint(req: PatientCreate):
    patient = create_patient_record(
        name=req.name, weeks=req.weeks, trimester=req.trimester,
        risk_level=req.risk_level, language_code=req.language_code,
        pregnancy_number=req.pregnancy_number, blood_group=req.blood_group,
        phone=req.phone, address=req.address, asha_phone=req.asha_phone,
    )
    return patient


@app.put("/api/patients/{patient_id}")
async def update_patient_endpoint(patient_id: int, req: PatientUpdate):
    existing = get_patient_by_id(patient_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Patient not found")
    data = {k: v for k, v in req.model_dump().items() if v is not None}
    patient = update_patient(patient_id, **data)
    return patient


@app.delete("/api/patients/{patient_id}")
async def delete_patient_endpoint(patient_id: int):
    existing = get_patient_by_id(patient_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Patient not found")
    delete_patient(patient_id)
    return {"status": "deleted", "id": patient_id}


@app.post("/api/patients/{patient_id}/prescriptions")
async def add_prescription_endpoint(patient_id: int, req: PrescriptionCreate):
    existing = get_patient_by_id(patient_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Patient not found")
    rx = add_prescription(patient_id, req.medicine_name, req.frequency, req.quantity_supplied)
    return rx


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
