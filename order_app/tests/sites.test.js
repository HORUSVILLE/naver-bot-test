// 실행: node --test order_app/tests/*.test.js
const test = require("node:test");
const assert = require("node:assert");
const { SITES, siteUrl, isMobile, platform, naverAppUrl } = require("../sites.js");

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

const ANDROID = "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36";
const IPAD_DESKTOP_MODE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15";

test("기기 구분: 아이폰·안드로이드·아이패드·PC", () => {
  assert.strictEqual(platform(IPHONE, 5), "ios");
  assert.strictEqual(platform(ANDROID, 5), "android");
  assert.strictEqual(platform(IPAD_DESKTOP_MODE, 5), "ios");
  assert.strictEqual(platform(IPAD_DESKTOP_MODE, 0), "other");
  assert.strictEqual(platform(PC, 0), "other");
});

test("네이버 앱 링크: 아이폰은 naversearchapp, 웹 주소를 그대로 담는다", () => {
  const web = siteUrl("naver", "하얀설탕 15kg", IPHONE);
  const app = naverAppUrl(web, IPHONE, 5);
  assert.ok(app.startsWith("naversearchapp://inappbrowser?"), app);
  const params = new URLSearchParams(app.split("?")[1]);
  assert.strictEqual(params.get("url"), web);            // 낮은가격순 주소가 손상 없이 들어감
  assert.ok(params.get("url").includes("sort=price_asc"));
});

test("네이버 앱 링크: 안드로이드는 앱이 없을 때 웹으로 넘어간다", () => {
  const web = siteUrl("naver", "설탕", ANDROID);
  const app = naverAppUrl(web, ANDROID, 5);
  assert.ok(app.startsWith("intent://inappbrowser?"), app);
  assert.ok(app.includes(";scheme=naversearchapp;package=com.nhn.android.search;"));
  const fallback = decodeURIComponent(app.match(/S\.browser_fallback_url=([^;]+)/)[1]);
  assert.strictEqual(fallback, web);
  assert.ok(app.endsWith(";end"));
});

test("PC에서는 앱 링크를 만들지 않는다", () => {
  assert.strictEqual(naverAppUrl("https://example.com", PC, 0), null);
});
