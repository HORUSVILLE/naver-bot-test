from pathlib import Path
import csv
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright

# 먼저 1개 검색어만 테스트
QUERIES = [
    "용인 맛집",
]

OUTPUT_DIR = Path("output")
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
OUTPUT_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)


def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")


def get_search_frame(page):
    for _ in range(20):
        try:
            page.wait_for_selector("iframe#searchIframe", timeout=3000)
            handle = page.locator("iframe#searchIframe").element_handle()
            if handle:
                frame = handle.content_frame()
                if frame:
                    return frame
        except:
            pass
        page.wait_for_timeout(1000)

    raise RuntimeError("searchIframe 못 찾음")


def open_search_results(page, query: str):
    encoded = quote(query)
    url = f"https://map.naver.com/p/search/{encoded}"

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    page.screenshot(
        path=str(SCREENSHOT_DIR / f"{safe_name(query)}_00_loaded.png"),
        full_page=True
    )

    return get_search_frame(page)


def click_new_open(frame, page):
    candidates = [
        frame.get_by_text("새로오픈", exact=True).first,
        frame.locator("a,button,span").filter(has_text="새로오픈").first,
    ]

    for loc in candidates:
        try:
            loc.click(timeout=5000)
            page.wait_for_timeout(4000)
            return True
        except:
            pass

    return False


def scroll_list_to_end(frame, page):
    frame.wait_for_selector("#_pcmap_list_scroll_container", timeout=15000)

    last_height = -1
    same_count = 0

    while same_count < 3:
        frame.evaluate("""
            () => {
                const el = document.querySelector('#_pcmap_list_scroll_container');
                if (el) el.scrollTop = el.scrollHeight;
            }
        """)
        page.wait_for_timeout(1500)

        current_height = frame.evaluate("""
            () => {
                const el = document.querySelector('#_pcmap_list_scroll_container');
                return el ? el.scrollHeight : 0;
            }
        """)

        if current_height == last_height:
            same_count += 1
        else:
            same_count = 0
            last_height = current_height


def scroll_list_to_top(frame):
    frame.evaluate("""
        () => {
            const el = document.querySelector('#_pcmap_list_scroll_container');
            if (el) el.scrollTop = 0;
        }
    """)


def get_visible_page_numbers(frame):
    try:
        nums = frame.evaluate("""
            () => {
                const result = [];
                const snapshot = document.evaluate(
                    "//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and normalize-space(text())!='']",
                    document,
                    null,
                    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                    null
                );

                for (let i = 0; i < snapshot.snapshotLength && i < 40; i++) {
                    const el = snapshot.snapshotItem(i);
                    const txt = (el.textContent || "").trim();
                    if (/^\\d+$/.test(txt)) {
                        result.push(Number(txt));
                    }
                }

                return [...new Set(result)];
            }
        """)
        return nums if nums else [1]
    except:
        return [1]


def click_page_number(frame, page, number: int):
    locator = frame.locator(
        f"xpath=//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and normalize-space(text())='{number}'][1]"
    )

    try:
        locator.click(timeout=5000)
        page.wait_for_timeout(3000)
        return True
    except:
        return False


def click_next_page_block(frame, page):
    candidates = [
        "xpath=//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and normalize-space(text())='>'][1]",
        "xpath=//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and contains(normalize-space(text()), '다음')][1]",
    ]

    for selector in candidates:
        loc = frame.locator(selector)
        try:
            loc.click(timeout=3000)
            page.wait_for_timeout(3000)
            return True
        except:
            pass

    return False


def extract_cards(frame, query: str, page_no: int):
    rows = []

    try:
        cards = frame.locator("#_pcmap_list_scroll_container ul > li")
        count = cards.count()
    except:
        count = 0

    for i in range(count):
        card = cards.nth(i)
        try:
            text = card.inner_text(timeout=2000).strip()
        except:
            continue

        if not text:
            continue

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue

        name = lines[0]
        href = ""
        try:
            href = card.locator("a").first.get_attribute("href") or ""
        except:
            pass

        rows.append({
            "query": query,
            "page": page_no,
            "rank": i + 1,
            "name": name,
            "raw_text": " | ".join(lines),
            "href": href
        })

    return rows


def save_csv(all_rows):
    csv_path = OUTPUT_DIR / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["query", "page", "rank", "name", "raw_text", "href"]
        )
        writer.writeheader()
        writer.writerows(all_rows)


def main():
    all_rows = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1600, "height": 1200},
            locale="ko-KR"
        )

        for query in QUERIES:
            print(f"[START] {query}")

            frame = open_search_results(page, query)

            clicked = click_new_open(frame, page)
            print(f"[새로오픈 클릭 여부] {clicked}")

            page.screenshot(
                path=str(SCREENSHOT_DIR / f"{safe_name(query)}_01_after_new_open.png"),
                full_page=True
            )

            block_index = 0
            max_blocks = 5

            while block_index < max_blocks:
                visible_pages = get_visible_page_numbers(frame)
                if not visible_pages:
                    visible_pages = [1]

                print(f"[현재 보이는 페이지 번호들] {visible_pages}")

                for idx, page_no in enumerate(visible_pages):
                    if not (block_index == 0 and idx == 0):
                        clicked_page = click_page_number(frame, page, page_no)
                        print(f"[페이지 클릭] {page_no} -> {clicked_page}")
                        if not clicked_page:
                            continue

                    scroll_list_to_end(frame, page)

                    rows = extract_cards(frame, query, page_no)
                    for row in rows:
                        key = (row["query"], row["name"], row["raw_text"])
                        if key in seen:
                            continue
                        seen.add(key)
                        all_rows.append(row)

                    scroll_list_to_top(frame)
                    page.screenshot(
                        path=str(SCREENSHOT_DIR / f"{safe_name(query)}_page_{page_no}.png"),
                        full_page=True
                    )

                moved = click_next_page_block(frame, page)
                print(f"[다음 페이지 블록 이동] {moved}")
                if not moved:
                    break

                block_index += 1

        browser.close()

    save_csv(all_rows)
    print(f"[DONE] 총 수집 건수: {len(all_rows)}")


if __name__ == "__main__":
    main()
