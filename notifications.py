import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
dp = Dispatcher()

if bot:
    @dp.message(Command("start"))
    async def start_command(message: Message):
        await message.answer(
            "Привет! Я бот для уведомлений от планировщика.\n"
            "Укажите ваш Telegram ID в профиле на сайте, чтобы получать уведомления."
        )

async def run_bot():
    if bot:
        await dp.start_polling(bot)
    else:
        await asyncio.Event().wait()

async def send_telegram_notification(telegram_id: str, text: str):
    if not bot:
        return
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")

def start_bot_background():
    if bot:
        asyncio.create_task(run_bot())
