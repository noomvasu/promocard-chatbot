"""ชั้นข้อมูล SQLite สำหรับระบบโปรโมชั่นบัตรเครดิต

ทำไมใช้ SQLite แทน TinyDB:
- เป็นไฟล์เดียวเหมือนเดิม ไม่ต้องมีเซิร์ฟเวอร์ฐานข้อมูล
- ค้นหาด้วยเงื่อนไขได้จริง (แพลตฟอร์ม, ยอดขั้นต่ำ, วันหมดอายุ, ธนาคาร)
- กันข้อมูลซ้ำด้วย UNIQUE constraint
"""

import os
import sqlite3
from datetime import date

# เปิดทางให้รันบน Docker/NAS ชี้ DB ไปที่ไฟล์ที่ mount มาได้
# ค่าเริ่มต้นเหมือนเดิม: promotions.db ในโฟลเดอร์เดียวกับโค้ด
DB_PATH = os.getenv("PROMOTIONS_DB", "promotions.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank TEXT NOT NULL,
    merchant_or_platform TEXT NOT NULL,
    min_spend REAL NOT NULL DEFAULT 0,
    reward_type TEXT,
    reward_detail TEXT,
    start_date TEXT,
    end_date TEXT,
    special_timing_condition TEXT,
    key_conditions TEXT,
    source_url TEXT,
    updated_at TEXT,
    UNIQUE(bank, merchant_or_platform, reward_detail)
);
"""


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def upsert_promo(conn: sqlite3.Connection, promo: dict) -> bool:
    """บันทึก 1 รายการ: คืน True = ใหม่, False = อัปเดตของเดิม"""
    cur = conn.execute(
        "SELECT id FROM promotions "
        "WHERE bank = ? AND merchant_or_platform = ? AND reward_detail = ?",
        (promo["bank"], promo["merchant_or_platform"], promo["reward_detail"]),
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            """UPDATE promotions
               SET min_spend = ?, reward_type = ?, start_date = ?, end_date = ?,
                   special_timing_condition = ?, key_conditions = ?,
                   source_url = ?, updated_at = ?
               WHERE id = ?""",
            (
                promo.get("min_spend", 0),
                promo.get("reward_type", ""),
                promo.get("start_date", ""),
                promo.get("end_date", ""),
                promo.get("special_timing_condition", ""),
                promo.get("key_conditions", ""),
                promo.get("source_url", ""),
                promo.get("updated_at", ""),
                row["id"],
            ),
        )
        return False
    conn.execute(
        """INSERT INTO promotions
           (bank, merchant_or_platform, min_spend, reward_type, reward_detail,
            start_date, end_date, special_timing_condition, key_conditions,
            source_url, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            promo["bank"],
            promo["merchant_or_platform"],
            promo.get("min_spend", 0),
            promo.get("reward_type", ""),
            promo.get("reward_detail", ""),
            promo.get("start_date", ""),
            promo.get("end_date", ""),
            promo.get("special_timing_condition", ""),
            promo.get("key_conditions", ""),
            promo.get("source_url", ""),
            promo.get("updated_at", ""),
        ),
    )
    return True


def find_candidates(
    conn: sqlite3.Connection,
    platform: str | None,
    amount: float,
    banks: set[str],
) -> list[dict]:
    """หาตัวเลือกที่ผ่านเงื่อนไขที่วัดได้ทั้งหมด:
    แพลตฟอร์มตรง + ยอดถึงขั้นต่ำ + ยังไม่หมดอายุ + เป็นธนาคารของบัตรที่ถืออยู่
    """
    today = date.today().isoformat()
    like = f"%{platform.lower()}%" if platform else "%"
    placeholders = ",".join("?" * len(banks))
    rows = conn.execute(
        f"""SELECT * FROM promotions
            WHERE lower(merchant_or_platform) LIKE ?
              AND min_spend <= ?
              AND (end_date = '' OR end_date IS NULL OR end_date >= ?)
              AND bank IN ({placeholders})
            ORDER BY min_spend DESC""",
        (like, amount, today, *sorted(banks)),
    ).fetchall()
    return [dict(r) for r in rows]


def count_all(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM promotions").fetchone()[0]


def load_all(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM promotions ORDER BY bank, merchant_or_platform"
    ).fetchall()
    return [dict(r) for r in rows]
