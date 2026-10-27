"""Dashboard ดูรายการโปรโมชั่น + ถาม AI (เวอร์ชัน SQLite)

ถาม AI ผ่าน advisor.advise() ซึ่งกรองตัวเลือกด้วยเงื่อนไขก่อน
แล้วค่อยให้ Gemini จัดอันดับ — ไม่ยัดฐานข้อมูลทั้งก้อนใส่ prompt

รัน: streamlit run app.py
ต้องตั้งค่า environment variable: GEMINI_API_KEY
"""

import pandas as pd
import sqlite3
import streamlit as st

from advisor import MY_CARDS, advise
from db import DB_PATH

st.set_page_config(
    page_title="Credit Card Promo Finder",
    page_icon="💳",
    layout="wide"
)


@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query("SELECT * FROM promotions ORDER BY bank, merchant_or_platform", conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


df = load_data()

st.title("💳 ระบบค้นหา & วิเคราะห์โปรโมชั่นบัตรเครดิต")
st.caption("อัปเดตข้อมูลอัตโนมัติจากเว็บไซต์ธนาคาร พร้อมระบบแนะนำความคุ้มค่าเฉพาะบัตรในกระเป๋า")

if df.empty:
    st.warning("⚠️ ไม่พบข้อมูลโปรโมชั่นใน promotions.db กรุณารันสคริปต์กวาดข้อมูลก่อน")
    st.stop()

with st.sidebar:
    st.header("🗂️ บัตรที่คุณถืออยู่")
    for card in MY_CARDS:
        st.write(f"- {card}")

    st.divider()
    st.header("🔍 ตัวกรองโปรโมชั่น")

    banks = ["ทั้งหมด"] + sorted(list(df["bank"].dropna().unique()))
    selected_bank = st.selectbox("เลือกธนาคาร/ผู้ออกบัตร", banks)

    search_keyword = st.text_input("ค้นหาร้านค้า / แพลตฟอร์ม", placeholder="เช่น Shopee, Lazada, Agoda")

filtered_df = df.copy()
if selected_bank != "ทั้งหมด":
    filtered_df = filtered_df[filtered_df["bank"] == selected_bank]
if search_keyword:
    filtered_df = filtered_df[
        filtered_df["merchant_or_platform"].str.contains(search_keyword, case=False, na=False) |
        filtered_df["reward_detail"].str.contains(search_keyword, case=False, na=False)
    ]

tab1, tab2 = st.tabs(["🤖 ปรึกษา AI ก่อนช้อป", "📋 รายการโปรโมชั่นทั้งหมด"])

with tab1:
    st.subheader("ถาม AI: ซื้อราคานี้ ที่นี่ ใช้บัตรไหนคุ้มสุด?")
    user_query = st.text_input(
        "ระบุสิ่งที่จะซื้อ ยอดเงิน และแพลตฟอร์ม:",
        placeholder="เช่น จะซื้อของใน Shopee ยอด 2,800 บาท ใช้บัตรไหนคุ้มสุด หรือควรรอวันไหน"
    )

    if st.button("คำนวณความคุ้มค่า", type="primary"):
        if not user_query.strip():
            st.error("กรุณาระบุสิ่งที่ต้องการซื้อก่อนกดคำนวณ")
        else:
            with st.spinner("กำลังวิเคราะห์เงื่อนไขและเปรียบเทียบส่วนลด..."):
                try:
                    answer = advise(user_query)
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาด: {e}")
                else:
                    st.markdown("### 🎯 ผลการวิเคราะห์")
                    st.info(answer)

with tab2:
    st.subheader(f"รายการโปรโมชั่นที่พบ ({len(filtered_df)} รายการ)")

    display_cols = ["bank", "merchant_or_platform", "min_spend", "reward_type", "reward_detail", "end_date", "special_timing_condition"]
    available_cols = [c for c in display_cols if c in filtered_df.columns]

    st.dataframe(
        filtered_df[available_cols],
        use_container_width=True,
        hide_index=True
    )

    st.divider()
    st.subheader("รายละเอียดเงื่อนไขแบบเจาะลึก")
    for _, row in filtered_df.iterrows():
        with st.expander(f"📌 [{row.get('bank', '')}] {row.get('merchant_or_platform', '')} - {row.get('reward_detail', '')}"):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**ประเภทสิทธิ์:** {row.get('reward_type', '-')}")
                st.write(f"**ยอดขั้นต่ำ:** {row.get('min_spend', 0):,} บาท")
                st.write(f"**ช่วงเวลาพิเศษ:** {row.get('special_timing_condition', 'ใช้ได้ทุกวัน')}")
            with col2:
                st.write(f"**วันสิ้นสุด:** {row.get('end_date', 'ไม่ระบุ')}")
                st.write(f"**เงื่อนไขสำคัญ:** {row.get('key_conditions', '-')}")
