import os

from dotenv import load_dotenv

from .helpers import PersistentDict

# Load environment variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
READECK_BASE_URL = os.getenv("READECK_BASE_URL", "http://localhost:8000")
READECK_CONFIG = os.getenv("READECK_CONFIG", None)
READECK_DATA = os.getenv("READECK_DATA", None)
USER_TOKEN_MAP = PersistentDict(".user_tokens.json")


# -- NEW: Attempt to enable LLM summarization
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash-lite")
LLM_KEY = os.getenv("LLM_KEY")
LLM_SUMMARY_MAX_LENGTH = int(os.getenv("LLM_SUMMARY_MAX_LENGTH", "2500"))

USER_TELEGRAPH = PersistentDict(".user_telegraph.json")


__all__ = [
    "TELEGRAM_BOT_TOKEN",
    "READECK_BASE_URL",
    "READECK_CONFIG",
    "READECK_DATA",
    "USER_TOKEN_MAP",
    "USER_TELEGRAPH",
    "LLM_MODEL",
    "LLM_KEY",
    "LLM_SUMMARY_MAX_LENGTH",
]
