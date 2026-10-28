import os
import sqlite3
import pandas as pd
import streamlit as st
from google import genai

# -------------------------------------------------------------
# 1. ตั้งค่าหน้าเว็บและตัวแปรพื้นฐาน
# -------------------------------------------------------------
st.set_page_config(
    page_title="Credit Card Promo Finder",
    page_icon="💳",
    layout="wide"
)

API_KEY = os.getenv("GEMINI_API_KEY", "")

# หากคุณมีไฟล์ advisor.py สามารถใช้ from advisor import MY_CARDS แทนการเขียนตรงนี้ได้
MY_CARDS = [
    "KTC Platinum Visa",
    "CardX Beyond Mastercard",
    "ttb so smart",
    "Krungsri Now"
]

# -------------------------------------------------------------
# 2. ฟังก์ชันโหลดข้อมูลจาก SQLite (พร้อมระบบ Cache)
# -------------------------------------------------------------
@st.cache_data(ttl=3600)  # รีเฟรชแคชทุกๆ 1 ชั่วโมง
def load_data():
    if not os.path.exists("promotions.db"):
        return pd.DataFrame()
        
    # เชื่อมต่อฐานข้อมูล SQLite
    conn = sqlite3.connect("promotions.db")
    try:
        # ดึงข้อมูลทั้งหมดจากตาราง (สมมติว่าตารางชื่อ promotions หากชื่ออื่นให้แก้ตรงนี้)
        df = pd.read_sql_query("SELECT * FROM promotions", conn)
        return df
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอ่านฐานข้อมูล: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

df = load_data()

# -------------------------------------------------------------
# 3. ส่วนแสดงผลหลักและ Sidebar
# -------------------------------------------------------------
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
    
    # ดึงรายชื่อธนาคารจากคอลัมน์ bank ใน Database
    banks = ["ทั้งหมด"] + sorted(list(df["bank"].dropna().unique()))
    selected_bank = st.selectbox("เลือกธนาคาร/ผู้ออกบัตร", banks)
    
    search_keyword = st.text_input("ค้นหาร้านค้า / แพลตฟอร์ม", placeholder="เช่น Shopee, Lazada, Agoda")

# กรองข้อมูลตามเงื่อนไขที่เลือก
filtered_df = df.copy()
if selected_bank != "ทั้งหมด":
    filtered_df = filtered_df[filtered_df["bank"] == selected_bank]
if search_keyword:
    filtered_df = filtered_df[
        filtered_df["merchant_or_platform"].str.contains(search_keyword, case=False, na=False) |
        filtered_df["reward_detail"].str.contains(search_keyword, case=False, na=False) |
        filtered_df["category"].str.contains(search_keyword, case=False, na=False) # รองรับการค้นหาตามหมวดหมู่ที่เพิ่งเพิ่มเข้าไป
    ]

# -------------------------------------------------------------
# 4. แท็บการใช้งาน
# -------------------------------------------------------------
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
        elif not API_KEY:
            st.error("ไม่พบ GEMINI_API_KEY ในระบบ")
        else:
            with st.spinner("กำลังวิเคราะห์เงื่อนไขและเปรียบเทียบส่วนลด..."):
                client = genai.Client(api_key=API_KEY)
                prompt = f"""
                คุณเป็นที่ปรึกษาด้านความคุ้มค่าของบัตรเครดิต
                
                บัตรที่ผู้ใช้ถืออยู่จริง: {MY_CARDS}
                ฐานข้อมูลโปรโมชั่น: {filtered_df.to_dict(orient='records')}

                คำถามของผู้ใช้: "{user_query}"

                โปรดตอบตามลำดับ:
                1. บัตรอันดับ 1 ที่คุ้มที่สุด (คำนวณยอดเงินที่ประหยัดหรือเงินคืนเป็นบาทให้เห็นชัดเจน)
                2. บัตรอันดับ 2 (ถ้ามี)
                3. เปรียบเทียบช่วงเวลา: ถ้าซื้อวันนี้ กับ รอซื้อวันแคมเปญพิเศษ (Payday สิ้นเดือน หรือวันพิเศษ) แบบไหนคุ้มกว่ากันเท่าไหร่
                4. ข้อควรระวัง / เงื่อนไขที่ห้ามพลาด (เช่น รหัส SMS, สิทธิ์จำกัด)
                """
                
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt
                    )
                    st.markdown("### 🎯 ผลการวิเคราะห์")
                    st.info(response.text)
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาดจาก AI: {e}")

with tab2:
    st.subheader(f"รายการโปรโมชั่นที่พบ ({len(filtered_df)} รายการ)")
    
    # อัปเดตคอลัมน์ที่จะแสดงให้มี category ด้วย
    display_cols = ["bank", "category", "merchant_or_platform", "min_spend", "reward_type", "reward_detail", "end_date", "special_timing_condition"]
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
                st.write(f"**หมวดหมู่:** {row.get('category', '-')}")
                st.write(f"**ประเภทสิทธิ์:** {row.get('reward_type', '-')}")
                st.write(f"**ยอดขั้นต่ำ:** {row.get('min_spend', 0):,} บาท")
            with col2:
                st.write(f"**ช่วงเวลาพิเศษ:** {row.get('special_timing_condition', 'ใช้ได้ทุกวัน')}")
                st.write(f"**วันสิ้นสุด:** {row.get('end_date', 'ไม่ระบุ')}")
                st.write(f"**เงื่อนไขสำคัญ:** {row.get('key_conditions', '-')}")