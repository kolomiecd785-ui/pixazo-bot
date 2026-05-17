import asyncio
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
import httpx
from dotenv import load_dotenv

load_dotenv()

# Ключи и токены
TOKEN = "8926963218:AAFgFkzC6eNMAM5i5CQQxiIv0E5rHqoG4JE"
PIXAZO_KEY = "dbc1fb526852431887f60f64488ebea3"

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- ФОНОВЫЙ ВЕБ-СЕРВЕР ДЛЯ ОБХОДА ПРОВЕРОК RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return  # Отключаем лишний спам в логи

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info(f"Фоновий веб-сервер запущено на порту {port}")
    server.serve_forever()
# -----------------------------------------------------

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("👋 Привіт! Бот успішно запущений в хмарі Render.\nНапиши мені опис картинки.")

@dp.message()
async def generate(message: types.Message):
    wait = await message.answer("⏳ Завдання додано в чергу Pixazo. Будь ласка, зачекайте...")

    try:
        timeout = httpx.Timeout(60.0, connect=10.0)
        
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(
                "https://pixazo.ai",
                json={
                    "prompt": message.text,
                    "image_size": "landscape_16_9"
                },
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "Ocp-Apim-Subscription-Key": PIXAZO_KEY 
                }
            )
            
            if resp.status_code not in [200, 201, 202]:
                raise Exception(f"HTTP {resp.status_code}: {resp.text[:150]}")
            
            result = resp.json()
            logging.info(f"Завдання створено: {result}")
            
            polling_url = result.get("polling_url")
            request_id = result.get("request_id")
            
            if not polling_url and request_id:
                polling_url = f"https://pixazo.ai{request_id}"
                
            if not polling_url:
                image_url = result.get("output") or result.get("url")
                if image_url:
                    await bot.send_photo(chat_id=message.chat.id, photo=image_url.strip(), caption=f"✅ Готово!\n\n{message.text}")
                    await wait.delete()
                    return
                raise Exception("Сервер не повернув посилання для відстеження статусу.")
            
            image_url = None
            max_attempts = 25  
            
            for attempt in range(max_attempts):
                await asyncio.sleep(3)
                
                try:
                    await wait.edit_text(f"🎨 Нейромережа малює... Спроба {attempt + 1}/{max_attempts}")
                except Exception:
                    pass
                
                status_resp = await client.get(polling_url, headers={"Ocp-Apim-Subscription-Key": PIXAZO_KEY})
                
                if status_resp.status_code not in [200, 201, 202]:
                    continue
                
                status_content_type = status_resp.headers.get("Content-Type", "").lower()
                if "application/json" not in status_content_type:
                    continue
                
                status_data = status_resp.json()
                current_status = status_data.get("status", "").upper()
                
                if current_status == "COMPLETED":
                    image_url = status_data.get("output") or status_data.get("url")
                    if not image_url and "data" in status_data:
                        if isinstance(status_data["data"], dict):
                            image_url = status_data["data"].get("url")
                        elif isinstance(status_data["data"], list) and len(status_data["data"]) > 0:
                            image_url = status_data["data"][0].get("url") if isinstance(status_data["data"][0], dict) else status_data["data"][0]
                    break
                elif current_status in ["FAILED", "ERROR"]:
                    raise Exception(f"Збій генерації: {status_data.get('error', 'Помилка')}")
            
            if not image_url:
                raise Exception("Час очікування генерації вичерпано.")
            
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=image_url.strip(),
                caption=f"✅ Готово!\n\n{message.text}"
            )
            await wait.delete()

    except Exception as e:
        logging.error(f"Помилка: {e}")
        await wait.edit_text(f"❌ Помилка: {str(e)[:300]}")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Запускаем фоновый веб-сервер в отдельном потоке, чтобы он не мешал боту
    threading.Thread(target=start_health_server, daemon=True).start()
    
    # Запускаем Telegram-бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
