#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v13 — TRONGRID API (без падения)
"""

import os
import asyncio
import aiohttp
import signal
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from openai import OpenAI
from aiohttp import web

# ==========================
# КОНФИГ (БЕЗ sys.exit!)
# ==========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")

if not TELEGRAM_TOKEN:
    print("ОШИБКА: TELEGRAM_TOKEN не задан!")
elif not OPENAI_API_KEY:
    print("ОШИБКА: OPENAI_API_KEY не задан!")
elif not TRONGRID_API_KEY:
    print("ОШИБКА: TRONGRID_API_KEY не задан! Получи на trongrid.io")
else:
    print("Все ключи загружены — бот стартует!")

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

TRX_PRICE = 0.15
HEADERS = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}

# ==========================
# Веб-сервер
# ==========================
async def handle(request):
    return web.Response(text="CryptoDoni v13 — alive")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер на {port}")

# ==========================
# Проверка кошелька
# ==========================
async def check_wallet(address: str) -> dict:
    result = {
        "address": address,
        "network": "TRON",
        "trx_amount": 0.0,
        "usdt_amount": 0.0,
        "total_usd": 0.0,
        "txs": []
    }

    if not TRONGRID_API_KEY:
        result["txs"].append("TRONGRID_API_KEY не задан")
        return result

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            # Баланс
            url = f"https://api.trongrid.io/v1/accounts/{address}"
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("data"):
                    acc = data["data"][0]
                    result["trx_amount"] = acc.get("balance", 0) / 1e6

                    usdt_contract = "TR7NHqjeKQxGTCuuP8qACi7c3eN6T5z"
                    for token in acc.get("trc20", []):
                        if list(token.keys())[0] == usdt_contract:
                            result["usdt_amount"] = int(list(token.values())[0]) / 1e6
                            break

            # USDT транзакции
            url_tx = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=3&contract_address={usdt_contract}"
            async with session.get(url_tx) as resp:
                tx_data = await resp.json()
                for tx in tx_data.get("data", []):
                    value = int(tx["value"]) / 1e6
                    to = tx["to"][:10] + "..."
                    time = datetime.fromtimestamp(tx["block_timestamp"]/1000).strftime("%d.%m %H:%M")
                    result["txs"].append(f"→ {to} | {value:.2f} USDT | {time}")

            result["total_usd"] = result["trx_amount"] * TRX_PRICE + result["usdt_amount"]
            result["txs"] = result["txs"][:3]

    except Exception as e:
        print(f"Ошибка: {e}")
        result["txs"].append("Ошибка API")

    return result

# ==========================
# ИИ
# ==========================
async def ai_analyze(data: dict) -> str:
    if not client:
        return "ИИ: ключ не задан"
    prompt = f"Кошелёк: {data['address'][:10]}... TRX: {data['trx_amount']:.2f}, USDT: {data['usdt_amount']:.2f}, Сумма: ${data['total_usd']:.2f}\nЭто скам?"
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except:
        return "ИИ: ошибка"

# ==========================
# Команды
# ==========================
@dp.message(Command("start"))
async def start(msg: Message):
    await msg.answer(
        "<b>CryptoDoni v13</b>\n\n"
        "Пришли TRON-адрес → получишь баланс + ИИ!"
    )

@dp.message()
async def handle(msg: Message):
    address = msg.text.strip() if msg.text else ""
    if not (address.startswith("T") and len(address) == 34):
        await msg.answer("Пришли валидный TRON-адрес!")
        return

    await msg.answer("Проверяю... (hourglass)")
    data = await check_wallet(address)
    short = address[:10] + "..."
    trx_usd = data["trx_amount"] * TRX_PRICE
    usdt_usd = data["usdt_amount"]

    balance = f"TRX: {data['trx_amount']:.2f} (~${trx_usd:.2f}) USDT: {data['usdt_amount']:.2f} (~${usdt_usd:.2f})"
    txs = "\n".join(data["txs"]) if data["txs"] else "нет"

    text = (
        f"<b>Кошелёк:</b> {short} <b>Сеть:</b> TRON <b>Баланс:</b> {balance}\n"
        f"<b>Общая сумма: ~${data['total_usd']:.2f}</b>\n"
        f"<b>Транзакции:</b> {txs}\n"
        f"<b>ИИ:</b> {await ai_analyze(data)}"
    )
    await msg.answer(text, disable_web_page_preview=True)

# ==========================
# Запуск
# ==========================
async def main():
    print("CryptoDoni v13 стартует...")
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
