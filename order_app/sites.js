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

  const api = { SITES, siteUrl, isMobile };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Sites = api;
})(this);
