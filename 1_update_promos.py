"""สคริปต์กวาดโปรโมชั่นบัตรเครดิตประจำเดือน (เวอร์ชัน SQLite)"""

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

# -------------------------------------------------------------
# 1. ตั้งค่า Environment Variables และ ตัวแปรพื้นฐาน
# -------------------------------------------------------------
API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

TARGET_URLS = [
    "https://www.ktc.co.th/promotion?promotion-card=credit-card",
    "https://www.cardx.co.th/th-TH/credit-card/promotion",
    "https://www.kasikornbank.com/th/promotion/creditcard/pages/index.aspx",
    "https://www.krungsricard.com/th/promotion",
    "https://www.ttbbank.com/th/promotion",
    "https://www.uob.co.th/personal/credit-cards/promotions.page?i_cid=default-top-menu",
    "https://www.aeon.co.th/aeon/promotions/",
    "https://www.bangkokbank.com/th/personal/cards/credit-cards/promotions",
    "https://www.icbcthai.com/th/column/1438059037072965646.html",
    "https://www.gsb.or.th/promotions-privilege/",
]

MAX_PAGES_PER_BANK = 25
LOAD_MORE_MAX_CLICKS = 5

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
    "a:has-text('>')",           # เพิ่มสัญลักษณ์ลูกศร
    "button:has-text('>')",      # เพิ่มสัญลักษณ์ลูกศรแบบปุ่ม
    ".pagination-next",          # เพิ่ม class ยอดฮิต
    "li.next a",                 # เพิ่มโครงสร้าง list ยอดฮิต
]

LOAD_MORE_SELECTORS = [
    "button:has-text('โหลดเพิ่มเติม')",
    "a:has-text('โหลดเพิ่มเติม')",
    "button:has-text('แสดงเพิ่มเติม')",
    "button:has-text('Load more')",
    "a:has-text('Load more')",
]

COOKIE_ACCEPT_SELECTORS = [
    "button:has-text('ยอมรับทั้งหมด')",
    "button:has-text('ยอมรับคุกกี้')",
    "button:has-text('Accept all')",
    "button:has-text('Accept cookies')",
]

# -------------------------------------------------------------
# 2. กำหนดโครงสร้างข้อมูล (Pydantic Models) - ต้องอยู่ก่อนฟังก์ชัน
# -------------------------------------------------------------
class PromoItem(BaseModel):
    bank: str = Field(description="ชื่อธนาคาร ใช้ตามนี้เท่านั้น: KTC, CardX, KBank, Krungsri, ttb, UOB, Aeon, Bangkok Bank, ICBC, ออมสิน")
    category: str = Field(description="หมวดหมู่ของโปรโมชั่น เช่น ร้านอาหาร, ช้อปปิ้งออนไลน์, ท่องเที่ยว, ซุปเปอร์มาร์เก็ต, ไอทีและเครื่องใช้ไฟฟ้า, อื่นๆ")
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

# -------------------------------------------------------------
# 3. ฟังก์ชันระบบแจ้งเตือนและเครื่องมือช่วยเหลือ
# -------------------------------------------------------------
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
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{"text": button_text, "url": button_url}]]
        })

    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
    except Exception:
        payload.pop("parse_mode", None)
        try:
            requests.post(url, json=payload, timeout=10).raise_for_status()
        except Exception as e:
            print(f"เกิดข้อผิดพลาดในการส่ง Telegram: {e}")

async def _click_if_visible(page, selectors):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() and await el.is_visible() and await el.is_enabled():
                await el.click(timeout=5000)
                return True
        except Exception:
            continue
    return False

# -------------------------------------------------------------
# 4. ฟังก์ชัน AI และการ Scraping
# -------------------------------------------------------------
async def extract_promos_from_page(client, page_text: str, source_url: str) -> list[PromoItem]:
    prompt = f"""
    คุณคือระบบดึงข้อมูลโปรโมชั่นบัตรเครดิตจากหน้าเว็บธนาคาร
    URL ต้นทาง: {source_url}

    เนื้อหาหน้าเว็บ:
    {page_text}

    ภารกิจ: ดึงข้อมูลโปรโมชั่นบัตรเครดิตทั้งหมด "ทุกหมวดหมู่" ที่ปรากฏในเนื้อหา 
    (เช่น ร้านอาหาร, ท่องเที่ยว, ช้อปปิ้ง, ซุปเปอร์มาร์เก็ต, เครื่องใช้ไฟฟ้า, โรงพยาบาล ฯลฯ) 
    และคืนค่าเป็น JSON ตาม schema ที่กำหนด

    ชื่อธนาคารให้ใช้ตามนี้เท่านั้น: KTC, CardX, KBank, Krungsri, ttb, UOB, Aeon, Bangkok Bank, ICBC, ออมสิน

    กฎ:
    - เก็บข้อมูลโปรโมชั่นทุกหมวดหมู่ ห้ามข้าม
    - จำแนกหมวดหมู่ (category) ให้ถูกต้องตามประเภทของร้านค้าหรือแพลตฟอร์ม
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
                raise
            if attempt == 2:
                raise
            wait = 30 * (attempt + 1)
            print(f"  Gemini ชั่วคราวไม่ว่าง รอ {wait} วินาทีแล้วลองใหม่ (ครั้งที่ {attempt + 2}/3)")
            await asyncio.sleep(wait)
    raise last_error

async def rank_top_promos(client, new_promos: list[dict]) -> str:
    if not new_promos:
        return ""
    items = [
        {
            "bank": p.get("bank", ""),
            "category": p.get("category", ""),
            "merchant": p.get("merchant_or_platform", ""),
            "min_spend": p.get("min_spend", 0),
            "reward_detail": p.get("reward_detail", ""),
        }
        for p in new_promos
    ]
    prompt = f"""
    คุณเป็นที่ปรึกษาด้านความคุ้มค่าของบัตรเครดิต
    บัตรที่ผู้ใช้ถืออยู่จริง: {MY_CARDS}
    โปรโมชั่นใหม่ประจำเดือนนี้:
    {json.dumps(items, ensure_ascii=False)}

    จัดอันดับโปรโมชั่นที่คุ้มที่สุด 3 อันดับแรก โดยดูจากมูลค่าที่ได้รับจริง
    ตอบสั้นๆ อันดับละ 1 บรรทัด รูปแบบนี้เท่านั้น:
    1. [ธนาคาร] ร้านค้า: ได้อะไรเท่าไหร่ (ขั้นต่ำ X บาท)
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
    print(f"กำลังดึงข้อมูล: {url}")
    page = await browser.new_page()
    all_promos = []
    seen_promo_keys = set()
    seen_hashes = set()
    pages_read = 0

    try:
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        await _click_if_visible(page, COOKIE_ACCEPT_SELECTORS)

        for _ in range(MAX_PAGES_PER_BANK):
            for _ in range(LOAD_MORE_MAX_CLICKS):
                if not await _click_if_visible(page, LOAD_MORE_SELECTORS):
                    break
                await page.wait_for_timeout(3000)

            await page.wait_for_timeout(2000)
            text = await page.evaluate("() => document.body.innerText")
            text_hash = hash(text)
            
            if text_hash in seen_hashes:
                break
            
            seen_hashes.add(text_hash)
            pages_read += 1

            print(f"  กำลังส่งข้อมูลหน้าที่ {pages_read} ให้ AI วิเคราะห์...")
            
            if text.strip():
                try:
                    # ตัดข้อความต่อหน้า ป้องกัน Token ทะลุ
                    page_text_limited = text[:15000] 
                    page_promos = await extract_promos_from_page(client, page_text_limited, url)
                    
                    new_in_page = 0
                    for promo in page_promos:
                        unique_key = (
                            promo.bank.strip(),
                            promo.merchant_or_platform.strip(),
                            promo.reward_detail.strip(),
                            promo.end_date.strip()
                        )
                        if unique_key not in seen_promo_keys:
                            seen_promo_keys.add(unique_key)
                            all_promos.append(promo)
                            new_in_page += 1
                            
                    print(f"  > หน้าที่ {pages_read} พบโปรโมชั่น {len(page_promos)} รายการ (ไม่ซ้ำ {new_in_page} รายการ)")
                except Exception as e:
                    print(f"  > หน้าที่ {pages_read} วิเคราะห์ไม่สำเร็จ ข้ามไปหน้าถัดไป: {e}")

            if not await _click_if_visible(page, NEXT_PAGE_SELECTORS):
                break
                
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(4000)

    except Exception as e:
        print(f"  ดึงข้อมูลจาก {url} ไม่สำเร็จ: {e}")
    finally:
        await page.close()

    print(f"  สรุป: อ่านทั้งหมด {pages_read} หน้า พบรวม (ไม่ซ้ำ) {len(all_promos)} รายการ")
    return all_promos, pages_read

# -------------------------------------------------------------
# 5. ฟังก์ชัน Main
# -------------------------------------------------------------
async def main():
    if not API_KEY:
        print("❌ ข้อผิดพลาด: ไม่พบ GEMINI_API_KEY")
        return

    client = genai.Client(api_key=API_KEY)
    total_new = 0
    total_updated = 0
    total_found = 0
    total_pages = 0
    new_records = []
    failed_banks = []
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
                    print(f"  บันทึกลง DB: ใหม่ {new_count}, อัปเดต {updated_count}")
            finally:
                await browser.close()
    finally:
        conn.close()

    conn = get_connection()
    try:
        total_in_db = count_all(conn)
    finally:
        conn.close()

    top_section = ""
    held_new = [r for r in new_records if r.get("bank") in MY_BANKS]
    if held_new:
        top_section = await rank_top_promos(client, held_new)

    status_icon = "✅" if not failed_banks else "⚠️"
    status_text = "อัปเดตโปรโมชั่นบัตรเครดิตประจำเดือนสำเร็จ" if not failed_banks else "อัปเดตโปรโมชั่นสำเร็จบางส่วน"
    
    summary = (
        f"{status_icon} *{status_text}*\n\n"
        f"• ตรวจ {len(TARGET_URLS)} เว็บธนาคาร ({total_pages} หน้า)\n"
        f"• ดึงโปรโมชั่นสุทธิมาได้ {total_found} รายการ\n"
        f"• บันทึกใหม่ {total_new} รายการ / อัปเดตทับ {total_updated} รายการ\n"
        f"• ฐานข้อมูลมีทั้งหมด {total_in_db} รายการ"
    )
    
    if failed_banks:
        summary += f"\n• ⚠️ อ่านไม่สำเร็จ {len(failed_banks)} ธนาคาร ({', '.join(failed_banks)})"
    if top_section:
        summary += f"\n\n🏆 *โปรเด่นเดือนนี้ (บัตรที่ถืออยู่)*\n{top_section}"
        
    print(summary)
    send_telegram_message(summary, button_url=DASHBOARD_URL if DASHBOARD_URL else None)

if __name__ == "__main__":
    asyncio.run(main())