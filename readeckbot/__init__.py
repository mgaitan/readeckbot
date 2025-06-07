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

__version__ = "0.1.1"
