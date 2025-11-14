#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v18 — ДЕБАГ + USDT + КРАСИВО
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
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")

print(f"КЛЮЧИ: TOKEN=OK, OPENAI={'OK' if OPENAI_API_KEY else 'НЕТ'}, TRONGRID={'OK' if TRONGRID_API_KEY else 'НЕТ'}")

if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, TRONGRID_API_KEY]):
    print("ОШИБКА: Проверь переменные в Render!")
    exit(1)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

TRX_PRICE = 0.15
HEADERS = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}
USDT_CONTRACT = "TR7NHqjeKQxGTCuuP8qACi7c3eN6T5z"

# ==========================
# Веб-сервер
# ==========================
async def handle(request):
    return web.Response(text="CryptoDoni v18 — alive")

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
# Проверка кошелька
# ==========================
async def check_wallet(address: str) -> dict:
    result = {
        "address": address,
        "trx": 0.0,
        "usdt": 0.0,
        "total_usd": 0.0,
        "txs": [],
        "debug": ""
    }

    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as session:
            # === 1. БАЛАНС ===
            url = f"https://api.trongrid.io/v1/accounts/{address}"
            print(f"Запрос баланса: {url}")
            async with session.get(url) as resp:
                data = await resp.json()
                print(f"Ответ баланса: {data}")
                result["debug"] += f"Баланс API: {len(data.get('data', []))} аккаунтов\n"

                if not data.get("data"):
                    result["txs"].append("Кошелёк не найден")
                    return result

                acc = data["data"][0]
                result["trx"] = acc.get("balance", 0) / 1e6
                print(f"TRX: {result['trx']}")

                # === USDT ===
                trc20 = acc.get("trc20", [])
                print(f"TRC20 токены: {trc20}")
                result["debug"] += f"TRC20 найдено: {len(trc20)}\n"

                for token in trc20:
                    if isinstance(token, dict) and USDT_CONTRACT in token:
                        raw = token[USDT_CONTRACT]
                        result["usdt"] = int(raw) / 1e6
                        print(f"USDT найден: {raw} → {result['usdt']}")
                        result["debug"] += f"USDT: {result['usdt']}\n"
                        break
                else:
                    result["debug"] += "USDT не найден в TRC20\n"

            # === 2. USDT ТРАНЗАКЦИИ ===
            url_usdt = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=3&contract_address={USDT_CONTRACT}"
            print(f"Запрос USDT tx: {url_usdt}")
            async with session.get(url_usdt) as resp:
                txs = await resp.json()
                print(f"USDT транзакции: {txs}")
                for tx in txs.get("data", []):
                    value = int(tx["value"]) / 1e6
                    to = tx["to"][:8] + "..." + tx["to"][-4:]
                    time = datetime.fromtimestamp(tx["block_timestamp"]/1000).strftime("%d.%m %H:%M")
                    result["txs"].append(f"<b>USDT</b> → {to}\n<code>{value:.2f}</code> | {time}")

            result["total_usd"] = result["trx"] * TRX_PRICE + result["usdt"]

    except Exception as e:
        error = f"API ОШИБКА: {type(e).__name__}: {e}"
        print(error)
        result["txs"].append("Ошибка API")
        result["debug"] += error

    return result

# ==========================
# ИИ
# ==========================
async def ai_analyze(data: dict) -> str:
    prompt = (
        f"TRX: {data['trx']:.2f}, USDT: {data['usdt']:.2f}, "
        f"Всего: ${data['total_usd']:.2f}\n"
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
        "<b>CryptoDoni v18</b>\n\n"
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

    # ДЕБАГ В ОТВЕТ (временно!)
    if data["usdt"] == 0:
        text += f"\n\n<b>DEBUG:</b>\n<pre>{data['debug']}</pre>"

    await msg.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# ==========================
# Запуск
# ==========================
async def main():
    print("CryptoDoni v18 запущен!")
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
