import asyncio
import logging
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# --- КОНФИГУРАЦИЯ БОТА ---
TOKEN = "8926963218:AAFgFkzC6eNMAM5i5CQQxiIv0E5rHqoG4JE"
TOGETHER_API_KEY = "tgp_v1_9P6y0kMQFvxzzo3yFpyF21ryGKMm2_4p06HzpHOb-P0"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавлен точный B2B-путь генерации картинок, чтобы избежать редиректа на Webflow
ai_client = AsyncOpenAI(
    api_key=TOGETHER_API_KEY,
    base_url="https://together.xyz"
)

# --- НАСТРОЙКА БАЗЫ ДАННЫХ SQLITE ---
DB_NAME = "users.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_limit INTEGER DEFAULT 5,
            is_premium INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def check_user_limit(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT free_limit, is_premium FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        return True, 5, False
    
    free_limit, is_premium = row
    conn.close()
    
    if is_premium == 1:
        return True, 999, True
    
    if free_limit > 0:
        return True, free_limit, False
        
    return False, 0, False

def decrease_limit(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET free_limit = free_limit - 1 WHERE user_id = ? AND is_premium = 0", (user_id,))
    conn.commit()
    conn.close()

# --- ФОНОВЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- ФУНКЦИЯ ПЕРЕВОДА С РУССКОГО НА АНГЛИЙСКИЙ ---
async def translate_to_english(text: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            url = "https://googleapis.com"
            params = {
                "client": "gtx",
                "sl": "auto",
                "tl": "en",
                "dt": "t",
                "q": text
            }
            response = await client.get(url, params=params, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                translated_text = "".join([part for part in result if part])
                return translated_text.strip()
    except Exception as e:
        logging.error(f"Помилка перекладу: {e}")
    return text

# --- ХЕНДЛЕРЫ ТЕЛЕГРАМ БОТА ---
@dp.message(Command("start"))
async def start(message: types.Message):
    can_generate, limit, is_prem = check_user_limit(message.from_user.id)
    
    text = (
        f"👋 Привет, {message.from_user.first_name}! Добро пожаловать в **Syntax AI** 🚀\n\n"
        f"Я генерирую невероятные изображения с помощью передовой нейросети **Flux 1 Schnell**.\n"
    )
    if not is_prem:
        text += f"🎁 Вам доступно: **{limit} бесплатных генераций**."
    else:
        text += "👑 У вас активирована безлимитная **Premium подписка**!"
        
    text += "\n\nПросто напиши мне описание картинки на **любом языке** (я всё пойму и переведу сам)!"
    await message.answer(text, parse_mode="Markdown")

@dp.message()
async def generate_image(message: types.Message):
    user_id = message.from_user.id
    can_generate, limit, is_prem = check_user_limit(user_id)
    
    if not can_generate:
        await message.answer(
            "❌ **У вас закончились бесплатные генерации!**\n\n"
            "Чтобы продолжить создавать шедевры без ограничений, оформляйте Premium-подписку всего за **150 грн / месяц**.\n\n"
            "💳 _Для активации подписки обратитесь к администратору._",
            parse_mode="Markdown"
        )
        return

    wait = await message.answer(f"🎨 **Syntax AI** создаёт ваше изображение... (Осталось попыток: {limit if not is_prem else '∞'})")

    try:
        # Переводим запрос
        english_prompt = await translate_to_english(message.text)
        logging.info(f"Оригинал: {message.text} -> Перевод: {english_prompt}")
        
        # Генерируем картинку по чистому B2B пути
        response = await ai_client.images.generate(
            model="black-forest-labs/FLUX.1-schnell",
            prompt=english_prompt,
            size="1024x768",
            n=1
        )
        
        image_url = response.data.url
        
        if not image_url:
            raise Exception("Не удалось извлечь URL из ответа нейросети.")
        
        # Отправляем готовое фото в Telegram
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=image_url.strip(),
            caption=f"✅ **Готово по вашему запросу:**\n_{message.text}_",
            parse_mode="Markdown"
        )
        
        decrease_limit(user_id)
        await wait.delete()

    except Exception as e:
        logging.error(f"Помилка генерації Together: {e}")
        await wait.edit_text(f"❌ Ошибка нейросети: {str(e)[:150]}")

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    threading.Thread(target=start_health_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
