"""
NotifyAgent — Decides and executes notification actions using NVIDIA NIM (via OpenAI SDK).
GREEN → log only, YELLOW → email, RED → email + Ntfy + Twilio call.
"""

import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from urllib.parse import quote

import httpx
from openai import OpenAI

from backend.config import (
    NVIDIA_API_KEY, NVIDIA_MODEL, NVIDIA_API_URL,
    NTFY_TOPIC, NTFY_URL,
    EMAIL_USER, EMAIL_PASS, ASHA_EMAIL,
    ASHA_PHONE_NUMBER,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER,
)
from backend.database import save_notification, save_agent_event, get_patient_by_id

logger = logging.getLogger("maa.notify")

nvidia_client = OpenAI(
    api_key=NVIDIA_API_KEY,
    base_url=NVIDIA_API_URL,
) if NVIDIA_API_KEY else None

# Twilio client (lazy init)
_twilio_client = None
def _get_twilio_client():
    global _twilio_client
    if _twilio_client is None and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        from twilio.rest import Client
        _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _twilio_client


async def process_notifications(
    patient_id: int,
    severity: str,
    reason: str,
    resource_flags: list[str],
) -> dict:
    """Main notification dispatcher."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        return {"actions": []}

    actions = []
    today = date.today().isoformat()

    # Generate action plan via NVIDIA NIM
    action_plan = await _generate_action_plan(patient, severity, reason, resource_flags)

    if severity == "GREEN" and not resource_flags:
        save_agent_event(patient_id, "NotifyAgent", "log_only", f"All clear today ✅ for {patient['name']}")
        save_notification(patient_id, today, "log", "All clear", True)
        actions.append("logged")
        return {"actions": actions, "plan": action_plan}

    # YELLOW or RED → Email to ASHA
    if severity in ("YELLOW", "RED"):
        email_sent = await _send_email(patient, severity, reason, action_plan)
        actions.append("email_sent" if email_sent else "email_failed")
        save_notification(patient_id, today, "email", f"{severity}: {reason}", email_sent)

    # RED → Ntfy push + Phone call
    if severity == "RED":
        ntfy_sent = await _send_ntfy(patient, severity, reason)
        actions.append("ntfy_sent" if ntfy_sent else "ntfy_failed")
        save_notification(patient_id, today, "ntfy", f"CRITICAL: {reason}", ntfy_sent)

        call_script = await _generate_call_script(patient, reason)
        call_made = await _make_twilio_call(patient, call_script)
        actions.append("call_made" if call_made else "call_failed")
        save_notification(patient_id, today, "phone_call", call_script, call_made)

        severity_msg = f"CRITICAL — contacting ASHA now 🚨 for {patient['name']}"
        save_agent_event(patient_id, "NotifyAgent", "red_alert", severity_msg)

    elif severity == "YELLOW":
        # If email failed for YELLOW, send ntfy push as fallback
        if "email_failed" in actions:
            logger.warning(f"Email failed for YELLOW alert, sending ntfy fallback for {patient['name']}")
            ntfy_sent = await _send_ntfy(patient, severity, reason)
            actions.append("ntfy_fallback_sent" if ntfy_sent else "ntfy_fallback_failed")
            save_notification(patient_id, today, "ntfy_fallback", f"YELLOW (email failed): {reason}", ntfy_sent)
        save_agent_event(patient_id, "NotifyAgent", "yellow_alert",
                         f"Notifying ASHA worker 📧 about {patient['name']}")

    # Resource flags → separate notifications
    for flag in resource_flags:
        email_sent = await _send_email(patient, "RESOURCE", flag, "")
        save_notification(patient_id, today, "resource_email", flag, email_sent)
        save_agent_event(patient_id, "NotifyAgent", "resource_flag", flag)
        actions.append("resource_email")

    return {"actions": actions, "plan": action_plan}


async def _generate_action_plan(patient: dict, severity: str, reason: str, flags: list[str]) -> str:
    """Use NVIDIA NIM to generate an action plan summary."""
    if not nvidia_client:
        return f"{severity} alert for {patient['name']}: {reason}"

    prompt = f"""You are a maternal health notification system. Generate a brief action plan.

Patient: {patient['name']}, {patient['weeks']} weeks pregnant, risk: {patient['risk_level']}
Severity: {severity}
Reason: {reason}
Resource flags: {json.dumps(flags)}

Write a 2-3 sentence action plan for the ASHA health worker. Be specific and actionable.
Do NOT use markdown formatting."""

    try:
        response = nvidia_client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"NVIDIA action plan error: {e}")
        return f"{severity} alert for {patient['name']}: {reason}"


async def _generate_call_script(patient: dict, reason: str) -> str:
    """Generate Vapi call script via NVIDIA NIM."""
    if not nvidia_client:
        return (
            f"This is Maa, the maternal health assistant. "
            f"{patient['name']}, {patient['weeks']} weeks pregnant, has been flagged as high risk today. "
            f"{reason}. Please visit her today. Her details are on your dashboard."
        )

    prompt = f"""Generate a brief voice call script for a health worker. The call is from an AI maternal health assistant.

Patient: {patient['name']}, {patient['weeks']} weeks pregnant
Issue: {reason}

The script should:
- Identify as "Maa, the maternal health assistant"
- State the patient name and pregnancy week
- Describe the issue clearly
- Ask the health worker to visit today
- Be under 50 words
- Be conversational, not robotic

Return ONLY the script text, nothing else."""

    try:
        response = nvidia_client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"NVIDIA call script error: {e}")
        return (
            f"This is Maa, the maternal health assistant. "
            f"{patient['name']}, {patient['weeks']} weeks pregnant, has been flagged as high risk. "
            f"{reason}. Please visit her today."
        )


async def _send_email(patient: dict, severity: str, reason: str, plan: str) -> bool:
    """Send email to ASHA worker."""
    if not EMAIL_USER or not EMAIL_PASS or not ASHA_EMAIL:
        logger.warning("Email not configured, skipping")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = ASHA_EMAIL
        msg["Subject"] = f"[Maa {severity}] {patient['name']} — {patient['weeks']} weeks"

        body = f"""Maa Maternal Health Alert
{'=' * 40}

Patient: {patient['name']}
Weeks Pregnant: {patient['weeks']}
Risk Level: {patient['risk_level']}
Language: {patient['language_code']}
Severity: {severity}

Reason: {reason}

Action Plan: {plan}

— Maa Health Assistant"""

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)

        logger.info(f"Email sent to ASHA for {patient['name']}")
        return True
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False


async def _send_ntfy(patient: dict, severity: str, reason: str) -> bool:
    """Send push notification via ntfy.sh."""
    if not NTFY_TOPIC:
        logger.warning("Ntfy not configured, skipping")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{NTFY_URL}/{NTFY_TOPIC}"
            response = await client.post(
                url,
                content=f"🚨 {severity}: {patient['name']} ({patient['weeks']}w) — {reason}",
                headers={
                    "Title": f"Maa Alert: {patient['name']}",
                    "Priority": "urgent" if severity == "RED" else "high",
                    "Tags": "warning,pregnant_woman",
                },
            )
            if response.status_code == 200:
                logger.info(f"Ntfy push sent for {patient['name']}")
                return True
            logger.error(f"Ntfy error: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Ntfy send error: {e}")
        return False


async def _make_twilio_call(patient: dict, script: str) -> bool:
    """Make outbound call via Twilio with native language TTS via Sarvam."""
    client = _get_twilio_client()
    if not client or not ASHA_PHONE_NUMBER or not TWILIO_PHONE_NUMBER:
        logger.warning("Twilio not configured, falling back to ntfy")
        await _send_ntfy(patient, "RED", f"Phone call unavailable — {script}")
        return False

    lang_code = patient.get("language_code", "en")

    try:
        # Step 1: Translate script to patient's native language
        from backend.sarvam import translate_to_patient, text_to_speech

        native_script = await translate_to_patient(script, lang_code)
        logger.info(f"Call script translated to {lang_code}: {native_script[:80]}...")

        # Step 2: Try Sarvam TTS for native language audio
        audio_bytes = await text_to_speech(native_script, lang_code)

        if audio_bytes:
            # Save audio temporarily and serve via FastAPI
            import uuid, os
            audio_id = str(uuid.uuid4())
            audio_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "audio_cache")
            os.makedirs(audio_dir, exist_ok=True)
            audio_path = os.path.join(audio_dir, f"{audio_id}.wav")

            with open(audio_path, "wb") as f:
                f.write(audio_bytes)

            # Use the audio endpoint — Twilio will fetch and play it
            twiml = (
                f'<Response>'
                f'<Play>/api/audio/{audio_id}.wav</Play>'
                f'<Pause length="1"/>'
                f'<Play>/api/audio/{audio_id}.wav</Play>'
                f'<Pause length="2"/>'
                f'<Say voice="Polly.Aditi" language="en-IN">'
                f'Thank you. Please take action immediately. Goodbye.'
                f'</Say>'
                f'</Response>'
            )
            logger.info(f"Using Sarvam TTS audio for call in {lang_code}")
        else:
            # Fallback: Use Twilio's built-in Polly TTS with translated text
            # Polly.Aditi supports Hindi; for others, use English
            voice = "Polly.Aditi"
            # Use native script even with Polly — it can handle Romanized text
            twiml = (
                f'<Response>'
                f'<Say voice="{voice}" language="en-IN">{script}</Say>'
                f'<Pause length="1"/>'
                f'<Say voice="{voice}" language="en-IN">'
                f'I repeat: {script}'
                f'</Say>'
                f'<Pause length="2"/>'
                f'<Say voice="{voice}" language="en-IN">'
                f'Thank you. Please take action immediately. Goodbye.'
                f'</Say>'
                f'</Response>'
            )
            logger.info(f"Using Polly TTS fallback for call")

        call = client.calls.create(
            to=ASHA_PHONE_NUMBER,
            from_=TWILIO_PHONE_NUMBER,
            twiml=twiml,
        )

        logger.info(f"Twilio call placed for {patient['name']}: SID={call.sid}, status={call.status}")
        save_agent_event(patient["id"], "NotifyAgent", "phone_call",
                         f"📞 Phone call placed to ASHA worker in {lang_code.upper()} (SID: {call.sid[:12]}...)")
        return True

    except Exception as e:
        logger.error(f"Twilio call error (attempt 1): {e}")
        # Retry once after a short delay for transient network/DNS issues
        try:
            import asyncio
            await asyncio.sleep(3)
            logger.info(f"Retrying Twilio call for {patient['name']}...")
            call = client.calls.create(
                to=ASHA_PHONE_NUMBER,
                from_=TWILIO_PHONE_NUMBER,
                twiml=twiml,
            )
            logger.info(f"Twilio call placed on retry for {patient['name']}: SID={call.sid}, status={call.status}")
            save_agent_event(patient["id"], "NotifyAgent", "phone_call",
                             f"📞 Phone call placed to ASHA worker on retry (SID: {call.sid[:12]}...)")
            return True
        except Exception as retry_e:
            logger.error(f"Twilio call error (attempt 2): {retry_e}")
            await _send_ntfy(patient, "RED", f"Phone call failed — {script}")
            return False

