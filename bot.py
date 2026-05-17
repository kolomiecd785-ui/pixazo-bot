import asyncio
import logging
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
import httpx
from dotenv import load_dotenv

load_dotenv()

# --- КОНФИГУРАЦИЯ БОТА ---
TOKEN = "8926963218:AAFgFkzC6eNMAM5i5CQQxiIv0E5rHqoG4JE"
TOGETHER_API_KEY = "tgp_v1_9P6y0kMQFvxzzo3yFpyF21ryGKMm2_4p06HzpHOb-P0"

bot = Bot(token=TOKEN)
dp = Dispatcher()

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

# --- ХЕНДЛЕРЫ ТЕЛЕГРАМ БОТА ---
@dp.message(Command("start"))
async def start(message: types.Message):
    can_generate, limit, is_prem = check_user_limit(message.from_user.id)
    
    text = (
        f"👋 Привіт, {message.from_user.first_name}! Ласкаво просимо до **Syntax AI** 🚀\n\n"
        f"Я генерую неймовірні зображення за допомогою моделі **Flux 1 Schnell** від Together AI.\n"
    )
    if not is_prem:
        text += f"🎁 Вам доступно: **{limit} безкоштовних генерацій**."
    else:
        text += "👑 У вас активована безлімітна **Premium підписка**!"
        
    text += "\n\nПросто напиши мені опис картинки англійською мовою."
    await message.answer(text, parse_mode="Markdown")

@dp.message()
async def generate_image(message: types.Message):
    user_id = message.from_user.id
    can_generate, limit, is_prem = check_user_limit(user_id)
    
    if not can_generate:
        await message.answer(
            "❌ **У вас закінчилися безкоштовні генерації!**\n\n"
            "Щоб продовжити створювати шедеври без обмежень, оформлюйте Premium-підписку всього за **150 грн / місяць**.\n\n"
            "💳 _Для активації підписки зверніться до адміністратора або натисніть кнопку ниже._",
            parse_mode="Markdown"
        )
        return

    wait = await message.answer(f"🎨 **Syntax AI** створює ваше зображення... (Залишилось спроб: {limit if not is_prem else '∞'})")

    try:
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            
            # Официальный B2B запрос к Together AI
            resp = await client.post(
                "https://together.xyz",
                json={
                    "model": "black-forest-labs/FLUX.1-schnell",
                    "prompt": message.text,
                    "width": 1024,
                    "height": 576,
                    "steps": 4,
                    "n": 1
                },
                headers={
                    "Authorization": f"Bearer {TOGETHER_API_KEY}",
                    "Content-Type": "application/json"
                }
            )
            
            if resp.status_code != 200:
                raise Exception(f"Together AI HTTP {resp.status_code}: {resp.text[:150]}")
                
            result = resp.json()
            logging.info(f"Відповідь Together AI: {result}")
            
            # ИСПРАВЛЕННЫЙ ТОЧНЫЙ ПАРСИНГ: Извлекаем ссылку из массива data
            image_url = None
            if "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                image_url = result["data"][0].get("url")
                
            if not image_url:
                raise Exception(f"Не вдалося знайти URL у відповіді: {str(result)[:100]}")
            
            # Отправляем фото по прямой ссылке
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=image_url.strip(),
                caption=f"✅ **Готово за запитом:**\n_{message.text}_",
                parse_mode="Markdown"
            )
            
            decrease_limit(user_id)
            await wait.delete()

    except Exception as e:
        logging.error(f"Помилка генерації Together AI: {e}")
        await wait.edit_text(f"❌ Помилка нейромережі: {str(e)[:150]}")

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    threading.Thread(target=start_health_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
