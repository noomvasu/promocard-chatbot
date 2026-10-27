"""ตัวเช็กแจ้งเตือนโปรโมชั่นล่วงหน้า (เวอร์ชัน SQLite)

รัน: python alert_checker.py (เช่น จาก GitHub Actions หลังสคริปต์กวาดข้อมูล)
ต้องตั้งค่า environment variable: GEMINI_API_KEY (บังคับ),
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / DASHBOARD_URL (ไม่บังคับ)
"""

import json
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()  # ให้รันบนเครื่องอ่านค่าจากไฟล์ .env ได้

import requests

from db import GEMINI_MODEL, get_connection, load_all

API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

MY_CARDS = [
    "KTC Platinum Visa",
    "CardX Beyond Mastercard",
    "ttb so smart",
    "Krungsri Now",
    "ออมสิน",
    "KBank",
    "UOB",
    "Aeon",
    "Bangkok Bank",
    "ICBC"
]


def send_telegram_alert(message: str, button_url: str = None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ ข้ามการส่ง Telegram: ไม่พบ Token หรือ Chat ID")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    if button_url:
        inline_keyboard = {
            "inline_keyboard": [[{"text": "💳 คำนวณความคุ้มค่าบนเว็บ", "url": button_url}]]
        }
        payload["reply_markup"] = json.dumps(inline_keyboard)

    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
    except Exception:
        # Fallback ส่งแบบข้อความธรรมดา หาก Telegram ติดปัญหาเรื่อง Markdown Syntax
        payload.pop("parse_mode", None)
        try:
            res = requests.post(url, json=payload, timeout=10)
            res.raise_for_status()
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการส่ง Telegram: {e}")


def check_upcoming_promotions():
    if not API_KEY:
        print("❌ ข้อผิดพลาด: ไม่พบ GEMINI_API_KEY")
        return

    conn = get_connection()
    try:
        all_promos = load_all(conn)
    finally:
        conn.close()

    if not all_promos:
        print("ยังไม่มีข้อมูลโปรโมชั่นในฐานข้อมูล")
        return

    from google import genai

    today = datetime.now().date()
    target_window = today + timedelta(days=3)
    today_str = today.strftime("%Y-%m-%d (%A)")

    client = genai.Client(api_key=API_KEY)
    prompt = f"""
    คุณเป็นระบบแจ้งเตือนโปรโมชั่นบัตรเครดิต
    - วันที่วันนี้: {today_str}
    - ช่วงเวลาตรวจล่วงหน้า: นับจากวันนี้ถึง {target_window}
    - บัตรที่ผู้ใช้ถืออยู่: {MY_CARDS}
    - ฐานข้อมูลโปรโมชั่น: {all_promos}

    กฎการจับคู่บัตร:
    - บัตรที่ผู้ใช้ถืออยู่สังกัดธนาคาร: KTC, CardX (SCB), ttb, Krungsri
    - หากโปรโมชั่นระบุว่า 'บัตรเครดิตทุกประเภท' ของธนาคารดังกล่าว หรือเข้าเงื่อนไขกับบัตรที่ถือ ให้ถือว่าเข้าเงื่อนไขทั้งหมด

    ภารกิจ:
    คัดกรองเฉพาะโปรโมชั่นของบัตรที่ผู้ใช้ถืออยู่ ที่เข้าเงื่อนไขข้อใดข้อหนึ่ง:
    1. เป็นวันแคมเปญพิเศษ (Payday, Double Digit, วันพิเศษประจำสัปดาห์) ที่จะเริ่มขึ้นในอีก 1-3 วัน หรือตรงกับวันนี้
    2. โปรโมชั่นที่กำลังจะหมดอายุลงภายใน 3 วันนี้

    รูปแบบการสรุป (สั้น กระชับ สำหรับอ่านบนมือถือ):
    - 🔔 หัวข้อแจ้งเตือน (เช่น อีก 2 วันเริ่ม Payday! หรือ ด่วน! สิทธิ์จะหมดเขตพรุ่งนี้)
    - 💳 บัตรที่ต้องใช้ และ แพลตฟอร์ม
    - 💰 สิทธิประโยชน์ที่จะได้รับ
    - ⏱️ ช่วงเวลาที่ต้องกดรับสิทธิ์ หรือเริ่มใช้จ่าย

    *หากไม่มีโปรโมชั่นใดเข้าเงื่อนไขในช่วง 3 วันนี้ ให้ตอบคำเดียวว่า: NO_ALERT*
    """

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    alert_content = response.text.strip()

    if "NO_ALERT" not in alert_content:
        send_telegram_alert(
            f"📢 *แจ้งเตือนสิทธิ์บัตรเครดิตล่วงหน้า*\n\n{alert_content}",
            button_url=DASHBOARD_URL if DASHBOARD_URL else None
        )
        print("ส่งการแจ้งเตือนสำเร็จ")
    else:
        print("ไม่มีโปรโมชั่นพิเศษที่เข้าเงื่อนไขในช่วงนี้")


if __name__ == "__main__":
    check_upcoming_promotions()
