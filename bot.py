"""
A Telegram bot that interfaces with a self-hosted Readeck instance to manage bookmarks.

Features that works:
- Save bookmarks by sending a URL (with optional title and tags).
- Supports per-user Readeck token configuration via @token <YOUR_TOKEN>.
- Configuration (Telegram token and Readeck URL) is loaded from a .env file.
- Uses a persistent dictionary (JSON file) to store user tokens.

Not working: 
- After saving, it provides a dynamic command (/md_<bookmark_id>) to fetch the article's markdown.
- Handles long markdown responses by splitting them into multiple messages.

Todo:
- List of saved bookmarks (today?) . optianlly filtering by tags
"""


# /// script
# dependencies = [
#   "requests<3",
#   "python-telegram-bot==13.*",
#   "rich",
#   "python-dotenv"
# ]
# ///

import os
import re
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from rich.logging import RichHandler
import logging

# Configure rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger(__name__)

class PersistentDict(dict):
    """A simple persistent dictionary stored as JSON using pathlib.
       Automatically saves on each set or delete operation.
    """
    def __init__(self, filename: str):
        super().__init__()
        self.path = Path(filename)
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self.update(data)
            except Exception:
                pass

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

    def _save(self):
        self.path.write_text(json.dumps(self,indent=2))

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("You must provide a TELEGRAM_BOT_TOKEN in your .env")

READECK_BASE_URL = os.getenv("READECK_BASE_URL", "http://localhost:8000")

USER_TOKEN_MAP = PersistentDict(".user_tokens.json")

def start(update: Update, context: CallbackContext) -> None:
    """Send a start message and log user ID."""
    user_id = update.effective_user.id
    logger.info(f"User started the bot. user_id={user_id}")
    update.message.reply_text(
        "Hi! Send me a URL to save it on Readeck.\n\n"
        "You can also specify a title and tags like:\n"
        "https://example.com Interesting Article +news +tech\n\n"
        "To set your Readeck token, send:\n"
        "@token YOUR_READECK_TOKEN\n\n"
        "After saving a bookmark, I'll give you a custom command like /md_<bookmark_id>\n"
        "to directly fetch its markdown."
    )

def help_command(update: Update, context: CallbackContext) -> None:
    """Show help text."""
    update.message.reply_text(
        "Send me a URL along with optional title and +labels.\n"
        "Example:\n"
        "https://example.com/article Interesting Article +news +tech\n\n"
        "I will save it to your Readeck account.\n"
        "After saving, I'll show you a command /md_<bookmark_id> to get the article's markdown.\n\n"
        "To set your Readeck token:\n"
        "@token YOUR_READECK_TOKEN"
    )

def extract_url_title_labels(text: str):
    """Extract URL, title, and labels from text."""
    url_pattern = r'(https?://[^\s]+)'
    match = re.search(url_pattern, text)
    if not match:
        return None, None, []
    url = match.group(0)
    after_url = text.replace(url, "").strip()
    labels = re.findall(r'\+(\w+)', after_url)
    for lbl in labels:
        after_url = after_url.replace(f"+{lbl}", "")
    title = after_url.strip()
    return url, (title if title else None), labels

def handle_message(update: Update, context: CallbackContext) -> None:
    """
    Handle incoming messages:
    - If message starts with '@token', store user token.
    - If message is a URL, save bookmark.
    - Otherwise, show a hint.
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text.startswith("@token"):
        # Format: @token MY_READECK_TOKEN
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            token = parts[1].strip()
            USER_TOKEN_MAP[str(user_id)] = token
            update.message.reply_text("Your Readeck token has been saved.")
            logger.info(f"Set token for user_id={user_id}")
        else:
            update.message.reply_text("Please provide a token after @token.")
        return

    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        update.message.reply_text("I don't have your Readeck token. Set it with '@token YOUR_TOKEN'.")
        return

    # Check if it's a URL
    if re.search(r'https?://', text):
        url, title, labels = extract_url_title_labels(text)
        if not url:
            update.message.reply_text("I couldn't find a valid URL.")
            return
        save_bookmark(update, url, title, labels, token)
    else:
        update.message.reply_text(
            "I don't recognize this input.\n"
            "After saving a bookmark, use the provided /md_<bookmark_id> command "
            "to view its markdown."
        )

def save_bookmark(update: Update, url: str, title: str, labels: list, token: str):
    """Save a bookmark to Readeck and return a link and the bookmark_id."""
    data = {"url": url}
    if title:
        data["title"] = title
    if labels:
        data["labels"] = labels

    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "content-type": "application/json",
    }
    r = requests.post(f"{READECK_BASE_URL}/api/bookmarks", json=data, headers=headers)
    if r.status_code == 202:
        bookmark_id = r.headers.get("Bookmark-Id")
        if bookmark_id:
            details = requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=headers)
            if details.status_code == 200:
                info = details.json()
                real_title = info.get("title", "No Title")
                href = info.get("href", "")
                # Provide a clickable link and a dynamic command
                if href:
                    message = (
                        f"Saved: [{real_title}]({href})\n\n"
                        f"Use `/md_{bookmark_id}` to view the article's markdown."
                    )
                    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
                else:
                    message = (
                        f"Saved: {real_title}\n\n"
                        f"Use `/md_{bookmark_id}` to view the article's markdown."
                    )
                    update.message.reply_text(message)
                logger.info(f"Saved bookmark '{real_title}' with ID {bookmark_id}")
            else:
                update.message.reply_text("Saved bookmark but failed to retrieve details.")
                logger.warning("Saved bookmark but failed to retrieve details.")
        else:
            update.message.reply_text("Saved bookmark but missing Bookmark-Id header.")
            logger.warning("Saved bookmark but missing Bookmark-Id header.")
    else:
        update.message.reply_text("Failed to save bookmark.")
        logger.error("Failed to save bookmark.")

def dynamic_md_handler(update: Update, context: CallbackContext) -> None:
    """
    Handle dynamic commands like /md_<bookmark_id> to fetch markdown.
    """
    text = update.message.text.strip()
    if text.startswith("/md_"):
        bookmark_id = text[len("/md_"):]
        user_id = update.effective_user.id
        token = USER_TOKEN_MAP.get(str(user_id))
        if not token:
            update.message.reply_text("I don't have your Readeck token. Set it with '@token YOUR_TOKEN'.")
            return
        fetch_article_markdown(update, bookmark_id, token)
    else:
        update.message.reply_text(
            "I don't recognize this command.\n"
            "If you want the markdown of a saved article, use /md_<bookmark_id>."
        )


def send_long_message(update: Update, text: str):
    # Telegram message limit ~4096 chars
    limit = 4000
    for start in range(0, len(text), limit):
        update.message.reply_text(text[start:start+limit])

def fetch_article_markdown(update: Update, bookmark_id: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/epub+zip",
    }
    r = requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}/article.md", headers=headers)
    if r.status_code == 200:
        article_text = r.text
        send_long_message(update, article_text)
        logger.info(f"Fetched markdown for bookmark {bookmark_id}")
    else:
        update.message.reply_text("Failed to retrieve the article markdown.")
        logger.error("Failed to retrieve the article markdown.")


def main():
    """Run the bot."""
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    # dynamic_md_handler will handle commands like /md_*
    dispatcher.add_handler(MessageHandler(Filters.command, dynamic_md_handler))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
