"""
CheckInAgent — Sends personalised daily morning message using Mistral.
Follows up on patient replies, extracts structured JSON.
"""

import json
import logging
from datetime import date

from mistralai import Mistral

from backend.config import MISTRAL_API_KEY, MISTRAL_MODEL
from backend.database import (
    get_daily_logs, get_conversation_state, save_conversation_state,
    save_daily_log, save_agent_event, get_prescriptions,
)

logger = logging.getLogger("maa.checkin")

client = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None


def _build_morning_prompt(patient: dict, yesterday_log: dict | None, prescriptions: list[dict]) -> str:
    meds = ", ".join(p["medicine_name"] for p in prescriptions)
    context = ""
    if yesterday_log:
        context = f"""Yesterday's check-in: She reported "{yesterday_log.get('raw_response', 'no data')}".
Severity was {yesterday_log.get('severity', 'GREEN')}. Symptoms: {yesterday_log.get('symptoms', 'none')}."""

    return f"""You are a warm, caring maternal health assistant named Maa.
You are checking in with {patient['name']}, who is {patient['weeks']} weeks pregnant (pregnancy #{patient.get('pregnancy_number', 1)}).
Risk level: {patient['risk_level']}.
Prescribed medicines: {meds}.

{context}

Write a SHORT, warm morning message (2-3 sentences max). Reference something real from yesterday if available.
Ask how she's feeling today and if she has any symptoms. Ask about fetal movement.
Be natural and conversational — like a caring older sister. Don't be clinical.
Do NOT use any formatting, markdown, or bullet points. Just plain conversational text."""


def _build_followup_prompt(patient: dict, conversation_history: list[dict]) -> str:
    history_text = "\n".join(
        f"{'Maa' if m['role'] == 'assistant' else patient['name']}: {m['content']}"
        for m in conversation_history
    )
    return f"""You are Maa, the maternal health assistant, having a conversation with {patient['name']}
({patient['weeks']} weeks pregnant, risk: {patient['risk_level']}).

Conversation so far:
{history_text}

IMPORTANT RULES:
- NEVER ask if she is okay or fine when she has already described a serious problem (injury, bleeding, fall, pain, etc.). That is redundant and wastes critical time.
- If she described an emergency or serious symptom (fall, bleeding, broken bone, severe pain, fainting, accident), do NOT keep questioning. Acknowledge the situation, reassure her that help is being contacted immediately, and end the conversation.
- Do NOT repeat questions she has already answered.
- If she has given enough information about her current state, do NOT ask more follow-up questions. Summarize and close.

For non-emergency situations:
- Continue the conversation naturally. If she mentioned mild symptoms, ask for more details.
- If she mentioned medicine, acknowledge it. Keep it warm and short (1-2 sentences).
- If you have enough information about her symptoms, fetal movement, and medicine compliance,
  say something reassuring and end naturally.

Do NOT use markdown or formatting. Plain conversational text only."""


def _build_extraction_prompt(patient: dict, conversation_history: list[dict]) -> str:
    history_text = "\n".join(
        f"{'Maa' if m['role'] == 'assistant' else patient['name']}: {m['content']}"
        for m in conversation_history
    )
    return f"""Extract structured health data from this conversation with {patient['name']}
({patient['weeks']} weeks pregnant).

Conversation:
{history_text}

CRITICAL RULES:
- Extract the patient's CURRENT health state as of their LATEST message(s).
- If the patient previously mentioned symptoms but LATER said she is feeling fine, better, recovered, or okay — those symptoms are RESOLVED and must NOT be listed in "symptoms". Only list symptoms the patient is STILL experiencing.
- Pay close attention to the chronological arc: the most recent messages override earlier ones. A patient saying "I'm fine now" or "I feel better" means previous symptoms have improved.
- Do NOT infer, assume, or hallucinate symptoms that were not directly mentioned.
- If the patient said something vague like "I'm not feeling well" or "I feel bad", put that in "concerns" but leave "symptoms" as an empty array — do NOT guess what might be wrong.
- If something was not discussed at all, use the default/empty value.
- "mood" should reflect the patient's mood in her LATEST message, not earlier ones.

Return ONLY valid JSON with these fields:
{{
    "symptoms": ["list of symptoms the patient is CURRENTLY experiencing — empty array if she says she is fine or better now"],
    "fetal_movement": "active/normal/reduced/not_mentioned",
    "medicine_taken": true/false/null,
    "medicine_details": "what she said about medicine, or empty string",
    "mood": "good/okay/worried/distressed",
    "concerns": "any specific concerns mentioned in the patient's own words, or empty string"
}}

Return ONLY the JSON, no other text."""


async def generate_morning_message(patient: dict) -> str:
    """Generate a personalised morning check-in message."""
    logs = get_daily_logs(patient["id"], days=2)
    yesterday_log = logs[0] if logs else None
    prescriptions = get_prescriptions(patient["id"])

    prompt = _build_morning_prompt(patient, yesterday_log, prescriptions)

    try:
        response = client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        message = response.choices[0].message.content.strip()
        logger.info(f"Morning message for {patient['name']}: {message[:80]}...")

        save_agent_event(patient["id"], "CheckInAgent", "morning_message",
                         f"Morning message sent to {patient['name']} 🌸")
        return message
    except Exception as e:
        logger.error(f"Mistral error generating morning message: {e}")
        return f"Good morning {patient['name']}! How are you feeling today? Any symptoms or discomfort? Have you taken your medicines?"


async def generate_followup(patient: dict, conversation_history: list[dict]) -> str:
    """Generate a follow-up response during conversation."""
    prompt = _build_followup_prompt(patient, conversation_history)

    try:
        response = client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Mistral followup error: {e}")
        return "Thank you for sharing. Take care of yourself today! 🌸"


async def extract_data(patient: dict, conversation_history: list[dict]) -> dict:
    """Extract structured health data from the conversation."""
    prompt = _build_extraction_prompt(patient, conversation_history)

    try:
        response = client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        text = response.choices[0].message.content.strip()
        # Clean up markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        logger.info(f"Extracted data for {patient['name']}: {data}")

        # Save to database
        today = date.today().isoformat()
        save_daily_log(
            patient["id"], today,
            raw_response=json.dumps(conversation_history),
            translated_response="",
            symptoms=json.dumps(data.get("symptoms", [])),
            fetal_movement=data.get("fetal_movement", "not_mentioned"),
            severity="PENDING",
            reason="Awaiting SymptomAgent analysis",
        )
        save_conversation_state(
            patient["id"], today, "extracted",
            len(conversation_history), data,
        )
        save_agent_event(patient["id"], "CheckInAgent", "data_extracted",
                         f"Extracted symptoms: {data.get('symptoms', [])}, movement: {data.get('fetal_movement', 'N/A')}")

        return data
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Extraction error: {e}")
        return {
            "symptoms": [],
            "fetal_movement": "not_mentioned",
            "medicine_taken": None,
            "medicine_details": "",
            "mood": "okay",
            "concerns": "",
        }
