#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v5 — USDT + $ + всё работает!
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
    raise RuntimeError("Укажи TELEGRAM_TOKEN и OPENAI_API_KEY!")

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

# Цены
PRICES = {"TRX": 0.15, "USDT": 1.0}

# ==========================
# Веб-сервер
# ==========================
async def handle(request):
    return web.Response(text="CryptoDoni v5 alive")

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
# Обновление цен
# ==========================
async def update_prices():
    global PRICES
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=usd"
            async with session.get(url) as resp:
                data = await resp.json()
                PRICES["TRX"] = data.get("tron", {}).get("usd", 0.15)
    except Exception as e:
        print(f"Ошибка цен: {e}")
        PRICES["TRX"] = 0.15

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
        data = await check_solana(address)
        result.update(data)

    # --- СЧИТАЕМ USD ---
    total = 0.0

    # TRX
    if result["trx_amount"] > 0:
        usd = result["trx_amount"] * PRICES["TRX"]
        total += usd
        result["balances"].append(f"TRX: {result['trx_amount']:.2f} (~${usd:.2f})")
    else:
        result["balances"].append("TRX: 0.00 (~$0.00)")

    # USDT
    if result["usdt_amount"] > 0:
        usd = result["usdt_amount"] * PRICES["USDT"]
        total += usd
        result["balances"].append(f"USDT: {result['usdt_amount']:.2f} (~${usd:.2f})")
    else:
        result["balances"].append("USDT: 0.00 (~$0.00)")

    result["total_usd"] = total
    result["ai_analysis"] = await ai_analyze(result)
    return result

# === BEP20 ===
async def check_bep20(address: str) -> dict:
    trx_amount = usdt_amount = 0.0
    txs = []
    async with aiohttp.ClientSession() as session:
        # BNB
        url = f"https://api.bscscan.com/api?module=account&action=balance&address={address}"
        async with session.get(url) as resp:
            data = await resp.json()
            if data.get("status") == "1":
                bnb = int(data["result"]) / 1e18
                if bnb > 0:
                    txs.append(f"BNB: {bnb:.6f}")

        # USDT
        usdt_contract = "0x55d398326f99059fF775485246999027B3197955"
        url = f"https://api.bscscan.com/api?module=account&action=tokenbalance&contractaddress={usdt_contract}&address={address}&tag=latest"
        async with session.get(url) as resp:
            data = await resp.json()
            if data.get("status") == "1":
                usdt_amount = int(data["result"]) / 1e18

    return {"network": "BEP20", "trx_amount": 0, "usdt_amount": usdt_amount, "txs": txs}

# === TRON ===
async def check_tron(address: str) -> dict:
    trx_amount = usdt_amount = 0.0
    txs = []
    async with aiohttp.ClientSession() as session:
        url = f"https://api.trongrid.io/v1/accounts/{address}"
        async with session.get(url) as resp:
            data = await resp.json()
            if "data" in data and data["data"]:
                acc = data["data"][0]
                trx_amount = acc.get("balance", 0) / 1e6

                # USDT TRC20
                usdt_contract = "TR7NHqjeKQxGTCuuP8qACi7c3eN6T5z"
                for token in acc.get("trc20", []):
                    contract = list(token.keys())[0]
                    if contract == usdt_contract:
                        usdt_amount = int(list(token.values())[0]) / 1e6
                        break  # Нашли — выходим

                # USDT транзакции
                url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=3&contract_address={usdt_contract}"
                async with session.get(url) as resp:
                    data = await resp.json()
                    for tx in data.get("data", []):
                        value = int(tx["value"]) / 1e6
                        to = tx["to"][:10] + "..."
                        time = datetime.fromtimestamp(tx["block_timestamp"] / 1000).strftime('%d.%m %H:%M')
                        txs.append(f"→ {to} | {value:.2f} USDT | {time}")

                # TRX транзакции
                url = f"https://api.trongrid.io/v1/accounts/{address}/transactions?limit=3"
                async with session.get(url) as resp:
                    data = await resp.json()
                    for tx in data.get("data", []):
                        if tx.get("value"):
                            value = int(tx["value"]) / 1e6
                            to = tx["to"][:10] + "..."
                            time = datetime.fromtimestamp(tx["block_timestamp"] / 1000).strftime('%d.%m %H:%M')
                            txs.append(f"→ {to} | {value:.2f} TRX | {time}")

    return {"network": "TRON", "trx_amount": trx_amount, "usdt_amount": usdt_amount, "txs": txs}

# === SOLANA ===
async def check_solana(address: str) -> dict:
    return {"network": "Solana", "trx_amount": 0, "usdt_amount": 0, "txs": []}

# === ИИ-АНАЛИЗ ===
async def ai_analyze(data: dict) -> str:
    prompt = f"""
Кошелёк: {data['address']}
Сеть: {data['network']}
TRX: {data['trx_amount']:.2f}, USDT: {data['usdt_amount']:.2f}
Общая сумма: ~${data['total_usd']:.2f}
Транзакции: {len(data['txs'])} шт.

Это скам? Кратко: СКАМ / НОРМ / РИСК + 1 предложение.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120
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
        "<b>CryptoDoni v5 — USDT + $!</b>\n\n"
        "Пришли адрес:\n"
        "• <code>0x...</code> — BEP20\n"
        "• <code>T...</code> — TRON\n"
        "• <code>So1...</code> — Solana\n\n"
        "Покажу TRX, USDT, $ и ИИ-анализ!"
    )

@dp.message()
async def handle_address(msg: Message):
    address = msg.text.strip()
    if len(address) < 20:
        await msg.answer("Неверный адрес.")
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
        await msg.answer(f"Ошибка: {str(e)}")

# ==========================
# Graceful Shutdown
# ==========================
async def shutdown():
    print("Остановка CryptoDoni v5...")
    await bot.session.close()
    sys.exit(0)

# ==========================
# Запуск
# ==========================
async def main():
    print("CryptoDoni v5 запущен!")
    asyncio.create_task(start_web_server())

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
