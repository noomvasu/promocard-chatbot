# บอท Telegram อย่างเดียว (ไม่รวมสคริปต์กวาดข้อมูล)
# สคริปต์กวาดข้อมูลรายเดือนยังรันบน GitHub Actions เหมือนเดิม
# อิมเมจนี้จึงไม่ต้องลง Playwright / Chromium / Streamlit ให้หนักเครื่อง NAS
FROM python:3.11-slim

WORKDIR /app

# ติดตั้งเฉพาะที่บอทต้องใช้จริง
RUN pip install --no-cache-dir \
    python-telegram-bot>=21.0 \
    google-genai>=1.0.0 \
    python-dotenv>=1.0.0

COPY db.py advisor.py bot.py ./

# promotions.db มาจากการ mount โฟลเดอร์ repo ของ NAS (ดู docker-compose.yml)
# ถ้าไฟล์ยังว่าง/ยังไม่มีข้อมูล บอทจะตอบว่าไม่เจอโปร — ต้อง git pull หลัง
# รัน workflow_dispatch บน GitHub สำเร็จก่อน (ดู README หัวข้อ "รันบอทบน NAS")
CMD ["python", "bot.py"]
