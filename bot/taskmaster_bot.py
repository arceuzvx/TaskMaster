"""
TASKMASTER — AI Accountability Telegram Bot
Upgraded from Group Organizer Bot.
Handles task management, midnight alerts, daily summaries, and Chrome Extension sync.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import google.generativeai as genai
from flask import Flask, request, jsonify
from threading import Thread

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    JobQueue,
)

from dotenv import load_dotenv
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

ADMIN_USER_ID = os.getenv("TELEGRAM_USER_ID")
if not ADMIN_USER_ID:
    raise ValueError("TELEGRAM_USER_ID environment variable not set!")

try:
    ADMIN_USER_ID = int(ADMIN_USER_ID)
except ValueError:
    raise ValueError("TELEGRAM_USER_ID must be a number!")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set!")

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")

# Active hours: bot responds 6AM to 12AM (midnight)
ACTIVE_HOUR_START = 6   # 6 AM
ACTIVE_HOUR_END   = 24  # 12 AM (midnight)

# Inactivity threshold (minutes) — used for reference/logging
INACTIVITY_THRESHOLD_MINS = 15

DATA_DIR  = Path("data")
DATA_DIR.mkdir(exist_ok=True)

TASKS_FILE   = DATA_DIR / "tasks.json"
SUMMARY_FILE = DATA_DIR / "summary.json"

# Flask app for Chrome Extension sync API
flask_app = Flask(__name__)

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATA HELPERS
# ============================================================================

def load_json(filepath: Path, default=None):
    if default is None:
        default = {}
    if filepath.exists():
        try:
            content = filepath.read_text(encoding="utf-8").strip()
            return json.loads(content) if content else default
        except Exception as e:
            logger.warning(f"Error reading {filepath}: {e}")
            return default
    return default


def save_json(filepath: Path, data):
    filepath.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_tasks() -> Dict:
    """
    Task store structure:
    {
      "date": "YYYY-MM-DD",
      "tasks": [
        {
          "id": 1,
          "name": "Write Dockerfile",
          "minutes": 45,
          "status": "pending" | "done" | "missed" | "postponed",
          "source": "telegram" | "extension",
          "added_at": "ISO datetime",
          "done_at": "ISO datetime" | null,
          "laptop_seen": false   -- did extension ever come online today?
        }
      ]
    }
    """
    data = load_json(TASKS_FILE, {"date": _today(), "tasks": []})
    # Roll over if it's a new day
    if data.get("date") != _today():
        data = _rollover(data)
    return data


def save_tasks(data: Dict):
    save_json(TASKS_FILE, data)


def load_summary() -> Dict:
    return load_json(SUMMARY_FILE, {})


def save_summary(data: Dict):
    save_json(SUMMARY_FILE, data)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _rollover(old_data: Dict) -> Dict:
    """Carry postponed tasks to today, archive the rest."""
    new_tasks = []
    counter = 1
    for task in old_data.get("tasks", []):
        if task["status"] == "postponed":
            task["id"] = counter
            task["status"] = "pending"
            task["added_at"] = datetime.now().isoformat()
            task["done_at"] = None
            task["laptop_seen"] = False
            new_tasks.append(task)
            counter += 1
    return {"date": _today(), "tasks": new_tasks}


def _next_id(tasks: List[Dict]) -> int:
    return max((t["id"] for t in tasks), default=0) + 1


def _is_active_hours() -> bool:
    hour = datetime.now().hour
    return ACTIVE_HOUR_START <= hour < ACTIVE_HOUR_END


def _is_admin(update: Update) -> bool:
    return update.message.from_user.id == ADMIN_USER_ID


# ============================================================================
# GEMINI HELPERS
# ============================================================================

async def gemini_message(prompt: str) -> str:
    """Call Gemini and return text response."""
    try:
        response = await asyncio.to_thread(gemini.generate_content, prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return None


async def build_midnight_alert(pending_tasks: List[Dict], laptop_seen: bool) -> str:
    context = "laptop was never opened today" if not laptop_seen else "tasks were started but not finished"
    names = ", ".join(f'"{t["name"]}"' for t in pending_tasks)
    prompt = (
        f"You are TASKMASTER, a friendly-but-firm AI accountability agent. "
        f"It's midnight and the user still has {len(pending_tasks)} pending task(s): {names}. "
        f"Context: {context}. "
        f"Write a SHORT (2-3 sentences) midnight reminder. "
        f"Be direct and slightly firm but not rude. No bullet points. No markdown. "
        f"End with a nudge to at least mark them done or postpone honestly."
    )
    msg = await gemini_message(prompt)
    if not msg:
        names_plain = ", ".join(f'"{t["name"]}"' for t in pending_tasks)
        msg = f"Hey — it's midnight and you still have {len(pending_tasks)} task(s) pending: {names_plain}. Sort them out before you sleep."
    return msg


async def build_daily_summary(done: int, missed: int, postponed: int, total: int, laptop_seen: bool) -> str:
    prompt = (
        f"You are TASKMASTER. End of day summary for the user: "
        f"{done}/{total} tasks completed, {missed} missed, {postponed} postponed. "
        f"Laptop {'was' if laptop_seen else 'was NOT'} opened today. "
        f"Write a SHORT (2-3 sentences) end-of-day message. "
        f"Be honest — celebrate if they did well, be blunt if they didn't. "
        f"No bullet points. No markdown. Keep it punchy."
    )
    msg = await gemini_message(prompt)
    if not msg:
        msg = f"Day done. {done}/{total} tasks completed, {missed} missed, {postponed} postponed."
    return msg


# ============================================================================
# ACTIVE HOURS GATE
# ============================================================================

async def gate(update: Update) -> bool:
    """Returns True if message should be processed, False if outside active hours."""
    if not _is_active_hours():
        await update.message.reply_text(
            "🌙 I'm offline right now (12AM–6AM). Come back after 6AM!"
        )
        return False
    return True


# ============================================================================
# COMMAND HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update):
        return
    await update.message.reply_text(
        "👋 *TASKMASTER is running.*\n\n"
        "Commands:\n"
        "/addtask `<name> <minutes>` — Add a task\n"
        "/tasks — View today's tasks\n"
        "/done `<id>` — Mark task done\n"
        "/delete `<id>` — Delete a task\n"
        "/postpone `<id>` — Move to tomorrow\n"
        "/edit `<id> <new name> <new minutes>` — Edit task\n"
        "/summary — Get today's summary now\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def addtask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a task. Usage: /addtask Write Dockerfile 45"""
    if not await gate(update):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addtask <task name> <minutes>`\n"
            "Example: `/addtask Write Dockerfile 45`",
            parse_mode="Markdown",
        )
        return

    # Last arg should be minutes, everything before is the name
    try:
        minutes = int(context.args[-1])
        name = " ".join(context.args[:-1])
    except ValueError:
        await update.message.reply_text(
            "⚠️ Last argument must be minutes.\n"
            "Example: `/addtask Write Dockerfile 45`",
            parse_mode="Markdown",
        )
        return

    data = load_tasks()
    task = {
        "id": _next_id(data["tasks"]),
        "name": name,
        "minutes": minutes,
        "status": "pending",
        "source": "telegram",
        "added_at": datetime.now().isoformat(),
        "done_at": None,
        "laptop_seen": False,
    }
    data["tasks"].append(task)
    save_tasks(data)

    await update.message.reply_text(
        f"✅ Task added!\n\n"
        f"*#{task['id']}* — {name}\n"
        f"⏱ {minutes} minutes\n\n"
        f"Your laptop extension will sync this when you open it.",
        parse_mode="Markdown",
    )


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's task list."""
    if not await gate(update):
        return

    data = load_tasks()
    task_list = data["tasks"]

    if not task_list:
        await update.message.reply_text(
            "No tasks for today yet.\nUse `/addtask <name> <minutes>` to add one.",
            parse_mode="Markdown",
        )
        return

    status_emoji = {
        "pending": "⏳",
        "done": "✅",
        "missed": "❌",
        "postponed": "📅",
    }

    lines = [f"📋 *Tasks for {data['date']}*\n"]
    for t in task_list:
        emoji = status_emoji.get(t["status"], "•")
        lines.append(f"{emoji} *#{t['id']}* {t['name']} — {t['minutes']}min")
        if t["status"] == "done" and t.get("done_at"):
            done_time = datetime.fromisoformat(t["done_at"]).strftime("%H:%M")
            lines.append(f"   _Completed at {done_time}_")

    pending = sum(1 for t in task_list if t["status"] == "pending")
    done    = sum(1 for t in task_list if t["status"] == "done")
    lines.append(f"\n_{done} done, {pending} pending_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark a task as done. Usage: /done <id>"""
    if not await gate(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/done <task id>`\nExample: `/done 1`",
            parse_mode="Markdown",
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.")
        return

    data = load_tasks()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)

    if not task:
        await update.message.reply_text(f"Task #{task_id} not found.")
        return

    if task["status"] == "done":
        await update.message.reply_text(f"Task #{task_id} is already marked done ✅")
        return

    task["status"] = "done"
    task["done_at"] = datetime.now().isoformat()
    save_tasks(data)

    await update.message.reply_text(
        f"✅ *{task['name']}* marked as done.\n_Trusted. No screenshot needed._",
        parse_mode="Markdown",
    )


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a task. Usage: /delete <id>"""
    if not await gate(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/delete <task id>`\nExample: `/delete 2`",
            parse_mode="Markdown",
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.")
        return

    data = load_tasks()
    original_len = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]

    if len(data["tasks"]) == original_len:
        await update.message.reply_text(f"Task #{task_id} not found.")
        return

    save_tasks(data)
    await update.message.reply_text(f"🗑 Task #{task_id} deleted.")


async def postpone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Postpone a task to tomorrow. Usage: /postpone <id>"""
    if not await gate(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/postpone <task id>`\nExample: `/postpone 3`",
            parse_mode="Markdown",
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.")
        return

    data = load_tasks()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)

    if not task:
        await update.message.reply_text(f"Task #{task_id} not found.")
        return

    task["status"] = "postponed"
    save_tasks(data)

    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    await update.message.reply_text(
        f"📅 *{task['name']}* postponed to tomorrow ({tomorrow}).",
        parse_mode="Markdown",
    )


async def edit_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit a task. Usage: /edit <id> <new name> <new minutes>"""
    if not await gate(update):
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/edit <id> <new name> <new minutes>`\n"
            "Example: `/edit 1 Write better Dockerfile 60`",
            parse_mode="Markdown",
        )
        return

    try:
        task_id = int(context.args[0])
        minutes  = int(context.args[-1])
        name     = " ".join(context.args[1:-1])
    except ValueError:
        await update.message.reply_text(
            "First arg = task ID, last arg = minutes, middle = new name."
        )
        return

    data = load_tasks()
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)

    if not task:
        await update.message.reply_text(f"Task #{task_id} not found.")
        return

    old_name = task["name"]
    task["name"]    = name
    task["minutes"] = minutes
    save_tasks(data)

    await update.message.reply_text(
        f"✏️ Task #{task_id} updated.\n"
        f"_{old_name}_ → *{name}* ({minutes} min)",
        parse_mode="Markdown",
    )


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually request today's summary."""
    if not await gate(update):
        return
    await _send_summary(context, ADMIN_USER_ID)


# ============================================================================
# SCHEDULED JOBS
# ============================================================================

async def midnight_check(context: ContextTypes.DEFAULT_TYPE):
    """Runs at 11:55 PM — check for pending tasks and alert user."""
    data = load_tasks()
    pending = [t for t in data["tasks"] if t["status"] == "pending"]

    if not pending:
        logger.info("Midnight check: no pending tasks. All good.")
        return

    laptop_seen = any(t.get("laptop_seen", False) for t in data["tasks"])
    message = await build_midnight_alert(pending, laptop_seen)

    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"🌙 *Midnight Check*\n\n{message}",
            parse_mode="Markdown",
        )
        logger.info(f"Midnight alert sent. {len(pending)} pending tasks.")
    except Exception as e:
        logger.error(f"Failed to send midnight alert: {e}")


async def _send_summary(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Build and send the daily summary."""
    data = load_tasks()
    task_list = data["tasks"]

    if not task_list:
        await context.bot.send_message(
            chat_id=user_id,
            text="📊 No tasks were set today.",
        )
        return

    done_count      = sum(1 for t in task_list if t["status"] == "done")
    missed_count    = sum(1 for t in task_list if t["status"] == "missed")
    postponed_count = sum(1 for t in task_list if t["status"] == "postponed")
    total           = len(task_list)
    laptop_seen     = any(t.get("laptop_seen", False) for t in task_list)

    ai_message = await build_daily_summary(
        done_count, missed_count, postponed_count, total, laptop_seen
    )

    status_emoji = {"pending": "⏳", "done": "✅", "missed": "❌", "postponed": "📅"}
    lines = ["📊 *Daily Summary*\n", ai_message, "\n"]
    for t in task_list:
        lines.append(f"{status_emoji.get(t['status'], '•')} {t['name']} ({t['minutes']}min) — {t['status']}")

    lines.append(f"\n✅ {done_count}  ❌ {missed_count}  📅 {postponed_count}  total {total}")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="\n".join(lines),
            parse_mode="Markdown",
        )
        logger.info("Daily summary sent.")
    except Exception as e:
        logger.error(f"Failed to send daily summary: {e}")


async def end_of_day_summary(context: ContextTypes.DEFAULT_TYPE):
    """Runs at 11:00 PM — send end of day summary."""
    await _send_summary(context, ADMIN_USER_ID)


# ============================================================================
# FLASK API — Chrome Extension Sync
# ============================================================================
# The Chrome Extension hits these endpoints to stay in sync with the bot.
# Run Flask in a background thread alongside the Telegram bot.

@flask_app.route("/tasks", methods=["GET"])
def api_get_tasks():
    """Extension fetches today's task list."""
    data = load_tasks()
    return jsonify(data)


@flask_app.route("/tasks/complete", methods=["POST"])
def api_complete_task():
    """
    Extension reports a task as completed (after screenshot verification).
    Body: { "id": 1, "verified": true }
    """
    body = request.get_json(silent=True)
    if not body or "id" not in body:
        return jsonify({"error": "Missing task id"}), 400

    data = load_tasks()
    task = next((t for t in data["tasks"] if t["id"] == body["id"]), None)

    if not task:
        return jsonify({"error": "Task not found"}), 404

    task["status"]  = "done"
    task["done_at"] = datetime.now().isoformat()
    task["laptop_seen"] = True
    save_tasks(data)

    return jsonify({"ok": True, "task": task})


@flask_app.route("/tasks/laptop-ping", methods=["POST"])
def api_laptop_ping():
    """
    Extension sends this on startup to mark that the laptop was opened today.
    Body: {} (empty is fine)
    """
    data = load_tasks()
    for task in data["tasks"]:
        task["laptop_seen"] = True
    save_tasks(data)
    return jsonify({"ok": True, "date": data["date"]})


@flask_app.route("/tasks/add", methods=["POST"])
def api_add_task():
    """
    Extension adds a task directly (if user adds from extension).
    Body: { "name": "Write Dockerfile", "minutes": 45 }
    """
    body = request.get_json(silent=True)
    if not body or "name" not in body or "minutes" not in body:
        return jsonify({"error": "Missing name or minutes"}), 400

    data = load_tasks()
    task = {
        "id": _next_id(data["tasks"]),
        "name": body["name"],
        "minutes": int(body["minutes"]),
        "status": "pending",
        "source": "extension",
        "added_at": datetime.now().isoformat(),
        "done_at": None,
        "laptop_seen": True,
    }
    data["tasks"].append(task)
    save_tasks(data)

    return jsonify({"ok": True, "task": task})


@flask_app.route("/alerts/pause", methods=["POST"])
def api_pause_alert():
    """
    Extension fires this when pause exceeds 15 minutes.
    Body: { "taskName": "...", "pausedMins": 18, "remainingMins": 42 }
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Missing body"}), 400

    task_name     = body.get("taskName", "your task")
    paused_mins   = body.get("pausedMins", 0)
    remaining_mins = body.get("remainingMins", 0)

    msg = (
        f"⏸ *Long pause detected!*\n\n"
        f"You've been paused for *{paused_mins} minutes* on: _{task_name}_\n"
        f"Time remaining on task: *{remaining_mins} min*\n\n"
        f"Get back to it or mark it done via /done or postpone via /postpone."
    )

    # Send async via a thread since Flask is sync
    import threading
    def send():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            _send_telegram_message(msg)
        )
        loop.close()
    threading.Thread(target=send, daemon=True).start()

    return jsonify({"ok": True})


async def _send_telegram_message(text: str):
    """Send a plain message to admin via bot."""
    try:
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=ADMIN_USER_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send telegram message: {e}")


def run_flask():
    """Run Flask in background thread."""
    flask_app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


# ============================================================================
# MAIN
# ============================================================================

def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .build()
    )

    # Command handlers
    application.add_handler(CommandHandler("start",    start))
    application.add_handler(CommandHandler("help",     help_command))
    application.add_handler(CommandHandler("addtask",  addtask))
    application.add_handler(CommandHandler("tasks",    tasks))
    application.add_handler(CommandHandler("done",     done))
    application.add_handler(CommandHandler("delete",   delete))
    application.add_handler(CommandHandler("postpone", postpone))
    application.add_handler(CommandHandler("edit",     edit_task))
    application.add_handler(CommandHandler("summary",  summary))

    # Schedule midnight check at 23:55 daily
    application.job_queue.run_daily(
        midnight_check,
        time=datetime.strptime("23:55", "%H:%M").time(),
        name="midnight_check",
    )

    # Schedule end of day summary at 23:00 daily
    application.job_queue.run_daily(
        end_of_day_summary,
        time=datetime.strptime("23:00", "%H:%M").time(),
        name="end_of_day_summary",
    )

    # Start Flask API in background thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask API running on port 5000")

    logger.info("TASKMASTER bot starting...")
    logger.info(f"Admin User ID: {ADMIN_USER_ID}")
    logger.info(f"Active hours: {ACTIVE_HOUR_START}:00 — {ACTIVE_HOUR_END}:00")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()