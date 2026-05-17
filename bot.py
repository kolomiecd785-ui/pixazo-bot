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
        return

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
            # МЕНЯЕМ НА ПРЯМОЙ ОБХОДНОЙ ШЛЮЗ БЭКЭНДА
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
            
            # Если первый шлюз выбивает ошибку JSON, автоматически пробуем прямой Node-хост Pixazo
            if resp.status_code != 200 or "application/json" not in resp.headers.get("Content-Type", "").lower():
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

            # Тотальная проверка ответа сервера перед чтением JSON
            content_type = resp.headers.get("Content-Type", "").lower()
            if "application/json" not in content_type:
                raw_response = resp.text.strip() if resp.text else f"Порожня відповідь (Код {resp.status_code})"
                raise Exception(f"Pixazo відхилив запит. Текст відповіді: {raw_response[:100]}")
            
            result = resp.json()
            logging.info(f"Завдання створено: {result}")
            
            # Пробуем достать прямую ссылку на готовую картинку (если шлюз выдал её сразу)
            image_url = result.get("output") or result.get("url") or result.get("data", {}).get("url")
            
            # Если шлюз асинхронный и выдал ссылку на опрос статуса
            polling_url = result.get("polling_url")
            request_id = result.get("request_id")
            
            if not image_url and (polling_url or request_id):
                if not polling_url:
                    polling_url = f"https://pixazo.ai{request_id}"
                
                max_attempts = 20
                for attempt in range(max_attempts):
                    await asyncio.sleep(3)
                    
                    try:
                        await wait.edit_text(f"🎨 Нейромережа малює... Спроба {attempt + 1}/{max_attempts}")
                    except Exception:
                        pass
                    
                    status_resp = await client.get(polling_url, headers={"Ocp-Apim-Subscription-Key": PIXAZO_KEY})
                    if "application/json" not in status_resp.headers.get("Content-Type", "").lower():
                        continue
                        
                    status_data = status_resp.json()
                    if status_data.get("status", "").upper() == "COMPLETED":
                        image_url = status_data.get("output") or status_data.get("url") or status_data.get("data", {}).get("url")
                        break
                    elif status_data.get("status", "").upper() in ["FAILED", "ERROR"]:
                        raise Exception(f"Збій генерації: {status_data.get('error')}")

            if not image_url:
                raise Exception("Не вдалося знайти або дочекатися посилання на медіафайл.")
            
            # Отправляем прямую ссылку в Telegram. Сервера TG сами скачают её из облака
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=image_url.strip(),
                caption=f"✅ Готово!\n\n{message.text}"
            )
            await wait.delete()

    except Exception as e:
        logging.error(f"Помилка: {e}")
        await wait.edit_text(f"❌ Помилка шлюзу Pixazo: {str(e)[:300]}")

async def main():
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=start_health_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
