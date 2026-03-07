"""
SymptomAgent — Analyses symptoms using Groq (LLaMA 3.3 70B).
Reads today's JSON + 14-day history, detects patterns, outputs severity.
"""

import json
import logging
from datetime import date

from groq import Groq

from backend.config import GROQ_API_KEY, GROQ_MODEL
from backend.database import (
    get_daily_logs, save_daily_log, save_agent_event, get_patient_by_id,
)

logger = logging.getLogger("maa.symptom")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


def _build_analysis_prompt(patient: dict, today_data: dict, history: list[dict]) -> str:
    history_text = ""
    for log in history:
        history_text += f"  {log['date']}: symptoms={log.get('symptoms', '[]')}, severity={log.get('severity', 'GREEN')}, movement={log.get('fetal_movement', 'N/A')}\n"

    return f"""You are a maternal health symptom analysis system. Analyse this patient's data.

PATIENT: {patient['name']}, {patient['weeks']} weeks pregnant, risk level: {patient['risk_level']}, pregnancy #{patient.get('pregnancy_number', 1)}

TODAY'S DATA:
- Symptoms: {json.dumps(today_data.get('symptoms', []))}
- Fetal movement: {today_data.get('fetal_movement', 'not_mentioned')}
- Mood: {today_data.get('mood', 'okay')}
- Concerns: {today_data.get('concerns', '')}

14-DAY HISTORY:
{history_text}

DETECTION RULES (check across multiple days, not just today):
1. PRE-ECLAMPSIA: headache + swelling together (any combination across last 3 days) → RED
2. HAEMORRHAGE: bleeding or abnormal discharge → RED immediately
3. INFECTION: fever + chills → RED
4. REDUCED MOVEMENT: fetal movement reduced for 2+ consecutive days → YELLOW, 3+ → RED
5. PATTERN: same symptom 3+ times in 7 days → YELLOW
6. HIGH RISK + ANY SYMPTOM: if patient is high risk, lower the threshold
7. SILENCE: if high-risk patient has no data today → RED (will be handled externally)

OUTPUT FORMAT — return ONLY valid JSON:
{{
    "severity": "GREEN" or "YELLOW" or "RED",
    "reason": "plain English explanation of why this severity was assigned",
    "patterns_detected": ["list of any concerning patterns found"],
    "recommendations": "brief recommendation for ASHA worker"
}}

Be thorough but avoid false positives. Consider the full picture across days."""


async def analyse_symptoms(patient_id: int, today_data: dict) -> dict:
    """Run symptom analysis and return severity assessment."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        return {"severity": "GREEN", "reason": "Patient not found", "patterns_detected": [], "recommendations": ""}

    history = get_daily_logs(patient_id, days=14)

    # Handle silence for high-risk patients
    if not today_data.get("symptoms") and patient["risk_level"] == "high":
        if not today_data.get("fetal_movement") or today_data["fetal_movement"] == "not_mentioned":
            result = {
                "severity": "RED",
                "reason": f"High-risk patient ({patient['weeks']} weeks) — no response received today. Automatic escalation.",
                "patterns_detected": ["silence_high_risk"],
                "recommendations": "Visit patient immediately to confirm wellbeing.",
            }
            _save_result(patient, result)
            return result

    prompt = _build_analysis_prompt(patient, today_data, history)

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        logger.info(f"Symptom analysis for {patient['name']}: {result['severity']} — {result['reason']}")
        _save_result(patient, result)
        return result

    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Groq symptom analysis error: {e}")
        # Default to YELLOW on error for safety
        result = {
            "severity": "YELLOW",
            "reason": f"Analysis error, defaulting to YELLOW for safety: {str(e)[:100]}",
            "patterns_detected": [],
            "recommendations": "Manual review recommended.",
        }
        _save_result(patient, result)
        return result


def _save_result(patient: dict, result: dict):
    today = date.today().isoformat()
    # Update today's log with severity
    save_daily_log(
        patient["id"], today,
        severity=result["severity"],
        reason=result["reason"],
    )
    severity_emoji = {"GREEN": "✅", "YELLOW": "⚠️", "RED": "🚨"}.get(result["severity"], "❓")
    save_agent_event(
        patient["id"], "SymptomAgent", "analysis_complete",
        f"{result['severity']} {severity_emoji}: {result['reason'][:120]}"
    )
