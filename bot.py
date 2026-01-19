"""
Telegram Group Organizer Bot
A local bot for extracting content, organizing lists, and setting reminders.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Get bot token from environment variable
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN environment variable not set!\n"
        "Set it with: export TELEGRAM_BOT_TOKEN='your_token_here'"
    )

# Get user ID from environment variable
ADMIN_USER_ID = os.getenv("TELEGRAM_USER_ID")
if not ADMIN_USER_ID:
    raise ValueError(
        "TELEGRAM_USER_ID environment variable not set!\n"
        "Set it with: export TELEGRAM_USER_ID='your_user_id'"
    )

# Convert user ID to integer
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID)
except ValueError:
    raise ValueError("TELEGRAM_USER_ID must be a number!")

# Directories for storage
IMAGES_DIR = Path("images")
DOCS_DIR = Path("documents")
DATA_DIR = Path("data")

# Data files
LINKS_FILE = DATA_DIR / "links.json"
LISTS_FILE = DATA_DIR / "lists.json"
REMINDERS_FILE = DATA_DIR / "reminders.json"

# ============================================================================
# SETUP
# ============================================================================

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create necessary directories
IMAGES_DIR.mkdir(exist_ok=True)
DOCS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ============================================================================
# DATA MANAGEMENT
# ============================================================================

def load_json(filepath: Path, default=None):
    """Load JSON data from file."""
    if default is None:
        default = {}
    if filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:  # Empty file
                    return default
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in {filepath}: {e}. Using default value.")
            return default
        except Exception as e:
            logger.error(f"Error reading {filepath}: {e}. Using default value.")
            return default
    return default

def save_json(filepath: Path, data):
    """Save data to JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_links() -> List[Dict]:
    """Load stored links."""
    return load_json(LINKS_FILE, [])

def save_links(links: List[Dict]):
    """Save links to file."""
    save_json(LINKS_FILE, links)

def load_lists() -> Dict:
    """Load user-created lists."""
    return load_json(LISTS_FILE, {})

def save_lists(lists: Dict):
    """Save lists to file."""
    save_json(LISTS_FILE, lists)

def load_reminders() -> List[Dict]:
    """Load reminders."""
    return load_json(REMINDERS_FILE, [])

def save_reminders(reminders: List[Dict]):
    """Save reminders to file."""
    save_json(REMINDERS_FILE, reminders)

# ============================================================================
# MESSAGE HANDLERS
# ============================================================================

async def track_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track links, images, and documents from group messages."""
    if not update.message:
        return
    
    message = update.message
    
    # Extract links from message text
    if message.text and message.entities:
        for entity in message.entities:
            if entity.type == "url":
                url = message.text[entity.offset:entity.offset + entity.length]
                links = load_links()
                links.append({
                    "url": url,
                    "from_user": message.from_user.username or message.from_user.first_name,
                    "date": message.date.isoformat(),
                    "message_id": message.message_id
                })
                save_links(links)
    
    # Track images
    if message.photo:
        # Images are tracked but downloaded on demand via /extract_images
        pass
    
    # Track documents
    if message.document:
        # Documents are tracked but downloaded on demand via /extract_docs
        pass

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    welcome_message = """
🤖 **Group Organizer Bot**

I help you organize group content!

**What I can do:**
• Extract and list all links shared in the group
• Download and organize images and documents
• Create custom lists for organizing information
• Set reminders that I'll send you via DM

**Quick Commands:**
• `/help` - See all available commands
• `/extract_links` - Get all shared links
• `/create_list <name>` - Create a new list

Add me to your group and let's get organized! 🚀
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = """
📚 **Available Commands**

**Extraction Commands:**
• `/extract_links` - Show all links posted in the group
• `/extract_images` - Download all images to local folder
• `/extract_docs` - Download all documents to local folder

**Organization Commands:**
• `/create_list <name>` - Create a new list
  Example: `/create_list resources`
  
• `/add_to_list <name> <content>` - Add item to a list
  Example: `/add_to_list resources https://example.com`
  
• `/show_list <name>` - Display a list
  Example: `/show_list resources`

**Reminder Commands:**
• `/remind <time> <message>` - Set a reminder
  Examples:
  - `/remind 2h Check links` (2 hours from now)
  - `/remind 30m Review docs` (30 minutes)
  - `/remind 2026-01-25 18:00 Meeting` (specific date/time)

**Notes:**
• Reminders are sent to you via DM
• All content is stored locally
• The bot tracks content from when it was added to the group
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def extract_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /extract_links command."""
    links = load_links()
    
    if not links:
        await update.message.reply_text("No links have been shared yet!")
        return
    
    message = "🔗 **Extracted Links:**\n\n"
    for i, link_data in enumerate(links, 1):
        message += f"{i}. {link_data['url']}\n"
        message += f"   _Posted by {link_data['from_user']} on {link_data['date'][:10]}_\n\n"
    
    # Telegram has message length limits, so split if needed
    if len(message) > 4000:
        await update.message.reply_text("Too many links! Sending in parts...")
        for i in range(0, len(message), 4000):
            await update.message.reply_text(message[i:i+4000], parse_mode='Markdown')
    else:
        await update.message.reply_text(message, parse_mode='Markdown')

async def extract_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /extract_images command - show summary of downloaded images."""
    image_files = list(IMAGES_DIR.glob("*.jpg")) + list(IMAGES_DIR.glob("*.png"))
    
    if not image_files:
        await update.message.reply_text(
            "📷 No images downloaded yet!\n\n"
            "Images are automatically saved when posted in the group.\n"
            "The bot only saves images posted after it was started."
        )
        return
    
    # Sort by modification time (newest first)
    image_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    
    message = f"🖼️ **Downloaded Images** ({len(image_files)} total)\n\n"
    message += f"📁 Location: `{IMAGES_DIR.absolute()}`\n\n"
    
    # Show recent images
    recent_count = min(10, len(image_files))
    message += f"**Most recent {recent_count}:**\n"
    for img in image_files[:recent_count]:
        size_mb = img.stat().st_size / (1024 * 1024)
        message += f"• {img.name} ({size_mb:.2f} MB)\n"
    
    if len(image_files) > 10:
        message += f"\n_...and {len(image_files) - 10} more_"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def extract_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /extract_docs command - show summary of downloaded documents."""
    doc_count = 0
    by_type = {}
    
    # Count documents by type
    for subfolder in DOCS_DIR.iterdir():
        if subfolder.is_dir():
            files = list(subfolder.glob("*"))
            if files:
                by_type[subfolder.name] = len(files)
                doc_count += len(files)
    
    if doc_count == 0:
        await update.message.reply_text(
            "📄 No documents downloaded yet!\n\n"
            "Documents are automatically saved when posted in the group.\n"
            "The bot only saves documents posted after it was started."
        )
        return
    
    message = f"📄 **Downloaded Documents** ({doc_count} total)\n\n"
    message += f"📁 Location: `{DOCS_DIR.absolute()}`\n\n"
    message += "**By type:**\n"
    
    for doc_type, count in sorted(by_type.items()):
        message += f"• {doc_type}: {count} file(s)\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def create_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /create_list command."""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/create_list <list_name>`\n"
            "Example: `/create_list resources`",
            parse_mode='Markdown'
        )
        return
    
    list_name = context.args[0].lower()
    lists = load_lists()
    
    if list_name in lists:
        await update.message.reply_text(f"List '{list_name}' already exists!")
        return
    
    lists[list_name] = []
    save_lists(lists)
    
    await update.message.reply_text(
        f"✅ Created list: **{list_name}**\n"
        f"Use `/add_to_list {list_name} <content>` to add items.",
        parse_mode='Markdown'
    )

async def add_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add_to_list command."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/add_to_list <list_name> <content>`\n"
            "Example: `/add_to_list resources https://example.com`",
            parse_mode='Markdown'
        )
        return
    
    list_name = context.args[0].lower()
    content = ' '.join(context.args[1:])
    
    lists = load_lists()
    
    if list_name not in lists:
        await update.message.reply_text(
            f"List '{list_name}' doesn't exist!\n"
            f"Create it first with `/create_list {list_name}`",
            parse_mode='Markdown'
        )
        return
    
    lists[list_name].append({
        "content": content,
        "added_by": update.message.from_user.username or update.message.from_user.first_name,
        "date": datetime.now().isoformat()
    })
    save_lists(lists)
    
    await update.message.reply_text(
        f"✅ Added to **{list_name}**:\n{content}",
        parse_mode='Markdown'
    )

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /show_list command."""
    if not context.args:
        # Show all available lists
        lists = load_lists()
        if not lists:
            await update.message.reply_text("No lists created yet!")
            return
        
        message = "📋 **Available Lists:**\n\n"
        for name, items in lists.items():
            message += f"• **{name}** ({len(items)} items)\n"
        message += f"\nUse `/show_list <name>` to view a specific list."
        
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    list_name = context.args[0].lower()
    lists = load_lists()
    
    if list_name not in lists:
        await update.message.reply_text(f"List '{list_name}' not found!")
        return
    
    items = lists[list_name]
    if not items:
        await update.message.reply_text(f"List **{list_name}** is empty!", parse_mode='Markdown')
        return
    
    message = f"📋 **List: {list_name}**\n\n"
    for i, item in enumerate(items, 1):
        message += f"{i}. {item['content']}\n"
        message += f"   _Added by {item['added_by']}_\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remind command."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/remind <time> <message>`\n\n"
            "Examples:\n"
            "• `/remind 2h Check links`\n"
            "• `/remind 30m Review docs`\n"
            "• `/remind 1m Test` (for testing)\n"
            "• `/remind 30s Quick test` (30 seconds)\n"
            "• `/remind 2026-01-25 18:00 Meeting`",
            parse_mode='Markdown'
        )
        return
    
    time_str = context.args[0]
    message_text = ' '.join(context.args[1:])
    
    # Check job queue
    if not context.job_queue:
        await update.message.reply_text("❌ Job queue not available! Reminders won't work.")
        logger.error("Job queue is None!")
        return
    
    # Parse time
    try:
        remind_time = parse_time(time_str)
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid time format: {e}")
        return
    
    # Check if time is in the past
    if remind_time <= datetime.now():
        await update.message.reply_text(
            f"❌ That time is in the past!\n"
            f"Parsed as: {remind_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return
    
    # Get user who set the reminder (not necessarily admin)
    user_id = update.message.from_user.id
    
    # Store reminder
    reminders = load_reminders()
    reminder_data = {
        "time": remind_time.isoformat(),
        "message": message_text,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
        "triggered": False
    }
    reminders.append(reminder_data)
    save_reminders(reminders)
    
    seconds_until = (remind_time - datetime.now()).total_seconds()
    logger.info(f"Setting reminder for {remind_time} (in {seconds_until} seconds)")
    logger.info(f"Will send to user ID: {user_id}")
    
    # Schedule the reminder
    try:
        job = context.job_queue.run_once(
            send_reminder,
            when=seconds_until,
            data={
                "message": message_text, 
                "user_id": user_id,
                "reminder_index": len(reminders) - 1
            },
            name=f"reminder_{len(reminders)}"
        )
        
        time_until = remind_time - datetime.now()
        hours = int(time_until.total_seconds() // 3600)
        minutes = int((time_until.total_seconds() % 3600) // 60)
        seconds = int(time_until.total_seconds() % 60)
        
        if hours > 0:
            time_desc = f"{hours}h {minutes}m"
        elif minutes > 0:
            time_desc = f"{minutes}m {seconds}s"
        else:
            time_desc = f"{seconds}s"
        
        await update.message.reply_text(
            f"⏰ Reminder set!\n"
            f"📅 Time: {remind_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"⏱️ In: {time_desc}\n"
            f"💬 Message: {message_text}\n"
            f"👤 Will DM user ID: {user_id}\n\n"
            f"✅ Job scheduled: {job.name}"
        )
        logger.info(f"Reminder scheduled successfully: {job.name}")
    except Exception as e:
        logger.error(f"Failed to schedule reminder: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Failed to schedule reminder: {e}")

def parse_time(time_str: str) -> datetime:
    """Parse time string into datetime object."""
    # Try relative time first (e.g., "2h", "30m", "45s")
    if time_str[-1] in ['h', 'm', 'd', 's']:
        unit = time_str[-1]
        try:
            value = int(time_str[:-1])
        except ValueError:
            raise ValueError("Invalid time format")
        
        now = datetime.now()
        if unit == 'h':
            return now + timedelta(hours=value)
        elif unit == 'm':
            return now + timedelta(minutes=value)
        elif unit == 's':
            return now + timedelta(seconds=value)
        elif unit == 'd':
            return now + timedelta(days=value)
    
    # Try absolute time (e.g., "2026-01-25 18:00")
    try:
        return datetime.fromisoformat(time_str.replace(' ', 'T'))
    except ValueError:
        pass
    
    # Try just time today (e.g., "18:00")
    try:
        time_obj = datetime.strptime(time_str, '%H:%M').time()
        today = datetime.now().date()
        result = datetime.combine(today, time_obj)
        if result < datetime.now():
            # If time has passed today, schedule for tomorrow
            result += timedelta(days=1)
        return result
    except ValueError:
        pass
    
    raise ValueError(
        "Use format: 2h, 30m, 45s, 3d, YYYY-MM-DD HH:MM, or HH:MM"
    )

async def check_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check_reminders command - show pending reminders."""
    reminders = load_reminders()
    
    if not reminders:
        await update.message.reply_text("No reminders set!")
        return
    
    now = datetime.now()
    pending = []
    triggered = []
    
    for i, reminder in enumerate(reminders):
        remind_time = datetime.fromisoformat(reminder["time"])
        if reminder.get("triggered", False):
            triggered.append((i, reminder, remind_time))
        elif remind_time > now:
            pending.append((i, reminder, remind_time))
    
    message = "⏰ **Reminders Status**\n\n"
    
    if pending:
        message += f"**Pending ({len(pending)}):**\n"
        for i, reminder, remind_time in pending:
            time_until = remind_time - now
            hours = int(time_until.total_seconds() // 3600)
            minutes = int((time_until.total_seconds() % 3600) // 60)
            seconds = int(time_until.total_seconds() % 60)
            
            if hours > 0:
                time_desc = f"{hours}h {minutes}m"
            elif minutes > 0:
                time_desc = f"{minutes}m {seconds}s"
            else:
                time_desc = f"{seconds}s"
            
            message += f"• {remind_time.strftime('%m/%d %H:%M:%S')} (in {time_desc})\n"
            message += f"  _{reminder['message']}_\n\n"
    
    if triggered:
        message += f"**Triggered ({len(triggered)}):**\n"
        for i, reminder, remind_time in triggered[:5]:  # Show last 5
            message += f"• {remind_time.strftime('%m/%d %H:%M:%S')}\n"
            message += f"  _{reminder['message']}_\n\n"
    
    if not pending and not triggered:
        message += "All reminders are in the past (expired)."
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send reminder via DM."""
    job = context.job
    message = job.data["message"]
    user_id = job.data["user_id"]
    
    logger.info(f"Attempting to send reminder to user {user_id}: {message}")
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⏰ Reminder\n\n{message}"
        )
        logger.info(f"✅ Reminder sent successfully to user {user_id}")
        
        # Mark reminder as triggered
        if "reminder_index" in job.data:
            reminders = load_reminders()
            if job.data["reminder_index"] < len(reminders):
                reminders[job.data["reminder_index"]]["triggered"] = True
                save_reminders(reminders)
                
    except Exception as e:
        logger.error(f"❌ Failed to send reminder: {e}")
        logger.error(f"User ID: {user_id}, Message: {message}")
        # Try to send error to the same user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ Reminder delivery failed: {e}\nOriginal message: {message}"
            )
        except:
            logger.error("Could not send error notification either")

async def download_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download photos posted in the group."""
    if not update.message or not update.message.photo:
        return
    
    try:
        photo = update.message.photo[-1]  # Get highest resolution
        file = await photo.get_file()
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        user = update.message.from_user.username or update.message.from_user.first_name
        filename = f"{timestamp}_{user}_{photo.file_id[:8]}.jpg"
        filepath = IMAGES_DIR / filename
        
        await file.download_to_drive(filepath)
        logger.info(f"Downloaded image: {filename}")
    except Exception as e:
        logger.error(f"Failed to download photo: {e}")

async def download_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download documents posted in the group."""
    if not update.message or not update.message.document:
        return
    
    try:
        document = update.message.document
        file = await document.get_file()
        
        # Get file extension
        filename = document.file_name or f"{document.file_id}.bin"
        extension = Path(filename).suffix.lower()
        
        # Create subfolder by file type
        if extension in ['.pdf']:
            subfolder = DOCS_DIR / "pdf"
        elif extension in ['.docx', '.doc']:
            subfolder = DOCS_DIR / "word"
        elif extension in ['.xlsx', '.xls']:
            subfolder = DOCS_DIR / "excel"
        elif extension in ['.pptx', '.ppt']:
            subfolder = DOCS_DIR / "powerpoint"
        else:
            subfolder = DOCS_DIR / "other"
        
        subfolder.mkdir(exist_ok=True)
        
        # Add timestamp to avoid name conflicts
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_parts = filename.rsplit('.', 1)
        if len(name_parts) == 2:
            new_filename = f"{timestamp}_{name_parts[0]}.{name_parts[1]}"
        else:
            new_filename = f"{timestamp}_{filename}"
        
        filepath = subfolder / new_filename
        await file.download_to_drive(filepath)
        logger.info(f"Downloaded document: {new_filename} to {subfolder.name}/")
    except Exception as e:
        logger.error(f"Failed to download document: {e}")

# ============================================================================
# MAIN
# ============================================================================

async def load_pending_reminders(application):
    """Load and schedule pending reminders on startup."""
    if not application.job_queue:
        logger.warning("Job queue not available, skipping reminder loading")
        return
    
    reminders = load_reminders()
    now = datetime.now()
    
    for i, reminder in enumerate(reminders):
        if reminder.get("triggered", False):
            continue  # Skip already triggered reminders
            
        remind_time = datetime.fromisoformat(reminder["time"])
        if remind_time > now:
            application.job_queue.run_once(
                send_reminder,
                when=remind_time,
                data={
                    "message": reminder["message"], 
                    "user_id": reminder["user_id"],
                    "reminder_index": i
                },
                name=f"reminder_{i}"
            )
            logger.info(f"Scheduled reminder for {remind_time}")

def main():
    """Start the bot."""
    # Create application with job queue explicitly enabled
    from telegram.ext import JobQueue
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .job_queue(JobQueue())
        .build()
    )
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("extract_links", extract_links))
    application.add_handler(CommandHandler("extract_images", extract_images))
    application.add_handler(CommandHandler("extract_docs", extract_docs))
    application.add_handler(CommandHandler("create_list", create_list))
    application.add_handler(CommandHandler("add_to_list", add_to_list))
    application.add_handler(CommandHandler("show_list", show_list))
    application.add_handler(CommandHandler("remind", remind))
    application.add_handler(CommandHandler("check_reminders", check_reminders))
    
    # Add message handlers for tracking content
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, track_content
    ))
    application.add_handler(MessageHandler(filters.PHOTO, download_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, download_document))
    
    # Set up post_init to load pending reminders
    application.post_init = load_pending_reminders
    
    # Start bot
    logger.info("Bot starting...")
    logger.info(f"Admin User ID: {ADMIN_USER_ID}")
    logger.info(f"Job queue available: {application.job_queue is not None}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()