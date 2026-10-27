#!/bin/sh
# อัปเดต promotions.db บน NAS จาก GitHub repo (สคริปต์กวาดข้อมูล commit ไฟล์นี้ทุกต้นเดือน)
# วิธีใช้บน Synology: Control Panel > Task Scheduler > Create > Scheduled Task > User-defined script
#   ตั้งรันวันที่ 2 ของทุกเดือน เวลา 08:00 น. ใส่คำสั่ง:
#     cd /volume1/docker/promo-chatbot && sh sync_db.sh
#   (แก้ path ให้ตรงโฟลเดอร์ที่ clone repo ไว้จริง)
# หรือรันมือ: sh sync_db.sh
# บอทอ่าน DB ใหม่ทุกคำถาม จึงไม่ต้อง restart container หลัง sync
set -e
cd "$(dirname "$0")"
git pull --ff-only
echo "promotions.db updated: $(ls -l promotions.db 2>/dev/null || echo 'ยังไม่มีไฟล์ — รัน workflow_dispatch บน GitHub ก่อน')"
