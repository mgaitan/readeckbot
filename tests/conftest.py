import os
import subprocess
import pytest
import threading
import time
import requests

# Telegram namespace conflict!
# https://github.com/alexander-akhmetov/python-telegram/issues/207
from telegram import Bot
from telegram.client import Telegram

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TEST_TELEGRAM_BOT_TOKEN = os.getenv("TEST_TELEGRAM_BOT_TOKEN")
TEST_CHAT_ID = os.getenv("TEST_CHAT_ID")
TEST_READECK_BASE_URL = os.getenv("TEST_READECK_BASE_URL")

TEST_API_ID = os.getenv("TEST_API_ID")
TEST_API_HASH = os.getenv("TEST_API_HASH")
TEST_PHONE = os.getenv("TEST_PHONE")
TEST_DATABASE_ENCRYPTION_KEY = os.getenv("TEST_DATABASE_ENCRYPTION_KEY")


if (
    not TEST_TELEGRAM_BOT_TOKEN
    or not TEST_CHAT_ID
    or not TEST_READECK_BASE_URL
    or not TEST_API_ID
    or not TEST_API_HASH
    or not TEST_PHONE
    or not TEST_DATABASE_ENCRYPTION_KEY
):
    raise ValueError("Some TEST environment variables are not set")


@pytest.fixture(scope="session")
def bot_token():
    """Fixture to provide the test telegram bot token"""
    return TEST_TELEGRAM_BOT_TOKEN


@pytest.fixture(scope="session")
def chat_id():
    """Fixture to provide the test chat ID"""
    return TEST_CHAT_ID


@pytest.fixture(scope="session", autouse=True)
def run_bot():
    """Fixture to run the bot in a separate process."""

    # Start the bot in a separate process
    process = subprocess.Popen(
        ["uv", "run", "readeckbot"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # Use the test token for the main bot
        env={**os.environ, "TELEGRAM_BOT_TOKEN": TEST_TELEGRAM_BOT_TOKEN, "READECK_BASE_URL": TEST_READECK_BASE_URL},
    )

    # Wait for the bot to start
    time.sleep(5)

    yield process

    # Cleanup
    process.terminate()
    process.wait()


@pytest.fixture(scope="session")
def readeck_temp_dir(tmp_path_factory):
    """Fixture to provide a temporary directory for Readeck"""
    return tmp_path_factory.mktemp("readeck")


@pytest.fixture(scope="session", autouse=True)
def readeck_server(readeck_temp_dir):
    """Fixture to run the Readeck server"""

    port = TEST_READECK_BASE_URL.split(":")[-1]
    # Start the server in the shared temp directory
    process = subprocess.Popen(
        ["readeck", "serve", "--port", f"{port}"],
        cwd=readeck_temp_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for the server to start
    time.sleep(2)

    yield process

    # Cleanup
    process.terminate()
    process.wait()


@pytest.fixture(scope="session")
def readeck_user(readeck_temp_dir):
    """Fixture to create a test user in Readeck"""
    try:
        create_user = subprocess.run(
            ["readeck", "user", "-u", "test", "-p", "test_pass"],
            cwd=readeck_temp_dir,  # Use the same temp directory
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        print("User created successfully:", create_user.stdout.decode())
        return {"username": "test", "password": "test_pass"}
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to create user: {e.stderr.decode()}")


@pytest.fixture(scope="session")
def readeck_token(readeck_server, readeck_user):
    """Fixture to get authentication token from Readeck"""
    try:
        url = "http://localhost:8005/api/auth"
        headers = {"accept": "application/json", "content-type": "application/json"}
        data = {"username": readeck_user["username"], "password": readeck_user["password"], "application": "api doc"}

        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        token = response.json().get("token")

        if not token:
            raise ValueError("No token received from Readeck server")

        return token

    except Exception as e:
        print("Response text:", getattr(response, "text", "No response"))
        raise Exception(f"Failed to get Readeck token: {e}")


@pytest.fixture(scope="function")
async def telegram_bot(bot_token: str):
    """Fixture to provide a fresh bot instance for each test"""
    bot = Bot(bot_token)
    # Clear any previous updates
    await bot.get_updates(offset=-1)
    yield bot
    # Clean up
    await bot.close()


@pytest.fixture(scope="session")
def send_telegram_message():
    """Fixture to provide the send_telegram_message function"""

    def _send(text: str) -> bool:
        """
        Send a message to a specific chat using the configured Telegram account.

        Args:
            text (str): The message text to send
        """
        chat_id = TEST_CHAT_ID.split(":")[0]  # Using BOT_ID to identify the chat

        try:
            # Initialize the Telegram client
            # Namespace Conflict!
            tg = Telegram(
                api_id=TEST_API_ID,
                api_hash=TEST_API_HASH,
                phone=TEST_PHONE,
                database_encryption_key=TEST_DATABASE_ENCRYPTION_KEY,
            )

            # Login to the account
            login_result = tg.login()
            # Get chats to ensure proper initialization
            get_chats_result = tg.get_chats()
            get_chats_result.wait()

            if get_chats_result.error:
                return False

            # Send the message
            send_message_result = tg.send_message(
                chat_id=chat_id,
                text=text,
            )
            send_message_result.wait()

            # Create event for message confirmation
            message_has_been_sent = threading.Event()
            new_message_id = None

            def update_message_send_succeeded_handler(update):
                nonlocal new_message_id
                if update["old_message_id"] == send_message_result.update["id"]:
                    new_message_id = update["message"]["id"]
                    message_has_been_sent.set()

            # Add handler for message confirmation
            tg.add_update_handler("updateMessageSendSucceeded", update_message_send_succeeded_handler)

            # Wait for message confirmation
            message_has_been_sent.wait(timeout=60)

            return new_message_id

        except Exception as e:
            return e

        finally:
            # Always stop the client
            if "tg" in locals():
                tg.stop()

    return _send
