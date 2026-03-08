"""
SQLite database setup, schema creation, and 14-day seed data for 4 patients.
"""

import hashlib
import secrets
import sqlite3
import json
import random
from datetime import date, timedelta
from pathlib import Path

from backend.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables and seed data if patients table is empty."""
    conn = get_connection()
    _create_tables(conn)

    # Add new columns to patients if they don't exist
    for col, coltype in [("blood_group", "TEXT"), ("phone", "TEXT"), ("address", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE patients ADD COLUMN {col} {coltype}")
        except Exception:
            pass

    # Auth tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS asha_workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (worker_id) REFERENCES asha_workers(id)
        );
    """)
    conn.commit()

    # Seed a demo ASHA worker if none exist
    worker_count = conn.execute("SELECT COUNT(*) as c FROM asha_workers").fetchone()["c"]
    if worker_count == 0:
        demo_salt = secrets.token_hex(16)
        demo_hash = hashlib.pbkdf2_hmac('sha256', 'demo1234'.encode(), demo_salt.encode(), 100000).hex()
        conn.execute(
            "INSERT INTO asha_workers (name, email, phone, password_hash, salt) VALUES (?,?,?,?,?)",
            ("Padmapriya", "demo@maa.in", "9876543210", demo_hash, demo_salt),
        )
        conn.commit()

    # Seed only if no patients exist
    row = conn.execute("SELECT COUNT(*) as c FROM patients").fetchone()
    if row["c"] == 0:
        _seed_patients(conn)
        _seed_prescriptions(conn)
        _seed_14_day_logs(conn)
    conn.close()


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            weeks INTEGER NOT NULL,
            trimester INTEGER NOT NULL,
            telegram_chat_id TEXT,
            risk_level TEXT NOT NULL DEFAULT 'low',
            language_code TEXT NOT NULL DEFAULT 'hi',
            asha_phone TEXT,
            pregnancy_number INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS prescriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            medicine_name TEXT NOT NULL,
            frequency TEXT NOT NULL DEFAULT 'daily',
            quantity_supplied INTEGER NOT NULL DEFAULT 30,
            supply_date TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );

        CREATE TABLE IF NOT EXISTS daily_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            raw_response TEXT,
            translated_response TEXT,
            symptoms TEXT,
            fetal_movement TEXT,
            severity TEXT DEFAULT 'GREEN',
            reason TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            UNIQUE(patient_id, date)
        );

        CREATE TABLE IF NOT EXISTS medicine_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            medicine_name TEXT NOT NULL,
            taken INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            UNIQUE(patient_id, date, medicine_name)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT,
            delivered INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );

        CREATE TABLE IF NOT EXISTS care_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            content_english TEXT,
            content_translated TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );

        CREATE TABLE IF NOT EXISTS conversation_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'idle',
            exchange_count INTEGER DEFAULT 0,
            extracted_data TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            UNIQUE(patient_id, date)
        );

        CREATE TABLE IF NOT EXISTS agent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            agent_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def _seed_patients(conn: sqlite3.Connection):
    patients = [
        ("Priya Sharma", 34, 3, "moderate", "hi", 1),
        ("Anita Devi", 28, 2, "low", "ta", 2),
        ("Meena Bai", 38, 3, "high", "mr", 3),
        ("Sunita Kumari", 22, 2, "low", "te", 1),
    ]
    conn.executemany(
        "INSERT INTO patients (name, weeks, trimester, risk_level, language_code, pregnancy_number) VALUES (?,?,?,?,?,?)",
        patients,
    )
    conn.commit()


def _seed_prescriptions(conn: sqlite3.Connection):
    today = date.today()
    supply_date = (today - timedelta(days=20)).isoformat()

    prescriptions = [
        # Priya: iron + calcium
        (1, "Iron Tablets", "daily", 30, supply_date),
        (1, "Calcium Tablets", "daily", 30, supply_date),
        # Anita: iron + folic acid
        (2, "Iron Tablets", "daily", 30, supply_date),
        (2, "Folic Acid Tablets", "daily", 30, supply_date),
        # Meena: calcium + MgSO4
        (3, "Calcium Tablets", "daily", 30, supply_date),
        (3, "MgSO4", "weekly", 8, supply_date),
        # Sunita: iron + folic acid
        (4, "Iron Tablets", "daily", 30, supply_date),
        (4, "Folic Acid Tablets", "daily", 30, supply_date),
    ]
    conn.executemany(
        "INSERT INTO prescriptions (patient_id, medicine_name, frequency, quantity_supplied, supply_date) VALUES (?,?,?,?,?)",
        prescriptions,
    )
    conn.commit()


def _seed_14_day_logs(conn: sqlite3.Connection):
    """Generate 14 days of realistic varied daily logs for each patient."""
    today = date.today()
    random.seed(42)

    # Patient 1: Priya — moderate risk, mild fatigue, missed 3 iron doses
    _seed_patient_logs(conn, 1, today, {
        "symptom_pool": ["mild fatigue", "slight nausea", "back pain", "none", "none", "mild headache"],
        "fetal_pool": ["active", "normal", "less than usual", "active", "normal"],
        "severity_pool": ["GREEN", "GREEN", "YELLOW", "GREEN", "GREEN", "GREEN", "YELLOW"],
        "medicines": ["Iron Tablets", "Calcium Tablets"],
        "missed_days_iron": [3, 7, 11],  # missed iron on these days ago
        "missed_days_other": [],
    })

    # Patient 2: Anita — low risk, all clear, consistent
    _seed_patient_logs(conn, 2, today, {
        "symptom_pool": ["none", "none", "mild tiredness", "none", "none"],
        "fetal_pool": ["active", "active", "normal", "active"],
        "severity_pool": ["GREEN", "GREEN", "GREEN", "GREEN"],
        "medicines": ["Iron Tablets", "Folic Acid Tablets"],
        "missed_days_iron": [],
        "missed_days_other": [],
    })

    # Patient 3: Meena — high risk, swelling + headache history
    _seed_patient_logs(conn, 3, today, {
        "symptom_pool": ["leg swelling", "none", "severe headache", "facial swelling", "none", "mild swelling", "none", "headache"],
        "fetal_pool": ["normal", "less active", "normal", "active", "normal"],
        "severity_pool": ["GREEN", "YELLOW", "RED", "GREEN", "YELLOW", "GREEN", "GREEN"],
        "medicines": ["Calcium Tablets", "MgSO4"],
        "missed_days_iron": [],
        "missed_days_other": [],
        "mgso4_weekly": True,
    })

    # Patient 4: Sunita — low risk, fully compliant, no issues
    _seed_patient_logs(conn, 4, today, {
        "symptom_pool": ["none", "none", "none", "mild nausea", "none"],
        "fetal_pool": ["active", "active", "normal", "active"],
        "severity_pool": ["GREEN", "GREEN", "GREEN", "GREEN"],
        "medicines": ["Iron Tablets", "Folic Acid Tablets"],
        "missed_days_iron": [],
        "missed_days_other": [],
    })


def _seed_patient_logs(conn: sqlite3.Connection, patient_id: int, today: date, profile: dict):
    symptom_pool = profile["symptom_pool"]
    fetal_pool = profile["fetal_pool"]
    severity_pool = profile["severity_pool"]
    medicines = profile["medicines"]
    missed_iron = set(profile.get("missed_days_iron", []))
    missed_other = set(profile.get("missed_days_other", []))
    is_mgso4_weekly = profile.get("mgso4_weekly", False)

    for days_ago in range(14, 0, -1):
        log_date = (today - timedelta(days=days_ago)).isoformat()
        symptom = random.choice(symptom_pool)
        fetal = random.choice(fetal_pool)
        severity = random.choice(severity_pool)

        # Adjust severity for realistic patterns
        if symptom in ("severe headache", "facial swelling") or "swelling" in symptom and "headache" in str(symptom_pool):
            if random.random() > 0.5:
                severity = "YELLOW"
        if symptom == "none":
            severity = "GREEN"

        reason = ""
        if severity == "YELLOW":
            reason = f"Symptom noted: {symptom}"
        elif severity == "RED":
            reason = f"Critical symptom pattern: {symptom}"

        raw_resp = f"Patient reported: {symptom}. Fetal movement: {fetal}."
        translated_resp = raw_resp  # seed data in English

        symptoms_json = json.dumps([symptom] if symptom != "none" else [])

        conn.execute(
            """INSERT OR IGNORE INTO daily_logs
               (patient_id, date, raw_response, translated_response, symptoms, fetal_movement, severity, reason)
               VALUES (?,?,?,?,?,?,?,?)""",
            (patient_id, log_date, raw_resp, translated_resp, symptoms_json, fetal, severity, reason),
        )

        # Medicine logs
        for med in medicines:
            if is_mgso4_weekly and med == "MgSO4":
                # Only on certain days of the week
                taken = 1 if days_ago % 7 == 0 else 0
            elif med == "Iron Tablets" and days_ago in missed_iron:
                taken = 0
            elif days_ago in missed_other:
                taken = 0
            else:
                taken = 1

            conn.execute(
                "INSERT OR IGNORE INTO medicine_logs (patient_id, date, medicine_name, taken) VALUES (?,?,?,?)",
                (patient_id, log_date, med, taken),
            )

        # Conversation state
        conn.execute(
            """INSERT OR IGNORE INTO conversation_state
               (patient_id, date, state, exchange_count, extracted_data)
               VALUES (?,?,?,?,?)""",
            (patient_id, log_date, "completed", random.randint(2, 4),
             json.dumps({"symptoms": symptom, "fetal_movement": fetal, "medicine_taken": True})),
        )

    conn.commit()


# ── Query helpers ──

def get_patient_by_chat_id(chat_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM patients WHERE telegram_chat_id = ?", (str(chat_id),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_patient_by_id(patient_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_patients() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM patients ORDER BY CASE risk_level WHEN 'high' THEN 0 WHEN 'moderate' THEN 1 ELSE 2 END").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_logs(patient_id: int, days: int = 14) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM daily_logs WHERE patient_id = ? ORDER BY date DESC LIMIT ?",
        (patient_id, days),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_medicine_logs(patient_id: int, days: int = 14) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM medicine_logs WHERE patient_id = ? ORDER BY date DESC LIMIT ?",
        (patient_id, days * 3),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_prescriptions(patient_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM prescriptions WHERE patient_id = ?", (patient_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation_state(patient_id: int, log_date: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM conversation_state WHERE patient_id = ? AND date = ?",
        (patient_id, log_date),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_daily_log(patient_id: int, log_date: str, **kwargs):
    conn = get_connection()
    # Check if a log already exists for this date
    existing = conn.execute(
        "SELECT * FROM daily_logs WHERE patient_id = ? AND date = ?",
        (patient_id, log_date),
    ).fetchone()

    if existing:
        # Update only the fields that are provided
        updates = []
        values = []
        for field in ("raw_response", "translated_response", "symptoms", "fetal_movement", "severity", "reason"):
            if field in kwargs:
                updates.append(f"{field} = ?")
                values.append(kwargs[field])
        if updates:
            values.extend([patient_id, log_date])
            conn.execute(
                f"UPDATE daily_logs SET {', '.join(updates)} WHERE patient_id = ? AND date = ?",
                values,
            )
    else:
        conn.execute(
            """INSERT INTO daily_logs
               (patient_id, date, raw_response, translated_response, symptoms, fetal_movement, severity, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (patient_id, log_date,
             kwargs.get("raw_response", ""),
             kwargs.get("translated_response", ""),
             kwargs.get("symptoms", "[]"),
             kwargs.get("fetal_movement", ""),
             kwargs.get("severity", "GREEN"),
             kwargs.get("reason", "")),
        )
    conn.commit()
    conn.close()


def save_medicine_log(patient_id: int, log_date: str, medicine_name: str, taken: bool):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO medicine_logs (patient_id, date, medicine_name, taken) VALUES (?,?,?,?)",
        (patient_id, log_date, medicine_name, 1 if taken else 0),
    )
    conn.commit()
    conn.close()


def save_conversation_state(patient_id: int, log_date: str, state: str, exchange_count: int, extracted_data: dict):
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO conversation_state
           (patient_id, date, state, exchange_count, extracted_data)
           VALUES (?,?,?,?,?)""",
        (patient_id, log_date, state, exchange_count, json.dumps(extracted_data)),
    )
    conn.commit()
    conn.close()


def save_notification(patient_id: int, log_date: str, ntype: str, content: str, delivered: bool = False):
    conn = get_connection()
    conn.execute(
        "INSERT INTO notifications (patient_id, date, type, content, delivered) VALUES (?,?,?,?,?)",
        (patient_id, log_date, ntype, content, 1 if delivered else 0),
    )
    conn.commit()
    conn.close()


def save_care_plan(patient_id: int, log_date: str, english: str, translated: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO care_plans (patient_id, date, content_english, content_translated) VALUES (?,?,?,?)",
        (patient_id, log_date, english, translated),
    )
    conn.commit()
    conn.close()


def save_agent_event(patient_id: int | None, agent_name: str, event_type: str, message: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO agent_events (patient_id, agent_name, event_type, message) VALUES (?,?,?,?)",
        (patient_id, agent_name, event_type, message),
    )
    conn.commit()
    conn.close()


def get_agent_events(limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agent_events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_care_plans(patient_id: int, limit: int = 3) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM care_plans WHERE patient_id = ? ORDER BY date DESC LIMIT ?",
        (patient_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_notifications(patient_id: int, limit: int = 10) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE patient_id = ? ORDER BY id DESC LIMIT ?",
        (patient_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def register_patient_chat_id(patient_id: int, chat_id: str):
    conn = get_connection()
    conn.execute(
        "UPDATE patients SET telegram_chat_id = ? WHERE id = ?",
        (str(chat_id), patient_id),
    )
    conn.commit()
    conn.close()


def match_patient_by_name(name: str) -> dict | None:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM patients").fetchall()
    conn.close()
    name_lower = name.strip().lower()
    for row in rows:
        if name_lower in dict(row)["name"].lower() or dict(row)["name"].lower() in name_lower:
            return dict(row)
    return None


# ── Auth helpers ──

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()


def create_asha_worker(name: str, email: str, phone: str, password: str) -> dict | None:
    conn = get_connection()
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    try:
        conn.execute(
            "INSERT INTO asha_workers (name, email, phone, password_hash, salt) VALUES (?,?,?,?,?)",
            (name, email, phone, password_hash, salt),
        )
        conn.commit()
        worker_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return {"id": worker_id, "name": name, "email": email, "phone": phone}
    except sqlite3.IntegrityError:
        conn.close()
        return None


def authenticate_worker(email: str, password: str) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM asha_workers WHERE email = ?", (email,)).fetchone()
    if not row:
        conn.close()
        return None
    worker = dict(row)
    password_hash = _hash_password(password, worker["salt"])
    if password_hash != worker["password_hash"]:
        conn.close()
        return None
    token = secrets.token_hex(32)
    conn.execute("INSERT INTO sessions (worker_id, token) VALUES (?,?)", (worker["id"], token))
    conn.commit()
    conn.close()
    return token


def get_worker_by_token(token: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT w.id, w.name, w.email, w.phone, w.created_at FROM asha_workers w "
        "JOIN sessions s ON w.id = s.worker_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token: str):
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# ── Patient CRUD ──

def create_patient_record(name, weeks, trimester, risk_level="low", language_code="hi",
                          pregnancy_number=1, blood_group="", phone="", address="", asha_phone="") -> dict:
    conn = get_connection()
    conn.execute(
        """INSERT INTO patients (name, weeks, trimester, risk_level, language_code,
           pregnancy_number, blood_group, phone, address, asha_phone)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (name, weeks, trimester, risk_level, language_code, pregnancy_number,
         blood_group, phone, address, asha_phone),
    )
    conn.commit()
    patient_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return get_patient_by_id(patient_id)


def update_patient(patient_id: int, **kwargs) -> dict | None:
    conn = get_connection()
    allowed = {"name", "weeks", "trimester", "risk_level", "language_code",
               "pregnancy_number", "blood_group", "phone", "address",
               "asha_phone", "telegram_chat_id"}
    updates = []
    values = []
    for key, val in kwargs.items():
        if key in allowed:
            updates.append(f"{key} = ?")
            values.append(val)
    if not updates:
        conn.close()
        return get_patient_by_id(patient_id)
    values.append(patient_id)
    conn.execute(f"UPDATE patients SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return get_patient_by_id(patient_id)


def delete_patient(patient_id: int) -> bool:
    conn = get_connection()
    for table in ("daily_logs", "medicine_logs", "prescriptions", "notifications",
                  "care_plans", "conversation_state"):
        conn.execute(f"DELETE FROM {table} WHERE patient_id = ?", (patient_id,))
    conn.execute("DELETE FROM agent_events WHERE patient_id = ?", (patient_id,))
    conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
    conn.commit()
    conn.close()
    return True


def add_prescription(patient_id: int, medicine_name: str, frequency: str = "daily",
                     quantity_supplied: int = 30) -> dict:
    conn = get_connection()
    supply_date = date.today().isoformat()
    conn.execute(
        "INSERT INTO prescriptions (patient_id, medicine_name, frequency, quantity_supplied, supply_date) VALUES (?,?,?,?,?)",
        (patient_id, medicine_name, frequency, quantity_supplied, supply_date),
    )
    conn.commit()
    rx_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": rx_id, "patient_id": patient_id, "medicine_name": medicine_name,
            "frequency": frequency, "quantity_supplied": quantity_supplied, "supply_date": supply_date}
