"""
CareAgent — Books appointments and generates care plans using Ollama (local).
Runs only on YELLOW or RED. Uses Sarvam to translate care plan.
"""

import json
import logging
from datetime import date, datetime, timedelta

import httpx

from backend.config import OLLAMA_API_URL, OLLAMA_MODEL, GOOGLE_CALENDAR_ID
from backend.database import (
    save_care_plan, save_agent_event, get_patient_by_id, get_daily_logs,
)
from backend.sarvam import translate_to_patient

logger = logging.getLogger("maa.care")


async def create_care_plan(patient_id: int, severity: str, reason: str) -> dict:
    """Generate care plan and book appointment for YELLOW/RED patients."""
    if severity == "GREEN":
        return {"care_plan": None, "appointment": None}

    patient = get_patient_by_id(patient_id)
    if not patient:
        return {"care_plan": None, "appointment": None}

    save_agent_event(patient_id, "CareAgent", "started",
                     f"Booking appointment and preparing care plan for {patient['name']}...")

    # Generate care plan via Ollama
    care_plan_english = await _generate_care_plan(patient, severity, reason)

    # Translate to patient's language via Sarvam
    care_plan_translated = await translate_to_patient(care_plan_english, patient["language_code"])

    # Book appointment
    appointment = await _book_appointment(patient, severity)

    # Save to database
    today = date.today().isoformat()
    save_care_plan(patient_id, today, care_plan_english, care_plan_translated)

    save_agent_event(patient_id, "CareAgent", "care_plan_sent",
                     f"Care plan sent in {patient['language_code'].upper()} ✅")

    return {
        "care_plan_english": care_plan_english,
        "care_plan_translated": care_plan_translated,
        "appointment": appointment,
    }


async def _generate_care_plan(patient: dict, severity: str, reason: str) -> str:
    """Generate personalised care plan via Ollama."""
    history = get_daily_logs(patient["id"], days=7)
    history_summary = "; ".join(
        f"{l['date']}: {l.get('symptoms', 'none')}"
        for l in history[:5]
    )

    prompt = f"""You are a maternal health care plan generator.

PATIENT: {patient['name']}, {patient['weeks']} weeks pregnant (trimester {patient['trimester']}),
pregnancy #{patient.get('pregnancy_number', 1)}, risk: {patient['risk_level']}

SEVERITY: {severity}
REASON: {reason}
RECENT HISTORY: {history_summary}

Generate a SHORT, personalised care plan (5-7 bullet points) that includes:
1. Immediate actions patient should take today
2. Warning signs to watch for
3. Diet/rest recommendations appropriate for her trimester
4. When to seek emergency care
5. Next check-in schedule

Keep it simple, warm, and actionable. No medical jargon.
Write in plain text, not markdown. Use simple dashes for bullet points."""

    # Try configured model first, then fallback to local model
    models_to_try = [OLLAMA_MODEL]
    # Add local fallback models if configured model is cloud-based
    if "cloud" in OLLAMA_MODEL.lower():
        models_to_try.extend(["qwen3.5:0.8b", "qwen2.5:1.5b", "qwen3:0.6b"])

    for model in models_to_try:
        try:
            logger.info(f"Trying care plan generation with model: {model}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{OLLAMA_API_URL}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "options": {"temperature": 0.5, "num_predict": 400},
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    plan = data.get("message", {}).get("content", "").strip()
                    if plan:
                        logger.info(f"Care plan generated for {patient['name']} using {model}")
                        return plan

                logger.warning(f"Ollama model {model} returned {response.status_code}")

        except httpx.TimeoutException:
            logger.warning(f"Ollama model {model} timed out (30s), trying next...")
        except Exception as e:
            logger.warning(f"Ollama model {model} error: {e}, trying next...")

    logger.warning(f"All Ollama models failed, using fallback care plan for {patient['name']}")
    return _fallback_care_plan(patient, severity, reason)


def _fallback_care_plan(patient: dict, severity: str, reason: str) -> str:
    """Generate a basic care plan without AI."""
    plan = f"""Care Plan for {patient['name']} — {date.today().strftime('%B %d, %Y')}

- Rest well today and avoid heavy physical work.
- Drink plenty of water (at least 8 glasses).
- Take all prescribed medicines on time.
- Monitor for: severe headache, blurred vision, swelling, bleeding, or reduced baby movement.
- If any danger sign appears, go to the nearest health centre immediately.
- Your ASHA worker has been notified and will check on you.
- Next check-in: Tomorrow morning via Maa."""
    if severity == "RED":
        plan += "\n- URGENT: Please visit the Primary Health Centre today for a check-up."
    return plan


async def _book_appointment(patient: dict, severity: str) -> dict | None:
    """Book a Google Calendar appointment at PHC."""
    # Calculate appointment time — next working day at 10:30 AM
    tomorrow = datetime.now() + timedelta(days=1)
    # Skip weekends
    while tomorrow.weekday() >= 5:
        tomorrow += timedelta(days=1)

    appointment_time = tomorrow.replace(hour=10, minute=30, second=0, microsecond=0)
    end_time = appointment_time + timedelta(hours=1)

    appointment = {
        "patient_name": patient["name"],
        "date": appointment_time.strftime("%Y-%m-%d"),
        "time": "10:30 AM",
        "location": "Primary Health Centre (PHC)",
        "type": "Antenatal Checkup" if severity == "YELLOW" else "Urgent Antenatal Visit",
        "severity": severity,
    }

    # Try Google Calendar API
    if GOOGLE_CALENDAR_ID:
        try:
            calendar_booked = await _create_calendar_event(
                patient, appointment, appointment_time, end_time
            )
            if calendar_booked:
                appointment["calendar_synced"] = True
                save_agent_event(patient["id"], "CareAgent", "appointment_booked",
                                 f"📅 Appointment booked: {appointment['date']} {appointment['time']} at PHC")
                return appointment
        except Exception as e:
            logger.error(f"Google Calendar error: {e}")

    # Even without calendar, return appointment info
    appointment["calendar_synced"] = False
    save_agent_event(patient["id"], "CareAgent", "appointment_booked",
                     f"📅 Appointment scheduled: {appointment['date']} {appointment['time']} at PHC (manual)")
    return appointment


async def _create_calendar_event(
    patient: dict, appointment: dict,
    start: datetime, end: datetime,
) -> bool:
    """Create Google Calendar event."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/calendar"]
        creds = service_account.Credentials.from_service_account_file(
            "credentials.json", scopes=SCOPES
        )
        service = build("calendar", "v3", credentials=creds)

        event = {
            "summary": f"Maa: {appointment['type']} — {patient['name']}",
            "location": appointment["location"],
            "description": (
                f"Patient: {patient['name']}\n"
                f"Weeks: {patient['weeks']}\n"
                f"Risk: {patient['risk_level']}\n"
                f"Severity: {appointment['severity']}"
            ),
            "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
            "reminders": {"useDefault": False, "overrides": [
                {"method": "popup", "minutes": 60},
            ]},
        }

        service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        logger.info(f"Calendar event created for {patient['name']}")
        return True

    except Exception as e:
        logger.error(f"Calendar event creation failed: {e}")
        return False
