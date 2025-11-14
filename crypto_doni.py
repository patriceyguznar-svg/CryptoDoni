#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v8 — TRONSCAN SCRAPER
Парсит TronScan + ИИ-анализ
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
    return web.Response(text="CryptoDoni v8 — TronScan scraper alive")

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
    options.add_argument("--headless")  # Без GUI
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(f"https://tronscan.org/#/address/{address}")
        wait = WebDriverWait(driver, 10)

        # Баланс TRX
        trx_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='balance-trx']")))
        trx_text = trx_elem.text.strip()
        trx_amount = float(trx_text.split()[0]) if trx_text else 0.0

        # USD TRX
        usd_trx_elem = driver.find_element(By.CSS_SELECTOR, "[data-testid='balance-usd']")
        usd_trx = float(usd_trx_elem.text.replace('$', '')) if usd_trx_elem.text else 0.0

        # USDT
        usdt_elem = driver.find_element(By.CSS_SELECTOR, "[data-testid='token-usdt']")
        usdt_text = usdt_elem.text.strip()
        usdt_amount = float(usdt_text.split()[0]) if usdt_text and 'USDT' in usdt_text else 0.0

        # USD USDT
        usd_usdt = usdt_amount * 1.0  # USDT = $1

        # Транзакции (3 последние)
        txs = []
        tx_elements = driver.find_elements(By.CSS_SELECTOR, "[data-testid='transaction-row']")[:3]
        for tx in tx_elements:
            to = tx.find_element(By.CSS_SELECTOR, ".to-address").text[:10] + "..."
            amount = tx.find_element(By.CSS_SELECTOR, ".amount").text
            time_elem = tx.find_element(By.CSS_SELECTOR, ".time")
            time = time_elem.text  # '14.11 12:15'
            txs.append(f"→ {to} | {amount} | {time}")

        total_usd = usd_trx + usd_usdt

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
    prompt = f"Кошелёк: {data['address'][:10]}... TRX: {data['trx_amount']:.2f}, USDT: {data['usdt_amount']:.2f}, Сумма: ${data['total_usd']:.2f}, Транзакций: {len(data['txs'])}\nЭто скам? Кратко: СКАМ / НОРМ / РИСК + причина."
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
        "<b>CryptoDoni v8 — TronScan scraper!</b>\n\n"
        "Пришли адрес TRON (T...): Покажу USDT, $, транзакции!"
    )

@dp.message()
async def handle(msg: Message):
    address = msg.text.strip()
    if not (address.startswith("T") and len(address) == 34):
        await msg.answer("Пришли TRON-адрес (T...34 символа)!")
        return

    await msg.answer("Парсю TronScan... (hourglass)")
    try:
        data = scrape_tronscan(address)
        trx_usd = data["trx_amount"] * 0.15  # Примерная цена TRX
        usdt_usd = data["usdt_amount"] * 1.0

        short_addr = address[:10] + "..."
        balance_line = f"TRX: {data['trx_amount']:.2f} (~${trx_usd:.2f}) USDT: {data['usdt_amount']:.2f} (~${usdt_usd:.2f})"
        total = trx_usd + usdt_usd
        tx_line = "\n".join(data['txs']) if data['txs'] else "нет"

        text = (
            f"<b>Кошелёк:</b> {short_addr} <b>Сеть:</b> {data['network']} <b>Баланс:</b> {balance_line}\n"
            f"<b>Общая сумма: ~${total:.2f}</b>\n"
            f"<b>Транзакции:</b> {tx_line}\n"
            f"<b>ИИ:</b> {await ai_analyze({'address': address, 'trx_amount': data['trx_amount'], 'usdt_amount': data['usdt_amount'], 'total_usd': total, 'txs': data['txs']})}"
        )

        await msg.answer(text)
    except Exception as e:
        await msg.answer(f"Ошибка: {e}")

# ==========================
# Запуск
# ==========================
async def main():
    print("CryptoDoni v8 запущен!")
    asyncio.create_task(start_web_server())

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.session.close()))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
