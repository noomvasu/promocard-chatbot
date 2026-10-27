"""สคริปต์กวาดโปรโมชั่นบัตรเครดิตประจำเดือน (เวอร์ชัน SQLite)

ขั้นตอน: Playwright เปิดหน้าโปรโมชั่นของ 10 ธนาคาร ไล่อ่านทุกหน้าจนหมด
(กดหน้าถัดไป / โหลดเพิ่มเติม) -> Gemini แปลงเป็นรายการแบบมีโครงสร้าง
-> บันทึกลง promotions.db (SQLite) -> สรุปผลทาง Telegram

รัน: python 1_update_promos.py
ต้องตั้งค่า environment variable: GEMINI_API_KEY (บังคับ),
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / DASHBOARD_URL (ไม่บังคับ)
"""

import asyncio
import json
import os
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()  # ให้รันบนเครื่องอ่านค่าจากไฟล์ .env ได้

import requests
from google import genai
from google.genai import types
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from advisor import MY_BANKS, MY_CARDS
from db import GEMINI_MODEL, count_all, get_connection, upsert_promo

API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

# เพิ่มหรือแก้ไข URL หน้าโปรโมชั่นของธนาคารต่างๆ ตรงนี้
TARGET_URLS = [
    # 1. KTC (บริษัท บัตรกรุงไทย จำกัด)
    "https://www.ktc.co.th/promotion?promotion-card=credit-card",
    # 2. CardX / SCB (คาร์ด เอกซ์ / ธนาคารไทยพาณิชย์)
    "https://www.cardx.co.th/th-TH/credit-card/promotion",
    # 3. KBank (ธนาคารกสิกรไทย)
    "https://www.kasikornbank.com/th/promotion/creditcard/pages/index.aspx",
    # 4. Krungsri Consumer (บัตรเครดิตในเครือกรุงศรี)
    "https://www.krungsricard.com/th/promotion",
    # 5. ttb (ธนาคารทหารไทยธนชาต)
    "https://www.ttbbank.com/th/promotion",
    # 6. UOB (ธนาคารยูโอบี ประเทศไทย)
    "https://www.uob.co.th/personal/credit-cards/promotions.page?i_cid=default-top-menu",
    # 7. Aeon (ธนาคารธนสินทรัพย์ ประเทศไทย)
    "https://www.aeon.co.th/aeon/promotions/",
    # 8. Bangkok Bank (ธนาคารกรุงเทพ ประเทศไทย)
    "https://www.bangkokbank.com/th/personal/cards/credit-cards/promotions",
    # 9. ICBC Bank (ธนาคารICBC ประเทศไทย)
    "https://www.icbcthai.com/th/column/1438059037072965646.html",
    # 10. GSB (ธนาคารออมสิน) — หน้ารวมโปรโมชั่นและสิทธิพิเศษ (ส่วนใหญ่ใช้ได้กับบัตรเครดิตออมสินทุกประเภท)
    "https://www.gsb.or.th/promotions-privilege/",
]


# --- การไล่อ่านทุกหน้า (pagination) ---
# แต่ละธนาคารมีหน้าโปรหลายหน้า (เช่น CardX มี 22 หน้า) สคริปต์จะกดปุ่ม
# "หน้าถัดไป" ไปเรื่อยๆ จนกว่าจะหมด แล้วรวมข้อความทุกหน้า ส่งให้ Gemini
# ครั้งเดียวต่อธนาคาร (ประหยัดจำนวนครั้งที่เรียก API)
MAX_PAGES_PER_BANK = 25       # อ่านสูงสุด 25 หน้าต่อธนาคาร (CardX มี 22 หน้า)
MAX_TEXT_CHARS = 150_000      # ตัวอักษรรวมต่อธนาคารที่ส่งให้ Gemini (เดิม 30,000/หน้า)
LOAD_MORE_MAX_CLICKS = 5      # กดปุ่มโหลดเพิ่มสูงสุดต่อหน้า

# ปุ่ม/ลิงก์ "หน้าถัดไป" แบบต่างๆ (ลองตามลำดับ อันแรกที่เจอและกดได้คือตัวจริง)
NEXT_PAGE_SELECTORS = [
    "a[rel='next']",
    "a.next",
    ".next.page-numbers",
    "a:has-text('ถัดไป')",
    "button:has-text('ถัดไป')",
    "a:has-text('Next')",
    "button:has-text('Next')",
    "a:has-text('›')",
    "a:has-text('»')",
]

# ปุ่ม "โหลดเพิ่มเติม" สำหรับหน้าที่โหลดโปรเพิ่มแบบไม่เปลี่ยนหน้า
LOAD_MORE_SELECTORS = [
    "button:has-text('โหลดเพิ่มเติม')",
    "a:has-text('โหลดเพิ่มเติม')",
    "button:has-text('แสดงเพิ่มเติม')",
    "button:has-text('Load more')",
    "a:has-text('Load more')",
]

# แบนเนอร์คุกกี้ที่บังปุ่มแบ่งหน้า (กดปิดก่อนเริ่มไล่หน้า)
COOKIE_ACCEPT_SELECTORS = [
    "button:has-text('ยอมรับทั้งหมด')",
    "button:has-text('ยอมรับคุกกี้')",
    "button:has-text('Accept all')",
    "button:has-text('Accept cookies')",
]


class PromoItem(BaseModel):
    bank: str = Field(description="ชื่อธนาคาร ใช้ตามนี้เท่านั้น: KTC, CardX, KBank, Krungsri, ttb, UOB, Aeon, Bangkok Bank, ICBC, ออมสิน")
    merchant_or_platform: str = Field(description="ร้านค้าหรือแพลตฟอร์ม เช่น Shopee, Lazada, Agoda")
    min_spend: float = Field(0, description="ยอดใช้จ่ายขั้นต่ำต่อสลิป (บาท)")
    reward_type: str = Field(description="ประเภท เช่น ส่วนลดทันที, เครดิตเงินคืน, โค้ดส่วนลด")
    reward_detail: str = Field(description="รายละเอียดส่วนลด เช่น ลด 15% สูงสุด 300 บาท หรือ รับเงินคืน 100 บาท")
    start_date: str = Field(description="วันเริ่มต้นโปรโมชั่น รูปแบบ YYYY-MM-DD")
    end_date: str = Field(description="วันสิ้นสุดโปรโมชั่น รูปแบบ YYYY-MM-DD")
    special_timing_condition: str = Field(description="เงื่อนไขวันพิเศษ เช่น Payday, Double Digit, ทุกวันศุกร์ หรือ ทุกวัน")
    key_conditions: str = Field(description="เงื่อนไขสำคัญ เช่น ต้องเก็บโค้ด, พิมพ์ SMS ลงทะเบียน, จำกัดสิทธิ์")


class PromoCollection(BaseModel):
    promotions: list[PromoItem]


def send_telegram_message(message: str, button_url: str = None, button_text: str = "🌐 เปิดดูบน Dashboard"):
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
            "inline_keyboard": [
                [
                    {
                        "text": button_text,
                        "url": button_url
                    }
                ]
            ]
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


async def extract_promos_from_page(client, page_text: str, source_url: str) -> list[PromoItem]:
    """ส่งข้อความหน้าเว็บให้ Gemini แปลงเป็นรายการโปรโมชั่นแบบมีโครงสร้าง

    ถ้า Gemini ชั่วคราวไม่ว่าง (503/429 — คนใช้เยอะ) จะรอแล้วลองใหม่
    สูงสุด 3 ครั้ง ก่อนยอมแพ้ (error อื่น เช่น key ผิด จะพังทันทีไม่รอ)
    """
    prompt = f"""
    คุณคือระบบดึงข้อมูลโปรโมชั่นบัตรเครดิตจากหน้าเว็บธนาคาร
    URL ต้นทาง: {source_url}

    เนื้อหาหน้าเว็บ:
    {page_text}

    ภารกิจ: ดึงเฉพาะโปรโมชั่นบัตรเครดิตที่เกี่ยวกับการช้อปปิ้งออนไลน์ / แพลตฟอร์ม e-Commerce
    (เช่น Shopee, Lazada, Agoda, Grab, Foodpanda) และคืนค่าเป็น JSON ตาม schema ที่กำหนด

    ชื่อธนาคารให้ใช้ตามนี้เท่านั้น: KTC, CardX, KBank, Krungsri, ttb, UOB, Aeon,
    Bangkok Bank, ICBC, ออมสิน

    กฎ:
    - ข้ามโปรโมชั่นที่ไม่เกี่ยวกับช้อปปิ้งออนไลน์
    - ถ้าไม่ระบุวันสิ้นสุด ให้ใส่ end_date เป็น "" (สตริงว่าง)
    - วันที่ทั้งหมดใช้รูปแบบ YYYY-MM-DD
    - min_spend ใส่เป็นตัวเลขบาท (ถ้าไม่ระบุให้ใส่ 0)
    - ถ้าไม่มีโปรโมชั่นที่เข้าเงื่อนไขเลย ให้คืน promotions เป็นลิสต์ว่าง
    """
    last_error = None
    for attempt in range(3):
        try:
            response = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PromoCollection,
                ),
            )
            collection = PromoCollection.model_validate_json(response.text)
            return collection.promotions
        except Exception as e:
            last_error = e
            if "503" not in str(e) and "429" not in str(e) and "UNAVAILABLE" not in str(e) \
                    and "RESOURCE_EXHAUSTED" not in str(e) and "overloaded" not in str(e) \
                    and "high demand" not in str(e):
                raise  # error ถาวร (เช่น key ผิด, โมเดลไม่มี) ไม่ต้องรอ
            if attempt == 2:
                raise
            wait = 30 * (attempt + 1)
            print(f"  Gemini ชั่วคราวไม่ว่าง ({str(e)[:100]}), รอ {wait} วินาทีแล้วลองใหม่ (ครั้งที่ {attempt + 2}/3)")
            await asyncio.sleep(wait)
    raise last_error


async def _click_if_visible(page, selectors):
    """คลิก element แรกที่มองเห็นและกดได้จากรายการ selector
    คืน True ถ้าคลิกสำเร็จ, False ถ้าไม่เจอตัวไหนเลย"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() and await el.is_visible() and await el.is_enabled():
                await el.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


async def rank_top_promos(client, new_promos: list[dict]) -> str:
    """ให้ Gemini จัดอันดับโปรใหม่เดือนนี้ที่คุ้มที่สุด 1-3 อันดับ
    เฉพาะธนาคารของบัตรที่ถืออยู่ คืนข้อความสั้นๆ สำหรับแปะท้ายสรุป
    ถ้าเรียกไม่สำเร็จคืนสตริงว่าง (สรุปหลักยังส่งได้ตามปกติ)"""
    if not new_promos:
        return ""
    items = [
        {
            "bank": p.get("bank", ""),
            "merchant": p.get("merchant_or_platform", ""),
            "min_spend": p.get("min_spend", 0),
            "reward_type": p.get("reward_type", ""),
            "reward_detail": p.get("reward_detail", ""),
            "end_date": p.get("end_date", ""),
        }
        for p in new_promos
    ]
    prompt = f"""
    คุณเป็นที่ปรึกษาด้านความคุ้มค่าของบัตรเครดิต

    บัตรที่ผู้ใช้ถืออยู่จริง: {MY_CARDS}
    โปรโมชั่นใหม่ประจำเดือนนี้ (เฉพาะธนาคารของบัตรที่ถืออยู่):
    {json.dumps(items, ensure_ascii=False)}

    จัดอันดับโปรโมชั่นที่คุ้มที่สุด 3 อันดับแรก โดยดูจากมูลค่าที่ได้รับจริง
    (เงินคืนหรือส่วนลดเป็นบาท, คะแนนสะสมคูณกี่เท่า, ยอดขั้นต่ำที่ต้องใช้)
    ตอบสั้นๆ อันดับละ 1 บรรทัด รูปแบบนี้เท่านั้น:
    1. [ธนาคาร] ร้านค้า: ได้อะไรเท่าไหร่ (ขั้นต่ำ X บาท, หมดเขตวันที่...)
    2. ...
    ถ้ามีน้อยกว่า 3 รายการก็จัดเท่าที่มี ถ้าไม่มีโปรที่น่าสนใจเลย
    ให้ตอบว่า "ไม่มีโปรเด่นเดือนนี้"
    ห้ามแต่งตัวเลขที่ไม่ได้อยู่ในข้อมูลที่ให้มา
    """
    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return (response.text or "").strip()
    except Exception as e:
        print(f"  จัดอันดับโปรเด่นไม่สำเร็จ: {e}")
        return ""


async def scrape_bank_pages(browser, client, url: str) -> tuple[list[PromoItem], int]:
    """เปิดหน้าลิสต์โปรของธนาคารหนึ่งแห่ง ไล่อ่านทุกหน้าจนหมด
    (กดหน้าถัดไป / โหลดเพิ่มเติม) แล้วสกัดโปรรวมกันครั้งเดียว

    คืน (รายการโปรโมชั่น, จำนวนหน้าที่อ่าน)
    หยุดเมื่อ: ไม่มีปุ่มหน้าถัดไปแล้ว / ข้อความหน้าซ้ำกับหน้าที่อ่านแล้ว
    (กดแล้วไม่เปลี่ยนหน้า เช่น ปุ่มลูกศรของแบนเนอร์) / ครบ MAX_PAGES_PER_BANK
    """
    print(f"กำลังดึงข้อมูล: {url}")
    page = await browser.new_page()
    page_texts = []
    seen_hashes = set()
    pages_read = 0
    try:
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        # ปิดแบนเนอร์คุกกี้ก่อน (ถ้ามี) จะได้ไม่บังปุ่มแบ่งหน้า
        await _click_if_visible(page, COOKIE_ACCEPT_SELECTORS)

        for _ in range(MAX_PAGES_PER_BANK):
            # กดปุ่มโหลดเพิ่ม (ถ้ามี) จนกว่าจะหมด แล้วค่อยอ่านข้อความของหน้านี้
            for _ in range(LOAD_MORE_MAX_CLICKS):
                if not await _click_if_visible(page, LOAD_MORE_SELECTORS):
                    break
                await page.wait_for_timeout(3000)

            await page.wait_for_timeout(2000)
            text = await page.evaluate("() => document.body.innerText")
            text_hash = hash(text)
            if text_hash in seen_hashes:
                break  # กดแล้วได้หน้าเดิมซ้ำ แปลว่าหมดหน้าแล้ว
            seen_hashes.add(text_hash)
            page_texts.append(text)
            pages_read += 1

            # หาปุ่มหน้าถัดไป ถ้าไม่มีก็จบ
            if not await _click_if_visible(page, NEXT_PAGE_SELECTORS):
                break
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  ดึงข้อมูลจาก {url} ไม่สำเร็จ: {e}")
        return [], pages_read
    finally:
        await page.close()

    combined = "\n\n===== หน้าถัดไป =====\n\n".join(page_texts)[:MAX_TEXT_CHARS]
    if not combined.strip():
        return [], pages_read
    promos = await extract_promos_from_page(client, combined, url)
    print(f"  อ่าน {pages_read} หน้า พบ {len(promos)} รายการ")
    return promos, pages_read


async def main():
    if not API_KEY:
        print("❌ ข้อผิดพลาด: ไม่พบ GEMINI_API_KEY")
        return

    client = genai.Client(api_key=API_KEY)
    total_new = 0
    total_updated = 0
    total_found = 0
    total_pages = 0
    new_records = []  # โปรใหม่เดือนนี้ (ไว้จัดอันดับโปรเด่น)
    failed_banks = []  # ธนาคารที่อ่านไม่สำเร็จ (จะได้ไม่พังทั้งรอบเพราะธนาคารเดียว)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = get_connection()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for url in TARGET_URLS:
                    try:
                        promos, pages = await scrape_bank_pages(browser, client, url)
                    except Exception as e:
                        print(f"  ข้าม {urlparse(url).netloc}: {e}")
                        failed_banks.append(urlparse(url).netloc)
                        continue
                    total_pages += pages
                    total_found += len(promos)
                    new_count = 0
                    updated_count = 0
                    for item in promos:
                        record = item.model_dump()
                        record["source_url"] = url
                        record["updated_at"] = now
                        if upsert_promo(conn, record):
                            new_count += 1
                            new_records.append(record)
                        else:
                            updated_count += 1
                    conn.commit()
                    total_new += new_count
                    total_updated += updated_count
                    print(f"  พบ {len(promos)} รายการ (ใหม่ {new_count}, อัปเดต {updated_count})")
            finally:
                await browser.close()
    finally:
        conn.close()

    conn = get_connection()
    try:
        total_in_db = count_all(conn)
    finally:
        conn.close()

    # จัดอันดับโปรใหม่เดือนนี้ที่คุ้มที่สุด 1-3 อันดับ (เฉพาะบัตรที่ถืออยู่)
    top_section = ""
    held_new = [r for r in new_records if r.get("bank") in MY_BANKS]
    if held_new:
        top_section = await rank_top_promos(client, held_new)

    status_icon = "✅" if not failed_banks else "⚠️"
    status_text = "อัปเดตโปรโมชั่นบัตรเครดิตประจำเดือนสำเร็จ" if not failed_banks else "อัปเดตโปรโมชั่นประจำเดือนสำเร็จบางส่วน"
    summary = (
        f"{status_icon} *{status_text}*\n\n"
        f"• ตรวจ {len(TARGET_URLS)} เว็บธนาคาร ({total_pages} หน้า)\n"
        f"• พบโปรโมชั่นทั้งหมด {total_found} รายการ\n"
        f"• ใหม่ {total_new} รายการ / อัปเดต {total_updated} รายการ\n"
        f"• ฐานข้อมูลมีทั้งหมด {total_in_db} รายการ"
    )
    if failed_banks:
        summary += f"\n• ⚠️ อ่านไม่สำเร็จ {len(failed_banks)} ธนาคาร ({', '.join(failed_banks)}) — จะลองใหม่รอบหน้า"
    if top_section:
        summary += f"\n\n🏆 *โปรเด่นเดือนนี้ (บัตรที่ถืออยู่)*\n{top_section}"
    print(summary)
    send_telegram_message(summary, button_url=DASHBOARD_URL if DASHBOARD_URL else None)


if __name__ == "__main__":
    asyncio.run(main())
