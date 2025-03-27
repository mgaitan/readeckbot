A Telegram bot that interfaces with a self-hosted Readeck instance to manage bookmarks.

Features:

- /register (create a new user) or /token to register the bot with an existent user
- Save bookmarks by sending a URL (with optional title and tags).
- Read. Create a simplified version of the article in telegra.ph
- /md_<id> return the raw markdown
- /list  . unread articles 
- /epub generate an epub with the unread articles


### How to setup
Create a `.env`

```
TELEGRAM_BOT_TOKEN=<your_bot_token>
READECK_BASE_URL=<your_readec_url>
READECK_CONFIG=<path_to_config.yaml>    # optional.
READECK_DATA=/PATH/TO/data    # optional.
```

run with `uv run readeckbot` and voilá, you can chat with your token

Happy reading! 
