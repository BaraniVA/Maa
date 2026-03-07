"""
ResourceAgent — Tracks medicine compliance and stock using Gemini.
Updates medicine log, predicts runout, flags issues.
"""

import json
import logging
from datetime import date, datetime, timedelta

import google.generativeai as genai

from backend.config import GEMINI_API_KEY, GEMINI_MODEL
from backend.database import (
    get_medicine_logs, get_prescriptions, save_medicine_log,
    save_agent_event, get_patient_by_id,
)

logger = logging.getLogger("maa.resource")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel(GEMINI_MODEL)
else:
    gemini_model = None


async def check_resources(patient_id: int, today_data: dict) -> dict:
    """Check medicine stock, compliance, and predict runout."""
    patient = get_patient_by_id(patient_id)
    if not patient:
        return {"flags": [], "stock_status": {}}

    prescriptions = get_prescriptions(patient_id)
    medicine_logs = get_medicine_logs(patient_id, days=14)
    today_str = date.today().isoformat()

    # Update today's medicine log from extracted data
    if today_data.get("medicine_taken") is not None:
        for p in prescriptions:
            if p["frequency"] == "daily":
                save_medicine_log(patient_id, today_str, p["medicine_name"], today_data["medicine_taken"])

    # Build analysis context
    stock_analysis = _calculate_stock(prescriptions, medicine_logs)
    compliance = _calculate_compliance(prescriptions, medicine_logs)

    prompt = f"""You are a medicine resource tracking system for maternal health.

PATIENT: {patient['name']}, {patient['weeks']} weeks pregnant

PRESCRIPTIONS:
{json.dumps([{"medicine": p["medicine_name"], "frequency": p["frequency"],
              "quantity_supplied": p["quantity_supplied"], "supply_date": p["supply_date"]}
             for p in prescriptions], indent=2)}

STOCK ANALYSIS:
{json.dumps(stock_analysis, indent=2)}

COMPLIANCE (last 14 days):
{json.dumps(compliance, indent=2)}

TODAY'S REPORT: Medicine taken = {today_data.get('medicine_taken', 'unknown')}

FLAG RULES:
1. LOW STOCK: if any medicine has ≤5 days supply remaining → flag
2. NON-COMPLIANCE: if 3+ consecutive missed doses for any medicine → flag
3. RUNOUT: predict exact runout date based on actual consumption rate

Return ONLY valid JSON:
{{
    "flags": ["list of flag strings — e.g., 'LOW_STOCK: Iron Tablets - 4 days remaining'"],
    "stock_status": {{
        "medicine_name": {{
            "remaining_days": number,
            "consumption_rate": number,
            "predicted_runout": "YYYY-MM-DD",
            "compliant": true/false
        }}
    }},
    "summary": "one sentence summary for the group"
}}"""

    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        logger.info(f"Resource check for {patient['name']}: {result.get('flags', [])}")

        # Log events
        if result.get("flags"):
            for flag in result["flags"]:
                save_agent_event(patient_id, "ResourceAgent", "flag", flag)
        else:
            save_agent_event(patient_id, "ResourceAgent", "check_complete",
                             f"Medicine stock OK for {patient['name']}")

        return result

    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Gemini resource check error: {e}")
        # Fallback to manual calculation
        result = _fallback_analysis(patient, prescriptions, stock_analysis, compliance)
        return result


def _calculate_stock(prescriptions: list[dict], logs: list[dict]) -> dict:
    """Calculate remaining stock for each medicine."""
    stock = {}
    today = date.today()

    for p in prescriptions:
        med = p["medicine_name"]
        supply_date = datetime.fromisoformat(p["supply_date"]).date()
        quantity = p["quantity_supplied"]

        # Count doses taken
        taken = sum(1 for log in logs if log["medicine_name"] == med and log["taken"])
        remaining = max(0, quantity - taken)

        # Calculate consumption rate
        days_since_supply = (today - supply_date).days or 1
        rate = taken / days_since_supply if days_since_supply > 0 else 0

        # Predict runout
        if rate > 0:
            days_left = remaining / rate
            runout_date = (today + timedelta(days=int(days_left))).isoformat()
        else:
            days_left = remaining
            runout_date = (today + timedelta(days=remaining)).isoformat()

        stock[med] = {
            "quantity_supplied": quantity,
            "taken": taken,
            "remaining": remaining,
            "days_left": round(days_left, 1),
            "consumption_rate": round(rate, 2),
            "predicted_runout": runout_date,
        }

    return stock


def _calculate_compliance(prescriptions: list[dict], logs: list[dict]) -> dict:
    """Calculate compliance metrics."""
    compliance = {}

    for p in prescriptions:
        med = p["medicine_name"]
        med_logs = sorted(
            [l for l in logs if l["medicine_name"] == med],
            key=lambda x: x["date"],
        )

        total = len(med_logs)
        taken = sum(1 for l in med_logs if l["taken"])
        missed_streak = 0
        max_missed_streak = 0
        for l in reversed(med_logs):
            if not l["taken"]:
                missed_streak += 1
                max_missed_streak = max(max_missed_streak, missed_streak)
            else:
                missed_streak = 0

        compliance[med] = {
            "total_days": total,
            "taken": taken,
            "missed": total - taken,
            "compliance_rate": round(taken / total * 100, 1) if total > 0 else 0,
            "current_missed_streak": missed_streak,
            "max_missed_streak": max_missed_streak,
        }

    return compliance


def _fallback_analysis(patient: dict, prescriptions: list, stock: dict, compliance: dict) -> dict:
    """Fallback analysis without AI."""
    flags = []
    stock_status = {}

    for med, s in stock.items():
        comp = compliance.get(med, {})
        status = {
            "remaining_days": s["days_left"],
            "consumption_rate": s["consumption_rate"],
            "predicted_runout": s["predicted_runout"],
            "compliant": comp.get("current_missed_streak", 0) < 3,
        }
        stock_status[med] = status

        if s["days_left"] <= 5:
            flag = f"LOW_STOCK: {med} — {s['days_left']:.0f} days remaining"
            flags.append(flag)
            save_agent_event(patient["id"], "ResourceAgent", "flag", flag)

        if comp.get("current_missed_streak", 0) >= 3:
            flag = f"NON_COMPLIANCE: {med} — {comp['current_missed_streak']} consecutive doses missed"
            flags.append(flag)
            save_agent_event(patient["id"], "ResourceAgent", "flag", flag)

    if not flags:
        save_agent_event(patient["id"], "ResourceAgent", "check_complete",
                         f"Medicine stock OK for {patient['name']}")

    return {
        "flags": flags,
        "stock_status": stock_status,
        "summary": f"{'⚠️ ' + ', '.join(flags) if flags else '✅ All medicines on track'} for {patient['name']}",
    }
