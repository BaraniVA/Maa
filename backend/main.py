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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from backend.config import DEMO_MODE
from backend.database import (
    init_db, get_all_patients, get_patient_by_id,
    get_daily_logs, get_medicine_logs, get_prescriptions,
    get_care_plans, get_notifications, get_agent_events,
    get_conversation_state,
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
