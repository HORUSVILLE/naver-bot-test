// 쇼핑몰별 "낮은 가격순" 검색 주소
// 새 사이트를 추가하려면 아래 목록에 한 줄만 넣으면 됩니다.
(function (root) {
  "use strict";

  const enc = encodeURIComponent;

  const SITES = [
    {
      id: "naver",
      name: "네이버쇼핑",
      note: "11번가·G마켓·옥션·SSG·스마트스토어 등 모음",
      url: (q, mobile) =>
        `https://${mobile ? "msearch" : "search"}.shopping.naver.com/search/all?query=${enc(q)}&sort=price_asc`,
    },
    {
      id: "coupang",
      name: "쿠팡",
      note: "네이버쇼핑에 없는 쿠팡 상품",
      url: (q) => `https://www.coupang.com/np/search?q=${enc(q)}&sorter=salePriceAsc`,
    },
    {
      id: "danawa",
      name: "다나와",
      note: "가격비교 사이트",
      url: (q) => `https://search.danawa.com/dsearch.php?query=${enc(q)}&sort=priceASC`,
    },
  ];

  function isMobile(ua) {
    return /Mobi|Android|iPhone|iPad|iPod/i.test(ua || "");
  }

  function siteUrl(siteId, query, ua) {
    const site = SITES.find((s) => s.id === siteId);
    if (!site) throw new Error("알 수 없는 사이트: " + siteId);
    return site.url(String(query).trim(), isMobile(ua));
  }

  function platform(ua, touchPoints) {
    if (/Android/i.test(ua || "")) return "android";
    // iPadOS는 PC(Macintosh)처럼 보이므로 터치 지원 여부로 구분
    if (/iPhone|iPad|iPod/i.test(ua || "") || (/Macintosh/i.test(ua || "") && touchPoints > 1)) return "ios";
    return "other";
  }

  // 네이버 앱 안에서 웹 주소를 여는 앱 링크.
  // 쿠팡은 일반 링크만으로도 휴대폰에서 쿠팡 앱이 열리므로 따로 필요 없습니다.
  //  - 아이폰: naversearchapp:// (앱이 없으면 아무 일도 일어나지 않음 → 화면에 웹으로 열기 안내)
  //  - 안드로이드: intent:// (앱이 없으면 자동으로 웹 주소로 이동)
  function naverAppUrl(webUrl, ua, touchPoints) {
    const path = `inappbrowser?url=${enc(webUrl)}&target=new&version=6`;
    const p = platform(ua, touchPoints);
    if (p === "ios") return `naversearchapp://${path}`;
    if (p === "android") {
      return `intent://${path}#Intent;scheme=naversearchapp;package=com.nhn.android.search;` +
        `S.browser_fallback_url=${enc(webUrl)};end`;
    }
    return null;
  }

  const api = { SITES, siteUrl, isMobile, platform, naverAppUrl };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Sites = api;
})(this);
