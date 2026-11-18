// 실행: node --test order_app/tests/*.test.js
const test = require("node:test");
const assert = require("node:assert");
const { SITES, siteUrl, isMobile } = require("../sites.js");

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148";
const PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36";

test("모든 사이트가 낮은 가격순 정렬 값을 넣는다", () => {
  const sortParam = { naver: "sort=price_asc", coupang: "sorter=salePriceAsc", danawa: "sort=priceASC" };
  for (const s of SITES) {
    const url = siteUrl(s.id, "설탕", PC);
    assert.ok(url.startsWith("https://"), url);
    assert.ok(url.includes(sortParam[s.id]), `${s.id}: ${url}`);
  }
});

test("검색어는 한글·공백·특수문자까지 인코딩된다", () => {
  const url = new URL(siteUrl("danawa", "  하얀설탕 15kg & 1+1 ", PC));
  assert.strictEqual(url.searchParams.get("query"), "하얀설탕 15kg & 1+1");
  assert.strictEqual(url.searchParams.get("sort"), "priceASC");
});

test("네이버쇼핑은 휴대폰이면 모바일 주소를 쓴다", () => {
  assert.ok(siteUrl("naver", "설탕", IPHONE).startsWith("https://msearch.shopping.naver.com/"));
  assert.ok(siteUrl("naver", "설탕", PC).startsWith("https://search.shopping.naver.com/"));
  assert.strictEqual(isMobile(IPHONE), true);
  assert.strictEqual(isMobile(PC), false);
});

test("없는 사이트는 오류", () => {
  assert.throws(() => siteUrl("nope", "설탕", PC));
});
