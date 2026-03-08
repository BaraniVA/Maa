"""
Sarvam AI translation + TTS layer with key rotation.
Every message to/from the patient passes through here.
"""

import base64
import logging
import httpx

from backend.config import SARVAM_API_KEYS, LANGUAGE_MAP
from backend.key_rotator import KeyRotator

logger = logging.getLogger("maa.sarvam")

SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech/stream"
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Initialize rotator
sarvam_rotator = KeyRotator("sarvam", SARVAM_API_KEYS) if SARVAM_API_KEYS else None

# Reverse map: sarvam_code → language_code (e.g. "ta-IN" → "ta")
_SARVAM_TO_LANG = {v["sarvam_code"]: k for k, v in LANGUAGE_MAP.items()}


def sarvam_lang_to_code(sarvam_code: str) -> str:
    """Convert Sarvam language code (e.g. 'ta-IN') to config code (e.g. 'ta'). Returns '' if unknown."""
    return _SARVAM_TO_LANG.get(sarvam_code, "")


async def translate_to_patient(text: str, language_code: str) -> str:
    """Translate English text to patient's language."""
    if language_code == "en" or not sarvam_rotator:
        return text
    sarvam_code = LANGUAGE_MAP.get(language_code, {}).get("sarvam_code")
    if not sarvam_code:
        return text
    return await _translate(text, "en-IN", sarvam_code)


async def translate_to_english(text: str, language_code: str) -> str:
    """Translate patient's message to English."""
    if language_code == "en" or not sarvam_rotator:
        return text
    sarvam_code = LANGUAGE_MAP.get(language_code, {}).get("sarvam_code")
    if not sarvam_code:
        return text
    return await _translate(text, sarvam_code, "en-IN")


async def text_to_speech(text: str, language_code: str) -> bytes | None:
    """Convert text to speech audio (WAV) via Sarvam TTS. Returns raw audio bytes or None."""
    if not sarvam_rotator:
        logger.warning("Sarvam not configured, TTS unavailable")
        return None

    sarvam_code = LANGUAGE_MAP.get(language_code, {}).get("sarvam_code", "en-IN")

    max_attempts = len(SARVAM_API_KEYS) if SARVAM_API_KEYS else 1

    for attempt in range(max_attempts):
        result = sarvam_rotator.get_key()
        if result is None:
            break

        api_key, _ = result

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "text": text,
                    "target_language_code": sarvam_code,
                    "speaker": "priya",
                    "model": "bulbul:v3",
                    "speech_sample_rate": 22050,
                    "output_audio_codec": "mp3",
                    "enable_preprocessing": True,
                }
                logger.info(f"TTS request: lang={sarvam_code}, text={text[:60]}...")

                response = await client.post(
                    SARVAM_TTS_URL,
                    headers={
                        "api-subscription-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                logger.info(f"TTS response: status={response.status_code}, content-type={response.headers.get('content-type')}, size={len(response.content)}")

                if response.status_code == 429:
                    sarvam_rotator.mark_exhausted(api_key)
                    continue

                if response.status_code >= 400:
                    logger.error(f"Sarvam TTS error {response.status_code}: {response.text}")
                    return None

                audio_bytes = response.content
                if audio_bytes:
                    logger.info(f"TTS generated: {len(audio_bytes)} bytes in {sarvam_code}")
                    return audio_bytes
                else:
                    logger.warning("TTS response had empty content")

        except Exception as e:
            logger.error(f"Sarvam TTS error: {e}")
            continue

    logger.warning("Sarvam TTS failed")
    return None


async def speech_to_text(audio_bytes: bytes, language_code: str = "") -> tuple[str, str]:
    """
    Convert speech audio to text via Sarvam STT.
    Returns (transcript, detected_language_code).
    If STT fails, returns ("", "").
    """
    if not sarvam_rotator:
        logger.warning("Sarvam not configured, STT unavailable")
        return "", ""

    sarvam_code = LANGUAGE_MAP.get(language_code, {}).get("sarvam_code", "")
    logger.info(f"STT request: {len(audio_bytes)} bytes, lang_hint={language_code!r}, sarvam_code={sarvam_code!r}")
    max_attempts = len(SARVAM_API_KEYS) if SARVAM_API_KEYS else 1

    for attempt in range(max_attempts):
        result = sarvam_rotator.get_key()
        if result is None:
            break

        api_key, _ = result

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                files = {"file": ("audio.ogg", audio_bytes, "audio/ogg")}
                data = {"model": "saarika:v2.5"}
                if sarvam_code:
                    data["language_code"] = sarvam_code

                response = await client.post(
                    SARVAM_STT_URL,
                    headers={"api-subscription-key": api_key},
                    files=files,
                    data=data,
                )

                if response.status_code == 429:
                    sarvam_rotator.mark_exhausted(api_key)
                    continue

                if response.status_code >= 400:
                    logger.error(f"Sarvam STT error {response.status_code}: {response.text}")
                    return "", ""

                resp_data = response.json()
                logger.info(f"STT raw response: {resp_data}")
                transcript = resp_data.get("transcript", "")
                detected_lang = resp_data.get("language_code", sarvam_code)
                logger.info(f"STT transcribed ({detected_lang}): {transcript}")
                return transcript, detected_lang

        except Exception as e:
            logger.error(f"Sarvam STT error: {e}")
            continue

    logger.warning("Sarvam STT failed after all attempts")
    return "", ""


async def _translate(text: str, source_lang: str, target_lang: str) -> str:
    """Core translation with key rotation and fallback."""
    max_attempts = len(SARVAM_API_KEYS) if SARVAM_API_KEYS else 1

    for attempt in range(max_attempts):
        result = sarvam_rotator.get_key()
        if result is None:
            logger.warning("All Sarvam keys exhausted, falling back to English")
            return text

        api_key, _ = result

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    SARVAM_TRANSLATE_URL,
                    headers={
                        "api-subscription-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "input": text,
                        "source_language_code": source_lang,
                        "target_language_code": target_lang,
                        "mode": "formal",
                        "model": "mayura:v1",
                        "enable_preprocessing": True,
                    },
                )

                if response.status_code == 429:
                    logger.warning(f"Sarvam key rate limited, rotating...")
                    sarvam_rotator.mark_exhausted(api_key)
                    continue

                if response.status_code >= 400:
                    logger.error(f"Sarvam error {response.status_code}: {response.text}")
                    return text

                data = response.json()
                translated = data.get("translated_text", text)
                logger.info(f"Translated [{source_lang} → {target_lang}]: {text[:50]}... → {translated[:50]}...")
                return translated

        except httpx.TimeoutException:
            logger.warning("Sarvam request timed out, retrying...")
            continue
        except Exception as e:
            logger.error(f"Sarvam translation error: {e}")
            continue

    logger.warning("All Sarvam translation attempts failed, returning original text")
    return text
