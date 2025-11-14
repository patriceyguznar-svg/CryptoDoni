#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v6 — USDT + $ + БЕЗ КОНФЛИКТОВ!
"""

import os
import asyncio
import aiohttp
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

# ==========================
# Конфиг
# ==========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    print("ОШИБКА: Укажи TELEGRAM_TOKEN и OPENAI_API_KEY в Render!")
    sys.exit(1)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ==========================
# Веб-сервер (чтобы Render не спал)
# ==========================
async def handle(request):
    return web.Response(text="CryptoDoni v6 — жив!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")

# ==========================
# Цены
# ==========================
PRICES = {"TRX": 0.15, "USDT": 1.0}

async def update_prices():
    global PRICES
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=usd"
            async with session.get(url) as resp:
                data = await resp.json()
                PRICES["TRX"] = data.get("tron", {}).get("usd", 0.15)
    except Exception as e:
        print(f"Цена TRX не обновилась: {e}")

# ==========================
# Проверка кошелька
# ==========================
async def check_wallet(address: str) -> dict:
    result = {
        "address": address,
        "balances": [],
        "txs": [],
        "network": "неизвестно",
        "total_usd": 0.0,
        "trx_amount": 0.0,
        "usdt_amount": 0.0
    }

    await update_prices()

    if address.startswith("0x") and len(address) == 42:
        data = await check_bep20(address)
        result.update(data)
    elif address.startswith("T") and len(address) == 34:
        data = await check_tron(address)
        result.update(data)
    elif len(address) > 50:
        result.update({"network": "Solana", "trx_amount": 0, "usdt_amount": 0, "txs": []})

    # === USD ===
    total = 0.0

    # TRX
    usd = result["trx_amount"] * PRICES["TRX"]
    total += usd
    result["balances"].append(f"TRX: {result['trx_amount']:.2f} (~${usd:.2f})")

    # USDT
    usd = result["usdt_amount"] * PRICES["USDT"]
    total += usd
    result["balances"].append(f"USDT: {result['usdt_amount']:.2f} (~${usd:.2f})")

    result["total_usd"] = total
    result["ai_analysis"] = await ai_analyze(result)
    return result

# === TRON ===
async def check_tron(address: str) -> dict:
    trx_amount = usdt_amount = 0.0
    txs = []
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.trongrid.io/v1/accounts/{address}"
            async with session.get(url) as resp:
                data = await resp.json()
                if "data" in data and data["data"]:
                    acc = data["data"][0]
                    trx_amount = acc.get("balance", 0) / 1e6

                    # USDT
                    usdt_contract = "TR7NHqjeKQxGTCuuP8qACi7c3eN6T5z"
                    for token in acc.get("trc20", []):
                        if list(token.keys())[0] == usdt_contract:
                            usdt_amount = int(list(token.values())[0]) / 1e6
                            break

                    # USDT транзакции
                    url_tx = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=3&contract_address={usdt_contract}"
                    async with session.get(url_tx) as resp:
                        data_tx = await resp.json()
                        for tx in data_tx.get("data", []):
                            value = int(tx["value"]) / 1e6
                            to = tx["to"][:10] + "..."
                            time = datetime.fromtimestamp(tx["block_timestamp"] / 1000).strftime('%d.%m %H:%M')
                            txs.append(f"→ {to} | {value:.2f} USDT | {time}")

                    # TRX транзакции
                    url_trx = f"https://api.trongrid.io/v1/accounts/{address}/transactions?limit=3"
                    async with session.get(url_trx) as resp:
                        data_trx = await resp.json()
                        for tx in data_trx.get("data", []):
                            if tx.get("value"):
                                value = int(tx["value"]) / 1e6
                                to = tx["to"][:10] + "..."
                                time = datetime.fromtimestamp(tx["block_timestamp"] / 1000).strftime('%d.%m %H:%M')
                                txs.append(f"→ {to} | {value:.2f} TRX | {time}")
    except Exception as e:
        print(f"Ошибка TRON: {e}")

    return {"network": "TRON", "trx_amount": trx_amount, "usdt_amount": usdt_amount, "txs": txs}

# === BEP20 (пока упрощённо) ===
async def check_bep20(address: str) -> dict:
    return {"network": "BEP20", "trx_amount": 0, "usdt_amount": 0, "txs": []}

# === ИИ ===
async def ai_analyze(data: dict) -> str:
    prompt = f"Кошелёк {data['address']} | TRX: {data['trx_amount']:.2f} | USDT: {data['usdt_amount']:.2f} | Сумма: ${data['total_usd']:.2f} | Транзакций: {len(data['txs'])}\nЭто скам? Кратко: СКАМ / НОРМ / РИСК + причина."
    try:
        response = OpenAI(api_key=OPENAI_API_KEY).chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"ИИ: ошибка ({e})"

# ==========================
# Команды
# ==========================
@dp.message(Command("start"))
async def start(msg: Message):
    await msg.answer(
        "<b>CryptoDoni v6 — USDT + $ + 24/7!</b>\n\n"
        "Пришли адрес TRON (T...) — покажу всё в $!"
    )

@dp.message()
async def handle(msg: Message):
    address = msg.text.strip()
    if not (address.startswith("T") and len(address) == 34):
        await msg.answer("Пришли адрес TRON (начинается с T, 34 символа)!")
        return

    await msg.answer("Проверяю... (hourglass)")
    try:
        result = await check_wallet(address)
        tx_text = "\n".join(result['txs']) if result['txs'] else "нет"
        text = f"""
<b>Кошелёк:</b> <code>{result['address']}</code>
<b>Сеть:</b> {result['network']}
<b>Баланс:</b>
{chr(10).join(result['balances'])}

<b>Общая сумма: ~${result['total_usd']:.2f}</b>

<b>Транзакции:</b>
{tx_text}

<b>ИИ:</b> {result['ai_analysis']}
        """
        await msg.answer(text)
    except Exception as e:
        await msg.answer(f"Ошибка: {e}")

# ==========================
# Запуск
# ==========================
async def main():
    print("CryptoDoni v6 запущен!")
    asyncio.create_task(start_web_server())

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.session.close()))

    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
