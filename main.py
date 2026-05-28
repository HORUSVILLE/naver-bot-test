"""
네이버 신규오픈 매장 자동 수집 봇 (사용자 워크플로우 정확 반영판)

[실제 동작 순서]
1. www.naver.com 에서 검색어 검색
2. 검색 결과의 '플레이스' 영역에서 [필터] 버튼 클릭
3. 뜬 필터 팝업을 마우스 올린 채 스크롤 → '새로오픈' 클릭
4. '결과보기' 클릭 → 새 탭(새 창)으로 네이버 지도 결과가 열림
5. 새 탭에서 5~10초 대기 (해외 접속 시 지도 중심 잡는 시간)
6. 왼쪽 목록에 마우스를 올린 채 스크롤하여 끝까지 수집
7. 페이지 번호를 넘기며 마지막 페이지까지 반복
8. 상호명 = '파란 큰 글씨'만 (회색/검정 작은 글씨는 부가설명)
"""
from pathlib import Path
import os
import re
import sys
import time
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
HEADLESS = True                # GitHub Actions에서는 True

SEARCH_LOAD_WAIT_MS = 5000      # 네이버 검색 결과 로드 대기
FILTER_PANEL_WAIT_MS = 1500     # 필터 팝업 뜨는 대기
NEW_TAB_WAIT_MS = 9000          # 새 탭(지도) 뜬 뒤 대기 (해외 접속 고려, 넉넉히)
PAGE_CLICK_WAIT_MS = 3500       # 페이지 넘김 후 대기
BETWEEN_QUERY_SEC = 7           # 검색어 사이 대기
MAX_PAGES_PER_QUERY = 15        # 쿼리당 최대 페이지 수
SCROLL_MAX_STEPS = 100          # 스크롤 최대 시도
SCROLL_STABLE_LIMIT = 5         # 같은 높이 N번 연속 → 끝 판정

DUMP_DEBUG_ON_FAIL = True

OUTPUT_DIR = Path("output")
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
DEBUG_DIR = OUTPUT_DIR / "debug"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "summary.txt").write_text("초기화됨 — 아직 실행 전\n", encoding="utf-8")


# ============================================================
# 공통 유틸
# ============================================================
def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", text or "").strip("_")[:40]


def save_shot(target, filename: str):
    try:
        target.screenshot(path=str(SCREENSHOT_DIR / filename), full_page=True)
    except Exception:
        pass


def save_text(filename: str, content: str):
    try:
        (OUTPUT_DIR / filename).write_text(content, encoding="utf-8")
    except Exception:
        pass


def save_debug(filename: str, content: str):
    try:
        (DEBUG_DIR / filename).write_text(content, encoding="utf-8")
    except Exception:
        pass


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def dump_clickable(target, query, tag):
    try:
        texts = target.evaluate(
            """() => {
                const out = [];
                const els = document.querySelectorAll("button, a, [role='button'], span");
                for (const el of els) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t && t.length <= 30) out.push(t);
                }
                return Array.from(new Set(out));
            }"""
        )
        save_debug(f"clickable_{safe_name(query)}_{tag}.txt", "\n".join(texts))
    except Exception as e:
        save_debug(f"clickable_{safe_name(query)}_{tag}_ERROR.txt", str(e))


def dump_html(target, query, tag):
    try:
        save_debug(f"html_{safe_name(query)}_{tag}.html", target.content()[:200000])
    except Exception:
        pass


# ============================================================
# 텍스트로 요소 클릭 (여러 방법 시도)
# ============================================================
def try_click_text(scope, text, exact=False, timeout=4000):
    patterns = [
        f"button:has-text('{text}')",
        f"a:has-text('{text}')",
        f"[role='button']:has-text('{text}')",
        f"label:has-text('{text}')",
        f"span:has-text('{text}')",
    ]
    for sel in patterns:
        try:
            loc = scope.locator(sel)
            n = loc.count()
            for i in range(min(n, 8)):
                el = loc.nth(i)
                if exact:
                    t = (el.inner_text(timeout=800) or "").strip()
                    if t != text:
                        continue
                el.scroll_into_view_if_needed(timeout=2000)
                el.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def js_force_click(scope, text):
    try:
        return scope.evaluate(
            """(label) => {
                const els = Array.from(document.querySelectorAll("button, a, [role='button'], span, label"));
                for (const el of els) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t === label || t.startsWith(label)) { el.click(); return true; }
                }
                return false;
            }""",
            text,
        )
    except Exception:
        return False


# ============================================================
# STEP 1~4: 네이버 검색 → 필터 → 새로오픈 → 결과보기(새 탭)
# ============================================================
def search_and_open_map(context, query):
    """
    네이버 검색 → 필터 팝업 → 새로오픈 → 결과보기.
    결과보기 클릭 시 새 탭이 열리면 그 탭(page)을 반환.
    새 탭이 안 열리면 같은 탭에서 지도로 이동했을 수 있으므로 현재 탭 반환.
    """
    page = context.new_page()
    search_url = f"https://search.naver.com/search.naver?query={query.replace(' ', '+')}"
    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(SEARCH_LOAD_WAIT_MS)
    save_shot(page, f"{safe_name(query)}_01_search.png")

    if DUMP_DEBUG_ON_FAIL and query == QUERIES[0]:
        dump_clickable(page, query, "search_initial")

    # --- STEP 4: [필터] 버튼 클릭 ---
    filter_opened = (
        try_click_text(page, "필터")
        or js_force_click(page, "필터")
    )
    page.wait_for_timeout(FILTER_PANEL_WAIT_MS)

    if not filter_opened:
        if DUMP_DEBUG_ON_FAIL:
            dump_clickable(page, query, "no_filter_btn")
            dump_html(page, query, "no_filter_btn")
            save_shot(page, f"{safe_name(query)}_FAIL_no_filter.png")
        raise RuntimeError("[필터] 버튼을 찾지 못함")

    save_shot(page, f"{safe_name(query)}_02_filter_panel.png")

    # --- STEP 6~7: 팝업 위에 마우스 올린 채 스크롤하며 '새로오픈' 찾기 ---
    new_open_clicked = False
    for step in range(10):
        if try_click_text(page, "새로오픈") or js_force_click(page, "새로오픈"):
            new_open_clicked = True
            print(f"[{query}] '새로오픈' 클릭 성공 (scroll step={step})")
            break
        # 팝업 영역(화면 좌측 상단 근처)에 마우스 올리고 스크롤
        try:
            page.mouse.move(630, 600)
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(500)
        except Exception:
            break

    if not new_open_clicked:
        if DUMP_DEBUG_ON_FAIL:
            dump_clickable(page, query, "no_newopen")
            dump_html(page, query, "no_newopen")
            save_shot(page, f"{safe_name(query)}_FAIL_no_newopen.png")
        raise RuntimeError("필터 팝업 내 '새로오픈'을 찾지 못함")

    page.wait_for_timeout(800)
    save_shot(page, f"{safe_name(query)}_03_newopen_checked.png")

    # --- STEP 8~9: '결과보기' 클릭 → 새 탭 열림 ---
    new_page = None
    try:
        with context.expect_page(timeout=12000) as new_page_info:
            if not (try_click_text(page, "결과보기") or js_force_click(page, "결과보기")):
                try_click_text(page, "적용")
        new_page = new_page_info.value
        print(f"[{query}] '결과보기' → 새 탭 열림")
    except Exception:
        # 새 탭이 안 열린 경우: 같은 탭이 지도로 바뀌었을 수 있음
        print(f"[{query}] 새 탭 감지 실패 — 현재 탭에서 진행 시도")
        new_page = page

    # --- STEP 10: 새 탭(지도)에서 충분히 대기 ---
    try:
        new_page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    new_page.wait_for_timeout(NEW_TAB_WAIT_MS)
    save_shot(new_page, f"{safe_name(query)}_04_map_result.png")

    # 검색 탭이 새 탭과 다르면 닫기(메모리 절약)
    if new_page is not page:
        try:
            page.close()
        except Exception:
            pass

    return new_page


# ============================================================
# 결과 목록 frame / 스크롤 / 수집
# ============================================================
def get_list_frame(page, timeout_sec=30):
    """
    결과 목록이 들어있는 컨텍스트 반환.
    1) pcmap iframe 이 있으면 그 frame
    2) 없으면 page 자체 (pcmap.place.naver.com 으로 직접 열린 경우)
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        # iframe 우선
        for fr in page.frames:
            u = fr.url or ""
            if "pcmap.place.naver.com" in u and "list" in u:
                return fr
        # page 자체가 pcmap 이면 page 반환
        if "pcmap.place.naver.com" in (page.url or ""):
            return page
        page.wait_for_timeout(500)
    # 마지막 fallback: page 자체
    return page


SCROLL_SELECTORS = [
    "#_pcmap_list_scroll_container",
    "div[id*='_list_scroll_container']",
    "div.Ryr1F",
    "#app-root",
]

# 상호명(파란 큰 글씨) 후보 셀렉터
NAME_SELECTORS = [
    "span.TYaxT",     # 구버전 상호명
    "span.place_bluelink",
    "a.place_bluelink span",
    "span.YwYLL",     # 신버전 상호명 후보
    "div.qbGlu span", # 후보
]

# 카드(매장 한 칸) 후보 셀렉터
CARD_SELECTORS = [
    "li.UEzoS",
    "li.VLTHu",
    "li.lLTC0",
    "ul > li:has(span)",
]


def find_first_existing(ctx, selectors):
    for sel in selectors:
        try:
            if ctx.locator(sel).count() > 0:
                return sel
        except Exception:
            continue
    return None


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


def extract_names_and_cards(frame, query, page_num):
    """
    카드 단위로 순회하며 상호명(파란 큰 글씨)을 추출.
    카드 셀렉터가 안 잡히면 상호명 셀렉터로 직접 추출(이름만이라도 확보).
    """
    rows = []

    card_sel = find_first_existing(frame, CARD_SELECTORS)
    if card_sel:
        cards = frame.locator(card_sel)
        count = cards.count()
        rank = 0
        for i in range(count):
            card = cards.nth(i)
            # 상호명: 카드 내부의 파란 글씨 후보 우선
            name = ""
            for nsel in NAME_SELECTORS:
                try:
                    loc = card.locator(nsel).first
                    if loc.count() > 0:
                        name = normalize(loc.inner_text(timeout=800))
                        if name:
                            break
                except Exception:
                    continue
            if not name:
                continue
            # 부가정보
            try:
                full = normalize(card.inner_text(timeout=800))
            except Exception:
                full = ""
            href = ""
            try:
                href = card.locator("a").first.get_attribute("href") or ""
            except Exception:
                pass
            rank += 1
            rows.append({
                "query": query, "page": page_num, "rank": rank,
                "name": name, "detail": full, "href": href,
            })
        if rows:
            return rows

    # fallback: 카드 못 잡으면 상호명 셀렉터로 이름만 수집
    name_sel = find_first_existing(frame, NAME_SELECTORS)
    if name_sel:
        loc = frame.locator(name_sel)
        count = loc.count()
        for i in range(count):
            try:
                name = normalize(loc.nth(i).inner_text(timeout=800))
            except Exception:
                continue
            if name:
                rows.append({
                    "query": query, "page": page_num, "rank": i + 1,
                    "name": name, "detail": "", "href": "",
                })
    return rows


def click_page_number(frame, page_num):
    selectors = [
        f"a:has-text('{page_num}')",
        f"button:has-text('{page_num}')",
        f"span:has-text('{page_num}')",
    ]
    for sel in selectors:
        try:
            loc = frame.locator(sel)
            n = loc.count()
            for i in range(n):
                el = loc.nth(i)
                txt = (el.inner_text(timeout=800) or "").strip()
                if txt == str(page_num):
                    el.scroll_into_view_if_needed(timeout=2000)
                    el.click(timeout=3000)
                    return True
        except Exception:
            continue
    return False


def collect_all_pages(page, frame, query):
    all_rows = []
    seen = set()

    scroll_list_to_end(page, frame)
    save_shot(page, f"{safe_name(query)}_p1_end.png")
    rows = extract_names_and_cards(frame, query, 1)

    # 첫 페이지에서 한 건도 못 잡으면 디버그 덤프
    if not rows and DUMP_DEBUG_ON_FAIL:
        dump_clickable(frame if hasattr(frame, "evaluate") else page, query, "no_cards_p1")
        try:
            save_debug(f"list_html_{safe_name(query)}_p1.html",
                       (frame.content() if hasattr(frame, "content") else "")[:200000])
        except Exception:
            pass

    for r in rows:
        key = (r["query"], r["name"])
        if key in seen:
            continue
        seen.add(key)
        all_rows.append(r)
    print(f"[{query}] p1 수집: {len(rows)}건")

    for p in range(2, MAX_PAGES_PER_QUERY + 1):
        if not click_page_number(frame, p):
            print(f"[{query}] p{p} 버튼 없음 — 종료")
            break
        page.wait_for_timeout(PAGE_CLICK_WAIT_MS)
        # frame 재취득
        frame = get_list_frame(page, timeout_sec=15)
        scroll_list_to_end(page, frame)
        save_shot(page, f"{safe_name(query)}_p{p}_end.png")
        rows = extract_names_and_cards(frame, query, p)
        if not rows:
            print(f"[{query}] p{p} 카드 없음 — 종료")
            break
        added = 0
        for r in rows:
            key = (r["query"], r["name"])
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(r)
            added += 1
        print(f"[{query}] p{p} 추가: {added}건 (누적 {len(all_rows)})")
        if added == 0:
            break

    return all_rows


def run_one_query(context, query):
    print(f"\n{'='*50}\n[START] {query}\n{'='*50}")
    map_page = search_and_open_map(context, query)
    frame = get_list_frame(map_page, timeout_sec=30)
    rows = collect_all_pages(map_page, frame, query)
    try:
        map_page.close()
    except Exception:
        pass
    print(f"[DONE] {query}: 총 {len(rows)}건")
    return rows


# ============================================================
# 엑셀 저장
# ============================================================
def save_excel(all_rows, summary_data):
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    headers = ["검색어", "페이지", "순위", "상호명", "부가정보", "링크"]
    ws.append(headers)
    header_fill = PatternFill("solid", start_color="305496")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF", name="맑은 고딕")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r in all_rows:
        ws.append([r["query"], r["page"], r["rank"], r["name"], r["detail"], r["href"]])
    widths = [12, 6, 6, 32, 55, 50]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("Summary")
    ws2.append(["항목", "값"])
    for cell in ws2[1]:
        cell.font = Font(bold=True, color="FFFFFF", name="맑은 고딕")
        cell.fill = header_fill
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
            headless=HEADLESS,
            args=[
                "--lang=ko-KR",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
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

        for idx, query in enumerate(QUERIES):
            try:
                rows = run_one_query(context, query)
                all_rows.extend(rows)
                summary.append((f"[{query}] 상태", "성공"))
                summary.append((f"[{query}] 수집건수", len(rows)))
            except Exception as e:
                save_text(f"error_{safe_name(query)}.txt", traceback.format_exc())
                summary.append((f"[{query}] 상태", f"실패: {e}"))
                print(traceback.format_exc())
            if idx < len(QUERIES) - 1:
                time.sleep(BETWEEN_QUERY_SEC)

        browser.close()

    summary.append(("== 총 수집 건수 ==", len(all_rows)))
    save_excel(all_rows, summary)
    lines = [f"총 수집: {len(all_rows)}건", "", "[검색어별 결과]"]
    for k, v in summary:
        lines.append(f"  {k}: {v}")
    save_text("summary.txt", "\n".join(lines))
    print(f"\n[FINAL] 총 {len(all_rows)}건 수집 완료")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print(err)
        save_text("summary.txt", f"치명적 오류로 중단됨:\n\n{err}")
        save_text("fatal_error.txt", err)
        sys.exit(0)
