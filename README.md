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


### How to setup
Create a `.env`

```
TELEGRAM_BOT_TOKEN=<your_bot_token>
READECK_BASE_URL=<your_readec_url>
READECK_CONFIG=<path_to_config.yaml>    # optional.
```

run with `uv run bot.py` and voilá, you can chat with your token

Happy reading! 
