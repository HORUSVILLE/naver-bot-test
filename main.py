from pathlib import Path
import re
import time
import traceback
from openpyxl import Workbook
from playwright.sync_api import sync_playwright

QUERIES = [
    "용인 맛집",
    "용인 카페",
    "용인 디저트",
    "용인 미용실",
    "용인 네일샵",
    "용인 펜션",
]

OUTPUT_DIR = Path("output")
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
OUTPUT_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)


NOISE_NAMES = {
    "결과보기",
    "플레이스 필터",
    "새로오픈",
    "초기화",
    "검색",
    "저장",
    "공유",
    "리뷰많은",
    "요즘뜨는",
    "영업중",
    "영업 종료",
    "포장주문",
    "실시간예약",
    "쿠폰",
    "주차",
    "단체석",
    "특별한메뉴",
    "고깃집",
    "삼겹살",
    "사진맛집",
    "부맛집",
    "넓은",
    "신선한",
    "다양한술",
    "분위기좋은",
    "조용한",
    "편한좌석",
    "대화",
    "혼밥",
    "혼술",
    "이국적인",
    "플레이스",
    "지도",
}


def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text or "").strip("_")


def save_text(filename: str, content: str):
    (OUTPUT_DIR / filename).write_text(content, encoding="utf-8")


def save_shot(page_or_frame, filename: str):
    try:
        page_or_frame.screenshot(path=str(SCREENSHOT_DIR / filename), full_page=True)
    except Exception:
        pass


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def split_text_lines(text: str):
    return [normalize_text(x) for x in re.split(r"[\r\n]+", text or "") if normalize_text(x)]


def extract_business_name(lines):
    for line in lines:
        candidate = normalize_text(line)
        if not candidate:
            continue
        if candidate in NOISE_NAMES:
            continue
        if candidate.startswith("place"):
            continue
        return candidate
    return lines[0] if lines else ""


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


def goto_naver_and_search(page, query: str):
    page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    save_shot(page, f"{safe_name(query)}_01_naver_home.png")

    search_input = None
    for sel in [
        "input#query",
        "input[name='query']",
        "input[placeholder*='검색어']",
    ]:
        loc = page.locator(sel).first
        try:
            loc.wait_for(timeout=5000)
            search_input = loc
            break
        except Exception:
            continue

    if not search_input:
        raise RuntimeError("네이버 검색창을 찾지 못함")

    search_input.click()
    search_input.fill(query)
    page.wait_for_timeout(500)
    search_input.press("Enter")

    page.wait_for_timeout(5000)
    save_shot(page, f"{safe_name(query)}_02_search_result.png")


def open_filter_on_search_result(page):
    page.wait_for_timeout(3000)

    if "search.naver.com" not in page.url:
        return False

    try:
        clicked = page.evaluate("""
        () => {
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
            page.wait_for_timeout(1500)
            save_shot(page, f"{safe_name(page.title())}_03_filter_open_try1.png")
            return True
    except Exception:
        pass

    try:
        clicked = page.evaluate("""
        () => {
            const sections = Array.from(document.querySelectorAll("section, div, article"));
            const root = sections.find(el => (el.innerText || "").includes("플레이스"));
            if (!root) return false;
            const btn = root.querySelector("button");
            if (!btn) return false;
            btn.click();
            return true;
        }
        """)
        if clicked:
            page.wait_for_timeout(1500)
            save_shot(page, f"{safe_name(page.title())}_03_filter_open_try2.png")
            return True
    except Exception:
        pass

    return False


def scroll_filter_modal_until_new_open(page, query, max_scroll=14):
    for i in range(max_scroll):
        try:
            if page.locator("text=새로오픈").count() > 0:
                return True
        except Exception:
            pass

        try:
            page.evaluate("""
            () => {
                const candidates = Array.from(document.querySelectorAll("div"));
                const modal = candidates.find(el => {
                    const txt = (el.innerText || "");
                    return txt.includes("플레이스 필터") && txt.includes("결과보기");
                });

                if (!modal) return;

                const scrollables = Array.from(modal.querySelectorAll("*")).filter(el => {
                    const style = window.getComputedStyle(el);
                    return (style.overflowY === 'auto' || style.overflowY === 'scroll') && el.scrollHeight > el.clientHeight;
                });

                if (scrollables.length > 0) {
                    scrollables[0].scrollTop += 420;
                } else {
                    modal.scrollTop += 420;
                }
            }
            """)
        except Exception:
            pass

        page.wait_for_timeout(700)
        save_shot(page, f"{safe_name(query)}_04_filter_scroll_{i+1}.png")

    try:
        return page.locator("text=새로오픈").count() > 0
    except Exception:
        return False


def apply_new_open_filter_on_search_result(page, query):
    page.wait_for_timeout(1000)

    visible = scroll_filter_modal_until_new_open(page, query, max_scroll=14)
    if not visible:
        return None

    clicked_new = click_if_exists(page, [
        "text=새로오픈",
        "button:has-text('새로오픈')",
        "a:has-text('새로오픈')",
        "span:has-text('새로오픈')",
    ], timeout=5000)

    if not clicked_new:
        return None

    page.wait_for_timeout(1200)
    save_shot(page, f"{safe_name(query)}_05_new_open_selected.png")

    try:
        with page.context.expect_page(timeout=12000) as new_page_info:
            clicked_result = click_if_exists(page, [
                "button:has-text('결과보기')",
                "text=결과보기",
            ], timeout=7000)

        if not clicked_result:
            return None

        new_page = new_page_info.value
        new_page.wait_for_load_state("domcontentloaded")
        new_page.wait_for_timeout(5000)
        save_shot(new_page, f"{safe_name(query)}_06_after_result_button_new_tab.png")
        return new_page

    except Exception:
        clicked_result = click_if_exists(page, [
            "button:has-text('결과보기')",
            "text=결과보기",
        ], timeout=7000)

        if not clicked_result:
            return None

        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(5000)
        save_shot(page, f"{safe_name(query)}_06_after_result_button_same_tab.png")
        return page


def get_search_frame(result_page, query):
    deadline = time.time() + 30
    last_error = None

    while time.time() < deadline:
        try:
            iframe_loc = result_page.locator("iframe#searchIframe").first
            if iframe_loc.count() > 0:
                try:
                    iframe_loc.wait_for(state="attached", timeout=1500)
                except Exception:
                    pass

                handle = iframe_loc.element_handle()
                if handle:
                    frame = handle.content_frame()
                    if frame:
                        try:
                            save_text(f"search_iframe_url_{safe_name(query)}.txt", frame.url)
                        except Exception:
                            pass
                        return frame
        except Exception as e:
            last_error = e

        try:
            for fr in result_page.frames:
                fr_url = fr.url or ""
                if "place/list" in fr_url:
                    try:
                        save_text(f"search_iframe_url_{safe_name(query)}.txt", fr_url)
                    except Exception:
                        pass
                    return fr
        except Exception as e:
            last_error = e

        result_page.wait_for_timeout(1000)

    try:
        save_text(f"search_page_debug_{safe_name(query)}.html", result_page.content())
    except Exception:
        pass

    if last_error:
        raise RuntimeError(f"searchIframe content_frame 못 찾음: {last_error}")
    raise RuntimeError("searchIframe content_frame 못 찾음")


def detect_list_context(frame):
    scroller_selectors = [
        "#_pcmap_list_scroll_container",
        "div[id*='pcmap_list_scroll_container']",
        "div.Ryr1F",
        "div[style*='overflow-y']",
        "body",
    ]

    item_selectors = [
        "li:has(a)",
        "ul > li",
        "li",
        "div.place_section",
    ]

    pager_selectors = [
        "div.zRM9F",
        "div[class*='zRM9F']",
        "div:has-text('1'):has-text('2')",
    ]

    found_scroller = None
    for sel in scroller_selectors:
        try:
            loc = frame.locator(sel).first
            if loc.count() > 0:
                found_scroller = sel
                break
        except Exception:
            continue

    if not found_scroller:
        try:
            save_text("search_iframe_debug.html", frame.content())
        except Exception:
            pass
        raise RuntimeError("iframe 내부 스크롤 영역을 찾지 못함")

    found_items = None
    best_count = 0

    for sel in item_selectors:
        try:
            count = frame.locator(sel).count()
            if count > best_count:
                best_count = count
                found_items = sel
        except Exception:
            continue

    if not found_items:
        try:
            save_text("search_iframe_debug.html", frame.content())
        except Exception:
            pass
        raise RuntimeError("iframe 내부 카드 선택자를 찾지 못함")

    found_pager = None
    for sel in pager_selectors:
        try:
            if frame.locator(sel).count() > 0:
                found_pager = sel
                break
        except Exception:
            continue

    return {
        "frame": frame,
        "scroller": found_scroller,
        "items": found_items,
        "pager": found_pager,
    }


def scroll_list_to_end(ctx):
    frame = ctx["frame"]
    scroller_selector = ctx["scroller"]

    last_height = -1
    same_count = 0

    for _ in range(80):
        try:
            frame.eval_on_selector(
                scroller_selector,
                "(el) => { el.scrollTop = el.scrollHeight; }"
            )
        except Exception:
            break

        frame.page.wait_for_timeout(1200)

        try:
            current_height = frame.eval_on_selector(
                scroller_selector,
                "(el) => el.scrollHeight"
            )
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
    frame = ctx["frame"]
    scroller_selector = ctx["scroller"]

    try:
        frame.eval_on_selector(
            scroller_selector,
            "(el) => { el.scrollTop = 0; }"
        )
    except Exception:
        pass


def is_probable_place_card(name: str, raw: str) -> bool:
    if not name or len(name) <= 1:
        return False

    if name in NOISE_NAMES:
        return False

    keywords = ["리뷰", "새로오픈", "영업", "예약", "포장", "메뉴", "쿠폰"]
    if any(k in raw for k in keywords):
        return True

    return len(raw) >= 15


def extract_cards(ctx, query, page_no):
    frame = ctx["frame"]
    item_selector = ctx["items"]

    rows = []
    cards = frame.locator(item_selector)
    count = cards.count()

    for i in range(count):
        card = cards.nth(i)

        try:
            raw_multiline = card.inner_text(timeout=1500)
        except Exception:
            continue

        lines = split_text_lines(raw_multiline)
        if not lines:
            continue

        name = extract_business_name(lines)
        raw = " ".join(lines)

        if not is_probable_place_card(name, raw):
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
    frame = ctx["frame"]

    try:
        nums = frame.evaluate("""
        () => {
            const els = Array.from(document.querySelectorAll("a, button, span"));
            const result = [];
            for (const el of els) {
                const txt = (el.textContent || "").trim();
                if (/^\\d+$/.test(txt)) {
                    const n = Number(txt);
                    if (n >= 1 && n <= 50) result.push(n);
                }
            }
            return [...new Set(result)].slice(0, 10);
        }
        """)
        return nums if nums else [1]
    except Exception:
        return [1]


def click_page_number(ctx, page_no):
    frame = ctx["frame"]

    selectors = [
        f"button:has-text('{page_no}')",
        f"a:has-text('{page_no}')",
        f"text={page_no}",
    ]

    for sel in selectors:
        try:
            loc = frame.locator(sel).first
            loc.click(timeout=4000)
            frame.page.wait_for_timeout(2500)
            return True
        except Exception:
            continue

    return False


def click_next_page_block(ctx):
    frame = ctx["frame"]

    selectors = [
        "div.zRM9F button:last-child",
        "div.zRM9F a:last-child",
        "button[aria-label*='다음']",
        "a[aria-label*='다음']",
        "text=>",
    ]

    for sel in selectors:
        try:
            loc = frame.locator(sel).first
            loc.click(timeout=4000)
            frame.page.wait_for_timeout(2500)
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

    goto_naver_and_search(page, query)

    opened = open_filter_on_search_result(page)
    print(f"[필터 열기] {opened}")
    if not opened:
        raise RuntimeError("플레이스 필터를 열지 못함")

    result_page = apply_new_open_filter_on_search_result(page, query)
    applied = result_page is not None
    print(f"[새로오픈 적용] {applied}")
    if not result_page:
        raise RuntimeError("새로오픈 클릭 또는 결과보기 클릭 실패")

    result_page.wait_for_timeout(4000)
    save_shot(result_page, f"{safe_name(query)}_07_map_loaded_after_result.png")

    frame = get_search_frame(result_page, query)
    ctx = detect_list_context(frame)

    try:
        save_text(
            f"detected_selectors_{safe_name(query)}.txt",
            f"scroller={ctx['scroller']}\nitems={ctx['items']}\npager={ctx['pager']}"
        )
    except Exception:
        pass

    block_index = 0
    max_blocks = 5

    while block_index < max_blocks:
        visible_pages = get_visible_page_numbers(ctx)
        if not visible_pages:
            visible_pages = [1]

        print(f"[보이는 페이지들] {visible_pages}")

        for idx, page_no in enumerate(visible_pages):
            if not (block_index == 0 and idx == 0):
                ok = click_page_number(ctx, page_no)
                print(f"[페이지 클릭 {page_no}] {ok}")
                if not ok:
                    continue

            scroll_list_to_end(ctx)
            rows = extract_cards(ctx, query, page_no)

            for row in rows:
                key = (row["query"], row["name"], row["raw_text"])
                if key in seen:
                    continue
                seen.add(key)
                all_rows.append(row)

            scroll_list_to_top(ctx)
            save_shot(result_page, f"{safe_name(query)}_page_{page_no}.png")

        moved = click_next_page_block(ctx)
        print(f"[다음 페이지 블록 이동] {moved}")
        if not moved:
            break

        block_index += 1

    return all_rows, True


def main():
    collected = []
    summary_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for query in QUERIES:
            page = browser.new_page(
                viewport={"width": 1600, "height": 1200},
                locale="ko-KR"
            )

            try:
                rows, applied = run_one_query(page, query)
                collected.extend(rows)

                summary_rows.append((f"{query}_status", "OK"))
                summary_rows.append((f"{query}_new_open_applied", str(applied)))
                summary_rows.append((f"{query}_count", len(rows)))

            except Exception as e:
                save_shot(page, f"ERROR_{safe_name(query)}_last_screen.png")
                save_text(f"error_{safe_name(query)}.txt", traceback.format_exc())
                summary_rows.append((f"{query}_status", "ERROR"))
                summary_rows.append((f"{query}_error", str(e)))
                print(traceback.format_exc())

            finally:
                page.close()

        browser.close()

    summary_rows.append(("total_count", len(collected)))
    save_excel(collected, summary_rows)
    save_text("summary.txt", f"총 수집 건수: {len(collected)}")
    print(f"[DONE] 총 수집 건수: {len(collected)}")


if __name__ == "__main__":
    main()
