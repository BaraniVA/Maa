"""
Telegram bots — 5 separate bots, one per agent.
Handles incoming messages, registration, and demo mode.
"""

import json
import logging
import asyncio
from datetime import date

import httpx
from telegram import Bot, Update
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes,
)

from backend.config import (
    TELEGRAM_CHECKIN_TOKEN, TELEGRAM_SYMPTOM_TOKEN,
    TELEGRAM_RESOURCE_TOKEN, TELEGRAM_NOTIFY_TOKEN,
    TELEGRAM_CARE_TOKEN, TELEGRAM_GROUP_CHAT_ID,
    DEMO_MODE, TELEGRAM_PROXY,
)
from backend.database import (
    get_patient_by_chat_id, match_patient_by_name,
    register_patient_chat_id, get_all_patients, save_agent_event,
    get_conversation_state,
)
from backend.pipeline import handle_patient_message, run_morning_pipeline, run_full_pipeline
from backend.sarvam import translate_to_english, translate_to_patient, speech_to_text

logger = logging.getLogger("maa.telegram")

# Bot instances (async-friendly)
bots: dict[str, Bot] = {}
applications: list[Application] = []

# Track registration conversations
_pending_registrations: dict[int, str] = {}  # chat_id → state


def _get_request_kwargs():
    """Return proxy config for httpx if TELEGRAM_PROXY is set."""
    if TELEGRAM_PROXY:
        logger.info(f"Using proxy for Telegram: {TELEGRAM_PROXY}")
        return {"proxy": TELEGRAM_PROXY}
    return {}


def _init_bots():
    """Initialize all 5 bot instances."""
    global bots
    tokens = {
        "checkin": TELEGRAM_CHECKIN_TOKEN,
        "symptom": TELEGRAM_SYMPTOM_TOKEN,
        "resource": TELEGRAM_RESOURCE_TOKEN,
        "notify": TELEGRAM_NOTIFY_TOKEN,
        "care": TELEGRAM_CARE_TOKEN,
    }
    for name, token in tokens.items():
        if token:
            bots[name] = Bot(token=token)
            logger.info(f"Bot initialized: {name}")
        else:
            logger.warning(f"No token for {name} bot")


async def _transcribe_voice(update: Update) -> tuple[str | None, str]:
    """Download and transcribe a voice message via Sarvam STT. Returns (transcript, detected_sarvam_lang) or (None, '')."""
    voice = update.message.voice
    if not voice:
        return None, ""
    try:
        file = await voice.get_file()
        audio_bytes = bytes(await file.download_as_bytearray())
    except Exception as e:
        logger.error(f"Voice download error: {e}")
        return None, ""

    chat_id = str(update.message.chat_id)
    patient = get_patient_by_chat_id(chat_id)
    lang_hint = patient["language_code"] if patient else ""
    logger.info(f"Voice msg from chat {chat_id}: duration={voice.duration}s, size={voice.file_size}, mime={voice.mime_type}, lang_hint={lang_hint!r}")

    transcript, detected_lang = await speech_to_text(audio_bytes, lang_hint)
    if transcript:
        logger.info(f"Voice transcribed for chat {chat_id} [{detected_lang}]: '{transcript}'")
    else:
        logger.warning(f"Voice transcription returned empty for chat {chat_id}")
    return (transcript or None), detected_lang


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any incoming private message — registration, conversation, or demo trigger."""
    if not update.message:
        return

    # Handle voice messages — transcribe to text
    voice_mode = False
    detected_lang = ""
    if update.message.voice:
        text, detected_lang = await _transcribe_voice(update)
        voice_mode = True
        if not text:
            chat_id = str(update.message.chat_id)
            if bots.get("checkin"):
                try:
                    await bots["checkin"].send_message(
                        chat_id=chat_id,
                        text="Sorry, I couldn't understand that voice message. Could you try again?",
                    )
                except Exception as e:
                    logger.error(f"Voice fallback msg error: {e}")
            return
    elif update.message.text:
        text = update.message.text.strip()
    else:
        return

    chat_id = str(update.message.chat_id)

    # Private message handling — check if already registered
    patient = get_patient_by_chat_id(chat_id)

    if patient:
        # Registered patient — reply in their DM
        if DEMO_MODE:
            # In demo mode, only trigger morning pipeline if no active conversation today
            today = date.today().isoformat()
            conv = get_conversation_state(patient["id"], today)
            if not conv or conv.get("state") == "idle":
                logger.info(f"DEMO MODE: {patient['name']} sent '{text}', triggering pipeline")
                save_agent_event(patient["id"], "System", "demo_trigger",
                                 f"Demo triggered by {patient['name']}")
                await run_morning_pipeline(patient["id"], bots, reply_chat_id=chat_id, voice_mode=voice_mode, detected_lang=detected_lang)
            else:
                # Conversation already active — handle as normal follow-up
                await handle_patient_message(patient["id"], text, bots, reply_chat_id=chat_id, voice_mode=voice_mode, detected_lang=detected_lang)
            return
        else:
            # Normal mode — handle as conversation, reply to DM
            await handle_patient_message(patient["id"], text, bots, reply_chat_id=chat_id, voice_mode=voice_mode, detected_lang=detected_lang)
            return

    # Not registered — start registration
    if chat_id in _pending_registrations:
        # They're in registration flow — trying to match name
        matched = match_patient_by_name(text)
        if matched:
            register_patient_chat_id(matched["id"], chat_id)
            del _pending_registrations[chat_id]

            welcome = await translate_to_patient(
                f"Welcome {matched['name']}! You are now registered with Maa. "
                f"I'll check in with you every morning to see how you're doing. 🌸",
                matched["language_code"],
            )
            if bots.get("checkin"):
                try:
                    await bots["checkin"].send_message(chat_id=chat_id, text=welcome)
                except Exception as e:
                    logger.error(f"Welcome message error: {e}")

            save_agent_event(matched["id"], "System", "registered",
                             f"{matched['name']} registered from chat {chat_id}")

            # In demo mode, immediately start pipeline (reply in DM)
            if DEMO_MODE:
                await asyncio.sleep(1)
                await run_morning_pipeline(matched["id"], bots, reply_chat_id=chat_id)
            return
        else:
            if bots.get("checkin"):
                try:
                    await bots["checkin"].send_message(
                        chat_id=chat_id,
                        text="I couldn't find that name. Please tell me your full name as registered (e.g., Priya Sharma):",
                    )
                except Exception as e:
                    logger.error(f"Registration retry error: {e}")
            return

    # First contact — ask for name
    _pending_registrations[chat_id] = "awaiting_name"
    if bots.get("checkin"):
        try:
            await bots["checkin"].send_message(
                chat_id=chat_id,
                text="🌸 Namaste! I'm Maa, your maternal health assistant.\n\nPlease tell me your full name so I can find your record:",
            )
        except Exception as e:
            logger.error(f"Registration start error: {e}")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages in the group chat."""
    if not update.message:
        return

    # Handle voice messages — transcribe to text
    voice_mode = False
    detected_lang = ""
    if update.message.voice:
        text, detected_lang = await _transcribe_voice(update)
        voice_mode = True
        if not text:
            return  # silently ignore failed transcription in group
    elif update.message.text:
        text = update.message.text.strip()
    else:
        return

    user_id = update.message.from_user.id if update.message.from_user else None
    group_chat_id = str(update.message.chat_id)

    if not user_id:
        return

    # Check if from a registered patient
    patient = get_patient_by_chat_id(str(user_id))
    if patient:
        if DEMO_MODE:
            # Only trigger morning pipeline if no active conversation today
            today = date.today().isoformat()
            conv = get_conversation_state(patient["id"], today)
            if not conv or conv.get("state") == "idle":
                save_agent_event(patient["id"], "System", "demo_trigger",
                                 f"Demo triggered by {patient['name']} in group")
                await run_morning_pipeline(patient["id"], bots, reply_chat_id=group_chat_id, voice_mode=voice_mode, detected_lang=detected_lang)
            else:
                # Conversation already active — handle as follow-up
                await handle_patient_message(patient["id"], text, bots, reply_chat_id=group_chat_id, voice_mode=voice_mode, detected_lang=detected_lang)
        else:
            await handle_patient_message(patient["id"], text, bots, reply_chat_id=group_chat_id, voice_mode=voice_mode, detected_lang=detected_lang)
        return

    # Not registered — try to match by name and register from group
    matched = match_patient_by_name(text)
    if matched:
        register_patient_chat_id(matched["id"], str(user_id))

        welcome = await translate_to_patient(
            f"Welcome {matched['name']}! You are now registered with Maa. "
            f"I'll check in with you every morning to see how you're doing. 🌸",
            matched["language_code"],
        )
        if bots.get("checkin"):
            try:
                await bots["checkin"].send_message(chat_id=group_chat_id, text=welcome)
            except Exception as e:
                logger.error(f"Group welcome message error: {e}")

        save_agent_event(matched["id"], "System", "registered",
                         f"{matched['name']} registered from group chat")

        if DEMO_MODE:
            await asyncio.sleep(1)
            await run_morning_pipeline(matched["id"], bots, reply_chat_id=group_chat_id)


def build_applications() -> list[Application]:
    """Build all 5 Telegram bot applications with handlers."""
    global applications

    tokens = {
        "checkin": TELEGRAM_CHECKIN_TOKEN,
        "symptom": TELEGRAM_SYMPTOM_TOKEN,
        "resource": TELEGRAM_RESOURCE_TOKEN,
        "notify": TELEGRAM_NOTIFY_TOKEN,
        "care": TELEGRAM_CARE_TOKEN,
    }

    for name, token in tokens.items():
        if not token:
            continue

        builder = Application.builder().token(token)
        if TELEGRAM_PROXY:
            builder = builder.proxy(TELEGRAM_PROXY).get_updates_proxy(TELEGRAM_PROXY)
        app = builder.build()

        if name == "checkin":
            # CheckIn bot handles text + voice messages
            app.add_handler(MessageHandler(
                (filters.TEXT | filters.VOICE) & filters.ChatType.PRIVATE,
                handle_message,
            ))
            app.add_handler(MessageHandler(
                (filters.TEXT | filters.VOICE) & filters.ChatType.GROUPS,
                handle_group_message,
            ))
        # Other bots don't need message handlers — they only send

        applications.append(app)
        logger.info(f"Application built for {name} bot")

    return applications


async def start_polling():
    """Start all bot applications with polling."""
    _init_bots()

    if not bots:
        logger.warning("No bot tokens configured — skipping Telegram startup")
        return

    apps = build_applications()

    if not apps:
        logger.warning("No bot applications built — check your tokens")
        return

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            for i, app in enumerate(apps):
                await app.initialize()
                await app.start()
                await app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES,
                )
                logger.info(f"Bot {i + 1}/{len(apps)} polling started")
            logger.info(f"All {len(apps)} bot(s) started polling")
            return  # Success — exit
        except Exception as e:
            logger.warning(f"Attempt {attempt}/{max_retries} failed: {e}")
            # Clean up partially started apps before retrying
            for app in apps:
                try:
                    if app.updater and app.updater.running:
                        await app.updater.stop()
                    if app.running:
                        await app.stop()
                    await app.shutdown()
                except Exception:
                    pass
            if attempt < max_retries:
                logger.info(f"Retrying in 3 seconds...")
                await asyncio.sleep(3)
            else:
                raise  # Re-raise on final attempt


async def stop_polling():
    """Stop all bot applications."""
    for app in applications:
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
