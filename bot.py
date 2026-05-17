import asyncio
import logging
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# --- КОНФИГУРАЦИЯ БОТА ---
TOKEN = "8926963218:AAFgFkzC6eNMAM5i5CQQxiIv0E5rHqoG4JE"
TOGETHER_API_KEY = "tgp_v1_9P6y0kMQFvxzzo3yFpyF21ryGKMm2_4p06HzpHOb-P0"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Инициализируем клиента под стандарты Together AI
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
            params = {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text}
            response = await client.get(url, params=params, timeout=5.0)
            if response.status_code == 200:
                result = response.json()
                if result and isinstance(result, list) and len(result) > 0:
                    translated_parts = []
                    for part in result[0]:
                        if part and isinstance(part, list) and len(part) > 0:
                            translated_parts.append(str(part[0]))
                    if translated_parts:
                        return "".join(translated_parts).strip()
    except Exception as e:
        logging.error(f"Помилка перекладу: {e}")
    return text

# --- КНОПКА КУПИТЬ ПОДПИСКУ ---
def get_payment_keyboard():
    buttons = [
        [InlineKeyboardButton(text="💳 Оформить Premium (150 грн)", url="https://t.me")] # Ссылка на ваш профиль для ручной оплаты, пока не подключен банк
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ХЕНДЛЕРЫ ТЕЛЕГРАМ БОТА ---
@dp.message(Command("start"))
async def start(message: types.Message):
    can_generate, limit, is_prem = check_user_limit(message.from_user.id)
    text = (
        f"👋 Привет, {message.from_user.first_name}! Добро пожаловать в **Syntax AI** 🚀\n\n"
        f"💡 **Я умею абсолютно всё:**\n"
        f"1. 📝 **Писать тексты**, статьи, посты, отвечать на любые вопросы (просто пиши мне).\n"
        f"2. 🎨 **Генерировать картинки** через ИИ Flux. Начни запрос со слова **нарисуй**, **картинка** или **фото**.\n\n"
    )
    if not is_prem:
        text += f"🎁 Вам доступно: **{limit} бесплатных попыток** (для текста и фото)."
    else:
        text += "👑 У вас активирована безлимитная **Premium подписка**!"
    await message.answer(text, parse_mode="Markdown")

@dp.message()
async def handle_user_request(message: types.Message):
    user_id = message.from_user.id
    can_generate, limit, is_prem = check_user_limit(user_id)
    
    if not can_generate:
        await message.answer(
            "❌ **У вас закончились бесплатные попытки!**\n\n"
            "Чтобы продолжить общаться и создавать шедевры без ограничений, оформляйте Premium-подписку всего за **150 грн / месяц**.",
            reply_markup=get_payment_keyboard(),
            parse_mode="Markdown"
        )
        return

    user_text = message.text.lower().strip()
    
    # СЦЕНАРИЙ 1: ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЯ
    if user_text.startswith(("нарисуй", "картинка", "фото", "draw", "image", "picture")):
        wait = await message.answer(f"🎨 **Syntax AI** генерирует ваше изображение... (Осталось попыток: {limit if not is_prem else '∞'})")
        try:
            clean_prompt = message.text
            for word in ["нарисуй", "картинка", "фото", "draw", "image", "picture"]:
                if user_text.startswith(word):
                    clean_prompt = clean_prompt[len(word):].strip()
            
            english_prompt = await translate_to_english(clean_prompt)
            
            response = await ai_client.images.generate(
                model="black-forest-labs/FLUX.1-schnell",
                prompt=english_prompt,
                n=1
            )
            
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавлен индекс [0] для извлечения ссылки по стандартам SDK
            image_url = response.data[0].url
            
            if not image_url:
                raise Exception("Не удалось извлечь URL из ответа нейросети.")
            
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=image_url.strip(),
                caption=f"✅ **Готово по вашему запросу:**\n_{clean_prompt}_",
                parse_mode="Markdown"
            )
            decrease_limit(user_id)
            await wait.delete()
        except Exception as e:
            logging.error(f"Помилка фото: {e}")
            await wait.edit_text(f"❌ Ошибка нейросети при создании фото: {str(e)[:150]}")

    # СЦЕНАРИЙ 2: ТЕКСТОВЫЙ ДИАЛОГ
    else:
        wait = await message.answer("⚡ **Syntax AI** думает над ответом...")
        try:
            response = await ai_client.chat.completions.create(
                model="meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                messages=[
                    {"role": "system", "content": "Ты профессиональный ИИ-ассистент Syntax AI. Отвечай дружелюбно, четко, информативно и строго на языке пользователя."},
                    {"role": "user", "content": message.text}
                ],
                max_tokens=1500
            )
            
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавлен индекс [0] для извлечения текстового ответа
            reply_text = response.choices[0].message.content
            
            await message.answer(reply_text)
            decrease_limit(user_id)
            await wait.delete()
        except Exception as e:
            logging.error(f"Помилка тексту: {e}")
            await wait.edit_text(f"❌ Ошибка нейросети при создании текста: {str(e)[:150]}")

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    threading.Thread(target=start_health_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
