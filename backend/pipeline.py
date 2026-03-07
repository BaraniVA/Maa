"""
Pipeline — Orchestrates the full 5-agent flow for a single patient.
Each agent runs in sequence, posts visibly in the Telegram group.
"""

import json
import logging
import asyncio
from datetime import date

from backend.database import (
    get_patient_by_id, save_agent_event, save_daily_log,
    get_conversation_state, save_conversation_state,
)
from backend.agents.checkin_agent import generate_morning_message, generate_followup, extract_data
from backend.agents.symptom_agent import analyse_symptoms
from backend.agents.resource_agent import check_resources
from backend.agents.notify_agent import process_notifications
from backend.agents.care_agent import create_care_plan
from backend.sarvam import translate_to_patient, translate_to_english

logger = logging.getLogger("maa.pipeline")

# Global event queue for SSE streaming
pipeline_events: asyncio.Queue = asyncio.Queue()


async def emit_event(event: dict):
    """Push event to SSE queue."""
    await pipeline_events.put(event)


async def run_full_pipeline(patient_id: int, today_data: dict, bots: dict):
    """Run the complete 5-agent pipeline for a patient."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        logger.error(f"Patient {patient_id} not found")
        return

    today = date.today().isoformat()
    group_chat_id = None

    # Get the group chat ID from bots config
    from backend.config import TELEGRAM_GROUP_CHAT_ID
    group_chat_id = TELEGRAM_GROUP_CHAT_ID

    logger.info(f"═══ Starting pipeline for {patient['name']} ═══")
    await emit_event({"agent": "Pipeline", "patient_id": patient_id,
                      "message": f"Starting pipeline for {patient['name']}..."})

    # ── Step 2: SymptomAgent ──
    if group_chat_id and bots.get("symptom"):
        try:
            await bots["symptom"].send_message(
                chat_id=group_chat_id,
                text=f"🔍 Analysing {patient['name']}'s symptoms..."
            )
        except Exception as e:
            logger.error(f"Telegram symptom bot send error: {e}")

    symptom_result = await analyse_symptoms(patient_id, today_data)
    severity = symptom_result.get("severity", "GREEN")
    reason = symptom_result.get("reason", "")

    if group_chat_id and bots.get("symptom"):
        severity_emoji = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨"}.get(severity, "❓")
        try:
            await bots["symptom"].send_message(
                chat_id=group_chat_id,
                text=f"{severity_emoji} {patient['name']}: {severity} — {reason}"
            )
        except Exception as e:
            logger.error(f"Telegram symptom result send error: {e}")

    await emit_event({"agent": "SymptomAgent", "patient_id": patient_id,
                      "message": f"{severity}: {reason}", "severity": severity})

    # ── Step 3: ResourceAgent ──
    if group_chat_id and bots.get("resource"):
        try:
            await bots["resource"].send_message(
                chat_id=group_chat_id,
                text=f"💊 Checking medicine stock for {patient['name']}..."
            )
        except Exception as e:
            logger.error(f"Telegram resource bot send error: {e}")

    resource_result = await check_resources(patient_id, today_data)
    resource_flags = resource_result.get("flags", [])

    if group_chat_id and bots.get("resource"):
        summary = resource_result.get("summary", "Medicine check complete")
        try:
            await bots["resource"].send_message(
                chat_id=group_chat_id,
                text=f"💊 {summary}"
            )
        except Exception as e:
            logger.error(f"Telegram resource result send error: {e}")

    await emit_event({"agent": "ResourceAgent", "patient_id": patient_id,
                      "message": resource_result.get("summary", "Check complete"),
                      "flags": resource_flags})

    # ── Step 4: NotifyAgent ──
    if group_chat_id and bots.get("notify"):
        try:
            await bots["notify"].send_message(
                chat_id=group_chat_id,
                text=f"📋 Taking action based on severity for {patient['name']}..."
            )
        except Exception as e:
            logger.error(f"Telegram notify bot send error: {e}")

    notify_result = await process_notifications(patient_id, severity, reason, resource_flags)

    if group_chat_id and bots.get("notify"):
        if severity == "GREEN" and not resource_flags:
            msg = f"✅ All clear today for {patient['name']}"
        elif severity == "YELLOW":
            msg = f"📧 Notifying ASHA worker about {patient['name']}"
        elif severity == "RED":
            msg = f"🚨 CRITICAL — contacting ASHA now for {patient['name']}"
        else:
            msg = f"📋 Notifications processed for {patient['name']}"
        try:
            await bots["notify"].send_message(chat_id=group_chat_id, text=msg)
        except Exception as e:
            logger.error(f"Telegram notify result send error: {e}")

    await emit_event({"agent": "NotifyAgent", "patient_id": patient_id,
                      "message": f"Actions: {notify_result.get('actions', [])}", "severity": severity})

    # ── Step 5: CareAgent (YELLOW/RED only) ──
    if severity in ("YELLOW", "RED"):
        if group_chat_id and bots.get("care"):
            try:
                await bots["care"].send_message(
                    chat_id=group_chat_id,
                    text=f"📋 Booking appointment and preparing care plan for {patient['name']}..."
                )
            except Exception as e:
                logger.error(f"Telegram care bot send error: {e}")

        care_result = await create_care_plan(patient_id, severity, reason)

        # Send translated care plan to group
        if group_chat_id and bots.get("care") and care_result.get("care_plan_translated"):
            appt = care_result.get("appointment", {})
            appt_text = ""
            if appt:
                appt_text = f"\n\n📅 Appointment: {appt.get('date', '')} at {appt.get('time', '')} — {appt.get('location', '')}"

            try:
                await bots["care"].send_message(
                    chat_id=group_chat_id,
                    text=f"📋 Care Plan for {patient['name']}:\n\n{care_result['care_plan_translated']}{appt_text}"
                )
            except Exception as e:
                logger.error(f"Telegram care plan send error: {e}")

        await emit_event({"agent": "CareAgent", "patient_id": patient_id,
                          "message": f"Care plan sent in {patient['language_code'].upper()}", "severity": severity})

    logger.info(f"═══ Pipeline complete for {patient['name']} — {severity} ═══")
    await emit_event({"agent": "Pipeline", "patient_id": patient_id,
                      "message": f"Pipeline complete for {patient['name']} — {severity}"})


async def handle_patient_message(patient_id: int, message_text: str, bots: dict, reply_chat_id: str = None):
    """Handle an incoming message from a patient — conversation flow."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        return

    today = date.today().isoformat()
    from backend.config import TELEGRAM_GROUP_CHAT_ID
    group_chat_id = TELEGRAM_GROUP_CHAT_ID

    # Send replies to the chat the message came from (DM or group)
    send_chat_id = reply_chat_id or group_chat_id

    # Translate patient message to English
    english_text = await translate_to_english(message_text, patient["language_code"])

    # Get or create conversation state
    conv = get_conversation_state(patient_id, today)
    if not conv:
        save_conversation_state(patient_id, today, "active", 0, {})
        conv = {"state": "active", "exchange_count": 0, "extracted_data": "{}"}

    exchange_count = conv.get("exchange_count", 0)
    state = conv.get("state", "active")

    # Load conversation history from extracted_data
    try:
        existing_data = json.loads(conv.get("extracted_data", "{}"))
    except (json.JSONDecodeError, TypeError):
        existing_data = {}

    history = existing_data.get("_history", [])
    history.append({"role": "user", "content": english_text})

    if exchange_count < 4 and state != "extracted":
        # Generate follow-up
        response = await generate_followup(patient, history)
        history.append({"role": "assistant", "content": response})

        # Translate and send to the correct chat
        translated_response = await translate_to_patient(response, patient["language_code"])

        if send_chat_id and bots.get("checkin"):
            try:
                await bots["checkin"].send_message(
                    chat_id=send_chat_id,
                    text=translated_response,
                )
            except Exception as e:
                logger.error(f"Telegram checkin followup send error: {e}")

        exchange_count += 1
        existing_data["_history"] = history
        save_conversation_state(patient_id, today, "active", exchange_count, existing_data)

        # If max exchanges reached, extract and run pipeline
        if exchange_count >= 4:
            await _finish_conversation(patient_id, patient, history, bots)
    else:
        # Already at max, extract and run pipeline
        await _finish_conversation(patient_id, patient, history, bots)


async def _finish_conversation(patient_id: int, patient: dict, history: list, bots: dict):
    """Extract data from conversation and run full pipeline."""
    today = date.today().isoformat()

    # Extract structured data
    extracted = await extract_data(patient, history)

    save_conversation_state(patient_id, today, "extracted",
                            len(history), {**extracted, "_history": history})

    # Run the rest of the pipeline
    await run_full_pipeline(patient_id, extracted, bots)


async def run_morning_pipeline(patient_id: int, bots: dict, reply_chat_id: str = None):
    """Start the morning check-in for a patient."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        return

    from backend.config import TELEGRAM_GROUP_CHAT_ID
    group_chat_id = TELEGRAM_GROUP_CHAT_ID

    # Send check-in to the chat that triggered it (DM or group)
    send_chat_id = reply_chat_id or group_chat_id

    # Generate morning message
    morning_msg = await generate_morning_message(patient)

    # Translate
    translated_msg = await translate_to_patient(morning_msg, patient["language_code"])

    if send_chat_id and bots.get("checkin"):
        try:
            await bots["checkin"].send_message(
                chat_id=send_chat_id,
                text=f"🌸 {patient['name']}:\n\n{translated_msg}",
            )
        except Exception as e:
            logger.error(f"Telegram morning send error: {e}")

    # Initialize conversation state
    today = date.today().isoformat()
    save_conversation_state(patient_id, today, "active", 1,
                            {"_history": [{"role": "assistant", "content": morning_msg}]})

    await emit_event({"agent": "CheckInAgent", "patient_id": patient_id,
                      "message": f"Morning message sent to {patient['name']} 🌸"})
