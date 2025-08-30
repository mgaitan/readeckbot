import re
import subprocess
from pathlib import Path

from io import BytesIO

from telegram import Update, Message, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
)
from telegramify_markdown import markdownify


from . import requests, telegraph, config, __version__
from .log import logger
from .helpers import chunker, escape_markdown_v2, normalize_url
from .readeck_client import (
    fetch_bookmarks,
    fetch_article_epub,
    save_bookmark,
    fetch_article_markdown,
    archive_bookmark,
    favorite_bookmark,
    unfavorite_bookmark,
    get_readeck_version,
    is_admin_user,
)


import os
import sys

try:
    import llm

    logger.info(f"LLM is ENABLED using model '{config.LLM_MODEL}' with max length {config.LLM_SUMMARY_MAX_LENGTH}.")
except ImportError:
    logger.warning("llm library not installed. Summarization feature is DISABLED.")
    llm = None


async def help_command(update: Update, context: CallbackContext) -> None:
    """
    Send a welcome message and log user ID.
    """
    user_id = update.effective_user.id
    logger.info(f"User started the bot. user_id={user_id}")
    await update.message.reply_text(
        "Hi! Send me a URL to save it on Readeck.\n\n"
        "To configure your Readeck credentials use one of:\n"
        "• /token <YOUR_READECK_TOKEN>\n"
        "• /register <password>  (your Telegram user ID is used as username)\n\n"
        "Other commands:\n"
        "• /version - show the bot version\n"
        "• /restart - restart the bot (admin only, for upgrades)"
    )


async def start(update: Update, context: CallbackContext) -> None:
    # /start behaves exactly like /help
    await help_command(update, context)


async def version_command(update: Update, context: CallbackContext) -> None:
    """Reply with the current bot and readeck backend version."""
    readeck_version = get_readeck_version()
    await update.message.reply_text(f"Readeckbot version: {__version__}\n{readeck_version}")


async def restart_command(update: Update, context: CallbackContext) -> None:
    """Restart the bot process (systemd will relaunch it, useful for upgrades). Only admins can use this."""
    user_id = update.effective_user.id
    token = config.USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await update.message.reply_text("You must register your Readeck token to use this command.")
        return
    if not await is_admin_user(token):
        await update.message.reply_text("You must be an admin in Readeck to restart the bot.")
        logger.warning(f"Unauthorized restart attempt by user_id={user_id}")
        return
    await update.message.reply_text("Restarting bot...")
    logger.info(f"Bot restart requested by admin user_id={user_id}")
    # Flush logs and exit process
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


async def handle_message(update: Update, context: CallbackContext) -> None:
    """
    Handle non-command text messages:
    - If the message contains a URL, save it as a bookmark.
    - Otherwise, provide guidance.
    """
    user_id = update.effective_user.id

    token = config.USER_TOKEN_MAP.get(str(user_id))

    for ent in update.message.entities:
        if ent.type == MessageEntity.TEXT_LINK:
            url = ent.url
        elif ent.type == MessageEntity.URL:
            url = normalize_url(update.message.parse_entity(ent))
        else:
            continue

        bookmark_id = await save_bookmark(url, token)
        await reply_details(update.message, token, bookmark_id)
        logger.info(f"Saved bookmark with ID {bookmark_id}")


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
    config.USER_TOKEN_MAP[str(user_id)] = token
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
        ["readeck", "user"]
        + (["-config", config.READECK_CONFIG] if config.READECK_CONFIG else [])
        + ["-u", username, "-p", password]
    )
    logger.info(f"Attempting to register user '{username}' using CLI")
    logger.debug(f"CLI command: {command}")
    kw = {}
    if config.READECK_DATA:
        logger.info(f"Using READECK_DATA={config.READECK_DATA}")
        kw["cwd"] = Path(config.READECK_DATA).parent
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

    auth_url = f"{config.READECK_BASE_URL}/api/auth"
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
        config.USER_TOKEN_MAP[str(update.effective_user.id)] = token
        await update.message.reply_text("Registration successful! Your token has been saved.")
        logger.info(f"Token for user '{username}' saved for Telegram user {update.effective_user.id}")
    else:
        await update.message.reply_text("Registration succeeded but failed to retrieve token.")
        logger.error("Token missing in auth response.")


def build_inline_keyboard(bookmark_id, is_favorite, show_read=True, show_publish=True, show_epub=True, show_summarize=False, show_archive=False):
    """Builds the inline keyboard for bookmark actions, including favorite toggle and optional actions."""
    buttons = []
    if show_read:
        buttons.append(InlineKeyboardButton("Read", callback_data=f"read_{bookmark_id}"))
    if show_publish:
        buttons.append(InlineKeyboardButton("Publish", callback_data=f"pub_{bookmark_id}"))
    row1 = buttons.copy() if buttons else None

    row2 = []
    if show_epub:
        row2.append(InlineKeyboardButton("Epub", callback_data=f"epub_{bookmark_id}"))
    if show_summarize and llm:
        row2.append(InlineKeyboardButton("Summarize", callback_data=f"summarize_{bookmark_id}"))
    row2 = row2 if row2 else None

    # Favorite toggle button (emoji only)
    fav_emoji = "❤️" if is_favorite else "🤍"
    fav_action = "unfavorite" if is_favorite else "favorite"
    row_fav = [InlineKeyboardButton(fav_emoji, callback_data=f"{fav_action}_{bookmark_id}")]

    row_archive = [InlineKeyboardButton("Archive", callback_data=f"archive_{bookmark_id}")] if show_archive else None

    # Compose keyboard rows
    keyboard = []
    if row1: keyboard.append(row1)
    if row2: keyboard.append(row2)
    if row_archive and row_fav:
        keyboard.append(row_archive + row_fav)
    else:
        keyboard.append(row_fav)
    return InlineKeyboardMarkup(keyboard)

async def reply_details(message: Message, token: str, bookmark_id: str):
    """Reply with details about the saved bookmark. Include a keyboard of actions"""
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "content-type": "application/json",
    }
    details = await requests.get(f"{config.READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=headers)
    details.raise_for_status()
    info = details.json()
    logger.info(info)
    title = info.get("title") or info.get("url")
    url = info.get("url")
    is_favorite = info.get("is_marked", False)
    reply_markup = build_inline_keyboard(
        bookmark_id,
        is_favorite,
        show_read=True,
        show_publish=True,
        show_epub=True,
        show_summarize=bool(llm),
        show_archive=False
    )
    await message.reply_markdown_v2(f"[{escape_markdown_v2(title)}]({url})", reply_markup=reply_markup)


async def summarize_handler(update: Update, context: CallbackContext) -> None:
    """Callback for 'Summarize' button that uses llm to summarize the article."""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    # Parse bookmark_id from "summarize_<bookmark_id>"
    _, bookmark_id = query.data.split("_", 1)
    user_id = update.effective_user.id
    token = config.USER_TOKEN_MAP.get(str(user_id))

    article_text = await fetch_article_markdown(bookmark_id, token)

    # 2) Build a prompt instructing the LLM to summarize in the same language
    #    and limit the summary to ~LLM_SUMMARY_MAX_LENGTH characters.
    prompt = (
        f"Summarize the following article. Keep the summary under {config.LLM_SUMMARY_MAX_LENGTH} characters. ",
        "Answer in the language of the original text (eg: spanish if the source is spanish, english if the source is english).\n\n",
        "ARTICLE:\n\n",
        article_text,
    )
    try:
        # 3) Call the llm library - usage will vary depending on your LLM setup
        # For example, if `llm` has a .predict() function:
        model = llm.get_async_model(config.LLM_MODEL)
        summary = await model.prompt(
            prompt=prompt,
            key=config.LLM_KEY,
        ).text()
        # If your library is synchronous or has a different API, adjust accordingly.
    except Exception as e:
        logger.error(f"LLM summarization failed: {e}")
        await query.message.reply_text("Could not summarize the article")
        return

    await query.message.reply_text(summary)


async def handle_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text
    match = re.match(r"^/b_(\w+)", command)
    if not match:
        await update.message.reply_text("Invalid command format. Use /b_<bookmark_id>")
        return

    bookmark_id = match.group(1)
    user_id = update.effective_user.id
    token = config.USER_TOKEN_MAP.get(str(user_id))
    await reply_details(update.message, token, bookmark_id)


async def read_handler(update: Update, context: CallbackContext) -> None:
    """
    Handle dynamic read_<bookmark_id> to fetch markdown.
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    text = query.data.strip()

    try:
        _, bookmark_id, chunk_n = text.split("_")
        chunk_n = int(chunk_n)
    except ValueError:
        # first page: it has no chunk suffix
        _, bookmark_id = text.split("_")
        chunk_n = 0

    user_id = update.effective_user.id
    token = config.USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await query.message.reply_text(
            "I don't have your Readeck token. Set it with /token <YOUR_TOKEN> or /register <password>."
        )
    article_text = await fetch_article_markdown(bookmark_id, token)
    article_chunks = chunker(article_text)
    chunk = article_chunks[chunk_n]

    if chunk_n < len(article_chunks) - 1:
        button_read = InlineKeyboardButton("Next", callback_data=f"read_{bookmark_id}_{chunk_n + 1}")
        reply_markup = InlineKeyboardMarkup([[button_read]])
    else:
        # Last chunk, show Archive and Favorite toggle buttons
        headers = {
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
            "content-type": "application/json",
        }
        details = await requests.get(f"{config.READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=headers)
        details.raise_for_status()
        info = details.json()
        is_favorite = info.get("is_marked", False)
        reply_markup = build_inline_keyboard(
            bookmark_id,
            is_favorite,
            show_read=False,
            show_publish=False,
            show_epub=False,
            show_summarize=False,
            show_archive=True
        )

    await query.message.reply_text(chunk, reply_markup=reply_markup)


async def archive_bookmark_handler(update: Update, context: CallbackContext) -> None:
    """Archive a bookmark by its ID."""
    user_id = update.effective_user.id
    token = config.USER_TOKEN_MAP.get(str(user_id))
    query = update.callback_query
    await query.answer()

    # Bookmark_id issue here: getting the bookmark_id again
    data = query.data  # 'archive_PXNJqD7KvTUdVhwVDjuXSr'
    _, bookmark_id = data.split("_", 1)  # extract 'PXNJqD7KvTUdVhwVDjuXSr'
    await archive_bookmark(bookmark_id, token)
    logger.info(f"Archived bookmark {bookmark_id} succesfully.")
    # Optionally update the inline keyboard to disable the archive button, but for now do nothing else.

async def favorite_bookmark_handler(update: Update, context: CallbackContext) -> None:
    """Toggle favorite status and update the inline keyboard (emoji only, toggle style)."""
    user_id = update.effective_user.id
    token = config.USER_TOKEN_MAP.get(str(user_id))
    query = update.callback_query
    await query.answer()

    data = query.data  # 'favorite_<id>' or 'unfavorite_<id>'
    action, bookmark_id = data.split("_", 1)
    if action == "favorite":
        await favorite_bookmark(bookmark_id, token)
    else:
        await unfavorite_bookmark(bookmark_id, token)

    # Fetch updated details to get new favorite state
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
        "content-type": "application/json",
    }
    details = await requests.get(f"{config.READECK_BASE_URL}/api/bookmarks/{bookmark_id}", headers=headers)
    details.raise_for_status()
    info = details.json()
    is_favorite = info.get("is_marked", False)

    # Try to detect context (detail or end-of-article) by inspecting the message text/buttons if needed
    # For simplicity, always show all actions except in the end-of-article case (where only archive+fav are shown)
    # If only archive+fav are present, keep that layout

    # Try to detect if the message has an Archive button (end-of-article)
    current_markup = query.message.reply_markup
    show_archive = False
    if current_markup:
        for row in current_markup.inline_keyboard:
            for btn in row:
                if btn.text == "Archive":
                    show_archive = True

    reply_markup = build_inline_keyboard(
        bookmark_id,
        is_favorite,
        show_read=not show_archive,
        show_publish=not show_archive,
        show_epub=not show_archive,
        show_summarize=not show_archive and bool(llm),
        show_archive=show_archive
    )

    try:
        await query.edit_message_reply_markup(reply_markup=reply_markup)
    except Exception as e:
        # Ignore "Message is not modified" error, log others
        if "Message is not modified" not in str(e):
            logger.error(f"Failed to update inline keyboard: {e}")


async def epub_handler(update: Update, context: CallbackContext) -> None:
    """
    Handle dynamic md_<bookmark_id> to fetch markdown.
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    text = query.data.strip()

    _, bookmark_id = text.split("_")

    user_id = update.effective_user.id
    token = config.USER_TOKEN_MAP.get(str(user_id))
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
    token = config.USER_TOKEN_MAP.get(str(user_id))
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
    list_url = f"{config.READECK_BASE_URL}/api/bookmarks"
    list_response = await requests.get(list_url, headers={**headers, "accept": "application/json"}, params=params)

    bookmarks = list_response.json()
    bookmark_ids = [b.get("id") for b in bookmarks if b.get("id")]

    if not bookmark_ids:
        await update.message.reply_text("There is no unread bookmarks. ")
        return

    await update.message.reply_text(f"Found {len(bookmark_ids)} unread bookmarks. Downloading epub.")

    epub_url = f"{config.READECK_BASE_URL}/api/bookmarks/export.epub"
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
        patch_url = f"{config.READECK_BASE_URL}/api/bookmarks/{bid}"
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
    token = config.USER_TOKEN_MAP.get(str(user_id))
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
    token = config.USER_TOKEN_MAP.get(str(user_id))
    bookmarks = await fetch_bookmarks(token, search=query)
    if not bookmarks:
        await update.message.reply_text("No bookmarks found.")
        return
    message = format_list(bookmarks)
    # TODO format markdown
    await update.message.reply_markdown_v2(markdownify(message))


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
    token = config.USER_TOKEN_MAP.get(str(user_id))
    if not token:
        await query.message.reply_text("I don't have your Readeck token. Use /token or /register <password>.")
        return

    # Fetch the bookmark's markdown content
    md_content = await fetch_article_markdown(bookmark_id, token)

    page_link = await telegraph.create_page(update.effective_user, md_content)
    await query.message.reply_text(f"Your article is live at: {page_link}")


async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, "message") and update.message:
        try:
            await update.message.reply_text("Having troubles now... try later.")
        except Exception as e:
            logger.error(f"Error sending error message: {e}")


def main():
    application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("register", register_command))
    application.add_handler(CommandHandler("token", token_command))
    application.add_handler(CommandHandler("epub", epub_command))
    application.add_handler(CommandHandler("version", version_command))
    application.add_handler(CommandHandler("restart", restart_command))

    application.add_handler(CommandHandler("unarchived", unarchived_command))
    application.add_handler(CommandHandler("search", search_command))

    application.add_handler(CallbackQueryHandler(read_handler, pattern=r"^read_"))
    application.add_handler(CallbackQueryHandler(publish_handler, pattern=r"^pub_"))
    application.add_handler(CallbackQueryHandler(epub_handler, pattern=r"^epub_"))
    application.add_handler(CallbackQueryHandler(archive_bookmark_handler, pattern=r"^archive_"))
    application.add_handler(CallbackQueryHandler(favorite_bookmark_handler, pattern=r"^(favorite|unfavorite)_"))
    if llm:
        application.add_handler(CallbackQueryHandler(summarize_handler, pattern=r"^summarize_"))

    # Non-command messages (likely bookmarks)
    application.add_handler(MessageHandler(filters.Regex(r"^/b_\w+"), handle_detail_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.add_error_handler(error_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
