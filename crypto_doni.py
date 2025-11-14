#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v29 — USDT + amountStr + БЕЗ КОНФЛИКТОВ
"""

import os
import asyncio
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from openai import OpenAI
from aiohttp import web

# ==========================
# КОНФИГ
# ==========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TRONSCAN_API_KEY = os.getenv("TRONSCAN_API_KEY")

if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, TRONSCAN_API_KEY]):
    print("ОШИБКА: Проверь переменные в Render!")
    exit(1)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

TRX_PRICE = 0.15
USDT_CONTRACT = "TR7NHqjeKQxGTCuuP8qACi7c3eN6T5z"
HEADERS = {"apikey": TRONSCAN_API_KEY}

# ==========================
# Веб-сервер (чтобы Render не спал)
# ==========================
async def handle(request):
    return web.Response(text="CryptoDoni v29 — USDT Fixed")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб запущен: порт {port}")

# ==========================
# Проверка кошелька
# ==========================
async def check_wallet(address: str) -> dict:
    result = {
        "trx": 0.0,
        "usdt": 0.0,
        "total_usd": 0.0,
        "txs": [],
        "debug": ""
    }

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            # === 1. БАЛАНС ===
            url = f"https://apilist.tronscanapi.com/api/account?address={address}"
            async with session.get(url) as resp:
                data = await resp.json()
                print(f"API Баланс: {data}")

                # TRX
                result["trx"] = data.get("balance", 0) / 1e6
                result["debug"] += f"TRX: {result['trx']:.6f}\n"

                # USDT — ищем по tokenId
                for token in data.get("trc20token_balances", []):
                    if token.get("tokenId") == USDT_CONTRACT:
                        raw = token.get("balance", "0")
                        result["usdt"] = int(raw) / 1e6
                        result["debug"] += f"USDT найден: {raw} → {result['usdt']:.6f}\n"
                        print(f"USDT найден: {result['usdt']}")
                        break
                else:
                    result["debug"] += "USDT не найден в балансе\n"

            # === 2. ТРАНЗАКЦИИ ===
            url_tx = f"https://apilist.tronscanapi.com/api/transaction?limit=5&address={address}&sort=-timestamp"
            async with session.get(url_tx) as resp:
                txs = await resp.json()
                result["debug"] += f"Транзакций: {len(txs.get('data', []))}\n"

                for tx in txs.get("data", []):
                    ctype = tx.get("contractType")

                    # TRX
                    if ctype == 1:
                        value = int(tx.get("amount", 0)) / 1e6
                        to = tx.get("toAddress", "")[:8] + "..." + tx.get("toAddress", "")[-4:]
                        time = datetime.fromtimestamp(tx["timestamp"]/1000).strftime("%d.%m %H:%M")
                        result["txs"].append(f"<b>TRX</b> → {to}\n<code>{value:.2f}</code> | {time}")

                    # TRC20 — USDT
                    elif ctype == 31:
                        token_info = tx.get("tokenInfo", {})
                        if token_info.get("tokenId") == USDT_CONTRACT:
                            amount_str = tx.get("amountStr", "0")  # КЛЮЧЕВОЕ: amountStr
                            value = int(amount_str) / 1e6
                            to = tx.get("toAddress", "")[:8] + "..." + tx.get("toAddress", "")[-4:]
                            time = datetime.fromtimestamp(tx["timestamp"]/1000).strftime("%d.%m %H:%M")
                            result["txs"].append(f"<b>USDT</b> → {to}\n<code>{value:.2f}</code> | {time}")

            result["txs"] = result["txs"][:3]
            result["total_usd"] = result["trx"] * TRX_PRICE + result["usdt"]

    except Exception as e:
        error = f"Ошибка: {type(e).__name__}: {e}"
        print(error)
        result["txs"].append("Ошибка API")
        result["debug"] += error

    return result

# ==========================
# ИИ-анализ
# ==========================
async def ai_analyze(data: dict) -> str:
    prompt = (
        f"TRX: {data['trx']:.2f}, USDT: {data['usdt']:.2f}, "
        f"Всего: ${data['total_usd']:.2f}, Транзакций: {len(data['txs'])}\n"
        "Это скам? Кратко: СКАМ / НОРМ / РИСК + причина."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120
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
        "<b>CryptoDoni v29</b>\n\n"
        "Пришли <b>TRON-адрес</b> → получишь:\n"
        "• TRX и <b>USDT</b>\n"
        "• Сумму в <b>$</b>\n"
        "• Транзакции\n"
        "• ИИ-анализ\n\n"
        "<i>Пример: TDqhrxGnktwBCim5ZXcJPvMWASSfYWsdt6</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message()
async def handle(msg: Message):
    address = msg.text.strip()
    if not (address.startswith("T") and len(address) == 34):
        await msg.answer("Неверный адрес!\nПример: <code>TDqhrxGnktwBCim5ZXcJPvMWASSfYWsdt6</code>", parse_mode=ParseMode.HTML)
        return

    await msg.answer("Проверяю...")

    data = await check_wallet(address)
    short = address[:8] + "..." + address[-6:]

    trx_usd = data["trx"] * TRX_PRICE
    usdt_usd = data["usdt"]

    txs_text = "\n\n".join(data["txs"]) if data["txs"] else "—"

    text = (
        f"<b>Кошелёк:</b> <code>{short}</code>\n"
        f"<b>Сеть:</b> TRON\n\n"
        f"<b>Баланс:</b>\n"
        f"   • TRX: <b>{data['trx']:.2f}</b> (~<b>${trx_usd:.2f}</b>)\n"
        f"   • USDT: <b>{data['usdt']:.2f}</b> (~<b>${usdt_usd:.2f}</b>)\n\n"
        f"<b>Общая сумма: ~<u>${data['total_usd']:.2f}</u></b>\n\n"
        f"<b>Последние транзакции:</b>\n{txs_text}\n\n"
        f"<b>ИИ-анализ:</b>\n{await ai_analyze(data)}"
    )

    # ДЕБАГ ТОЛЬКО ПРИ USDT = 0
    if data["usdt"] == 0:
        text += f"\n\n<b>DEBUG:</b>\n<pre>{data['debug']}</pre>"

    await msg.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ==========================
# Запуск
# ==========================
async def main():
    print("CryptoDoni v29 запущен!")
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
