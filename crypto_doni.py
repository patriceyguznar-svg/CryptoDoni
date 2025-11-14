Леха Юрко, [14.11.2025 14:57]
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v30 — FIXED USDT BALANCE + amountStr + STABLE TRONSCAN API
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
    print("ОШИБКА: Проверь переменные окружения!")
    exit(1)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

TRX_PRICE = 0.15
USDT_CONTRACT = "TR7NHqjeKQxGTCuuP8qACi7c3eN6T5z"

HEADERS = {
    "apikey": TRONSCAN_API_KEY,
    "accept": "application/json",
    "User-Agent": "Mozilla/5.0"
}

# ==========================
# KEEP-ALIVE WEB
# ==========================
async def handle(request):
    return web.Response(text="CryptoDoni v30 — Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб запущен на порту {port}")

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

            # === 1. TRX баланс ===
            url_acc = f"https://apilist.tronscanapi.com/api/account?address={address}"
            async with session.get(url_acc) as resp:
                if resp.status != 200:
                    result["debug"] += f"ERR account status {resp.status}\n"
                else:
                    acc = await resp.json()
                    result["trx"] = acc.get("balance", 0) / 1e6
                    result["debug"] += f"TRX: {result['trx']:.6f}\n"

            # === 2. USDT через стабильный endpoint ===
            try:
                url_tokens = f"https://apilist.tronscanapi.com/api/account/tokens?address={address}&start=0&limit=200"
                async with session.get(url_tokens) as resp:
                    if resp.status != 200:
                        result["debug"] += f"ERR tokens status {resp.status}\n"
                    else:
                        tok = await resp.json()

                        for t in tok.get("data", []):
                            if t.get("tokenId") == USDT_CONTRACT:
                                raw = t.get("balance", "0")
                                result["usdt"] = int(raw) / 1e6
                                result["debug"] += f"USDT OK: {raw} → {result['usdt']:.6f}\n"
                                break
                        else:
                            result["debug"] += "USDT not found in tokens\n"

            except Exception as e:
                result["debug"] += f"USDT error: {e}\n"

            # === 3. ТРАНЗАКЦИИ ===
            url_tx = f"https://apilist.tronscanapi.com/api/transaction?limit=5&address={address}&sort=-timestamp"
            async with session.get(url_tx) as resp:
                if resp.status != 200:
                    result["debug"] += f"ERR tx status {resp.status}\n"
                else:
                    txs = await resp.json()
                    data = txs.get("data", [])
                    result["debug"] += f"TX count: {len(data)}\n"

Леха Юрко, [14.11.2025 14:57]
for tx in data:
                        ctype = tx.get("contractType")
                        time = datetime.fromtimestamp(tx["timestamp"] / 1000).strftime("%d.%m %H:%M")

                        # TRX transfer
                        if ctype == 1:
                            value = int(tx.get("amount", 0)) / 1e6
                            to = tx.get("toAddress", "")
                            to = to[:8] + "..." + to[-4:]
                            result["txs"].append(f"<b>TRX</b> → {to}\n<code>{value:.2f}</code> | {time}")

                        # USDT (TRC20)
                        elif ctype == 31:
                            token_info = tx.get("tokenInfo", {})
                            if token_info.get("tokenId") == USDT_CONTRACT:
                                raw = tx.get("amountStr", "0")
                                value = int(raw) / 1e6
                                to = tx.get("toAddress", "")
                                to = to[:8] + "..." + to[-4:]
                                result["txs"].append(f"<b>USDT</b> → {to}\n<code>{value:.2f}</code> | {time}")

            # Итоговая сумма
            result["total_usd"] = result["trx"] * TRX_PRICE + result["usdt"]

    except Exception as e:
        result["debug"] += f"GLOBAL ERROR: {e}\n"
        result["txs"].append("Ошибка API")

    return result

# ==========================
# ИИ-анализ
# ==========================
async def ai_analyze(data: dict) -> str:
    prompt = (
        f"TRX: {data['trx']:.2f}, USDT: {data['usdt']:.2f}, "
        f"Всего: ${data['total_usd']:.2f}, Транзакций: {len(data['txs'])}\n"
        "Это скам? Ответь коротко: СКАМ / НОРМ / РИСК + причина."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"ИИ ошибка: {e}"

# ==========================
# Команды
# ==========================
@dp.message(Command("start"))
async def start(msg: Message):
    await msg.answer(
        "<b>CryptoDoni v30</b>\n\n"
        "Пришли <b>TRON-адрес</b>:\n"
        "• TRX и USDT\n"
        "• USD сумма\n"
        "• Транзакции\n"
        "• ИИ-анализ\n\n"
        "<i>Пример: TDqhrxGnktwBCim5ZXcJPvMWASSfYWsdt6</i>"
    )

@dp.message()
async def handle_wallet(msg: Message):
    address = msg.text.strip()
    if not (address.startswith("T") and len(address) == 34):
        await msg.answer("Неверный адрес!\nПример: <code>TDqhrxGnktwBCim5ZXcJPvMWASSfYWsdt6</code>")
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
        f"• TRX: <b>{data['trx']:.2f}</b> (~${trx_usd:.2f})\n"
        f"• USDT: <b>{data['usdt']:.2f}</b> (~${usdt_usd:.2f})\n\n"
        f"<b>Итого: <u>${data['total_usd']:.2f}</u></b>\n\n"
        f"<b>Последние транзакции:</b>\n{txs_text}\n\n"
        f"<b>ИИ-анализ:</b>\n{await ai_analyze(data)}"
    )

    if data["usdt"] == 0:
        text += f"\n\n<b>DEBUG:</b>\n<pre>{data['debug']}</pre>"

    await msg.answer(text, disable_web_page_preview=True)

# ==========================
# RUN
# ==========================
async def main():
    print("CryptoDoni v30 запущен!")
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot, polling_timeout=30)

if name == "main":
    asyncio.run(main())
