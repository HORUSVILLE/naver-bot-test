from pathlib import Path
from urllib.parse import quote
import csv
import re
import traceback
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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
    path = OUTPUT_DIR / filename
    path.write_text(content, encoding="utf-8")


def save_shot(page, name: str):
    try:
        page.screenshot(path=str(SCREENSHOT_DIR / name), full_page=True)
    except Exception:
        pass


def first_working_locator(container, selectors, timeout=5000):
    for sel in selectors:
        loc = container.locator(sel).first
        try:
            loc.wait_for(timeout=timeout)
            return loc
        except Exception:
            continue
    return None


def click_if_exists(container, selectors, timeout=5000):
    loc = first_working_locator(container, selectors, timeout=timeout)
    if not loc:
        return False
    try:
        loc.click(timeout=timeout)
        return True
    except Exception:
        try:
            loc.click(force=True, timeout=timeout)
            return True
        except Exception:
            return False


def goto_naver_and_search(page, query: str):
    page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    save_shot(page, f"{safe_name(query)}_01_naver_home.png")

    search_input = first_working_locator(page, [
        "input#query",
        "input[name='query']",
        "input[placeholder*='검색어']",
    ], timeout=8000)

    if not search_input:
        raise RuntimeError("네이버 검색창을 찾지 못함")

    search_input.click()
    search_input.fill(query)
    page.wait_for_timeout(1000)
    search_input.press("Enter")

    page.wait_for_timeout(5000)
    save_shot(page, f"{safe_name(query)}_02_search_result.png")


def open_filter_on_search_result(page):
    # 검색결과 페이지에서 '플레이스' 영역의 필터 버튼 클릭
    page.wait_for_timeout(3000)

    # 플레이스 영역이 보이는지 먼저 확인
    if "search.naver.com" not in page.url:
        return False

    # 1차: 영업중 버튼 앞의 필터 버튼 추정 클릭
    clicked = page.evaluate("""
    () => {
        const bodyText = document.body.innerText || "";
        if (!bodyText.includes("플레이스")) return false;

        const all = Array.from(document.querySelectorAll("button, a"));
        const openState = all.find(el => (el.textContent || "").trim() === "영업중");
        if (openState) {
            const idx = all.indexOf(openState);
            if (idx > 0) {
                all[idx - 1].click();
                return true;
            }
        }
        return false;
    }
    """)
    if clicked:
        page.wait_for_timeout(2000)
        save_shot(page, "03_filter_open_try1.png")
        return True

    # 2차: 플레이스 텍스트 근처 첫 버튼 클릭 시도
    clicked = page.evaluate("""
    () => {
        const walker = Array.from(document.querySelectorAll("div, section, article"));
        const root = walker.find(el => (el.innerText || "").includes("플레이스"));
        if (!root) return false;

        const btn = root.querySelector("button");
        if (!btn) return false;
        btn.click();
        return true;
    }
    """)
    if clicked:
        page.wait_for_timeout(2000)
        save_shot(page, "03_filter_open_try2.png")
        return True

    return False


def apply_new_open_filter_on_search_result(page):
    # 검색결과 필터 모달에서 새로오픈 클릭 + 결과보기 클릭
    page.wait_for_timeout(1500)

    clicked_new = click_if_exists(page, [
        "text=새로오픈",
        "button:has-text('새로오픈')",
        "a:has-text('새로오픈')",
        "span:has-text('새로오픈')",
    ], timeout=5000)

    if not clicked_new:
        return False

    page.wait_for_timeout(1500)
    save_shot(page, "04_new_open_selected.png")

    clicked_result = click_if_exists(page, [
        "button:has-text('결과보기')",
        "text=결과보기",
    ], timeout=7000)

    if not clicked_result:
        return False

    page.wait_for_timeout(6000)
    save_shot(page, "05_after_result_button.png")
    return True


def goto_map_search_direct(page, query: str):
    url = f"https://map.naver.com/p/search/{quote(query)}?searchType=place"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    save_shot(page, f"{safe_name(query)}_06_map_direct.png")


def click_new_open_on_map(page):
    # map.naver.com 화면의 새로오픈 클릭
    clicked = click_if_exists(page, [
        "text=새로오픈",
        "button:has-text('새로오픈')",
        "a:has-text('새로오픈')",
        "span:has-text('새로오픈')",
    ], timeout=7000)

    page.wait_for_timeout(3000)
    save_shot(page, "07_after_map_new_open_click.png")
    return clicked


def get_list_context(page):
    # page 본문에 목록이 있으면 page 반환, iframe 안에 있으면 frame 반환
    try:
        if page.locator("#_pcmap_list_scroll_container").count() > 0:
            return page
    except Exception:
        pass

    for frame in page.frames:
        try:
            if frame.locator("#_pcmap_list_scroll_container").count() > 0:
                return frame
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
    cards = ctx.locator("#_pcmap_list_scroll_container ul > li")
    count = cards.count()

    for i in range(count):
        card = cards.nth(i)
        try:
            text = card.inner_text(timeout=2000).strip()
        except Exception:
            continue

        if not text:
            continue

        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if not lines:
            continue

        name = lines[0]
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
            "raw_text": " | ".join(lines),
            "href": href,
        })
    return rows


def get_visible_page_numbers(ctx):
    try:
        nums = ctx.evaluate("""
        () => {
            const result = [];
            const root = document.querySelector('#_pcmap_list_scroll_container');
            if (!root) return [1];

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


def save_csv(rows):
    path = OUTPUT_DIR / "results.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["query", "page", "rank", "name", "raw_text", "href"]
        )
        writer.writeheader()
        writer.writerows(rows)


def run_one_query(page, query):
    all_rows = []
    seen = set()

    print(f"[START] {query}")

    # 1) 네이버 메인 → 검색결과 → 필터 → 새로오픈 → 결과보기
    goto_naver_and_search(page, query)

    opened = open_filter_on_search_result(page)
    print(f"[필터 열기] {opened}")

    if opened:
        applied = apply_new_open_filter_on_search_result(page)
        print(f"[새로오픈 적용] {applied}")
    else:
        applied = False

    # 2) 실패하면 map 직접 진입 후 새로오픈 클릭
    if "map.naver.com" not in page.url:
        goto_map_search_direct(page, query)
        click_new_open_on_map(page)
    else:
        # 이미 map으로 넘어왔더라도 새로오픈이 안 먹었을 수 있으니 한 번 더 시도
        click_new_open_on_map(page)

    save_shot(page, f"{safe_name(query)}_08_before_collect.png")

    # 3) 목록 수집
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

    return all_rows


def main():
    collected = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1600, "height": 1200},
            locale="ko-KR"
        )

        try:
            for query in QUERIES:
                rows = run_one_query(page, query)
                collected.extend(rows)

        except Exception as e:
            save_shot(page, "ERROR_last_screen.png")
            save_text("error.txt", traceback.format_exc())
            print(traceback.format_exc())
            raise e

        finally:
            browser.close()

    save_csv(collected)
    save_text("summary.txt", f"총 수집 건수: {len(collected)}")
    print(f"[DONE] 총 수집 건수: {len(collected)}")


if __name__ == "__main__":
    main()
