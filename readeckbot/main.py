import os
import re
import json
import subprocess
from pathlib import Path
from typing import Any

from io import BytesIO

from dotenv import load_dotenv
from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
)


from rich.logging import RichHandler
from telegramify_markdown import markdownify
from ytelegraph import TelegraphAPI
import logging

from . import requests
from .md_to_dom import md_to_dom


# Configure rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=False, markup=True)],
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
READECK_DATA = os.getenv("READECK_DATA", None)
USER_TOKEN_MAP = PersistentDict(".user_tokens.json")


def escape_markdown_v2(text: str) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", text)


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
        "Send me a URL along with an optional +labels.\n"
        "Example:\n"
        "https://example.com/article Interesting Article +news +tech\n\n"
        "I will save it to your Readeck account.\n"
        "After saving, I'll show you a command /md_<bookmark_id> to get the article's markdown.\n\n"
        "To login or register, use:\n"
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
            "I don't have your Readeck token. Set it with /token <YOUR_TOKEN> or /register <password>."
        )
        return

    if not re.search(r"https?://", text):
        await update.message.reply_text(
            "I don't recognize this input.\n"
            "After saving a bookmark, use the provided /md_<bookmark_id> command to view its markdown."
        )
    else:
        # Check if the text contains a URL
        for line in text.splitlines():
            url, title, labels = await extract_url_title_labels(line)
            if url:
                await save_bookmark(update, url, title, labels, token)


async def register_command(update: Update, context: CallbackContext) -> None:
    """
    Handle the /register command.
    Usage: /register <password>
    Uses the Telegram user ID as the username.
    """
    user_id = update.effective_user.id
    if len(context.args) == 1:
        username = str(user_id)
        password = context.args[0]
    elif len(context.args) == 2:
        username = context.args[0]
        password = context.args[1]
    else:
        await update.message.reply_text(
            "Usage: /register <user> <password>\nor /register <password> (your Telegram user ID will be used as username)."
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
        ["readeck", "user"] + (["-config", READECK_CONFIG] if READECK_CONFIG else []) + ["-u", username, "-p", password]
    )
    logger.info(f"Attempting to register user '{username}' using CLI")
    logger.debug(f"CLI command: {command}")
    kw = {}
    if READECK_DATA:
        logger.info(f"Using READECK_DATA={READECK_DATA}")
        kw["cwd"] = Path(READECK_DATA).parent
    result = subprocess.run(command, capture_output=True, text=True, **kw)
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
            await update.message.reply_text(f"Registration failed: {result.stderr.strip()}")
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
    r = await requests.post(auth_url, headers=headers, json=payload)
    r.raise_for_status()

    data = r.json()
    token = data.get("token")
    if token:
        USER_TOKEN_MAP[str(update.effective_user.id)] = token
        await update.message.reply_text("Registration successful! Your token has been saved.")
        logger.info(f"Token for user '{username}' saved for Telegram user {update.effective_user.id}")
    else:
        await update.message.reply_text("Registration succeeded but failed to retrieve token.")
        logger.error("Token missing in auth response.")


async def reply_details(message: Message, token: str, bookmark_id: str):
    """Reply with details about the saved bookmark. Include a keyboard of actions"""

    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "content-type": "application/json",
    }
    details = await requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=headers)
    details.raise_for_status()
    info = details.json()
    logger.info(info)
    title = info.get("title", "No Title")
    url = info.get("url", "")

    # Create an inline keyboard with actions pre-fills
    button_read = InlineKeyboardButton("Read", callback_data=f"read_{bookmark_id}")
    button_publish = InlineKeyboardButton("Publish", callback_data=f"pub_{bookmark_id}")
    button_epub = InlineKeyboardButton("Epub", callback_data=f"epub_{bookmark_id}")
    reply_markup = InlineKeyboardMarkup([[button_read, button_publish], [button_epub]])

    await message.reply_markdown_v2(f"[{escape_markdown_v2(title)}]({url})", reply_markup=reply_markup)


async def handle_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text
    match = re.match(r"^/b_(\w+)", command)
    if not match:
        await update.message.reply_text("Invalid command format. Use /b_<bookmark_id>")
        return

    bookmark_id = match.group(1)
    user_id = update.effective_user.id
    token = USER_TOKEN_MAP.get(str(user_id))
    await reply_details(update.message, token, bookmark_id)


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

    r = await requests.post(f"{READECK_BASE_URL}/api/bookmarks", json=data, headers=headers)
    r.raise_for_status()
    data = r.json()
    bookmark_id = r.headers.get("Bookmark-Id")
    await reply_details(update.message, token, bookmark_id)
    logger.info(f"Saved bookmark with ID {bookmark_id}")


async def read_handler(update: Update, context: CallbackContext) -> None:
    """
    Handle dynamic md_<bookmark_id> to fetch markdown.
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    text = query.data.strip()

    _, bookmark_id = text.split("_")

    user_id = update.effective_user.id
    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await query.message.reply_text(
            "I don't have your Readeck token. Set it with /token <YOUR_TOKEN> or /register <password>."
        )
        return
    article_text = await fetch_article_markdown(bookmark_id, token)
    await send_long_message(query.message, article_text)


async def send_long_message(message: Message, text: str):
    # Telegram message limit ~4096 characters
    limit = 4000
    for start in range(0, len(text), limit):
        await message.reply_text(text[start : start + limit])


async def fetch_article_markdown(bookmark_id: str, token: str):
    """Fetch the markdown of a bookmark by its ID."""
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "text/markdown",
    }
    r = await requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}/article.md", headers=headers)
    r.raise_for_status()
    return r.text


async def fetch_bookmarks(
    token: str,
    author: str | None = None,
    is_archived: bool | None = None,
    search: str | None = None,
    site: str | None = None,
    title: str | None = None,
    type_: list[str] | None = None,
    labels: str | None = None,
    is_loaded: bool | None = None,
    has_errors: bool | None = None,
    has_labels: bool | None = None,
    is_marked: bool | None = None,
    range_start: str | None = None,
    range_end: str | None = None,
    read_status: list[str] | None = None,
    updated_since: str | None = None,
    bookmark_id: str | None = None,
    collection: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    sort: list[str] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
    }

    # Prepare query parameters, skipping any that are None
    params = {
        "author": author,
        "is_archived": is_archived,
        "search": search,
        "site": site,
        "title": title,
        "type": type_,
        "labels": labels,
        "is_loaded": is_loaded,
        "has_errors": has_errors,
        "has_labels": has_labels,
        "is_marked": is_marked,
        "range_start": range_start,
        "range_end": range_end,
        "read_status": read_status,
        "updated_since": updated_since,
        "id": bookmark_id,
        "collection": collection,
        "limit": limit,
        "offset": offset,
        "sort": sort,
    }

    # Remove keys with None values
    filtered_params = {k: v for k, v in params.items() if v is not None}

    response = await requests.get(
        f"{READECK_BASE_URL}/api/bookmarks",
        headers=headers,
        params=filtered_params,
    )
    response.raise_for_status()
    return response.json()


async def fetch_article_epub(bookmark_id: str, token: str):
    """Fetch the markdown of a bookmark by its ID."""
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "text/epub+zip",
    }
    r = await requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}/article.epub", headers=headers)
    r.raise_for_status()
    return BytesIO(r.content)


async def epub_handler(update: Update, context: CallbackContext) -> None:
    """
    Handle dynamic md_<bookmark_id> to fetch markdown.
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    text = query.data.strip()

    _, bookmark_id = text.split("_")

    user_id = update.effective_user.id
    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await query.message.reply_text(
            "I don't have your Readeck token. Set it with /token <YOUR_TOKEN> or /register <password>."
        )
        return
    epub = await fetch_article_epub(bookmark_id, token)

    await query.message.reply_document(
        document=epub,
        filename=f"{bookmark_id}.epub",
        caption="Here is your epub file.",
    )


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
    list_response = await requests.get(list_url, headers={**headers, "accept": "application/json"}, params=params)

    bookmarks = list_response.json()
    bookmark_ids = [b.get("id") for b in bookmarks if b.get("id")]

    if not bookmark_ids:
        await update.message.reply_text("There is no unread bookmarks. ")
        return

    await update.message.reply_text(f"Found {len(bookmark_ids)} unread bookmarks. Downloading epub.")

    epub_url = f"{READECK_BASE_URL}/api/bookmarks/export.epub"
    epub_response = await requests.get(
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
        r = await requests.patch(patch_url, headers=headers, json=patch_payload)
        logger.info(f"Archived {bid} bookmark: {r.status_code}")


def format_list(bookmarks):
    """Format a list of bookmarks for display."""
    lines = []
    for bookmark in bookmarks:
        title = bookmark.get("title", "No Title")
        url = bookmark.get("url", "")
        lines.append(f"- [{title}]({url}) | /b_{bookmark['id']}")
    return "\n".join(lines)


async def unarchived_command(update: Update, context: CallbackContext) -> None:
    """List all unarchived bookmarks"""
    user_id = update.effective_user.id
    token = USER_TOKEN_MAP.get(str(user_id))
    bookmarks = await fetch_bookmarks(token, is_archived=False)
    if not bookmarks:
        await update.message.reply_text("No unarchived bookmarks found.")
        return
    message = format_list(bookmarks)
    # TODO format markdown
    await update.message.reply_markdown_v2(markdownify(message))


async def search_command(update: Update, context: CallbackContext) -> None:
    """Search bookmarks"""
    user_id = update.effective_user.id
    query = update.message.text.removeprefix("/search ").strip()
    if not query:
        await update.message.reply_text("Please provide a search query.")
        return
    token = USER_TOKEN_MAP.get(str(user_id))
    bookmarks = await fetch_bookmarks(token, search=query)
    if not bookmarks:
        await update.message.reply_text("No bookmarks found.")
        return
    message = format_list(bookmarks)
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


async def publish_handler(update: Update, context: CallbackContext) -> None:
    """
    Handles the "publish" callback triggered by the inline button.
    Extracts the bookmark_id from the callback data and publishes
    the corresponding article's markdown to Telegraph.
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    user_id = update.effective_user.id
    # Extract the bookmark_id from the callback data ("read_<bookmark_id>")
    try:
        _, bookmark_id = query.data.split("_", 1)
    except ValueError:
        await query.message.reply_text("Invalid callback data.")
        return

    # Retrieve the user's Readeck token
    token = USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await query.message.reply_text("I don't have your Readeck token. Use /token or /register <password>.")
        return

    # Fetch the bookmark's markdown content
    md_content = await fetch_article_markdown(bookmark_id, token)

    # Fetch bookmark details to retrieve the title and additional info
    details_header = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    details_response = await requests.get(f"{READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=details_header)
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
        telegraph_token = ph.account.access_token
        USER_TELEGRAPH[str(user_id)] = {
            "access_token": telegraph_token,
            "author_name": f"User {user_id}",
        }

    # Convert the markdown to a Telegraph-compatible DOM
    dom = md_to_dom(md_content)
    # Optionally remove the first node if it redundantly contains the title
    if dom and title in dom[0]["children"]:
        dom = dom[1:]

    # Publish the markdown as a Telegraph page.
    page_link = ph.create_page(
        title,
        dom,
        author_name=details.get("author"),
        author_url=details.get("url"),
    )
    await query.message.reply_text(f"Your article is live at: {page_link}")


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

    application.add_handler(CommandHandler("unarchived", unarchived_command))
    application.add_handler(CommandHandler("search", search_command))

    application.add_handler(CallbackQueryHandler(read_handler, pattern=r"^read_"))
    application.add_handler(CallbackQueryHandler(publish_handler, pattern=r"^pub_"))
    application.add_handler(CallbackQueryHandler(epub_handler, pattern=r"^epub_"))

    # Non-command messages (likely bookmarks)
    application.add_handler(MessageHandler(filters.Regex(r"^/b_\w+"), handle_detail_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.add_error_handler(error_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
