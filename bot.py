"""Telegram bot ถาม-ตอบโปรโมชั่นบัตรเครดิต (ใช้ advisor.py)

รัน: python bot.py
ต้องตั้งค่า environment variable: TELEGRAM_BOT_TOKEN และ GEMINI_API_KEY
รันแบบ polling (เหมาะกับรันบนเครื่องตัวเอง / NAS / VPS ขนาดเล็ก)
"""

import os

from dotenv import load_dotenv

load_dotenv()  # ให้รันบนเครื่อง/NAS อ่านค่าจากไฟล์ .env ได้ (ต้องมาก่อน import advisor)

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from advisor import MY_CARDS, advise
from db import count_all, get_connection

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

HELP_TEXT = (
    "สวัสดีครับ ผมช่วยเลือกบัตรเครดิตที่คุ้มที่สุดให้ได้\n\n"
    "ถามได้เลย เช่น:\n"
    "• ซื้อของ Shopee 2,800 บาท ใช้บัตรไหนดี\n"
    "• Lazada 5,000 บาท บัตรไหนคุ้มสุด\n\n"
    "ผมจะเช็กโปรโมชั่นของบัตรที่คุณถืออยู่ก่อน:\n"
    + "\n".join(f"• {card}" for card in MY_CARDS)
    + "\n\nแล้วตอบเฉพาะโปรที่ตรงแพลตฟอร์ม ยอดถึงขั้นต่ำ และยังไม่หมดอายุครับ"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text or ""
    await update.message.reply_text("กำลังเช็กโปรโมชั่นให้ครับ...")
    try:
        answer = advise(query)
    except Exception as e:
        answer = f"เกิดข้อผิดพลาดระหว่างวิเคราะห์ครับ: {e}"
    await update.message.reply_text(answer)


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "❌ ไม่พบ TELEGRAM_BOT_TOKEN "
            "(ตั้งค่าใน .env หรือ environment variable)"
        )
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    try:
        conn = get_connection()
        try:
            n = count_all(conn)
        finally:
            conn.close()
        print(f"📦 โหลดโปรโมชั่นแล้ว {n} รายการ")
        if n == 0:
            print("⚠️ ฐานข้อมูลยังว่าง — บอทจะตอบว่าไม่เจอโปรจนกว่า promotions.db จะมีข้อมูล (รัน workflow_dispatch บน GitHub แล้ว git pull บน NAS)")
    except Exception as e:
        print(f"⚠️ อ่านฐานข้อมูลไม่ได้: {e}")
    print("🤖 บอทเริ่มทำงานแล้ว (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
