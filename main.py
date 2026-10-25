import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("evilgpt")

# This bot is a general-purpose chat assistant. It does not provide instructions
# for malware, credential theft, phishing, or evading security controls.
SYSTEM_PROMPT = """You are EvilGPT, a witty, informal, multilingual chat assistant.
Reply in the language used by the user, including Hindi/Hinglish when appropriate.
Be helpful, accurate, and conversational. Do not claim you performed actions you
did not perform. Do not provide instructions that facilitate cyber abuse, malware,
credential theft, phishing, or evasion of security controls. Offer safe defensive
or educational alternatives when relevant."""

LLM_API_URL = os.getenv("LLM_API_URL", "http://127.0.0.1:8080/v1/chat/completions").strip().rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-oss-20b").strip()
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
MAX_HISTORY_MESSAGES = 12
MAX_TELEGRAM_CHARS = 4000


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Hey! I'm online. Send me a message to chat. Use /reset to clear our conversation. 💀🔥"
        )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("history", None)
    if update.effective_message:
        await update.effective_message.reply_text("Conversation cleared. Start fresh! 🔥")


def ask_local_model(history: list[dict[str, str]]) -> str:
    """Call the local llama.cpp OpenAI-compatible HTTP endpoint."""
    if not LLM_API_URL:
        raise RuntimeError("LLM_API_URL is not configured.")

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 700,
    }
    request = urllib.request.Request(
        LLM_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Local model server returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach local llama.cpp server at {LLM_API_URL}: {exc}") from exc

    answer = (result.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    if not answer:
        raise RuntimeError("Local model server returned an empty response.")
    return answer


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    history = context.user_data.setdefault("history", [])
    history.append({"role": "user", "content": message.text})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    try:
        answer = await asyncio.to_thread(ask_local_model, history)
    except Exception as exc:
        logger.exception("Message generation failed")
        await message.reply_text(f"Sorry, I couldn't get a reply from the AI server.\n\nDetails: {exc}")
        history.pop()
        return

    history.append({"role": "assistant", "content": answer})
    history[:] = history[-MAX_HISTORY_MESSAGES:]

    # Telegram message limit is 4096 characters; leave some room.
    for start_index in range(0, len(answer), MAX_TELEGRAM_CHARS):
        await message.reply_text(answer[start_index : start_index + MAX_TELEGRAM_CHARS])


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from GitHub Actions Secrets.")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Starting Telegram bot; local model=%s; endpoint=%s", LLM_MODEL, LLM_API_URL)
    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
