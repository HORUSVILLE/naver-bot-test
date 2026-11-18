import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shopping  # noqa: E402


@pytest.mark.parametrize("title,total,base", [
    ("백설 하얀설탕 15kg", 15000, "g"),
    ("CJ 중력분 1kg x 3개", 3000, "g"),
    ("우유 900ml 2개", 1800, "ml"),
    ("콩기름 18L 업소용", 18000, "ml"),
    ("올리브유 0.5L", 500, "ml"),
    ("특란 30구", 30, "개"),
    ("설탕 20kg(10kg x 2)", 20000, "g"),
    ("설탕 1kg 1개입", 1000, "g"),
])
def test_parse_unit(title, total, base):
    u = shopping.parse_unit(title)
    assert u is not None
    assert u.total == total and u.base == base


def test_parse_unit_none():
    assert shopping.parse_unit("설탕 업소용 대용량") is None


def test_unit_price():
    u = shopping.parse_unit("설탕 15kg")
    assert shopping.unit_price(15000, u) == {"value": 100.0, "per": "100g"}
    assert shopping.unit_price(9000, shopping.parse_unit("계란 30구")) == {"value": 300.0, "per": "1개"}


def test_matches_requires_all_words_and_respects_exclude():
    assert shopping.matches("백설 하얀 설탕 15kg", "하얀설탕 15kg", [])
    assert not shopping.matches("설탕 스틱 100개", "설탕", ["스틱"])
    assert not shopping.matches("흑설탕 1kg", "하얀설탕", [])


def _raw(pid, title, price, ptype="2", mall="몰"):
    return {"productId": pid, "title": title, "lprice": str(price), "productType": ptype,
            "mallName": mall, "link": f"https://example.com/{pid}", "image": ""}


def test_pick_cheapest_filters_and_sorts():
    raw = [
        _raw("1", "<b>설탕</b> 15kg", 25000),
        _raw("2", "설탕 스틱 50개", 3000),           # 제외어
        _raw("3", "설탕 15kg 중고", 1000, ptype="4"),  # 중고 상품 타입
        _raw("4", "설탕 15kg 업소용", 21000),
        _raw("1", "<b>설탕</b> 15kg", 25000),        # 중복
        _raw("5", "소금 15kg", 5000),                 # 검색어 불일치
    ]
    out = shopping.pick_cheapest(raw, "설탕", ["스틱"], limit=10)
    assert [x["id"] for x in out] == ["4", "1"]
    assert out[0]["title"] == "설탕 15kg 업소용"
    assert out[1]["title"] == "설탕 15kg"  # HTML 태그 제거


def test_search_uses_naver_api(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")
    shopping._cache.clear()
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        assert req.headers["X-Naver-Client-Id"] == "id"
        sort = req.url.params["sort"]
        items = [_raw("a", "설탕 3kg", 9000)] if sort == "asc" else [_raw("b", "설탕 15kg", 20000)]
        return httpx.Response(200, json={"items": items})

    real = httpx.AsyncClient
    monkeypatch.setattr(shopping.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    res = asyncio.run(shopping.search_lowest("설탕", [], 10))
    assert res["mock"] is False
    assert [x["id"] for x in res["items"]] == ["a", "b"]
    assert {c.url.params["sort"] for c in calls} == {"asc", "sim"}
    assert res["items"][1]["unit_price"] == {"value": 133.3, "per": "100g"}


def test_search_reports_bad_key(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "bad")
    shopping._cache.clear()
    real = httpx.AsyncClient
    monkeypatch.setattr(shopping.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(401)), **kw))
    with pytest.raises(shopping.SearchError, match="API 키"):
        asyncio.run(shopping.search_lowest("설탕", [], 10))


def test_mock_mode_without_keys(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    shopping._cache.clear()
    res = asyncio.run(shopping.search_lowest("설탕", [], 5))
    assert res["mock"] is True
    prices = [x["price"] for x in res["items"]]
    assert prices == sorted(prices) and len(prices) == 5
