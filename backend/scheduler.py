"""
Scheduler — APScheduler for daily 8am pipeline + silence follow-ups.
"""

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.database import get_all_patients, get_conversation_state, save_agent_event
from backend.pipeline import run_morning_pipeline, run_full_pipeline, emit_event
from backend.telegram_bots import bots
from backend.config import DEMO_MODE

logger = logging.getLogger("maa.scheduler")

scheduler = AsyncIOScheduler()


async def morning_checkin_job():
    """8:00 AM — Send morning check-in to all patients."""
    if DEMO_MODE:
        logger.info("DEMO_MODE active — scheduler bypassed")
        return

    logger.info("═══ Morning check-in job starting ═══")
    patients = get_all_patients()

    for patient in patients:
        if not patient.get("telegram_chat_id"):
            logger.warning(f"Skipping {patient['name']} — no chat_id registered")
            continue

        try:
            await run_morning_pipeline(patient["id"], bots)
        except Exception as e:
            logger.error(f"Morning pipeline error for {patient['name']}: {e}")

    logger.info("═══ Morning check-in job complete ═══")


async def followup_10am_job():
    """10:00 AM — Gentle follow-up for patients who haven't replied."""
    if DEMO_MODE:
        return

    logger.info("Running 10am follow-up check")
    patients = get_all_patients()
    today = date.today().isoformat()

    for patient in patients:
        if not patient.get("telegram_chat_id"):
            continue

        conv = get_conversation_state(patient["id"], today)
        if conv and conv.get("exchange_count", 0) <= 1:
            # Only sent morning message, no reply yet
            from backend.sarvam import translate_to_patient
            msg = await translate_to_patient(
                f"Hi {patient['name']}, just checking — how are you feeling today? 🌸",
                patient["language_code"],
            )
            if bots.get("checkin"):
                try:
                    await bots["checkin"].send_message(
                        chat_id=patient["telegram_chat_id"],
                        text=msg,
                    )
                    save_agent_event(patient["id"], "CheckInAgent", "followup_10am",
                                     "Gentle 10am follow-up sent")
                except Exception as e:
                    logger.error(f"10am follow-up error: {e}")


async def silence_12pm_job():
    """12:00 PM — Flag silent patients. High-risk + silent = RED."""
    if DEMO_MODE:
        return

    logger.info("Running 12pm silence check")
    patients = get_all_patients()
    today = date.today().isoformat()

    for patient in patients:
        conv = get_conversation_state(patient["id"], today)

        # No conversation state at all or only 1 exchange = silence
        if not conv or conv.get("exchange_count", 0) <= 1:
            if patient["risk_level"] == "high":
                logger.warning(f"HIGH RISK + SILENT: {patient['name']} — triggering RED pipeline")
                save_agent_event(patient["id"], "System", "silence_red",
                                 f"🚨 High-risk patient {patient['name']} silent — auto-escalating to RED")
                await emit_event({
                    "agent": "System", "patient_id": patient["id"],
                    "message": f"High-risk silence detected for {patient['name']} — escalating"
                })

                # Run pipeline with silence data
                silence_data = {
                    "symptoms": [],
                    "fetal_movement": "not_mentioned",
                    "medicine_taken": None,
                    "mood": "unknown",
                    "concerns": "Patient silent — no response to morning check-in",
                }
                await run_full_pipeline(patient["id"], silence_data, bots)
            else:
                save_agent_event(patient["id"], "System", "silence_noted",
                                 f"⚠️ {patient['name']} hasn't responded today")


def setup_scheduler():
    """Configure and start the scheduler."""
    if DEMO_MODE:
        logger.info("DEMO_MODE — scheduler configured but jobs won't run automatically")
        return scheduler

    scheduler.add_job(morning_checkin_job, CronTrigger(hour=8, minute=0), id="morning_checkin")
    scheduler.add_job(followup_10am_job, CronTrigger(hour=10, minute=0), id="followup_10am")
    scheduler.add_job(silence_12pm_job, CronTrigger(hour=12, minute=0), id="silence_12pm")

    logger.info("Scheduler configured: 8am check-in, 10am follow-up, 12pm silence check")
    return scheduler
