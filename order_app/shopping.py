"""
네이버 쇼핑 검색 API로 재료 최저가를 찾는 모듈.

- 공식 API: https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
- 네이버 쇼핑에는 11번가, G마켓, 옥션, SSG, 스마트스토어 등 국내 쇼핑몰 대부분이
  모여 있어 API 하나로 여러 사이트 가격을 비교할 수 있습니다. (쿠팡은 미포함)

최저가 정렬(sort=asc)만 쓰면 '설탕' 검색에 설탕 스틱 1개, 설탕 통 같은 엉뚱한
싼 상품이 먼저 나옵니다. 그래서
  1) 정확도순 100개 + 최저가순 100개를 함께 가져오고
  2) 검색어 단어가 모두 들어간 상품만 남기고 (제외어가 들어간 상품은 버림)
  3) 남은 것 중에서 가격순으로 정렬합니다.
상품명에서 용량(15kg, 500g x 2개 등)을 읽어 단위가격도 같이 계산합니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import quote

import httpx

NAVER_SHOP_URL = "https://openapi.naver.com/v1/search/shop.json"

# 네이버 productType: 1~3 = 일반 판매 상품, 4~6 중고, 7~9 단종, 10~12 판매예정
SELLABLE_PRODUCT_TYPES = {"1", "2", "3"}

CACHE_TTL_SEC = 10 * 60
_cache: dict[str, tuple[float, dict]] = {}


# ------------------------------------------------------------------
# 용량 / 단위가격
# ------------------------------------------------------------------
@dataclass
class UnitInfo:
    total: float          # 총량 (g, ml, 또는 개수)
    base: str             # "g" | "ml" | "개"
    label: str            # 화면 표시용 예: "15kg", "500g × 2"


_AMOUNT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|키로|g|그램|ml|mL|l|L|리터)(?![a-zA-Z])",
    re.IGNORECASE,
)
_MULT_RE = re.compile(
    r"(?:[x×*]\s*(\d+)(?![\d.,])(?!\s*(?:kg|g|ml|l|리터)))"
    r"|(?:(\d+)\s*(?:개|팩|봉|병|입|ea|박스|캔|포)(?!\s*월))",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(r"(\d+)\s*(구|알|매)(?![a-zA-Z가-힣])")

_UNIT_TO_BASE = {
    "kg": ("g", 1000), "키로": ("g", 1000), "g": ("g", 1), "그램": ("g", 1),
    "ml": ("ml", 1), "l": ("ml", 1000), "리터": ("ml", 1000),
}


def parse_unit(title: str) -> Optional[UnitInfo]:
    """상품명에서 총 용량을 추정합니다. 못 읽으면 None."""
    m = _AMOUNT_RE.search(title)
    if m:
        num = float(m.group(1).replace(",", "."))
        unit_raw = m.group(2).lower()
        base, factor = _UNIT_TO_BASE[unit_raw]
        amount = num * factor
        if amount <= 0:
            return None

        # 용량 뒤에 붙은 배수 (예: "1kg x 3", "500g 2개")
        mult = 1
        tail = title[m.end(): m.end() + 15]
        mm = _MULT_RE.search(tail)
        # "20kg(10kg x 2)" 처럼 배수 앞에 다른 용량이 또 있으면 이미 합계로 보고 무시
        if mm and not _AMOUNT_RE.search(tail[: mm.start()]):
            n = int(mm.group(1) or mm.group(2))
            if 1 < n <= 200:
                mult = n

        label = f"{m.group(1)}{m.group(2)}" + (f" × {mult}" if mult > 1 else "")
        return UnitInfo(total=amount * mult, base=base, label=label)

    c = _COUNT_RE.search(title)
    if c:
        n = int(c.group(1))
        if n > 0:
            return UnitInfo(total=n, base="개", label=f"{n}{c.group(2)}")
    return None


def unit_price(price: int, unit: Optional[UnitInfo]) -> Optional[dict]:
    """가격을 100g/100ml/1개당 가격으로 환산."""
    if not unit or unit.total <= 0:
        return None
    if unit.base == "개":
        per, per_label = 1, "1개"
    else:
        per, per_label = 100, f"100{unit.base}"
    value = price / unit.total * per
    return {"value": round(value, 1), "per": per_label}


# ------------------------------------------------------------------
# 검색 결과 정리
# ------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")


def clean_title(raw: str) -> str:
    return html.unescape(_TAG_RE.sub("", raw or "")).strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def matches(title: str, query: str, exclude_words: list[str]) -> bool:
    """검색어의 모든 단어가 상품명에 있고, 제외어는 하나도 없어야 통과."""
    t = _norm(title)
    for word in query.split():
        if _norm(word) not in t:
            return False
    for word in exclude_words:
        if word and _norm(word) in t:
            return False
    return True


def normalize_item(raw: dict) -> Optional[dict]:
    try:
        price = int(raw.get("lprice") or 0)
    except ValueError:
        return None
    if price <= 0:
        return None
    if str(raw.get("productType", "1")) not in SELLABLE_PRODUCT_TYPES:
        return None

    title = clean_title(raw.get("title", ""))
    unit = parse_unit(title)
    return {
        "id": str(raw.get("productId") or raw.get("link")),
        "title": title,
        "price": price,
        "mall": raw.get("mallName") or "",
        "link": raw.get("link") or "",
        "image": raw.get("image") or "",
        "brand": raw.get("brand") or raw.get("maker") or "",
        # productType 1 = 가격비교 묶음 페이지 (여러 판매처 비교 화면이 열림)
        "is_catalog": str(raw.get("productType")) == "1",
        "unit": asdict(unit) if unit else None,
        "unit_price": unit_price(price, unit),
    }


def pick_cheapest(raw_items: list[dict], query: str, exclude_words: list[str], limit: int) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for raw in raw_items:
        item = normalize_item(raw)
        if not item or item["id"] in seen:
            continue
        if not matches(item["title"], query, exclude_words):
            continue
        seen.add(item["id"])
        out.append(item)
    out.sort(key=lambda x: x["price"])
    return out[:limit]


# ------------------------------------------------------------------
# API 호출
# ------------------------------------------------------------------
def has_credentials() -> bool:
    return bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET"))


class SearchError(Exception):
    pass


async def _fetch(client: httpx.AsyncClient, query: str, sort: str) -> list[dict]:
    r = await client.get(
        NAVER_SHOP_URL,
        params={"query": query, "display": 100, "start": 1, "sort": sort,
                "exclude": "used:rental:cbshop"},
        headers={
            "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
        },
        timeout=10,
    )
    if r.status_code == 401:
        raise SearchError("네이버 API 키가 올바르지 않습니다. Client ID/Secret을 확인하세요.")
    if r.status_code == 429:
        raise SearchError("오늘 네이버 API 호출 한도(25,000회)를 넘었습니다.")
    if r.status_code != 200:
        raise SearchError(f"네이버 API 오류 (HTTP {r.status_code}): {r.text[:200]}")
    return r.json().get("items", [])


async def search_lowest(query: str, exclude_words: list[str], limit: int = 20) -> dict:
    query = query.strip()
    key = f"{query}|{','.join(sorted(exclude_words))}|{limit}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_SEC:
        return hit[1]

    if has_credentials():
        async with httpx.AsyncClient() as client:
            by_sim, by_price = await asyncio.gather(
                _fetch(client, query, "sim"), _fetch(client, query, "asc")
            )
        items = pick_cheapest(by_price + by_sim, query, exclude_words, limit)
        result = {"query": query, "mock": False, "items": items}
    else:
        result = {"query": query, "mock": True,
                  "items": pick_cheapest(_mock_items(query), query, exclude_words, limit)}

    _cache[key] = (time.time(), result)
    return result


# ------------------------------------------------------------------
# API 키가 없을 때 화면을 미리 볼 수 있는 샘플 데이터
# ------------------------------------------------------------------
def _mock_items(query: str) -> list[dict]:
    seed = int(hashlib.md5(query.encode()).hexdigest(), 16)
    malls = ["11번가", "G마켓", "옥션", "SSG닷컴", "식자재왕", "오늘식자재", "스마트스토어 A", "롯데ON"]
    sizes = ["1kg", "3kg", "5kg", "500g x 2개", "10kg", "1kg x 3개"]
    search_url = "https://search.shopping.naver.com/search/all?query=" + quote(query)
    has_size = parse_unit(query) is not None
    items = []
    for i in range(12):
        size = "" if has_size else sizes[(seed >> i) % len(sizes)]
        base = 3000 + (seed >> (i * 3)) % 40000
        items.append({
            "title": f"[샘플] {query} {size} 업소용".replace("  ", " "),
            "lprice": str(base // 10 * 10),
            "mallName": malls[(seed >> (i * 2)) % len(malls)],
            "link": search_url,
            "image": "",
            "productId": f"mock-{i}",
            "productType": "2",
        })
    return items
