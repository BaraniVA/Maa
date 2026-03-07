"""
KeyRotator — Thread-safe API key rotation with persistent state.
Used by both Sarvam and Vapi integrations.
"""

import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from filelock import FileLock

from backend.config import STATE_PATH


EXHAUSTION_COOLDOWN_SECONDS = 3600  # 60 minutes


class KeyRotator:
    """Manages a pool of API keys with automatic rotation on failure."""

    def __init__(self, service_name: str, keys: list[str], extra_data: dict | None = None):
        """
        Args:
            service_name: 'sarvam' or 'vapi'
            keys: list of API keys
            extra_data: optional dict mapping key index to extra info (e.g. phone_number_id for vapi)
        """
        self.service_name = service_name
        self.keys = keys
        self.extra_data = extra_data or {}
        self.lock = threading.Lock()
        self.state_path = Path(STATE_PATH)
        self.file_lock = FileLock(str(self.state_path) + ".lock")
        self._load_or_init_state()

    def _load_or_init_state(self):
        with self.file_lock:
            if self.state_path.exists():
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
            else:
                state = {}

            if self.service_name not in state:
                state[self.service_name] = {
                    "keys": [],
                    "current_index": 0,
                }

            svc = state[self.service_name]
            existing_keys = {k["key"]: k for k in svc.get("keys", [])}

            key_states = []
            for key in self.keys:
                masked = key[:8] + "..." if len(key) > 8 else key
                if masked in existing_keys:
                    key_states.append(existing_keys[masked])
                else:
                    key_states.append({
                        "key": masked,
                        "requests_today": 0,
                        "exhausted": False,
                        "exhausted_at": None,
                        "last_used": None,
                    })

            svc["keys"] = key_states
            if svc["current_index"] >= len(self.keys):
                svc["current_index"] = 0

            state[self.service_name] = svc
            self.state_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
            self._current_index = svc["current_index"]

    def _save_state(self, key_states: list[dict], current_index: int):
        with self.file_lock:
            if self.state_path.exists():
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
            else:
                state = {}
            state[self.service_name] = {
                "keys": key_states,
                "current_index": current_index,
            }
            self.state_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    def _read_key_states(self) -> list[dict]:
        with self.file_lock:
            if self.state_path.exists():
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                return state.get(self.service_name, {}).get("keys", [])
        return []

    def get_key(self) -> tuple[str, dict] | None:
        """Returns (api_key, extra_data) or None if all keys exhausted."""
        with self.lock:
            if not self.keys:
                return None

            key_states = self._read_key_states()
            now = datetime.now(timezone.utc)

            # Try to un-exhaust keys past cooldown
            for ks in key_states:
                if ks["exhausted"] and ks["exhausted_at"]:
                    exhausted_time = datetime.fromisoformat(ks["exhausted_at"])
                    if (now - exhausted_time).total_seconds() > EXHAUSTION_COOLDOWN_SECONDS:
                        ks["exhausted"] = False
                        ks["exhausted_at"] = None
                        ks["requests_today"] = 0

            # Find next available key starting from current_index
            for i in range(len(self.keys)):
                idx = (self._current_index + i) % len(self.keys)
                if not key_states[idx]["exhausted"]:
                    self._current_index = idx
                    key_states[idx]["requests_today"] += 1
                    key_states[idx]["last_used"] = now.isoformat()
                    self._save_state(key_states, idx)
                    extra = self.extra_data.get(idx, {})
                    return self.keys[idx], extra

            # All exhausted
            self._save_state(key_states, self._current_index)
            return None

    def mark_exhausted(self, key: str):
        """Mark a key as exhausted (e.g., on 429 or auth error)."""
        with self.lock:
            key_states = self._read_key_states()
            now = datetime.now(timezone.utc).isoformat()
            for i, k in enumerate(self.keys):
                if k == key:
                    if i < len(key_states):
                        key_states[i]["exhausted"] = True
                        key_states[i]["exhausted_at"] = now
                    break
            # Advance to next key
            self._current_index = (self._current_index + 1) % len(self.keys)
            self._save_state(key_states, self._current_index)

    def get_current_index(self) -> int:
        return self._current_index

    def get_status(self) -> dict:
        """Return current rotation status for dashboard."""
        key_states = self._read_key_states()
        return {
            "service": self.service_name,
            "current_index": self._current_index,
            "keys": key_states,
            "total_keys": len(self.keys),
        }
