import os
from pathlib import Path
from dotenv import load_dotenv

# Always load .env from the project root (parent of backend/)
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")


# Telegram bots
TELEGRAM_CHECKIN_TOKEN = os.getenv("TELEGRAM_CHECKIN_TOKEN", "")
TELEGRAM_SYMPTOM_TOKEN = os.getenv("TELEGRAM_SYMPTOM_TOKEN", "")
TELEGRAM_RESOURCE_TOKEN = os.getenv("TELEGRAM_RESOURCE_TOKEN", "")
TELEGRAM_NOTIFY_TOKEN = os.getenv("TELEGRAM_NOTIFY_TOKEN", "")
TELEGRAM_CARE_TOKEN = os.getenv("TELEGRAM_CARE_TOKEN", "")
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID", "")
TELEGRAM_ADMIN_USER_ID = os.getenv("TELEGRAM_ADMIN_USER_ID", "")
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "")  # e.g. socks5://127.0.0.1:1080 or http://proxy:8080

# AI Models
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct")
NVIDIA_API_URL = os.getenv("NVIDIA_API_URL", "https://integrate.api.nvidia.com/v1")

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud")

# Sarvam - comma separated keys for rotation
SARVAM_API_KEYS = [k.strip() for k in os.getenv("SARVAM_API_KEYS", "").split(",") if k.strip()]

# Vapi - comma separated keys/phone IDs for rotation
VAPI_API_KEYS = [k.strip() for k in os.getenv("VAPI_API_KEYS", "").split(",") if k.strip()]
VAPI_PHONE_NUMBER_IDS = [k.strip() for k in os.getenv("VAPI_PHONE_NUMBER_IDS", "").split(",") if k.strip()]
ASHA_PHONE_NUMBER = os.getenv("ASHA_PHONE_NUMBER", "")

# Twilio (replacement for Vapi — works with Indian numbers)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")  # Your Twilio trial number

# Notifications
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "maa-alerts")
NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.sh")

# Email
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
ASHA_EMAIL = os.getenv("ASHA_EMAIL", "")

# Calendar
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")

# Demo mode
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# Database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "maa.db")
STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")

# Language mapping
LANGUAGE_MAP = {
    "hi": {"name": "Hindi", "sarvam_code": "hi-IN"},
    "ta": {"name": "Tamil", "sarvam_code": "ta-IN"},
    "mr": {"name": "Marathi", "sarvam_code": "mr-IN"},
    "te": {"name": "Telugu", "sarvam_code": "te-IN"},
    "en": {"name": "English", "sarvam_code": "en-IN"},
}
