"""
Pipeline — Orchestrates the full 5-agent flow for a single patient.
Each agent runs in sequence, posts visibly in the Telegram group.
"""

import json
import logging
import asyncio
import io
import re
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
from backend.sarvam import translate_to_patient, translate_to_english, text_to_speech, sarvam_lang_to_code

logger = logging.getLogger("maa.pipeline")

# Emergency keywords/phrases that should skip conversation follow-ups
_EMERGENCY_PATTERNS = re.compile(
    r"(?:fell\s*down|falling|broken?\s*(?:leg|arm|bone|hip)|fracture|"
    r"bleeding|hemorrhag|haemorrhag|blood\s*(?:coming|loss|everywhere)|"
    r"unconscious|fainted|passed\s*out|seizure|convulsion|"
    r"accident|hit\s*by|crash|severe\s*pain|unbearable\s*pain|"
    r"can'?t\s*(?:breathe|move|stand|walk|see)|chest\s*pain|"
    r"head\s*injury|blurr(?:y|ed)\s*vision|water\s*broke|"
    r"baby\s*(?:coming|not\s*moving)|no\s*(?:fetal|baby)\s*movement|"
    r"snake\s*bite|burn(?:ed|s|ing)|poison|swallow|"
    r"stabbed|cut\s*(?:deep|bad)|emergency|ambulance|hospital\s*now|"
    r"help\s*(?:me|us)|dying|very\s*serious|critical)",
    re.IGNORECASE,
)


def _is_emergency(text: str) -> bool:
    """Detect obvious emergency situations from patient message."""
    return bool(_EMERGENCY_PATTERNS.search(text))


# Global event queue for SSE streaming
pipeline_events: asyncio.Queue = asyncio.Queue()


async def _send_response(bot, chat_id: str, text: str, language_code: str, voice_mode: bool = False):
    """Send response to patient. Voice-only if voice_mode, text-only otherwise."""
    logger.info(f"_send_response: chat={chat_id}, voice_mode={voice_mode}, lang={language_code}, text={text[:60]}...")
    if voice_mode:
        try:
            audio_bytes = await text_to_speech(text, language_code)
            if audio_bytes:
                logger.info(f"TTS returned {len(audio_bytes)} bytes, sending voice to {chat_id}")
                voice_file = io.BytesIO(audio_bytes)
                voice_file.name = "response.mp3"
                await bot.send_voice(chat_id=chat_id, voice=voice_file)
                logger.info(f"Voice message sent to {chat_id}")
            else:
                logger.warning(f"TTS returned None, falling back to text for {chat_id}")
                await bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Telegram voice send error: {e}")
            try:
                await bot.send_message(chat_id=chat_id, text=text)
            except Exception as e2:
                logger.error(f"Telegram text fallback error: {e2}")
    else:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Telegram text send error: {e}")


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

    # ── RED URGENCY: Notify IMMEDIATELY before resource check ──
    if severity == "RED":
        if group_chat_id and bots.get("notify"):
            try:
                await bots["notify"].send_message(
                    chat_id=group_chat_id,
                    text=f"🚨 CRITICAL — contacting doctor/ASHA NOW for {patient['name']}..."
                )
            except Exception as e:
                logger.error(f"Telegram notify bot send error: {e}")

        notify_result = await process_notifications(patient_id, severity, reason, [])

        if group_chat_id and bots.get("notify"):
            try:
                await bots["notify"].send_message(
                    chat_id=group_chat_id,
                    text=f"🚨 CRITICAL — ASHA/doctor contacted for {patient['name']}"
                )
            except Exception as e:
                logger.error(f"Telegram notify result send error: {e}")

        await emit_event({"agent": "NotifyAgent", "patient_id": patient_id,
                          "message": f"IMMEDIATE RED ESCALATION — Actions: {notify_result.get('actions', [])}", "severity": severity})

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

    # ── Step 4: NotifyAgent (non-RED, or resource flag follow-up for RED) ──
    if severity != "RED":
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
            else:
                msg = f"📋 Notifications processed for {patient['name']}"
            try:
                await bots["notify"].send_message(chat_id=group_chat_id, text=msg)
            except Exception as e:
                logger.error(f"Telegram notify result send error: {e}")

        await emit_event({"agent": "NotifyAgent", "patient_id": patient_id,
                          "message": f"Actions: {notify_result.get('actions', [])}", "severity": severity})
    elif resource_flags:
        # RED was already notified above; send resource flag follow-up
        from backend.agents.notify_agent import process_notifications as _notify
        resource_notify = await _notify(patient_id, "RESOURCE", "Resource flags after RED escalation", resource_flags)
        await emit_event({"agent": "NotifyAgent", "patient_id": patient_id,
                          "message": f"Resource follow-up: {resource_notify.get('actions', [])}", "severity": severity})

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


async def handle_patient_message(patient_id: int, message_text: str, bots: dict, reply_chat_id: str = None, voice_mode: bool = False, detected_lang: str = ""):
    """Handle an incoming message from a patient — conversation flow."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        return

    # Use detected language from STT if available, otherwise patient's registered language
    effective_lang = sarvam_lang_to_code(detected_lang) if detected_lang else ""
    lang_code = effective_lang or patient["language_code"]
    if effective_lang and effective_lang != patient["language_code"]:
        logger.info(f"Using detected language '{effective_lang}' instead of registered '{patient['language_code']}'")

    today = date.today().isoformat()
    from backend.config import TELEGRAM_GROUP_CHAT_ID
    group_chat_id = TELEGRAM_GROUP_CHAT_ID

    # Send replies to the chat the message came from (DM or group)
    send_chat_id = reply_chat_id or group_chat_id

    # Translate patient message to English
    english_text = await translate_to_english(message_text, lang_code)

    # ── Emergency detection: skip follow-ups for obvious emergencies ──
    if _is_emergency(english_text):
        logger.warning(f"EMERGENCY detected for {patient['name']}: {english_text[:100]}")
        # Build minimal history and immediately extract + run pipeline
        conv = get_conversation_state(patient_id, today)
        try:
            existing_data = json.loads(conv.get("extracted_data", "{}")) if conv else {}
        except (json.JSONDecodeError, TypeError):
            existing_data = {}
        history = existing_data.get("_history", [])
        history.append({"role": "user", "content": english_text})

        # Send an immediate acknowledgement
        ack_msg = await translate_to_patient(
            "I understand this is an emergency. Stay calm — I am immediately alerting your doctor and ASHA worker. Help is on the way.",
            lang_code
        )
        send_chat_id_ack = reply_chat_id or group_chat_id
        if send_chat_id_ack and bots.get("checkin"):
            await _send_response(bots["checkin"], send_chat_id_ack, f"🚨 {ack_msg}", lang_code, voice_mode)

        await _finish_conversation(patient_id, patient, history, bots, send_chat_id=send_chat_id_ack, voice_mode=voice_mode, lang_code=lang_code)
        return

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

    # If conversation was already extracted (pipeline ran), re-open it
    # so the patient's new message gets a proper follow-up response.
    if state == "extracted":
        logger.info(f"Re-opening conversation for {patient['name']} — new message after pipeline")
        state = "active"
        # Reset exchange count for the new round (keep history intact)
        exchange_count = 0

    if exchange_count < 4:
        # Generate follow-up
        response = await generate_followup(patient, history)
        history.append({"role": "assistant", "content": response})

        # Translate and send to the correct chat
        translated_response = await translate_to_patient(response, lang_code)

        if send_chat_id and bots.get("checkin"):
            await _send_response(bots["checkin"], send_chat_id, translated_response, lang_code, voice_mode)

        exchange_count += 1
        existing_data["_history"] = history
        save_conversation_state(patient_id, today, "active", exchange_count, existing_data)

        # If max exchanges reached, extract and run pipeline
        if exchange_count >= 4:
            await _finish_conversation(patient_id, patient, history, bots, send_chat_id=send_chat_id, voice_mode=voice_mode, lang_code=lang_code)
    else:
        # Already at max, extract and run pipeline
        await _finish_conversation(patient_id, patient, history, bots, send_chat_id=send_chat_id, voice_mode=voice_mode, lang_code=lang_code)


async def _finish_conversation(patient_id: int, patient: dict, history: list, bots: dict,
                               send_chat_id: str = None, voice_mode: bool = False, lang_code: str = ""):
    """Extract data from conversation and run full pipeline."""
    today = date.today().isoformat()

    # Send acknowledgement to patient
    if send_chat_id and bots.get("checkin"):
        ack = await translate_to_patient(
            "Thank you for sharing. I've noted everything — take care of yourself! \U0001f338",
            lang_code or patient.get("language_code", "en"),
        )
        await _send_response(bots["checkin"], send_chat_id, ack,
                             lang_code or patient.get("language_code", "en"), voice_mode)

    # Extract structured data
    extracted = await extract_data(patient, history)

    save_conversation_state(patient_id, today, "extracted",
                            len(history), {**extracted, "_history": history})

    # Run the rest of the pipeline
    await run_full_pipeline(patient_id, extracted, bots)


async def run_morning_pipeline(patient_id: int, bots: dict, reply_chat_id: str = None, voice_mode: bool = False, detected_lang: str = ""):
    """Start the morning check-in for a patient."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        return

    # Use detected language if available
    effective_lang = sarvam_lang_to_code(detected_lang) if detected_lang else ""
    lang_code = effective_lang or patient["language_code"]

    from backend.config import TELEGRAM_GROUP_CHAT_ID
    group_chat_id = TELEGRAM_GROUP_CHAT_ID

    # Send check-in to the chat that triggered it (DM or group)
    send_chat_id = reply_chat_id or group_chat_id

    # Generate morning message
    morning_msg = await generate_morning_message(patient)

    # Translate
    translated_msg = await translate_to_patient(morning_msg, lang_code)

    if send_chat_id and bots.get("checkin"):
        await _send_response(
            bots["checkin"], send_chat_id,
            f"🌸 {patient['name']}:\n\n{translated_msg}",
            lang_code,
            voice_mode,
        )

    # Initialize conversation state
    today = date.today().isoformat()
    save_conversation_state(patient_id, today, "active", 1,
                            {"_history": [{"role": "assistant", "content": morning_msg}]})

    await emit_event({"agent": "CheckInAgent", "patient_id": patient_id,
                      "message": f"Morning message sent to {patient['name']} 🌸"})
