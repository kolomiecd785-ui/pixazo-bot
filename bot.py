import logging
import asyncio
from aiogram import Bot, Dispatcher, html, F
from aiogram.types import Message
from aiogram.filters import CommandStart

# Вставьте сюда токен вашего бота из @BotFather
TOKEN = "ВАШ_ТОКЕН_БОТА"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"Привет, {message.from_user.full_name}!\n"
        f"Твой Telegram User ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML"
    )

# Обработчик любого текста (защищен от падений из-за HTML)
@dp.message(F.text)
async def handle_text(message: Message):
    # Если в тексте будет '<!DOCTYPE html>', функция html.quote() сделает его безопасным
    safe_text = html.quote(message.text)
    
    await message.answer(
        f"Вы написали: {safe_text}", 
        parse_mode="HTML"
    )

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
