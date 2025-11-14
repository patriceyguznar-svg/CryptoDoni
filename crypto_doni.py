#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v9 — TronScan Scraper (Render-ready)
"""

import os
import asyncio
import signal
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from openai import OpenAI
from aiohttp import web
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# ==========================
# Конфиг
# ==========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    print("ОШИБКА: Укажи TELEGRAM_TOKEN и OPENAI_API_KEY!")
    sys.exit(1)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# Веб-сервер
# ==========================
async def handle(request):
    return web.Response(text="CryptoDoni v9 — TronScan scraper alive")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер на порту {port}")

# ==========================
# Парсинг TronScan
# ==========================
def scrape_tronscan(address: str) -> dict:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    try:
        print(f"Открываю https://tronscan.org/#/address/{address}")
        driver.get(f"https://tronscan.org/#/address/{address}")
        wait = WebDriverWait(driver, 15)

        # Ждём загрузки баланса
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.account-balance")))

        # TRX
        trx_elem = driver.find_element(By.XPATH, "//span[contains(text(), 'TRX')]/preceding-sibling::span")
        trx_text = trx_elem.text.replace(",", "")
        trx_amount = float(trx_text) if trx_text.replace(".", "").isdigit() else 0.0

        # USDT (ищем в токенах)
        usdt_amount = 0.0
        try:
            usdt_elem = driver.find_element(By.XPATH, "//div[contains(text(), 'USDT')]/following-sibling::div//span")
            usdt_text = usdt_elem.text.replace(",", "")
            usdt_amount = float(usdt_text) if usdt_text.replace(".", "").isdigit() else 0.0
        except:
            pass

        # Транзакции (последние 3)
        txs = []
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "table tr")[1:4]  # Пропускаем заголовок
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 5: continue
                to = cols[2].text[:10] + "..." if cols[2].text else "contract"
                amount = cols[3].text
                time_raw = cols[1].text.split(" ")[0]  # "14.11.2025" → "14.11"
                time = time_raw[:5].replace(".", ".")
                txs.append(f"→ {to} | {amount} | {time}")
        except:
            pass

        # Цена TRX (примерная)
        trx_price = 0.15
        total_usd = trx_amount * trx_price + usdt_amount

        return {
            "network": "TRON",
            "trx_amount": trx_amount,
            "usdt_amount": usdt_amount,
            "total_usd": total_usd,
            "txs": txs
        }
    except Exception as e:
        print(f"Ошибка парсинга: {e}")
        return {"network": "TRON", "trx_amount": 0, "usdt_amount": 0, "total_usd": 0, "txs": []}
    finally:
        driver.quit()

# ==========================
# ИИ-анализ
# ==========================
async def ai_analyze(data: dict) -> str:
    prompt = (
        f"Кошелёк: {data.get('address', '')[:10]}...\n"
        f"TRX: {data['trx_amount']:.2f}, USDT: {data['usdt_amount']:.2f}\n"
        f"Сумма: ${data['total_usd']:.2f}, транзакций: {len(data['txs'])}\n"
        "Это скам? Кратко: СКАМ / НОРМ / РИСК + 1 предложение."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return "ИИ: недоступен"

# ==========================
# Команды
# ==========================
@dp.message(Command("start"))
async def start(msg: Message):
    await msg.answer(
        "<b>CryptoDoni v9 — TronScan парсер!</b>\n\n"
        "Пришли адрес TRON (T...): получишь всё в $!"
    )

@dp.message()
async def handle(msg: Message):
    address = msg.text.strip()
    if not (address.startswith("T") and len(address) == 34):
        await msg.answer("Пришли валидный TRON-адрес (T...34 символа)!")
        return

    await msg.answer("Парсю TronScan... (hourglass)")
    try:
        data = scrape_tronscan(address)
        data["address"] = address  # Добавляем адрес

        short_addr = address[:10] + "..."
        trx_usd = data["trx_amount"] * 0.15
        usdt_usd = data["usdt_amount"]
        total = trx_usd + usdt_usd

        balance_line = f"TRX: {data['trx_amount']:.2f} (~${trx_usd:.2f}) USDT: {data['usdt_amount']:.2f} (~${usdt_usd:.2f})"
        tx_line = "\n".join(data['txs']) if data['txs'] else "нет"

        text = (
            f"<b>Кошелёк:</b> {short_addr} <b>Сеть:</b> {data['network']} <b>Баланс:</b> {balance_line}\n"
            f"<b>Общая сумма: ~${total:.2f}</b>\n"
            f"<b>Транзакции:</b> {tx_line}\n"
            f"<b>ИИ:</b> {await ai_analyze(data)}"
        )

        await msg.answer(text, disable_web_page_preview=True)
    except Exception as e:
        await msg.answer(f"Ошибка: {str(e)}")

# ==========================
# Запуск
# ==========================
async def main():
    print("CryptoDoni v9 запущен!")
    asyncio.create_task(start_web_server())

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.session.close()))

    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
