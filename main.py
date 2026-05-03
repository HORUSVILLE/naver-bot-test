from pathlib import Path
from urllib.parse import quote
import re
import traceback
from openpyxl import Workbook
from playwright.sync_api import sync_playwright

QUERIES = [
    "용인 맛집",
]

OUTPUT_DIR = Path("output")
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
OUTPUT_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)


def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")


def save_text(filename: str, content: str):
    (OUTPUT_DIR / filename).write_text(content, encoding="utf-8")


def save_shot(page, filename: str):
    try:
        page.screenshot(path=str(SCREENSHOT_DIR / filename), full_page=True)
    except Exception:
        pass


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def is_noise_row(name: str, raw_text: str) -> bool:
    combined = f"{name} {raw_text}".strip()

    noise_patterns = [
        "새로 오픈했어요",
        "결과보기",
        "플레이스 필터",
        "영업중",
        "포장주문",
        "실시간예약",
        "쿠폰",
        "주차",
        "단체석",
        "특별한메뉴",
        "고깃집",
        "삼겹살",
        "영업 종료",
    ]

    if len(name.strip()) <= 1:
        return True

    if re.fullmatch(r"\d+", name.strip()):
        return True

    for p in noise_patterns:
        if combined == p or combined.startswith(p):
            return True

    return False


def click_if_exists(container, selectors, timeout=5000):
    for sel in selectors:
        loc = container.locator(sel).first
        try:
            loc.wait_for(timeout=timeout)
            try:
                loc.click(timeout=timeout)
            except Exception:
                loc.click(force=True, timeout=timeout)
            return True
        except Exception:
            continue
    return False


def open_map_search(page, query: str):
    url = f"https://map.naver.com/p/search/{quote(query)}?searchType=place"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    save_shot(page, f"{safe_name(query)}_01_map_loaded.png")


def click_new_open_on_map(page) -> bool:
    clicked = click_if_exists(page, [
        "text=새로오픈",
        "button:has-text('새로오픈')",
        "a:has-text('새로오픈')",
        "span:has-text('새로오픈')",
    ], timeout=7000)

    page.wait_for_timeout(3000)
    save_shot(page, "02_after_new_open_click.png")
    return clicked


def get_list_context(page):
    # 현재는 page 본문에서 수집
    candidates = [
        "#_pcmap_list_scroll_container",
        "#_pcmap_list_scroll_container ul",
        "#_pcmap_list_scroll_container li",
    ]

    for sel in candidates:
        try:
            if page.locator(sel).count() > 0:
                return page
        except Exception:
            continue

    raise RuntimeError("목록 컨테이너(#_pcmap_list_scroll_container)를 찾지 못함")


def scroll_list_to_end(ctx, page):
    last_height = -1
    same_count = 0

    for _ in range(80):
        try:
            ctx.evaluate("""
            () => {
                const el = document.querySelector('#_pcmap_list_scroll_container');
                if (el) el.scrollTop = el.scrollHeight;
            }
            """)
        except Exception:
            break

        page.wait_for_timeout(1300)

        try:
            current_height = ctx.evaluate("""
            () => {
                const el = document.querySelector('#_pcmap_list_scroll_container');
                return el ? el.scrollHeight : 0;
            }
            """)
        except Exception:
            break

        if current_height == last_height:
            same_count += 1
        else:
            same_count = 0
            last_height = current_height

        if same_count >= 3:
            break


def scroll_list_to_top(ctx):
    try:
        ctx.evaluate("""
        () => {
            const el = document.querySelector('#_pcmap_list_scroll_container');
            if (el) el.scrollTop = 0;
        }
        """)
    except Exception:
        pass


def extract_cards(ctx, query, page_no):
    rows = []

    selectors = [
        "#_pcmap_list_scroll_container ul > li",
        "#_pcmap_list_scroll_container li",
    ]

    cards = None
    count = 0

    for sel in selectors:
        try:
            candidate = ctx.locator(sel)
            c = candidate.count()
            if c > 0:
                cards = candidate
                count = c
                break
        except Exception:
            continue

    if not cards or count == 0:
        return rows

    for i in range(count):
        card = cards.nth(i)
        try:
            raw = card.inner_text(timeout=2000)
        except Exception:
            continue

        raw = normalize_text(raw)
        if not raw:
            continue

        try:
            raw_lines = card.inner_text(timeout=2000).splitlines()
            lines = [normalize_text(x) for x in raw_lines if normalize_text(x)]
        except Exception:
            lines = []

        if not lines:
            continue

        name = normalize_text(lines[0])

        if is_noise_row(name, raw):
            continue

        href = ""
        try:
            href = card.locator("a").first.get_attribute("href") or ""
        except Exception:
            pass

        rows.append({
            "query": query,
            "page": page_no,
            "rank": i + 1,
            "name": name,
            "raw_text": raw,
            "href": href,
        })

    return rows


def get_visible_page_numbers(ctx):
    try:
        nums = ctx.evaluate("""
        () => {
            const result = [];
            const snapshot = document.evaluate(
                "//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and normalize-space(text())!='']",
                document,
                null,
                XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                null
            );

            for (let i = 0; i < snapshot.snapshotLength && i < 50; i++) {
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
    except Exception:
        return [1]


def click_page_number(ctx, page, number: int):
    locator = ctx.locator(
        f"xpath=//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and normalize-space(text())='{number}'][1]"
    )

    try:
        locator.click(timeout=5000)
        page.wait_for_timeout(3000)
        return True
    except Exception:
        try:
            locator.click(force=True, timeout=5000)
            page.wait_for_timeout(3000)
            return True
        except Exception:
            return False


def click_next_page_block(ctx, page):
    candidates = [
        "xpath=//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and normalize-space(text())='>'][1]",
        "xpath=//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and contains(normalize-space(text()), '다음')][1]",
        "xpath=//*[@id='_pcmap_list_scroll_container']/following::*[(self::a or self::button) and contains(@aria-label, '다음')][1]",
    ]

    for selector in candidates:
        loc = ctx.locator(selector)
        try:
            loc.click(timeout=3000)
            page.wait_for_timeout(3000)
            return True
        except Exception:
            continue
    return False


def save_excel(rows, summary_rows):
    wb = Workbook()

    ws = wb.active
    ws.title = "Results"
    ws.append(["query", "page", "rank", "name", "raw_text", "href"])

    for row in rows:
        ws.append([
            row["query"],
            row["page"],
            row["rank"],
            row["name"],
            row["raw_text"],
            row["href"],
        ])

    ws2 = wb.create_sheet("Summary")
    ws2.append(["item", "value"])
    for item, value in summary_rows:
        ws2.append([item, value])

    wb.save(OUTPUT_DIR / "results.xlsx")


def run_one_query(page, query):
    all_rows = []
    seen = set()

    print(f"[START] {query}")

    open_map_search(page, query)

    clicked = click_new_open_on_map(page)
    print(f"[새로오픈 클릭] {clicked}")

    ctx = get_list_context(page)

    block_index = 0
    max_blocks = 5

    while block_index < max_blocks:
        visible_pages = get_visible_page_numbers(ctx)
        if not visible_pages:
            visible_pages = [1]

        print(f"[보이는 페이지들] {visible_pages}")

        for idx, page_no in enumerate(visible_pages):
            if not (block_index == 0 and idx == 0):
                ok = click_page_number(ctx, page, page_no)
                print(f"[페이지 클릭 {page_no}] {ok}")
                if not ok:
                    continue

            scroll_list_to_end(ctx, page)

            rows = extract_cards(ctx, query, page_no)
            for row in rows:
                key = (row["query"], row["name"], row["raw_text"])
                if key in seen:
                    continue
                seen.add(key)
                all_rows.append(row)

            scroll_list_to_top(ctx)
            save_shot(page, f"{safe_name(query)}_page_{page_no}.png")

        moved = click_next_page_block(ctx, page)
        print(f"[다음 페이지 블록 이동] {moved}")
        if not moved:
            break

        block_index += 1

    return all_rows, clicked


def main():
    collected = []
    summary_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1600, "height": 1200},
            locale="ko-KR"
        )

        try:
            for query in QUERIES:
                rows, clicked = run_one_query(page, query)
                collected.extend(rows)
                summary_rows.append((f"{query}_new_open_clicked", str(clicked)))
                summary_rows.append((f"{query}_count", len(rows)))

        except Exception as e:
            save_shot(page, "ERROR_last_screen.png")
            save_text("error.txt", traceback.format_exc())
            print(traceback.format_exc())
            raise e

        finally:
            browser.close()

    summary_rows.append(("total_count", len(collected)))
    save_excel(collected, summary_rows)
    save_text("summary.txt", f"총 수집 건수: {len(collected)}")
    print(f"[DONE] 총 수집 건수: {len(collected)}")


if __name__ == "__main__":
    main()
