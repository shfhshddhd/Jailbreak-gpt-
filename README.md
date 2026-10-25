# EvilGPT Telegram Bot

A Telegram conversational bot powered by Ollama. It keeps the existing /start, /reset, and normal text-message flow, with a darker witty style that becomes professional for serious questions.

## Current architecture

- Telegram interface: python-telegram-bot
- Local inference API: Ollama
- Default model: qwen3:4b-instruct-2507-q4_K_M
- Recent conversation memory: SQLite, isolated by Telegram user ID
- Error handling: user-friendly Telegram errors and detailed server-side logs
- Tests: Python's built-in unittest

## GitHub Actions configuration

Add this repository secret:

- TELEGRAM_BOT_TOKEN: your Telegram bot token

Optional repository variable:

- OLLAMA_MODEL: override the model. The default is qwen3:4b-instruct-2507-q4_K_M.

Run the Run EvilGPT Bot workflow manually from the Actions tab. The workflow downloads the model each time a new runner starts, so cold starts take time.

## Memory limitation to understand

SQLite memory is stored in data/conversations.sqlite3. It survives normal messages while that file remains on the same machine. A fresh GitHub-hosted Actions runner has a clean filesystem, so memory does not automatically carry across a runner restart or the next workflow run. For durable cross-restart memory, deploy on a persistent machine or connect a private persistent database; do not store private chats in a public Git repository or commit database files.

The /reset command clears the current user's stored conversation history.

## Local checks

Install dependencies, then run:

    python -m py_compile main.py
    python -m unittest discover -s tests -v

For local operation, set TELEGRAM_BOT_TOKEN, OLLAMA_HOST, and optionally OLLAMA_MODEL, then run python main.py.

## Resource and reliability notes

GitHub-hosted runners are temporary CI machines, not a dedicated always-on AI server. Model download and CPU inference can be slow, and a successful code/test run does not guarantee uninterrupted Telegram availability. A persistent host with enough RAM and a persistent disk is the better long-term option.
