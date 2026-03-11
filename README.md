# TASKMASTER

An AI-powered personal accountability agent built as a Chrome Extension with a Telegram bot backend. It watches your work sessions, tracks what sites you visit, takes random screenshots during tasks, and uses Gemini to verify you actually did the work before letting you mark a task as done.

---

## What It Does

- Tracks active work time per task, excluding pauses
- Monitors which websites you visit during a task session
- Takes random mid-task screenshots to catch off-task activity
- Sends all evidence to Gemini for verification when you mark a task done
- Blocks task completion if you have not worked the minimum required time
- Pokes you via popup if you go inactive for too long
- Sends a Telegram alert if you pause for more than 15 minutes
- Lets you add tasks from your phone via Telegram before you open your laptop
- Syncs task state between the extension and the Telegram bot
- Sends a midnight alert and daily summary to Telegram

---

## Stack

| Component | Technology |
|---|---|
| Chrome Extension | HTML, CSS, JavaScript, Chrome Extension APIs (Manifest V3) |
| AI Verification | Google Gemini 2.5 Flash (free tier) |
| Telegram Bot | Python, python-telegram-bot |
| Sync API | Flask (runs alongside the bot) |
| Storage | chrome.storage.local + JSON flat files |
| Hosting | Railway free tier (bot only) |

---

## Project Structure

```
taskmaster/
├── bot/
│   ├── taskmaster_bot.py       Main bot + Flask API
│   ├── requirements.txt
│   ├── railway.toml            Railway deployment config
│   └── data/
│       └── tasks.json          Task state (auto-created)
└── extension/
    ├── manifest.json
    ├── background.js           Service worker: tracking, alarms, Gemini calls
    ├── content.js              Activity detection on pages
    ├── popup.html
    ├── popup.css
    ├── popup.js                UI logic
    └── icon.png
```

---

## Prerequisites

- Python 3.11+
- Google Chrome
- A Telegram account
- A Gemini API key (free at aistudio.google.com)
- A Telegram bot token (instructions below)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/taskmaster.git
cd taskmaster
```

### 2. Set up the bot

```bash
cd bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file inside the `bot/` folder:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_USER_ID=your_telegram_user_id_here
GEMINI_API_KEY=your_gemini_api_key_here
```

Run the bot locally:

```bash
python taskmaster_bot.py
```

You should see:

```
INFO - TASKMASTER bot starting...
INFO - Flask API running on port 5000
```

### 3. Set up the Chrome Extension

Open `extension/background.js` and add your Gemini API key on line 8:

```js
const GEMINI_API_KEY = "your_key_here";
```

Then load it in Chrome:

1. Go to `chrome://extensions`
2. Enable Developer mode (top right toggle)
3. Click Load unpacked
4. Select the `extension/` folder

Pin the extension to your toolbar.

---

## Getting Your Telegram User ID

Send a message to `@userinfobot` on Telegram. It will reply with your numeric user ID. Use that as `TELEGRAM_USER_ID` in your `.env` file.

---

## Creating a Telegram Bot with BotFather

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Choose a name for your bot, for example: `TASKMASTER`
4. Choose a username, it must end in `bot`, for example: `mytaskmaster_bot`
5. BotFather will reply with a token that looks like this:

```
1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
```

6. Copy that token and use it as `TELEGRAM_BOT_TOKEN` in your `.env` file
7. Start a conversation with your bot by searching for it on Telegram and sending `/start`

The bot will only respond to the user ID set in `TELEGRAM_USER_ID`. Messages from anyone else are ignored.

---

## Telegram Bot Commands

| Command | Description |
|---|---|
| `/addtask <name> <minutes>` | Add a task with estimated time |
| `/tasks` | View today's task list and status |
| `/done <id>` | Mark a task as done (trusted, no screenshot required) |
| `/delete <id>` | Delete a task |
| `/postpone <id>` | Move a task to tomorrow |
| `/edit <id> <new name> <new minutes>` | Edit a task |
| `/summary` | Get today's summary immediately |

Example:

```
/addtask Write Jenkins Dockerfile 45
/tasks
/done 1
```

---

## How Verification Works

When you click Done on a task in the extension, the following happens in order:

**Step 1 - Time check**

The extension checks how much time you actually worked (paused time excluded). Minimum thresholds:

| Task duration | Minimum required |
|---|---|
| Under 30 minutes | 50% |
| 30 to 120 minutes | 60% |
| Over 120 minutes | 70% |

If you have not met the threshold, the task is rejected immediately without involving Gemini.

**Step 2 - Evidence collection**

The extension collects:
- A final screenshot of your current tab
- Up to 2 random mid-task screenshots taken at unpredictable points during the session
- A breakdown of time spent per domain (e.g. youtube.com 18 min, notion.so 2 min)

**Step 3 - Gemini review**

All evidence is sent to Gemini with the task name and time data. Gemini looks at all screenshots together, not just the final one. If mid-task screenshots show clearly off-task activity, the task is rejected.

**Step 4 - Verdict**

- Approved: a Confirm Done button appears
- Rejected by time threshold: only a dismiss option, no override
- Rejected by Gemini: only a Try Again option, no override

There is no "mark done anyway" button. If the task is rejected and you want to drop it, delete it via `/delete` in Telegram.

---

## Privacy

Tracking only runs when Focus Mode is ON. Pausing immediately stops all tracking including domain time, screenshots, and activity detection. Nothing is tracked during a pause.

---

## Deploying the Bot to Railway

1. Push the `bot/` folder to a GitHub repository
2. Go to railway.app and create a new project from your repo
3. Add the following environment variables in Railway's dashboard:

```
TELEGRAM_BOT_TOKEN
TELEGRAM_USER_ID
GEMINI_API_KEY
```

4. Railway will detect Python automatically via the `railway.toml` config and deploy

Once deployed, update `API_BASE` in `extension/background.js` from `http://localhost:5000` to your Railway URL:

```js
const API_BASE = "https://your-app.up.railway.app";
```

Then reload the extension in Chrome.

---

## Bot Active Hours

The bot only responds to commands between 6 AM and midnight. Messages sent outside this window are ignored. This is intentional to avoid noise during sleep hours.

---

## Environment Variables Reference

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_USER_ID` | Your numeric Telegram user ID |
| `GEMINI_API_KEY` | API key from Google AI Studio |

---

## Future Plans

- Daily, weekly, and monthly productivity dashboard
- Telegram follow-up with trend analysis
- Onboarding flow for routine and timetable analysis

---

## Security

**Before pushing to GitHub, do the following:**

The Gemini API key is hardcoded in `extension/background.js` because Chrome extensions cannot read environment variables. You must remove your personal key before committing.

Open `extension/background.js` and make sure line 8 reads:

```js
const GEMINI_API_KEY = ""; // Add your Gemini API key here
```

Never commit a real key in this field. Anyone cloning the repo will add their own.

The `.env` file in the `bot/` folder must never be committed. Confirm your `.gitignore` includes:

```
.env
venv/
data/
__pycache__/
*.pyc
```

The bot only responds to the Telegram user ID set in `TELEGRAM_USER_ID`. Even if someone finds your deployed Railway URL, the bot ignores all messages from unknown users.

---

## Contributing

This project is fully open source under the MIT license. Contributions are welcome.

Open an issue first before submitting a pull request.

Areas where contributions would be most useful:

- Dashboard for daily, weekly, and monthly productivity stats
- Better Gemini prompting for edge cases
- Support for multiple user IDs on the Telegram bot
- Firefox extension port