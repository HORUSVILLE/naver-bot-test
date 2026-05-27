"""
네이버 신규오픈 매장 자동 수집 봇
- 검색어별로 네이버 지도에서 새로오픈 필터를 적용 (DOM 클릭 방식)
- 모든 페이지 끝까지 순회하며 매장 정보 수집
- output/results.xlsx + output/summary.txt 저장
"""
from pathlib import Path
import re
import time
import urllib.parse
import traceback

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from playwright.sync_api import sync_playwright


# ============================================================
# 검색어 — 추가/변경은 여기만 수정
# ============================================================
QUERIES = [
    "용인 맛집",
    "용인 카페",
    "용인 디저트",
    "용인 미용실",
    "용인 네일샵",
    "용인 펜션",
]

# ============================================================
# 동작 설정
# ============================================================
MAX_PAGES_PER_QUERY = 10        # 쿼리당 최대 페이지 수
PAGE_WAIT_MS = 3500             # 페이지 로드 후 대기 (ms)
IFRAME_WAIT_MS = 5500           # iframe src 변경 후 대기 (ms)
FILTER_WAIT_MS = 4000           # 필터 클릭 후 대기 (ms)
SCROLL_MAX_STEPS = 80           # 스크롤 최대 시도 횟수
SCROLL_STABLE_LIMIT = 4         # 같은 높이 N번 연속 → 끝으로 판정

OUTPUT_DIR = Path("output")
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 공통 유틸
# ============================================================
def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text or "").strip("_")[:40]


def save_shot(page, filename: str):
    try:
        page.screenshot(path=str(SCREENSHOT_DIR / filename), full_page=True)
    except Exception:
        pass


def save_text(filename: str, content: str):
    try:
        (OUTPUT_DIR / filename).write_text(content, encoding="utf-8")
    except Exception:
        pass


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def split_lines(text: str):
    if not text:
        return []
    return [normalize(x) for x in re.split(r"[\r\n]+", text) if normalize(x)]


# ============================================================
# 검색 iframe 찾기
# ============================================================
def get_search_frame(page, timeout_sec=30):
    """검색결과 iframe(frame 객체) 반환."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for fr in page.frames:
            url = fr.url or ""
            if "pcmap.place.naver.com" in url and "/list" in url:
                return fr
        page.wait_for_timeout(500)
    raise RuntimeError("검색결과 iframe을 찾지 못함")


def get_current_list_url(page, timeout_sec=30):
    """페이지 안의 검색결과 iframe URL 반환."""
    fr = get_search_frame(page, timeout_sec)
    return fr.url


# ============================================================
# 핵심: '새로오픈' 필터를 DOM 클릭으로 적용
# ============================================================
def click_new_open_filter(page, frame, query):
    """
    iframe 내부의 '새로오픈' 필터 버튼을 직접 클릭.
    네이버가 URL 파라미터를 자주 바꾸므로, DOM 클릭이 가장 안정적.
    """
    candidates = [
        "a:has-text('새로오픈')",
        "button:has-text('새로오픈')",
        "span:has-text('새로오픈')",
        "[role='button']:has-text('새로오픈')",
    ]

    clicked = False
    for sel in candidates:
        try:
            loc = frame.locator(sel).first
            if loc.count() == 0:
                continue
            loc.wait_for(state="visible", timeout=5000)
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            clicked = True
            print(f"[{query}] '새로오픈' 클릭 성공 (selector={sel})")
            break
        except Exception as e:
            continue

    if not clicked:
        # 페이지 본문(iframe 바깥)에서 시도
        for sel in candidates:
            try:
                loc = page.locator(sel).first
                if loc.count() == 0:
                    continue
                loc.wait_for(state="visible", timeout=3000)
                loc.click(timeout=5000)
                clicked = True
                print(f"[{query}] '새로오픈' 클릭 성공 (page-level, selector={sel})")
                break
            except Exception:
                continue

    if not clicked:
        raise RuntimeError("'새로오픈' 필터 버튼을 찾지 못함 — 네이버 UI 변경 가능성")

    page.wait_for_timeout(FILTER_WAIT_MS)

    # 필터 적용 후 iframe이 갱신되므로 다시 가져옴
    new_frame = get_search_frame(page, timeout_sec=20)
    return new_frame


def set_page_param(url: str, page_num: int) -> str:
    url = re.sub(r"[?&]page=\d+", "", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}page={page_num}"


def navigate_iframe_to(page, target_url: str, expect_marker: str = "", timeout_sec=30):
    """iframe#searchIframe의 src를 target_url로 변경하고, 갱신된 frame 반환."""
    page.evaluate(
        "(u) => { const f = document.querySelector('iframe#searchIframe'); if (f) f.src = u; }",
        target_url,
    )
    page.wait_for_timeout(IFRAME_WAIT_MS)

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for fr in page.frames:
            u = fr.url or ""
            if "pcmap.place.naver.com" in u and "/list" in u:
                if expect_marker and expect_marker not in u:
                    continue
                return fr
        page.wait_for_timeout(500)
    raise RuntimeError(f"iframe 이동 실패 (marker={expect_marker})")


def open_search_with_new_open(page, query: str):
    """
    검색어 진입 → '새로오픈' 필터 클릭 적용 → 갱신된 frame, 베이스 URL 반환.
    """
    encoded = urllib.parse.quote(query)
    map_url = f"https://map.naver.com/p/search/{encoded}"

    page.goto(map_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    save_shot(page, f"{safe_name(query)}_01_map.png")

    # 검색결과 iframe이 뜰 때까지 대기
    frame = get_search_frame(page, timeout_sec=30)
    save_shot(page, f"{safe_name(query)}_02_before_filter.png")

    # '새로오픈' 필터 클릭으로 적용
    frame = click_new_open_filter(page, frame, query)
    save_shot(page, f"{safe_name(query)}_03_filtered.png")

    # 필터 적용 후의 iframe URL을 base_url로 사용
    base_url = frame.url
    save_text(f"target_url_{safe_name(query)}.txt", base_url)

    return frame, base_url


# ============================================================
# 카드 수집
# ============================================================
SCROLL_SELECTORS = [
    "#_pcmap_list_scroll_container",
    "div[id*='_list_scroll_container']",
    "div.Ryr1F",
]

CARD_SELECTORS = [
    "ul > li:has(a)",
    "li:has(a):has(span)",
    "li.UEzoS",
    "li.VLTHu",
]

# 라벨 텍스트(이름이 아님)
LABELS = {
    "새로오픈", "예약", "주문", "톡톡", "쿠폰", "포장", "광고",
    "영업 종료", "영업종료", "영업중", "영업 중", "place+", "Npay+", "Npay",
    "단체석", "주차", "리뷰많은", "요즘뜨는", "신선한", "분위기좋은",
}

# 카테고리 힌트
CATEGORY_HINTS = {
    "카페", "디저트", "음식점", "한식", "중식", "양식", "일식", "분식",
    "이자카야", "베이커리", "피자", "치킨", "고기", "국밥", "라면",
    "미용실", "네일", "마사지", "에스테틱", "헤어", "바버샵",
    "펜션", "숙박", "호텔", "모텔", "게스트하우스", "리조트", "풀빌라",
}


def find_first_existing(ctx, selectors):
    for sel in selectors:
        try:
            if ctx.locator(sel).count() > 0:
                return sel
        except Exception:
            continue
    return None


def is_address_line(line: str) -> bool:
    if re.search(r"(시|군|구|동|읍|면|로|길|가)\s*[\d가-힣]", line):
        return True
    if re.search(r"\d+[-\d]*번지", line):
        return True
    if re.match(r"^[가-힣\s]+(시|군)\s+[가-힣]+(구|동|읍|면)", line):
        return True
    return False


def is_review_line(line: str) -> bool:
    return "리뷰" in line and re.search(r"\d", line) is not None


def extract_card_info(card, query, page_num, rank):
    try:
        text = card.inner_text(timeout=2000)
    except Exception:
        return None

    lines = split_lines(text)
    if len(lines) < 2:
        return None
    if all(line in LABELS for line in lines):
        return None

    name = lines[0]
    if name in LABELS or len(name) < 2:
        return None

    category = ""
    address = ""
    review = ""
    extras = []

    for line in lines[1:]:
        if line in LABELS:
            continue
        if not address and is_address_line(line):
            address = line
            continue
        if not review and is_review_line(line):
            review = line
            continue
        if not category and any(h in line for h in CATEGORY_HINTS) and len(line) <= 25:
            category = line
            continue
        extras.append(line)

    href = ""
    try:
        href = card.locator("a").first.get_attribute("href") or ""
    except Exception:
        pass

    return {
        "query": query,
        "page": page_num,
        "rank": rank,
        "name": name,
        "category": category,
        "address": address,
        "review": review,
        "extras": " | ".join(extras[:5]),
        "href": href,
        "raw": " / ".join(lines),
    }


def collect_cards(frame, query, page_num):
    card_sel = find_first_existing(frame, CARD_SELECTORS)
    if not card_sel:
        save_text(
            f"no_cards_{safe_name(query)}_p{page_num}.html",
            (frame.content() if hasattr(frame, "content") else "")[:50000],
        )
        return []

    cards = frame.locator(card_sel)
    count = cards.count()

    rows = []
    rank = 0
    for i in range(count):
        info = extract_card_info(cards.nth(i), query, page_num, rank + 1)
        if info:
            rank += 1
            rows.append(info)
    return rows


def scroll_list_to_end(page, frame):
    scroller = find_first_existing(frame, SCROLL_SELECTORS) or "body"
    last_h = -1
    same = 0

    for _ in range(SCROLL_MAX_STEPS):
        try:
            frame.evaluate(
                "(sel) => { const el = sel === 'body' ? document.scrollingElement : document.querySelector(sel); if (el) el.scrollTop = el.scrollHeight; }",
                scroller,
            )
        except Exception:
            break

        page.wait_for_timeout(900)

        try:
            cur_h = frame.evaluate(
                "(sel) => { const el = sel === 'body' ? document.scrollingElement : document.querySelector(sel); return el ? el.scrollHeight : 0; }",
                scroller,
            )
        except Exception:
            break

        if cur_h == last_h:
            same += 1
        else:
            same = 0
            last_h = cur_h
        if same >= SCROLL_STABLE_LIMIT:
            break


def get_max_page_number(frame) -> int:
    try:
        return frame.evaluate(
            r"""() => {
                const els = Array.from(document.querySelectorAll("a, button, span"));
                let mx = 1;
                for (const el of els) {
                    const t = (el.textContent || "").trim();
                    if (/^\d+$/.test(t)) {
                        const n = Number(t);
                        if (n > mx && n <= 50) mx = n;
                    }
                }
                return mx;
            }"""
        )
    except Exception:
        return 1


# ============================================================
# 페이지 순회
# ============================================================
def collect_all_pages(page, frame, base_url, query):
    all_rows = []
    seen = set()

    # 1페이지
    scroll_list_to_end(page, frame)
    save_shot(page, f"{safe_name(query)}_p1_end.png")
    rows = collect_cards(frame, query, 1)
    for r in rows:
        key = (r["query"], r["name"], r["address"])
        if key in seen:
            continue
        seen.add(key)
        all_rows.append(r)

    max_page = get_max_page_number(frame)
    print(f"[{query}] p1 수집: {len(rows)}건, 추정 최대 페이지: {max_page}")

    if max_page <= 1:
        return all_rows

    target_max = min(max_page, MAX_PAGES_PER_QUERY)
    for p in range(2, target_max + 1):
        page_url = set_page_param(base_url, p)
        try:
            frame = navigate_iframe_to(page, page_url, expect_marker=f"page={p}")
        except Exception as e:
            print(f"[{query}] p{p} 이동 실패: {e}")
            break

        scroll_list_to_end(page, frame)
        save_shot(page, f"{safe_name(query)}_p{p}_end.png")

        rows = collect_cards(frame, query, p)
        if not rows:
            print(f"[{query}] p{p} 카드 없음 — 중단")
            break

        added = 0
        for r in rows:
            key = (r["query"], r["name"], r["address"])
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(r)
            added += 1

        print(f"[{query}] p{p} 추가: {added}건 (누적 {len(all_rows)})")
        if added == 0:
            break

    return all_rows


def run_one_query(page, query):
    print(f"\n{'='*50}\n[START] {query}\n{'='*50}")
    frame, base_url = open_search_with_new_open(page, query)
    rows = collect_all_pages(page, frame, base_url, query)
    print(f"[DONE] {query}: 총 {len(rows)}건")
    return rows


# ============================================================
# 엑셀 저장
# ============================================================
def save_excel(all_rows, summary_data):
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    headers = ["검색어", "페이지", "순위", "상호명", "카테고리", "주소",
               "리뷰", "참고사항", "링크", "원본텍스트"]
    ws.append(headers)
    header_fill = PatternFill("solid", start_color="305496")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF", name="맑은 고딕")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in all_rows:
        ws.append([
            r["query"], r["page"], r["rank"],
            r["name"], r["category"], r["address"],
            r["review"], r["extras"], r["href"], r["raw"],
        ])

    widths = [12, 6, 6, 30, 18, 40, 14, 35, 50, 60]
    for i, w in enumerate(widths, 1):
        col = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("Summary")
    ws2.append(["항목", "값"])
    for cell in ws2[1]:
        cell.font = Font(bold=True, name="맑은 고딕")
        cell.fill = header_fill
        cell.font = Font(bold=True, color="FFFFFF", name="맑은 고딕")
    for k, v in summary_data:
        ws2.append([k, str(v)])
    ws2.column_dimensions["A"].width = 32
    ws2.column_dimensions["B"].width = 70

    wb.save(OUTPUT_DIR / "results.xlsx")


# ============================================================
# main
# ============================================================
def main():
    all_rows = []
    summary = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--lang=ko-KR", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1600, "height": 1200},
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
        )

        for query in QUERIES:
            page = context.new_page()
            try:
                rows = run_one_query(page, query)
                all_rows.extend(rows)
                summary.append((f"[{query}] 상태", "성공"))
                summary.append((f"[{query}] 수집건수", len(rows)))
            except Exception as e:
                save_shot(page, f"ERROR_{safe_name(query)}.png")
                save_text(f"error_{safe_name(query)}.txt", traceback.format_exc())
                summary.append((f"[{query}] 상태", f"실패: {e}"))
                print(traceback.format_exc())
            finally:
                page.close()

        browser.close()

    summary.append(("== 총 수집 건수 ==", len(all_rows)))
    save_excel(all_rows, summary)

    summary_lines = [f"총 수집: {len(all_rows)}건", "", "[검색어별 결과]"]
    for k, v in summary:
        summary_lines.append(f"  {k}: {v}")
    save_text("summary.txt", "\n".join(summary_lines))

    print(f"\n[FINAL] 총 {len(all_rows)}건 수집 완료")


if __name__ == "__main__":
    main()
