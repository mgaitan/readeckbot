import asyncio
import pytest
from telegram import Bot, Message
from typing import Optional


async def get_bot_response(bot: Bot, message_id: int) -> Optional[str]:
    """Helper function to get bot response"""
    # Wait for the bot to process and respond
    await asyncio.sleep(2)

    # Get the most recent updates
    updates = await bot.get_updates()

    # Find the bot's response to our command
    for update in reversed(updates):
        if (
            update.message
            and update.message.reply_to_message
            and update.message.reply_to_message.message_id == message_id
        ):
            return update.message.text

    return None


@pytest.mark.asyncio
async def test_bot_start_command(telegram_bot: Bot, chat_id: str, send_telegram_message: str):
    """Test the /start command with the real bot"""

    message_id = send_telegram_message("/start")
    bot_response = await get_bot_response(telegram_bot, message_id)

    assert bot_response is not None, "No bot response found for the /start command"
    assert "Hi! Send me a URL to save it on Readeck" in bot_response


@pytest.mark.asyncio
async def test_bot_token_command(telegram_bot: Bot, chat_id: str, readeck_token: str, send_telegram_message: str):
    """Test the /token command with the real bot"""

    message_id = send_telegram_message(f"/token {readeck_token}")
    bot_response = await get_bot_response(telegram_bot, message.message_id)

    assert bot_response is not None, "No bot response found for the /token command"
    assert "Your Readeck token has been saved" in bot_response
