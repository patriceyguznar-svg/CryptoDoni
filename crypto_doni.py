#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CryptoDoni v31 — точный USDT и TRX, с поиском по названию
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
    print("ОШИБКА: проверь переменные окружения!")
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
    return web.Response(text="CryptoDoni v31 — Running!")

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
            # === TRX баланс ===
            url_acc = f"https://apilist.tronscanapi.com/api/account?address={address}"
            async with session.get(url_acc, timeout=10) as resp:
                acc = await resp.json()
                result["trx"] = acc.get("balance", 0) / 1e6
                result["debug"] += f"TRX: {result['trx']}\n"

            # === USDT баланс (по названию + ID) ===
            url_tokens = f"https://apilist.tronscanapi.com/api/account/tokens?address={address}&start=0&limit=200"
            async with session.get(url_tokens, timeout=10) as resp:
                tok = await resp.json()
                usdt_found = False
                for t in tok.get("data", []):
                    token_name = t.get("tokenName", "").strip()
                    token_abbr = t.get("tokenAbbr", "").strip()
                    token_id = t.get("tokenId", "")

                    is_usdt_by_name = (
                        "tether" in token_name.lower() and
                        "usd" in token_name.lower() and
                        token_abbr.upper() == "USDT"
                    )
                    is_usdt_by_id = token_id == USDT_CONTRACT

                    if is_usdt_by_name or is_usdt_by_id:
                        raw = t.get("balance", "0")
                        try:
                            result["usdt"] = int(raw) / 1e6
                            method = "названию" if is_usdt_by_name else "ID"
                            result["debug"] += f"USDT: {raw} → {result['usdt']} (по {method})\n"
                        except (ValueError, TypeError):
                            result["usdt"] = 0.0
                            result["debug"] += f"USDT: ошибка парсинга balance={raw}\n"
                        usdt_found = True
                        break

                if not usdt_found:
                    result["debug"] += "USDT не найден\n"

            # === Транзакции ===
            url_tx = f"https://apilist.tronscanapi.com/api/transaction?limit=5&address={address}&sort=-timestamp"
            async with session.get(url_tx, timeout=10) as resp:
                txs = await resp.json()
                data = txs.get("data", [])
                for tx in data:
                    ctype = tx.get("contractType")
                    time = datetime.fromtimestamp(tx["timestamp"]/1000).strftime("%d.%m %H:%M")
                    to = tx.get("toAddress", "")
                    to_short = to[:8] + "..." + to[-4:] if to else "?"

                    if ctype == 1:  # TRX
                        value = int(tx.get("amount", 0)) / 1e6
                        result["txs"].append(f"<b>TRX</b> → {to_short}\n<code>{value}</code> | {time}")
                    elif ctype == 31:  # TRC-20
                        token_info = tx.get("tokenInfo", {})
                        token_name = token_info.get("tokenName", "").lower()
                        token_abbr = token_info.get("tokenAbbr", "")
                        token_id = token_info.get("tokenId", "")

                        if (token_id == USDT_CONTRACT or
                            ("tether" in token_name and "usd" in token_name and token_abbr == "USDT")):
                            raw = tx.get("amountStr", "0")
                            try:
                                value = int(raw) / 1e6
                                result["txs"].append(f"<b>USDT</b> → {to_short}\n<code>{value}</code> | {time}")
                            except (ValueError, TypeError):
                                pass

            # === ИТОГО (один раз!) ===
            result["total_usd"] = round(result["trx"] * TRX_PRICE + result["usdt"], 2)

    except Exception as e:
        result["debug"] += f"GLOBAL ERROR: {e}\n"
        result["txs"].append("Ошибка API")

    return result

# ==========================
# ИИ-анализ
# ==========================
async def ai_analyze(data: dict) -> str:
    prompt = (
        f"TRX: {data['trx']}, USDT: {data['usdt']}, "
        f"Всего: ${data['total_usd']}, Транзакций: {len(data['txs'])}\n"
        "Это скам? Коротко: СКАМ / НОРМ / РИСК + причина."
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
        "<b>CryptoDoni v31</b>\n\n"
        "Пришли TRON-адрес:\n"
        "• TRX и USDT (фактические)\n"
        "• USD сумма\n"
        "• Последние транзакции\n"
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
    trx_usd = round(data["trx"] * TRX_PRICE, 2)
    usdt_usd = data["usdt"]
    txs_text = "\n\n".join(data["txs"]) if data["txs"] else "—"

    text = (
        f"<b>Кошелёк:</b> <code>{short}</code>\n"
        f"<b>Сеть:</b> TRON\n\n"
        f"<b>Баланс:</b>\n"
        f"• TRX: <b>{data['trx']}</b> (~${trx_usd})\n"
        f"• USDT: <b>{data['usdt']}</b>\n\n"
        f"<b>Итого: <u>${data['total_usd']}</u></b>\n\n"
        f"<b>Последние транзакции:</b>\n{txs_text}\n\n"
        f"<b>ИИ-анализ:</b>\n{await ai_analyze(data)}"
    )
    text += f"\n\n<b>DEBUG:</b>\n<pre>{data['debug']}</pre>"
    await msg.answer(text, disable_web_page_preview=True)

# ==========================
# RUN
# ==========================
async def main():
    print("CryptoDoni v31 запущен!")
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
