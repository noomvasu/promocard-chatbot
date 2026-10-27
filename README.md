# แชทบอทโปรโมชั่นบัตรเครดิต 💳

เก็บโปรโมชั่นบัตรเครดิตของธนาคารไทยทุกต้นเดือน แล้วถามได้ว่า
"ซื้อของที่แอพนี้ ยอดเท่านี้ ควรใช้บัตรใบไหน"

## หลักการทำงาน

```
ทุกวันที่ 1 ของเดือน (GitHub Actions)
  1_update_promos.py  -- Playwright เปิดหน้าโปรโมชั่น 10 ธนาคาร
  ไล่อ่านทุกหน้าจนหมด (กดหน้าถัดไป / โหลดเพิ่มเติม, สูงสุด 25 หน้าต่อธนาคาร)
  แล้วรวมข้อความทุกหน้าส่งให้ Gemini ครั้งเดียวต่อธนาคาร
  สุดท้ายให้ Gemini จัดอันดับโปรใหม่เดือนนี้ที่คุ้มที่สุด 1-3 อันดับ
  (เฉพาะธนาคารของบัตรที่ถืออยู่) แปะท้ายสรุป Telegram
                      -> Gemini แปลงเป็นรายการแบบมีโครงสร้าง
                      -> บันทึกลง promotions.db (SQLite)
                      -> สรุปผลทาง Telegram

ถาม-ตอบ (Telegram bot / Streamlit)
  advisor.py          -- แยกแพลตฟอร์ม + ยอดเงินออกจากคำถาม
                      -> กรองด้วย SQL (แพลตฟอร์มตรง, ยอดถึงขั้นต่ำ,
                         ยังไม่หมดอายุ, เฉพาะธนาคารของบัตรที่ถือ)
                      -> Gemini จัดอันดับเฉพาะตัวที่ผ่าน
```

ต่างจากแบบเดิมตรงที่ **ไม่ยัดฐานข้อมูลทั้งก้อนใส่ prompt** —
กรองด้วยเงื่อนไขที่วัดได้ก่อน แล้วค่อยให้ LLM คำนวณและอธิบาย
เฉพาะตัวเลือกที่ผ่าน ถูกกว่า แม่นกว่า ไม่หลอน

## โครงสร้างไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `db.py` | ชั้นข้อมูล SQLite (schema, upsert, ค้นหาตัวเลือก) |
| `1_update_promos.py` | สคริปต์กวาดโปรโมชั่นรายเดือน |
| `advisor.py` | ตรรกะแนะนำบัตร (แยกคำถาม → กรอง → จัดอันดับ) |
| `bot.py` | Telegram bot ถาม-ตอบ |
| `alert_checker.py` | แจ้งเตือนโปรใกล้เริ่ม/ใกล้หมด (ล่วงหน้า 3 วัน) |
| `app.py` | Dashboard Streamlit ดูรายการโปรโมชั่น + ถาม AI |
| `.github/workflows/scrape_and_alert.yaml` | GitHub Actions รันรายเดือน |
| `Dockerfile` / `docker-compose.yml` | รัน Telegram bot บน NAS ด้วย Docker |
| `sync_db.sh` | ดึง `promotions.db` ตัวใหม่จาก GitHub ลง NAS (รันผ่าน DSM Task Scheduler) |
| `.env.example` | ตัวอย่างไฟล์ `.env` (คัดลอกเป็น `.env` แล้วใส่ค่าจริง) |
| `promotions.db` | ฐานข้อมูล SQLite (สร้างอัตโนมัติตอนรันครั้งแรก) |

## บัตรที่รองรับ (แก้ได้ใน `advisor.py`)

- KTC Platinum Visa
- CardX Beyond Mastercard
- ttb so smart
- Krungsri Now
- ออมสิน
- KBank
- UOB
- Aeon
- Bangkok Bank
- ICBC

## ตั้งค่า

### 1. ติดตั้ง dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. ตั้งค่า Secrets (GitHub → Settings → Secrets and variables → Actions)

| Secret | ใช้ทำอะไร |
|---|---|
| `GEMINI_API_KEY` | เรียก Gemini (สกัดโปร + จัดอันดับ) |
| `TELEGRAM_BOT_TOKEN` | ส่งสรุปผลและแจ้งเตือนทาง Telegram |
| `TELEGRAM_CHAT_ID` | แชทปลายทางที่จะรับข้อความ |
| `DASHBOARD_URL` | ลิงก์ปุ่มเปิด Dashboard (ไม่บังคับ) |

สำหรับรันบนเครื่องตัวเอง ให้ตั้งค่าเป็น environment variable แทน
หรือสร้างไฟล์ `.env` (อย่า commit ขึ้น repo)

### 3. วาง workflow ให้ถูกที่

ไฟล์ `scrape_and_alert.yaml` ต้องอยู่ที่ `.github/workflows/scrape_and_alert.yaml`
ใน repo ถึงจะทำงาน

### 4. ทดสอบรันครั้งแรก

บนหน้า GitHub: Actions → Monthly Bank Promos Scraper and Alert
→ Run workflow (ปุ่ม `workflow_dispatch`)

รันสำเร็จแล้ว `promotions.db` จะมีข้อมูลเข้า และบอทจะตอบคำถามได้

## รัน Telegram bot

```bash
cp .env.example .env   # แล้วใส่ TELEGRAM_BOT_TOKEN กับ GEMINI_API_KEY
export TELEGRAM_BOT_TOKEN="xxx"
export GEMINI_API_KEY="xxx"
python bot.py
```

บอททำงานแบบ polling — ต้องเปิดเครื่องทิ้งไว้

### รันบอทบน NAS ด้วย Docker (แนะนำ — NAS เปิดทิ้งไว้อยู่แล้ว)

ไฟล์ที่เตรียมไว้ให้: `Dockerfile`, `docker-compose.yml`, `sync_db.sh`, `.env.example`

1. **บน NAS (Synology Container Manager):** clone repo นี้ลงโฟลเดอร์ เช่น `/volume1/docker/promo-chatbot`
2. คัดลอก `.env.example` เป็น `.env` แล้วใส่ `TELEGRAM_BOT_TOKEN` กับ `GEMINI_API_KEY` (ค่าเดียวกับ GitHub Secrets)
3. **สำคัญ — บอทตอบได้ก็ต่อเมื่อ `promotions.db` มีข้อมูลแล้ว:** ต้องรัน `workflow_dispatch` บน GitHub ให้สำเร็จก่อน 1 รอบ แล้วค่อย `git pull` ในโฟลเดอร์บน NAS (หรือรัน `sh sync_db.sh`) ไม่งั้นบอทจะขึ้น log ว่า "ฐานข้อมูลยังว่าง" และตอบว่าไม่เจอโปร
4. รัน `docker compose up -d` (หรือสร้าง Project ใน Container Manager แล้ววางเนื้อหา `docker-compose.yml`)
5. **อัปเดต DB ทุกเดือน:** สคริปต์กวาดข้อมูล commit `promotions.db` ใหม่ทุกวันที่ 1 — ตั้ง Task Scheduler บน DSM ให้รันวันที่ 2 เวลา 08:00 น. ด้วยคำสั่ง `cd /volume1/docker/promo-chatbot && sh sync_db.sh` (แก้ path ให้ตรงโฟลเดอร์จริง) บอทอ่าน DB ใหม่ทุกคำถาม ไม่ต้อง restart container

ทางเลือกอื่นถ้าไม่อยากรันบน NAS: VPS / Railway / Fly.io เครื่องเล็กๆ

ตัวอย่างคำถาม:
- ซื้อของ Shopee 2,800 บาท ใช้บัตรไหนดี
- Lazada 5,000 บาท บัตรไหนคุ้มสุด

## รัน Dashboard

```bash
streamlit run app.py
```

## หมายเหตุ

- หน้าเว็บธนาคารส่วนใหญ่ต้องใช้ JavaScript — การกวาดข้อมูลจริง
- สคริปต์ไล่อ่านทุกหน้าของแต่ละธนาคาร (สูงสุด 25 หน้า) แต่ยังไม่เปิดหน้า
  รายละเอียดของแต่ละโปร ("ดูเพิ่มเติม") เงื่อนไขเต็มๆ บางโปรอาจไม่ครบ
  ถ้าต้องการรายละเอียดเต็ม ต้องเพิ่มขั้นเปิดหน้ารายละเอียดทีละโปร
  (แลกกับจำนวนครั้งที่เรียก Gemini เพิ่มขึ้นมาก)
  ต้องรันด้วย Playwright เท่านั้น เปิดดูแบบข้อความธรรมดาพิสูจน์อะไรไม่ได้
- ถ้าธนาคารเปลี่ยน layout หน้าเว็บ Gemini อาจสกัดข้อมูลพลาด
  ให้เช็ก `source_url` ในฐานข้อมูลย้อนกลับไปดูต้นทางได้เสมอ
- รอบอัตโนมัติ: ทุกวันที่ 1 เวลา 00:00 UTC (07:00 น. เวลาไทย)
