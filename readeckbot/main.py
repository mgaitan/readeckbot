"""
A Telegram bot that interfaces with a self-hosted Readeck instance to manage bookmarks.

Features:
- Save bookmarks by sending a URL (with optional title and tags).
- Supports per-user Readeck token configuration via:
    • /token <YOUR_READECK_TOKEN>
    • /register <password>  (your Telegram user ID is used as username)
- Configuration (Telegram token and Readeck URL) is loaded from a .env file.
- Uses a persistent dictionary (JSON file) to store user tokens.
"""


import os
import re
import json
import requests
import subprocess
from pathlib import Path

from io import BytesIO

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ApplicationBuilder,
)
from rich.logging import RichHandler
from telegramify_markdown import markdownify
from ytelegraph import TelegraphAPI
import logging

# Configure rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)

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
        self.path.write_text(json.dumps(self, indent=2))


# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("You must provide a TELEGRAM_BOT_TOKEN in your .env")

READECK_BASE_URL = os.getenv("READECK_BASE_URL", "http://localhost:8000")
READECK_CONFIG = os.getenv("READECK_CONFIG", None)
USER_TOKEN_MAP = PersistentDict(".user_tokens.json")


async def start(update: Update, context: CallbackContext) -> None:
    """Send a welcome message and log user ID."""
    user_id = update.effective_user.id
    logger.info(f"User started the bot. user_id={user_id}")
    await update.message.reply_text(
        "Hi! Send me a URL to save it on Readeck.\n\n"
        "You can also specify a title and tags like:\n"
        "https://example.com Interesting Article +news +tech\n\n"
        "To configure your Readeck credentials use one of:\n"
        "• /token <YOUR_READECK_TOKEN>\n"
        "• /register <password>  (your Telegram user ID is used as username)\n\n"
        "After saving a bookmark, I'll give you a custom command like /md_<bookmark_id> "
        "to directly fetch its markdown."
    )


async def help_command(update: Update, context: CallbackContext) -> None:
    """Show help text."""
    await update.message.reply_text(
        "Send me a URL along with an optional title and +labels.\n"
        "Example:\n"
        "https://example.com/article Interesting Article +news +tech\n\n"
        "I will save it to your Readeck account.\n"
        "After saving, I'll show you a command /md_<bookmark_id> to get the article's markdown.\n\n"
        "To set your Readeck credentials use:\n"
        "• /token <YOUR_READECK_TOKEN>\n"
        "or\n"
        "• /register <password>  (your Telegram user ID is used as username)"
    )


async def extract_url_title_labels(text: str):
    """Extract URL, title, and labels from text."""
    url_pattern = r"(https?://[^\s]+)"
    match = re.search(url_pattern, text)
    if not match:
        return None, None, []
    url = match.group(0)
    after_url = text.replace(url, "").strip()
    labels = re.findall(r"\+(\w+)", after_url)
    for lbl in labels:
        after_url = after_url.replace(f"+{lbl}", "")
    title = after_url.strip()
    return url, (title if title else None), labels


async def handle_message(update: Update, context: CallbackContext) -> None:
    """
    Handle non-command text messages:
    - If the message contains a URL, save it as a bookmark.
    - Otherwise, provide guidance.
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()

    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await update.message.reply_text(
            "I don't have your Readeck token. "
            "Set it with /token <YOUR_TOKEN> or /register <password>."
        )
        return

    # Check if the text contains a URL
    if re.search(r"https?://", text):
        url, title, labels = await extract_url_title_labels(text)
        if not url:
            await update.message.reply_text("I couldn't find a valid URL.")
            return
        await save_bookmark(update, url, title, labels, token)
    else:
        await update.message.reply_text(
            "I don't recognize this input.\n"
            "After saving a bookmark, use the provided /md_<bookmark_id> command to view its markdown."
        )


async def register_command(update: Update, context: CallbackContext) -> None:
    """
    Handle the /register command.
    Usage: /register <password>
    Uses the Telegram user ID as the username.
    """
    user_id = update.effective_user.id
    if not context.args:
        username = str(user_id)
        password = str(user_id)
    elif len(context.args) == 1:
        username = str(user_id)
        password = context.args[0]
    elif len(context.args) == 2:
        username = context.args[0]
        password = context.args[1]
    else:
        await update.message.reply_text(
            "Usage: /register <user> <password>\nUsage: /register <password> (your Telegram user ID will be used as username)."
        )
        return
    await register_and_fetch_token(update, username, password)


async def token_command(update: Update, context: CallbackContext) -> None:
    """
    Handle the /token command.
    Usage: /token <YOUR_READECK_TOKEN>
    """
    user_id = update.effective_user.id
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /token <YOUR_READECK_TOKEN>")
        return
    token = context.args[0]
    USER_TOKEN_MAP[str(user_id)] = token
    await update.message.reply_text("Your Readeck token has been saved.")
    logger.info(f"Set token for user_id={user_id}")


async def register_and_fetch_token(update: Update, username: str, password: str):
    """
    Register a new user in Readeck and fetch the corresponding token.
    First, try using the CLI command.
    If it fails, try via Docker.
    Then obtain the token via the API.
    """
    command = (
        ["readeck", "user"] + ["-config", READECK_CONFIG]
        if READECK_CONFIG
        else [] + ["-u", username, "-p", password]
    )
    logger.info(f"Attempting to register user '{username}' using CLI")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"CLI command failed: {result.stderr.strip()}, trying docker")
        docker_command = [
            "docker",
            "run",
            "codeberg.org/readeck/readeck:latest",
            "readeck",
            "user",
            "-u",
            username,
            "-p",
            password,
        ]
        result = subprocess.run(docker_command, capture_output=True, text=True)
        if result.returncode != 0:
            await update.message.reply_text(
                f"Registration failed: {result.stderr.strip()}"
            )
            logger.error(f"Registration failed with docker: {result.stderr.strip()}")
            return

    logger.info(f"User '{username}' registered successfully. Fetching token...")

    auth_url = f"{READECK_BASE_URL}/api/auth"
    payload = {
        "application": "telegram bot",
        "username": username,
        "password": password,
    }
    headers = {"accept": "application/json", "content-type": "application/json"}
    r = requests.post(auth_url, headers=headers, json=payload)
    r.raise_for_status()

    data = r.json()
    token = data.get("token")
    if token:
        USER_TOKEN_MAP[str(update.effective_user.id)] = token
        await update.message.reply_text(
            "Registration successful! Your token has been saved."
        )
        logger.info(
            f"Token for user '{username}' saved for Telegram user {update.effective_user.id}"
        )
    else:
        await update.message.reply_text(
            "Registration succeeded but failed to retrieve token."
        )
        logger.error("Token missing in auth response.")


async def save_bookmark(update: Update, url: str, title: str, labels: list, token: str):
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
    r.raise_for_status()

    bookmark_id = r.headers.get("Bookmark-Id")

    details = requests.get(
        f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=headers
    )
    details.raise_for_status()
    info = details.json()
    logger.info(info)
    real_title = info.get("title", "No Title")
    href = info.get("href", "")
    if href:
        message = (
            f"Saved: [{real_title}]({href})\n\n"
            f"Use `/md_{bookmark_id}` to view the article's markdown."
        )
        await update.message.reply_markdown_v2(markdownify(message))
    else:
        message = (
            f"Saved: {real_title}\n\n"
            f"Use `/md_{bookmark_id}` to view the article's markdown."
        )
        await update.message.reply_text(message)
    logger.info(f"Saved bookmark '{real_title}' with ID {bookmark_id}")


async def dynamic_md_handler(update: Update, context: CallbackContext) -> None:
    """
    Handle dynamic commands like /md_<bookmark_id> to fetch markdown.
    """
    text = update.message.text.strip()
    if text.startswith("/md_"):
        bookmark_id = text[len("/md_") :]
        user_id = update.effective_user.id
        token = USER_TOKEN_MAP.get(str(user_id))
        if not token:
            await update.message.reply_text(
                "I don't have your Readeck token. "
                "Set it with /token <YOUR_TOKEN> or /register <password>."
            )
            return
        await fetch_article_markdown(update, bookmark_id, token)
    else:
        await update.message.reply_text(
            "I don't recognize this command.\n"
            "If you want the markdown of a saved article, use /md_<bookmark_id>."
        )


async def send_long_message(update: Update, text: str):
    # Telegram message limit ~4096 characters
    limit = 4000
    for start in range(0, len(text), limit):
        await update.message.reply_text(text[start : start + limit])


async def fetch_article_markdown(update: Update, bookmark_id: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "text/markdown",
    }
    r = requests.get(
        f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}/article.md", headers=headers
    )
    r.raise_for_status()
    article_text = r.text
    await send_long_message(update, article_text)
    logger.info(f"Fetched markdown for bookmark {bookmark_id}")


async def epub_command(update: Update, context: CallbackContext) -> None:
    """Generate an epub of all unread bookmarks, send it, and archive them."""
    user_id = update.effective_user.id
    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await update.message.reply_text(
            "I don't have your Readeck token. Set it with /token <YOUR_TOKEN> or /register <password>."
        )
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "content-type": "application/json",
    }
    # Define el filtro: bookmarks no archivados.
    params = {
        "author": "",
        "is_archived": "false",
        "labels": "",
        "search": "",
        "site": "",
        "title": "",
    }

    # Step 1: unarchive bookmarks
    list_url = f"{READECK_BASE_URL}/api/bookmarks"
    list_response = requests.get(
        list_url, headers={**headers, "accept": "application/json"}, params=params
    )

    bookmarks = list_response.json()
    bookmark_ids = [b.get("id") for b in bookmarks if b.get("id")]

    if not bookmark_ids:
        await update.message.reply_text("There is no unread bookmarks. ")
        return

    await update.message.reply_text(
        f"Found {len(bookmark_ids)} unread bookmarks. Downloading epub."
    )

    epub_url = f"{READECK_BASE_URL}/api/bookmarks/export.epub"
    epub_response = requests.get(
        epub_url,
        headers={"Authorization": f"Bearer {token}", "accept": "application/epub+zip"},
        params=params,
    )

    # Fetch the epub file
    epub_bytes = BytesIO(epub_response.content)
    epub_bytes.name = "bookmarks.epub"
    await update.message.reply_document(
        document=epub_bytes,
        filename="bookmarks.epub",
        caption="Here is your epub file.",
    )

    # archive
    for bid in bookmark_ids:
        patch_url = f"{READECK_BASE_URL}/api/bookmarks/{bid}"
        patch_payload = {"is_archived": True}
        r = requests.patch(patch_url, headers=headers, json=patch_payload)
        logger.info(f"Archived {bid} bookmark: {r.status_code}")


async def list_command(update: Update, context: CallbackContext) -> None:
    """List all unarchived bookmarks with title, site and dynamic /md_<bookmark_id>."""
    user_id = update.effective_user.id
    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await update.message.reply_text(
            "I don't have your Readeck token. Set it with /token <YOUR_TOKEN> or /register <password>."
        )
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
    }
    params = {
        "author": "",
        "is_archived": "false",
        "labels": "",
        "search": "",
        "site": "",
        "title": "",
    }

    response = requests.get(
        f"{READECK_BASE_URL}/api/bookmarks", headers=headers, params=params
    )

    bookmarks = response.json()
    if not bookmarks:
        await update.message.reply_text("No unarchived bookmarks found.")
        return

    lines = []
    for bookmark in bookmarks:
        logger.info(bookmark)
        title = bookmark.get("title", "No Title")
        url = bookmark.get("url", "")
        site = bookmark.get("site", "Unknown")
        bookmark_id = bookmark.get("id", "")
        lines.append(f"- [{title}]({url}) | {site} | /md_{bookmark_id}")
    message = "\n".join(lines)
    # TODO format markdown
    await update.message.reply_markdown_v2(markdownify(message))


# Nuevo diccionario persistente para almacenar cuentas Telegraph
USER_TELEGRAPH = PersistentDict(".user_telegraph.json")


def parse_inline(text: str) -> list:
    """
    Converts text that may contain markdown links into a list of nodes.

    For example, the text:
      "Visit [Google](https://google.com)"
    is converted into:
      ["Visit ", {"tag": "a", "attrs": {"href": "https://google.com"}, "children": ["Google"]}]
    """
    parts = []
    last_index = 0
    # Regex for links: [text](url)
    for m in re.finditer(r"\[(.*?)\]\((.*?)\)", text):
        start, end = m.span()
        # Add text before the link if any
        if start > last_index:
            parts.append(text[last_index:start])
        link_text = m.group(1)
        link_url = m.group(2)
        parts.append({"tag": "a", "attrs": {"href": link_url}, "children": [link_text]})
        last_index = end
    # Append remaining text
    if last_index < len(text):
        parts.append(text[last_index:])
    return parts


def markdown_to_nodes(md: str) -> list:
    """
    A very basic function that converts markdown into a list of NodeElement objects for Telegraph.

    Supported:
      - Headers: "# " is converted to <h3> and "## " to <h4>.
      - Inline links (using parse_inline)
      - Other lines are wrapped in <p> tags.
    """
    nodes = []
    for line in md.splitlines():
        line = line.strip()
        if not line:
            continue
        # Check for headers
        if line.startswith("## "):
            content = line[3:].strip()
            children = parse_inline(content)
            nodes.append({"tag": "h4", "children": children})
        elif line.startswith("# "):
            content = line[2:].strip()
            children = parse_inline(content)
            nodes.append({"tag": "h3", "children": children})
        else:
            children = parse_inline(line)
            nodes.append({"tag": "p", "children": children})
    return nodes


async def read_command(update: Update, context: CallbackContext) -> None:
    """
    /read <bookmark_id>

    Publishes the markdown of the specified bookmark to Telegraph.
    If the user does not have a Telegraph account stored, one is created automatically,
    and its account information is saved in USER_TELEGRAPH.
    """
    user_id = update.effective_user.id
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /read <bookmark_id>")
        return
    bookmark_id = context.args[0]

    # Retrieve the user's Readeck token
    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await update.message.reply_text(
            "I don't have your Readeck token. Use /token or /register <password>."
        )
        return

    # Fetch the bookmark's markdown content (synchronously, letting errors propagate)
    auth_header = {
        "Authorization": f"Bearer {token}",
        "accept": "text/markdown",
    }
    md_response = requests.get(
        f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}/article.md",
        headers=auth_header,
    )
    md_response.raise_for_status()
    md_content = md_response.text

    # Fetch bookmark details to retrieve the title
    details_header = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    details_response = requests.get(
        f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=details_header
    )
    details_response.raise_for_status()
    details = details_response.json()
    title = details.get("title", "No Title")

    # Check if the user already has a Telegraph account; if not, create one automatically.
    telegraph_account = USER_TELEGRAPH.get(str(user_id))
    if telegraph_account:
        telegraph_token = telegraph_account.get("access_token")
        ph = TelegraphAPI(telegraph_token)
    else:
        telegram_user = update.effective_user.username or str(user_id)
        ph = TelegraphAPI(
            short_name=f"@{telegram_user}'s readeckbot blog",
            author_name=f"@{telegram_user}",
            author_url=f"https://t.me/{telegram_user}",
        )
        telegraph_token = ph.access_token
        USER_TELEGRAPH[str(user_id)] = {
            "access_token": telegraph_token,
            "author_name": f"User {user_id}",
        }

    # Publish the markdown as a Telegraph page.
    page_link = ph.create_page_md(
        title,
        md_content,
        author_name=details.get("author"),
        author_url=details.get("url"),
    )
    await update.message.reply_text(f"Your article is live at: {page_link}")


async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, "message") and update.message:
        try:
            await update.message.reply_text("Having troubles now... try later.")
        except Exception as e:
            logger.error(f"Error sending error message: {e}")


def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("token", token_command))
    application.add_handler(CommandHandler("epub", epub_command))

    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("read", read_command))

    application.add_handler(MessageHandler(filters.COMMAND, dynamic_md_handler))
    # Non-command messages (likely bookmarks)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    application.add_error_handler(error_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
