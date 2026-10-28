"""ตรรกะแนะนำบัตรเครดิต: แยกวิเคราะห์คำถาม -> กรองด้วยเงื่อนไขที่วัดได้
-> ให้ Gemini จัดอันดับเฉพาะตัวที่ผ่านเงื่อนไข

หลักการสำคัญ: ไม่ยัดฐานข้อมูลทั้งก้อนใส่ prompt
กรองด้วย SQL ก่อน (แพลตฟอร์มตรง + ยอดถึงขั้นต่ำ + ยังไม่หมดอายุ
+ เฉพาะธนาคารของบัตรที่ถืออยู่) แล้วค่อยให้ LLM คำนวณและอธิบาย
เฉพาะตัวเลือกที่ผ่าน — ถูกกว่า แม่นกว่า ไม่หลอน
"""

import os
import re
import time

from dotenv import load_dotenv

load_dotenv()  # ให้รันบนเครื่อง/NAS อ่านค่าจากไฟล์ .env ได้

from db import DB_PATH, GEMINI_MODEL, find_candidates, get_connection

API_KEY = os.getenv("GEMINI_API_KEY", "")

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
    "ICBC",
]

CARD_BANK = {
    "KTC Platinum Visa": "KTC",
    "CardX Beyond Mastercard": "CardX",
    "ttb so smart": "ttb",
    "Krungsri Now": "Krungsri",
    "ออมสิน": "ออมสิน",
    "KBank": "KBank",
    "UOB": "UOB",
    "Aeon": "Aeon",
    "Bangkok Bank": "Bangkok Bank",
    "ICBC": "ICBC",
}
MY_BANKS = set(CARD_BANK.values())

# ตัวเลขตามด้วย บาท/฿ เช่น "2,800 บาท" หรือ "500฿"
AMOUNT_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:บาท|฿)")
# ตัวเลขลอยๆ อย่างน้อย 3 หลัก (ใช้เฉพาะเมื่อไม่เจอแบบมีหน่วย)
BARE_AMOUNT_RE = re.compile(r"([\d,]{3,}(?:\.\d+)?)")


def parse_query(query: str, conn=None) -> tuple[str | None, float | None]:
    """ดึงแพลตฟอร์มและยอดเงินออกจากคำถามภาษาธรรมชาติ

    - ยอดเงิน: ตัวเลขตามด้วย บาท/฿ ถ้าไม่มีหน่วยให้ใช้ตัวเลขลอยๆ อย่างน้อย 3 หลัก
    - แพลตฟอร์ม: เทียบกับชื่อร้านค้าในฐานข้อมูล (ไม่เจอถือว่าไม่ระบุ = ดูทุกแพลตฟอร์ม)
    """
    amount = None
    m = AMOUNT_RE.search(query)
    if not m:
        m = BARE_AMOUNT_RE.search(query)
    if m:
        try:
            amount = float(m.group(1).replace(",", ""))
        except ValueError:
            amount = None

    platform = None
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        merchants = [
            r["merchant_or_platform"]
            for r in conn.execute(
                "SELECT DISTINCT merchant_or_platform FROM promotions"
            ).fetchall()
        ]
    finally:
        if own_conn:
            conn.close()

    q = query.lower()
    for merchant in merchants:
        if merchant and merchant.lower() in q:
            platform = merchant
            break
    return platform, amount


def rank_with_gemini(
    query: str, platform: str | None, amount: float, candidates: list[dict]
) -> str:
    """ให้ Gemini จัดอันดับเฉพาะตัวที่ผ่านเงื่อนไขแล้ว และคำนวณเงินที่ประหยัดได้

    กันค้าง: เรียก Gemini แบบมี timeout 60 วินาทีต่อครั้ง
    (ก่อนหน้านี้ไม่มี timeout บอทเลยเงียบไปหลายนาทีตอน Gemini ช้า
    เช่นที่เจอ 2026-10-28) ถ้า Gemini ชั่วคราวไม่ว่าง (503/429/overloaded)
    จะลองใหม่อีก 1 ครั้ง แล้วค่อยโยน error ให้ advise() ตอบแบบรายการแทน
    """
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=API_KEY,
        http_options=types.HttpOptions(timeout=60_000),  # มิลลิวินาที
    )
    prompt = f"""
    คุณเป็นที่ปรึกษาด้านความคุ้มค่าของบัตรเครดิต

    บัตรที่ผู้ใช้ถืออยู่จริง: {MY_CARDS}
    ผู้ใช้จะซื้อของที่: {platform or 'ไม่ระบุแพลตฟอร์ม'} ยอดเงิน: {amount:,.0f} บาท
    โปรโมชั่นที่ผ่านเงื่อนไขแล้ว (แพลตฟอร์มตรง ยอดถึงขั้นต่ำ ยังไม่หมดอายุ):
    {candidates}

    โปรดตอบตามลำดับ:
    1. บัตรอันดับ 1 ที่คุ้มที่สุด (คำนวณยอดเงินที่ประหยัดหรือเงินคืนเป็นบาทให้เห็นชัดเจน)
    2. บัตรอันดับ 2 (ถ้ามี)
    3. เปรียบเทียบช่วงเวลา: ถ้าซื้อวันนี้ กับ รอซื้อวันแคมเปญพิเศษ (Payday สิ้นเดือน หรือวันพิเศษ) แบบไหนคุ้มกว่ากันเท่าไหร่
    4. ข้อควรระวัง / เงื่อนไขที่ห้ามพลาด (เช่น รหัส SMS, สิทธิ์จำกัด)
    """
    last_error = None
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            last_error = e
            msg = str(e)
            transient = any(
                s in msg
                for s in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
                          "overloaded", "high demand", "timeout", "timed out")
            )
            if not transient or attempt == 1:
                raise
            print(f"  Gemini ชั่วคราวไม่ว่าง ({msg[:100]}), รอ 10 วินาทีแล้วลองใหม่")
            time.sleep(10)
    raise last_error


def format_links_section(candidates: list[dict]) -> str:
    """ลิงก์ไปหน้าโปรของธนาคารสำหรับโปรที่แนะนำ (กดแล้วเปิดหน้าลิสต์โปรของธนาคารนั้น)

    หมายเหตุ: scraper เก็บ source_url เป็น URL หน้าลิสต์โปรของธนาคาร
    (ไม่ได้ตามลิงก์ "ดูเพิ่มเติม" ไปหน้าละเอียดของแต่ละโปร) ลิงก์จึงพาไป
    หน้าลิสต์โปรของธนาคาร ให้หาโปรชื่อนี้ในหน้านั้นอีกที
    โปรที่ไม่มี URL จะไม่มีบรรทัดลิงก์ และ URL ซ้ำกันจะแสดงครั้งเดียว
    """
    seen: dict[str, tuple[str, str]] = {}
    for c in candidates:
        url = (c.get("source_url") or "").strip()
        if not url:
            continue
        if url not in seen:
            seen[url] = (c.get("bank", ""), c.get("merchant_or_platform", ""))
    if not seen:
        return ""
    lines = ["\n🔗 ลิงก์โปรโมชันที่แนะนำ (กดเพื่อเปิดหน้าลิสต์โปรของธนาคาร)"]
    for url, (bank, merchant) in seen.items():
        lines.append(f"• [{bank}] {merchant}: {url}")
    return "\n".join(lines)


def format_plain_list(candidates: list[dict], note: str = "") -> str:
    """รายการโปรที่เข้าเงื่อนไขแบบไม่ผ่าน AI (ใช้ตอนไม่มี API key
    หรือตอน Gemini ตอบไม่ทัน/ไม่ว่าง — อย่างน้อยผู้ใช้ก็ได้คำตอบ)"""
    lines = [f"เจอ {len(candidates)} โปรโมชั่นที่เข้าเงื่อนไข:"]
    for c in candidates:
        lines.append(
            f"- [{c['bank']}] {c['merchant_or_platform']}: "
            f"{c['reward_detail']} (ขั้นต่ำ {c['min_spend']:,.0f} บาท)"
        )
    if note:
        lines.append(f"\n({note})")
    return "\n".join(lines)


def advise(query: str, db_path: str = DB_PATH) -> str:
    """จุดเข้าเดียว: รับคำถามภาษาธรรมชาติ คืนคำแนะนำเป็นข้อความ"""
    conn = get_connection(db_path)
    try:
        platform, amount = parse_query(query, conn)
        if amount is None:
            return (
                "บอกยอดเงินที่จะซื้อหน่อยครับ เช่น "
                "\"ซื้อของ Shopee 2,800 บาท ใช้บัตรไหนดี\""
            )
        candidates = find_candidates(conn, platform, amount, MY_BANKS)
    finally:
        conn.close()

    if not candidates:
        where = f"ที่ {platform} " if platform else ""
        return (
            f"ไม่เจอโปรโมชั่นของบัตรที่ถืออยู่ {where}"
            f"สำหรับยอด {amount:,.0f} บาทครับ "
            "(อาจยังไม่ถึงยอดขั้นต่ำ หรือโปรหมดอายุแล้ว) "
            "ลองเช็กยอดขั้นต่ำหรือแพลตฟอร์มอื่นดูครับ"
        )

    if not API_KEY:
        return format_plain_list(
            candidates, "ตั้งค่า GEMINI_API_KEY เพื่อให้ AI คำนวณและจัดอันดับให้"
        ) + format_links_section(candidates)

    try:
        answer = rank_with_gemini(query, platform, amount, candidates)
    except Exception as e:
        # Gemini ตอบไม่ทันหรือไม่ว่าง: ตอบเป็นรายการที่เข้าเงื่อนไขแทน
        # ดีกว่าปล่อยให้ผู้ใช้รอโดยไม่มีคำตอบ (เจอ 2026-10-28)
        print(f"  ⚠️ Gemini จัดอันดับไม่ได้ ({str(e)[:120]}), ตอบแบบรายการแทน")
        return format_plain_list(
            candidates,
            "AI จัดอันดับให้ไม่ทันตอนนี้ เลยแสดงรายการที่เข้าเงื่อนไขให้ก่อน — ลองถามใหม่อีกครั้งได้ครับ",
        ) + format_links_section(candidates)
    return answer + format_links_section(candidates)
