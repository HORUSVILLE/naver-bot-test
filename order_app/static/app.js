// 재료 최저가 — 화면 로직
// 재료 목록은 이 브라우저(localStorage)에만 저장됩니다.
(() => {
  "use strict";

  const STORE_KEY = "order_app.items.v1";
  const CODE_KEY = "order_app.access_code";
  const $ = (sel) => document.querySelector(sel);

  const won = (n) => Math.round(n).toLocaleString("ko-KR") + "원";
  const today = () => new Date().toISOString().slice(0, 10);
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

  function storageGet(key, fallback) {
    try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  }
  function storageSet(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장 불가 환경 */ }
  }

  const SAMPLE = [
    { name: "설탕", query: "하얀설탕 15kg", exclude: "스틱, 시럽, 각설탕" },
    { name: "중력분", query: "중력분 20kg", exclude: "" },
    { name: "식용유", query: "콩기름 18L", exclude: "" },
  ];

  let items = storageGet(STORE_KEY, null);
  if (!Array.isArray(items)) {
    items = SAMPLE.map((s) => ({ id: uid(), memo: "", last: null, ...s }));
    storageSet(STORE_KEY, items);
  }
  const save = () => storageSet(STORE_KEY, items);

  let status = { naver_configured: true, access_code_required: false };
  let current = null;        // 현재 검색 중인 재료
  let lastResults = [];
  let sortMode = "price";

  // ---------------- 재료 목록 ----------------
  function renderList() {
    const f = $("#filter").value.trim().toLowerCase();
    const list = $("#items");
    list.innerHTML = "";
    const shown = items.filter((it) => !f || it.name.toLowerCase().includes(f) || (it.query || "").toLowerCase().includes(f));
    $("#empty").hidden = items.length > 0;

    for (const it of shown) {
      const li = document.createElement("li");
      li.className = "item";

      const main = document.createElement("div");
      main.className = "item-main";
      main.tabIndex = 0;
      main.setAttribute("role", "button");
      main.innerHTML = `<div class="item-name"></div><div class="item-meta"></div><div class="item-last"></div>`;
      main.querySelector(".item-name").textContent = it.name;
      const meta = [];
      if (it.query && it.query !== it.name) meta.push(`검색어: ${it.query}`);
      if (it.memo) meta.push(it.memo);
      main.querySelector(".item-meta").textContent = meta.join(" · ");
      const last = main.querySelector(".item-last");
      if (it.last) {
        last.innerHTML = `지난 최저가 <b></b> <span class="hint"></span>`;
        last.querySelector("b").textContent = won(it.last.price);
        last.querySelector(".hint").textContent = `${it.last.mall} · ${it.last.date}`;
      } else {
        last.innerHTML = `<span class="hint">눌러서 최저가 찾기</span>`;
      }
      const open = () => openResults(it);
      main.addEventListener("click", open);
      main.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });

      const side = document.createElement("div");
      side.className = "item-side";
      const findBtn = btn("최저가 찾기", "btn primary small", open);
      const editBtn = btn("편집", "btn small ghost", () => openDialog(it));
      side.append(findBtn, editBtn);

      li.append(main, side);
      list.append(li);
    }
  }

  function btn(text, cls, onClick) {
    const b = document.createElement("button");
    b.type = "button"; b.className = cls; b.textContent = text;
    b.addEventListener("click", onClick);
    return b;
  }

  // ---------------- 추가 / 편집 ----------------
  const dialog = $("#item-dialog");
  const form = $("#item-form");
  let editing = null;

  function openDialog(it) {
    editing = it || null;
    $("#dialog-title").textContent = it ? "재료 편집" : "재료 추가";
    form.name.value = it?.name || "";
    form.query.value = it?.query || "";
    form.exclude.value = it?.exclude || "";
    form.memo.value = it?.memo || "";
    let del = form.querySelector(".btn.danger");
    if (del) del.remove();
    if (it) {
      del = btn("삭제", "btn danger ghost", () => {
        if (!confirm(`'${it.name}'을(를) 목록에서 지울까요?`)) return;
        items = items.filter((x) => x.id !== it.id);
        save(); dialog.close(); renderList();
      });
      del.style.marginRight = "auto";
      form.querySelector(".actions").prepend(del);
    }
    dialog.showModal();
    form.name.focus();
  }

  form.addEventListener("submit", (e) => {
    const name = form.name.value.trim();
    if (!name) { e.preventDefault(); return; }
    const data = {
      name,
      query: form.query.value.trim() || name,
      exclude: form.exclude.value.trim(),
      memo: form.memo.value.trim(),
    };
    if (editing) {
      if (editing.query !== data.query || editing.exclude !== data.exclude) data.last = null;
      Object.assign(editing, data);
    } else {
      items.unshift({ id: uid(), last: null, ...data });
    }
    save(); renderList();
  });
  $("#cancel-btn").addEventListener("click", () => dialog.close());
  $("#add-btn").addEventListener("click", () => openDialog(null));
  $("#filter").addEventListener("input", renderList);

  // ---------------- 최저가 검색 ----------------
  async function openResults(it, force = false) {
    current = it;
    $("#list-view").hidden = true;
    $("#result-view").hidden = false;
    $("#result-title").textContent = it.name;
    $("#result-query").textContent = `검색어: ${it.query}` + (it.exclude ? ` · 제외: ${it.exclude}` : "");
    $("#ext-naver").href = "https://search.shopping.naver.com/search/all?sort=price_asc&query=" + encodeURIComponent(it.query);
    $("#ext-coupang").href = "https://www.coupang.com/np/search?sorter=salePriceAsc&q=" + encodeURIComponent(it.query);
    if (!force) history.pushState({ view: "result" }, "");
    window.scrollTo(0, 0);

    $("#best").innerHTML = "";
    $("#results").innerHTML = '<li class="skeleton"></li><li class="skeleton"></li><li class="skeleton"></li>';
    $("#result-msg").hidden = true;

    try {
      const params = new URLSearchParams({ q: it.query, exclude: it.exclude || "", limit: "20" });
      const headers = {};
      const code = storageGet(CODE_KEY, "");
      if (code) headers["X-Access-Code"] = code;
      const r = await fetch("/api/search?" + params, { headers });
      if (r.status === 401) {
        askCode(true);
        throw new Error("접속 코드를 입력한 뒤 다시 시도하세요.");
      }
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "검색에 실패했습니다.");
      if (current !== it) return;
      lastResults = data.items;
      if (data.items.length) {
        const top = data.items[0];
        it.last = { price: top.price, mall: top.mall, date: today() };
        save();
      }
      renderResults();
    } catch (err) {
      if (current !== it) return;
      $("#results").innerHTML = "";
      showMsg(err.message || "검색 중 문제가 생겼습니다.");
    }
  }

  function sorted() {
    const arr = lastResults.slice();
    if (sortMode === "unit") {
      arr.sort((a, b) => {
        const au = a.unit_price?.value ?? Infinity, bu = b.unit_price?.value ?? Infinity;
        return au - bu || a.price - b.price;
      });
    }
    return arr;
  }

  function renderResults() {
    const list = $("#results");
    const best = $("#best");
    list.innerHTML = ""; best.innerHTML = "";

    if (!lastResults.length) {
      showMsg("조건에 맞는 상품이 없습니다. 재료 편집에서 검색어를 짧게 바꾸거나 제외어를 줄여보세요.");
      return;
    }
    $("#result-msg").hidden = true;

    const arr = sorted();
    const top = arr[0];
    const box = document.createElement("div");
    box.className = "best";
    box.innerHTML = `<div class="label">${sortMode === "unit" ? "단위가격 최저" : "최저가"}</div>`;
    box.append(resultCard(top, false));
    const go = document.createElement("a");
    go.className = "btn primary";
    go.href = top.link; go.target = "_blank"; go.rel = "noopener";
    go.textContent = top.is_catalog ? "판매처 비교 화면 열기 ↗" : `${top.mall || "판매"} 구매 페이지 열기 ↗`;
    box.append(go);
    best.append(box);

    for (const p of arr.slice(1)) {
      const li = document.createElement("li");
      li.append(resultCard(p, true));
      list.append(li);
    }
  }

  function resultCard(p, withButton) {
    const el = document.createElement("div");
    el.className = "result";
    if (p.image) {
      const img = document.createElement("img");
      img.src = p.image; img.alt = ""; img.loading = "lazy"; img.referrerPolicy = "no-referrer";
      el.append(img);
    } else {
      const ph = document.createElement("div"); ph.className = "noimg"; el.append(ph);
    }
    const body = document.createElement("div");
    body.className = "result-body";
    body.innerHTML = `<div class="result-title"></div><div class="result-mall"></div><div class="result-row"><div><div class="result-price"></div><div class="result-unit"></div></div></div>`;
    body.querySelector(".result-title").textContent = p.title;
    body.querySelector(".result-mall").textContent = (p.mall || "판매처 정보 없음") + (p.is_catalog ? " · 여러 판매처 비교" : "");
    body.querySelector(".result-price").textContent = won(p.price);
    body.querySelector(".result-unit").textContent = p.unit_price
      ? `${p.unit.label} · ${p.unit_price.per}당 ${won(p.unit_price.value)}`
      : "용량 정보 없음";
    if (withButton) {
      const a = document.createElement("a");
      a.className = "btn small"; a.href = p.link; a.target = "_blank"; a.rel = "noopener";
      a.textContent = "열기 ↗";
      body.querySelector(".result-row").append(a);
    }
    el.append(body);
    return el;
  }

  function showMsg(text) {
    const m = $("#result-msg");
    m.textContent = text; m.hidden = false;
  }

  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    sortMode = b.dataset.sort;
    document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
    if (lastResults.length) renderResults();
  }));

  function backToList() {
    current = null; lastResults = [];
    $("#result-view").hidden = true;
    $("#list-view").hidden = false;
    renderList();
  }
  $("#back-btn").addEventListener("click", () => history.back());
  window.addEventListener("popstate", () => { if (!$("#result-view").hidden) backToList(); });
  $("#refresh-btn").addEventListener("click", () => current && openResults(current, true));

  // ---------------- 백업 ----------------
  const menu = $("#menu-dialog");
  $("#menu-btn").addEventListener("click", () => menu.showModal());
  $("#menu-close").addEventListener("click", () => menu.close());
  $("#export-btn").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(items, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `재료목록-${today()}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
  $("#import-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      if (!Array.isArray(data)) throw new Error();
      const clean = data
        .filter((x) => x && typeof x.name === "string" && x.name.trim())
        .map((x) => ({
          id: uid(), name: x.name.trim().slice(0, 40),
          query: String(x.query || x.name).trim().slice(0, 100),
          exclude: String(x.exclude || "").slice(0, 200),
          memo: String(x.memo || "").slice(0, 100),
          last: null,
        }));
      if (!confirm(`${clean.length}개 재료를 가져올까요? 지금 목록은 바뀝니다.`)) return;
      items = clean; save(); renderList(); menu.close();
    } catch {
      alert("파일을 읽을 수 없습니다. 이 앱에서 내보낸 파일인지 확인하세요.");
    } finally {
      e.target.value = "";
    }
  });

  // ---------------- 접속 코드 ----------------
  function askCode(force) {
    if (!force && storageGet(CODE_KEY, "")) return;
    const code = prompt("접속 코드를 입력하세요");
    if (code != null) storageSet(CODE_KEY, code.trim());
  }
  $("#code-btn").addEventListener("click", () => askCode(true));

  // ---------------- 시작 ----------------
  fetch("/api/status").then((r) => r.json()).then((s) => {
    status = s;
    if (!s.naver_configured) {
      const b = $("#mode-banner");
      b.textContent = "샘플 모드: 네이버 API 키가 아직 설정되지 않아 가짜 가격이 표시됩니다.";
      b.hidden = false;
    }
    if (s.access_code_required) {
      $("#code-btn").hidden = false;
      askCode(false);
    }
  }).catch(() => {});

  renderList();
})();
