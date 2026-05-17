import asyncio
import logging
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from dotenv import load_dotenv

load_dotenv()

# Ключи и токены — строго на своих местах
TOKEN = "8926963218:AAFgFkzC6eNMAM5i5CQQxiIv0E5rHqoG4JE"
PIXAZO_KEY = "dbc1fb526852431887f60f64488ebea3"

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("👋 Привіт! Бот успішно підключений до стабільного B2B шлюзу Pixazo.\nНапиши мені опис картинки.")

@dp.message()
async def generate(message: types.Message):
    wait = await message.answer("⏳ Надсилаю промпт до черги Pixazo. Будь ласка, зачекайте...")

    try:
        timeout = httpx.Timeout(60.0, connect=10.0)
        
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            # СТАДИЯ 1: Отправляем запрос на создание картинки
            resp = await client.post(
                "https://pixazo.ai",
                json={
                    "prompt": message.text,
                    "image_size": "landscape_16_9",
                    "n": 1,
                    "locale": "en-US"  # Обязательный параметр локализации для европейских IP-адресов
                },
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "Ocp-Apim-Subscription-Key": PIXAZO_KEY 
                }
            )
            
            # АБСОЛЮТНАЯ ЗАЩИТА: Проверяем тип ответа до вызова .json()
            content_type = resp.headers.get("Content-Type", "").lower()
            
            if "application/json" not in content_type:
                # Если сервер Pixazo сбросил сессию или выдал ошибку авторизации
                raw_text = resp.text.strip() if resp.text else f"Порожня відповідь сервера (Код: {resp.status_code})"
                raise Exception(f"Шлюз відхилив запит промпту. Деталі: {raw_text[:150]}")
            
            # Если всё ок и пришел JSON — парсим его
            result = resp.json()
            logging.info(f"Завдання створено успішно: {result}")
            
            # Если Pixazo вернул скрытую ошибку внутри JSON структуры
            if "error" in result or "message" in result and resp.status_code != 200:
                error_msg = result.get("error", {}).get("message") or result.get("message", "Невідома помилка ключа")
                raise Exception(f"API Error: {error_msg}")
            
            polling_url = result.get("polling_url")
            request_id = result.get("request_id")
            
            if not polling_url and request_id:
                polling_url = f"https://pixazo.ai{request_id}"
                
            if not polling_url:
                # На случай, если для Schnell-модели картинка отдалась мгновенно прямо в первом ответе
                image_url = result.get("output") or result.get("url") or result.get("data", {}).get("url")
                if image_url:
                    await bot.send_photo(chat_id=message.chat.id, photo=image_url.strip(), caption=f"✅ Готово!\n\n{message.text}")
                    await wait.delete()
                    return
                raise Exception("Сервер не повернув посилання для відстеження статусу генерації.")
            
            # СТАДИЯ 2: Цикл ожидания готовности картинки (Polling)
            image_url = None
            max_attempts = 25  
            
            for attempt in range(max_attempts):
                await asyncio.sleep(3)  
                
                try:
                    await wait.edit_text(f"🎨 Нейромережа малює... Спроба {attempt + 1}/{max_attempts}")
                except Exception:
                    pass  
                
                status_resp = await client.get(
                    polling_url,
                    headers={"Ocp-Apim-Subscription-Key": PIXAZO_KEY}
                )
                
                status_content_type = status_resp.headers.get("Content-Type", "").lower()
                if "application/json" not in status_content_type:
                    raw_status = status_resp.text.strip().upper()
                    logging.info(f"Отримано текстовий статус: {raw_status}")
                    continue
                
                status_data = status_resp.json()
                logging.info(f"Статус генерації (JSON): {status_data}")
                
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
                    raise Exception(f"Нейромережа повернула помилку: {status_data.get('error', 'Збій генерації')}")
            
            if not image_url:
                raise Exception("Час очікування генерації вичерпано. Сервер Pixazo перевантажений.")
            
            # СТАДИЯ 3: Отправляем готовое фото в Telegram
            try:
                await wait.edit_text("🚀 Завантажую фото в чат...")
            except Exception:
                pass
                
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=image_url.strip(),
                caption=f"✅ Готово!\n\n{message.text}"
            )
            await wait.delete()

    except Exception as e:
        logging.error(f"Помилка під час генерації: {e}")
        await wait.edit_text(f"❌ Помилка: {str(e)[:300]}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
