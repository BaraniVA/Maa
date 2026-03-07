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
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# Initialize rotator
sarvam_rotator = KeyRotator("sarvam", SARVAM_API_KEYS) if SARVAM_API_KEYS else None


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
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    SARVAM_TTS_URL,
                    headers={
                        "api-subscription-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "inputs": [text],
                        "target_language_code": sarvam_code,
                        "speaker": "meera",
                        "model": "bulbul:v1",
                    },
                )

                if response.status_code == 429:
                    sarvam_rotator.mark_exhausted(api_key)
                    continue

                if response.status_code >= 400:
                    logger.error(f"Sarvam TTS error {response.status_code}: {response.text}")
                    sarvam_rotator.mark_exhausted(api_key)
                    continue

                data = response.json()
                audios = data.get("audios")
                if audios and len(audios) > 0:
                    audio_bytes = base64.b64decode(audios[0])
                    logger.info(f"TTS generated: {len(audio_bytes)} bytes in {sarvam_code}")
                    return audio_bytes

        except Exception as e:
            logger.error(f"Sarvam TTS error: {e}")
            sarvam_rotator.mark_exhausted(api_key)
            continue

    logger.warning("Sarvam TTS failed")
    return None


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
                    sarvam_rotator.mark_exhausted(api_key)
                    continue

                data = response.json()
                translated = data.get("translated_text", text)
                logger.info(f"Translated [{source_lang} → {target_lang}]: {text[:50]}... → {translated[:50]}...")
                return translated

        except httpx.TimeoutException:
            logger.warning("Sarvam request timed out, rotating key...")
            sarvam_rotator.mark_exhausted(api_key)
            continue
        except Exception as e:
            logger.error(f"Sarvam translation error: {e}")
            sarvam_rotator.mark_exhausted(api_key)
            continue

    logger.warning("All Sarvam translation attempts failed, returning original text")
    return text
