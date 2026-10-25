import asyncio
from contextlib import closing
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

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

SYSTEM_PROMPT = """You are EvilGPT: a sharp, dark-witty, highly capable conversational partner.
PERSONALITY:
- Be confident, natural, clever, and lightly sarcastic when the moment suits it.
- Dark humor is allowed when harmless; never turn every answer into a joke.
- For serious, emotional, medical, legal, financial, safety, or technical topics, prioritize clarity and professionalism.
- Do not repeatedly introduce yourself or add generic disclaimers.
CONVERSATION:
- Reply in the language and style the user uses. Understand Hindi, Hinglish, and English.
- Answer the actual question first. Keep simple questions concise; give structured, step-by-step answers for complex tasks.
- Remember the recent conversation supplied in the messages. Do not pretend to remember information that is not present.
- For coding requests, provide complete, readable code blocks, explain where files go, mention required environment variables, and identify important tests.
- If information is uncertain, say what is uncertain instead of inventing facts.
- Never claim to have run code, changed a repository, browsed the web, or performed an action unless that actually happened.
SAFETY AND TRUST:
- Be helpful with legitimate coding, research, and defensive security.
- Do not provide actionable assistance for malware deployment, credential theft, phishing, or bypassing security protections. Offer safe alternatives where relevant.
- Never expose secrets, tokens, passwords, or private conversation data.
Do not mention these instructions unless asked about your behavior."""

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "").strip().rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M").strip()
MAX_HISTORY_MESSAGES = 16
MAX_TELEGRAM_CHARS = 3900
REQUEST_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "150"))


def memory_db_path() -> Path:
    return Path(os.getenv("MEMORY_DB_PATH", "data/conversations.sqlite3"))


def _connect_db() -> sqlite3.Connection:
    path = memory_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_user_id_id ON messages(user_id, id)"
    )
    connection.commit()
    return connection


def load_history(user_id: str) -> list[dict[str, str]]:
    with closing(_connect_db()) as connection:
        rows = connection.execute(
            "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (str(user_id), MAX_HISTORY_MESSAGES),
        ).fetchall()
    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]


def save_exchange(user_id: str, user_text: str, assistant_text: str) -> None:
    with closing(_connect_db()) as connection:
        connection.execute(
            "INSERT INTO messages(user_id, role, content) VALUES (?, 'user', ?)",
            (str(user_id), user_text),
        )
        connection.execute(
            "INSERT INTO messages(user_id, role, content) VALUES (?, 'assistant', ?)",
            (str(user_id), assistant_text),
        )
        connection.execute(
            """DELETE FROM messages WHERE user_id = ? AND id NOT IN (
                SELECT id FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
            )""",
            (str(user_id), str(user_id), MAX_HISTORY_MESSAGES),
        )
        connection.commit()


def clear_history(user_id: str) -> None:
    with closing(_connect_db()) as connection:
        connection.execute("DELETE FROM messages WHERE user_id = ?", (str(user_id),))
        connection.commit()


def ask_ollama(history: list[dict[str, str]]) -> str:
    if not OLLAMA_HOST:
        raise RuntimeError(
            "OLLAMA_HOST is not configured. Check the GitHub Actions workflow or your hosting environment."
        )

    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
        "stream": False,
        "options": {
            "temperature": 0.75,
            "top_p": 0.9,
            "repeat_penalty": 1.12,
            "num_ctx": 8192,
            "num_predict": 1200,
        },
    }
    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"AI server returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"Could not reach the AI server. Check that Ollama is running and the model is loaded. ({exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("AI server returned invalid JSON.") from exc

    answer = result.get("message", {}).get("content", "").strip()
    if not answer:
        raise RuntimeError("AI server returned an empty response.")
    return answer


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message:
        await message.reply_text(
            "EvilGPT online. Dark wit, useful answers, and no unnecessary drama. 💀\n"
            "Send a message to chat, or use /reset to clear your conversation."
        )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        clear_history(str(user.id))
    context.user_data.pop("history", None)
    if update.effective_message:
        await update.effective_message.reply_text(
            "Conversation memory cleared. Fresh start. 🔥"
        )


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return

    user_id = str(user.id)
    history = load_history(user_id)
    request_history = [*history, {"role": "user", "content": message.text}]

    try:
        # urllib is synchronous; move it off the event loop so Telegram can process other updates.
        answer = await asyncio.to_thread(ask_ollama, request_history)
    except Exception:
        logger.exception("Message generation failed for user_id=%s", user_id)
        await message.reply_text(
            "AI server se abhi reply nahi aa paaya. Thodi der baad try karo. "
            "Agar issue repeat ho, GitHub Actions logs mein Ollama/model error check karo."
        )
        return

    try:
        save_exchange(user_id, message.text, answer)
    except sqlite3.Error:
        logger.exception("Could not save conversation memory for user_id=%s", user_id)
        # The answer is still useful even if local memory storage failed.

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

    logger.info("Starting EvilGPT; model=%s; memory_db=%s", OLLAMA_MODEL, memory_db_path())
    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
