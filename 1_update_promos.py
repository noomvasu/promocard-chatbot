async def scrape_bank_pages(browser, client, url: str) -> tuple[list[PromoItem], int]:
    """เปิดหน้าเว็บ ไล่อ่านและส่งให้ Gemini วิเคราะห์ทีละหน้า พร้อมกรองข้อมูลซ้ำ"""
    print(f"กำลังดึงข้อมูล: {url}")
    page = await browser.new_page()
    
    all_promos = []  # เก็บรายการโปรโมชั่นที่ไม่ซ้ำ
    seen_promo_keys = set()  # เก็บ Unique Key เพื่อเช็กซ้ำข้ามหน้า
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
                    page_text_limited = text[:15000] 
                    page_promos = await extract_promos_from_page(client, page_text_limited, url)
                    
                    # --- ระบบกรองข้อมูลซ้ำ ---
                    new_in_page = 0
                    for promo in page_promos:
                        # สร้างคีย์อ้างอิงจากฟิลด์สำคัญเพื่อระบุตัวตนโปรโมชั่น
                        unique_key = (
                            promo.bank.strip(),
                            promo.merchant_or_platform.strip(),
                            promo.reward_detail.strip(),
                            promo.end_date.strip()
                        )
                        
                        # ถ้ารายการนี้ยังไม่เคยเจอในหน้าก่อนๆ ถึงจะเก็บเข้า all_promos
                        if unique_key not in seen_promo_keys:
                            seen_promo_keys.add(unique_key)
                            all_promos.append(promo)
                            new_in_page += 1
                            
                    print(f"  > หน้าที่ {pages_read} พบโปรโมชั่น {len(page_promos)} รายการ (เป็นโปรฯ ไม่ซ้ำ {new_in_page} รายการ)")
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

    print(f"  สรุป: อ่านทั้งหมด {pages_read} หน้า พบโปรโมชั่นสุทธิ (ไม่ซ้ำ) {len(all_promos)} รายการ")
    return all_promos, pages_read