// 재료 최저가 — 화면 로직
// 재료 목록과 설정은 이 브라우저(localStorage)에만 저장됩니다.
(() => {
  "use strict";

  const STORE_KEY = "order_app.items.v1";
  const SETTINGS_KEY = "order_app.settings.v1";
  const { SITES, siteUrl, naverAppUrl, platform } = window.Sites;
  const $ = (sel) => document.querySelector(sel);
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
    { name: "설탕", query: "하얀설탕 15kg" },
    { name: "중력분", query: "중력분 20kg" },
    { name: "식용유", query: "콩기름 18L" },
  ];

  let items = storageGet(STORE_KEY, null);
  if (!Array.isArray(items)) {
    items = SAMPLE.map((s) => ({ id: uid(), memo: "", opened: null, ...s }));
    storageSet(STORE_KEY, items);
  }
  items = items.map((x) => ({ ...x, query: x.query || x.name, memo: x.memo || "" }));
  const save = () => storageSet(STORE_KEY, items);

  let settings = { mainSite: "naver", naverApp: true, ...storageGet(SETTINGS_KEY, {}) };
  if (!SITES.some((s) => s.id === settings.mainSite)) settings.mainSite = "naver";

  const siteName = (id) => SITES.find((s) => s.id === id).name;

  // ---------------- 재료 목록 ----------------
  function renderList() {
    const f = $("#filter").value.trim().toLowerCase();
    const list = $("#items");
    list.innerHTML = "";
    const shown = items.filter((it) => !f || it.name.toLowerCase().includes(f) || it.query.toLowerCase().includes(f));
    $("#empty").hidden = items.length > 0;
    $("#no-match").hidden = !(items.length > 0 && shown.length === 0);

    for (const it of shown) {
      const li = document.createElement("li");
      li.className = "item";

      const head = document.createElement("div");
      head.className = "item-head";
      const info = document.createElement("div");
      info.className = "item-info";
      const name = document.createElement("div");
      name.className = "item-name";
      name.textContent = it.name;
      const meta = document.createElement("div");
      meta.className = "item-meta";
      const parts = [];
      if (it.query !== it.name) parts.push(`검색어: ${it.query}`);
      if (it.memo) parts.push(it.memo);
      if (it.opened) parts.push(`최근 확인 ${+it.opened.slice(5, 7)}/${+it.opened.slice(8, 10)}`);
      meta.textContent = parts.join(" · ");
      info.append(name, meta);
      head.append(info, button("편집", "btn small ghost", () => openDialog(it)));

      const actions = document.createElement("div");
      actions.className = "item-actions";
      const main = siteLink(it, settings.mainSite, "btn primary main-link", `${siteName(settings.mainSite)} 최저가 ↗`);
      const others = document.createElement("div");
      others.className = "chips";
      for (const s of SITES) {
        if (s.id === settings.mainSite) continue;
        others.append(siteLink(it, s.id, "chip", `${s.name} ↗`));
      }
      actions.append(main, others);

      li.append(head, actions);
      list.append(li);
    }
  }

  function siteLink(it, siteId, cls, text) {
    const webUrl = siteUrl(siteId, it.query, navigator.userAgent);
    const appUrl = siteId === "naver" && settings.naverApp
      ? naverAppUrl(webUrl, navigator.userAgent, navigator.maxTouchPoints || 0)
      : null;

    const a = document.createElement("a");
    a.className = cls;
    a.href = webUrl;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = text;
    a.addEventListener("click", (e) => {
      it.opened = today();
      save();
      if (appUrl) {
        e.preventDefault();
        location.href = appUrl;
        // 아이폰은 앱이 없을 때 자동으로 웹으로 넘어갈 수 없어 안내를 띄웁니다.
        if (platform(navigator.userAgent, navigator.maxTouchPoints || 0) === "ios") showFallback(webUrl);
      }
      setTimeout(renderList, 300);
    });
    return a;
  }

  let toastTimer = null;
  function showFallback(webUrl) {
    const t = $("#toast");
    t.querySelector("a").href = webUrl;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 8000);
  }

  function button(text, cls, onClick) {
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
    form.name.value = it ? it.name : "";
    form.query.value = it && it.query !== it.name ? it.query : "";
    form.memo.value = it ? it.memo : "";
    $("#delete-btn").hidden = !it;
    dialog.showModal();
    if (!it) form.name.focus();
  }

  form.addEventListener("submit", (e) => {
    const name = form.name.value.trim();
    if (!name) { e.preventDefault(); return; }
    const data = { name, query: form.query.value.trim() || name, memo: form.memo.value.trim() };
    if (editing) Object.assign(editing, data);
    else items.unshift({ id: uid(), opened: null, ...data });
    save(); renderList();
  });
  $("#delete-btn").addEventListener("click", () => {
    if (!editing || !confirm(`'${editing.name}'을(를) 목록에서 지울까요?`)) return;
    items = items.filter((x) => x.id !== editing.id);
    save(); dialog.close(); renderList();
  });
  $("#cancel-btn").addEventListener("click", () => dialog.close());
  $("#add-btn").addEventListener("click", () => openDialog(null));
  $("#filter").addEventListener("input", renderList);

  // ---------------- 메뉴: 기본 사이트 / 백업 ----------------
  const menu = $("#menu-dialog");
  function renderSiteChoice() {
    const box = $("#main-site");
    box.innerHTML = "";
    for (const s of SITES) {
      const label = document.createElement("label");
      label.className = "radio";
      const input = document.createElement("input");
      input.type = "radio"; input.name = "main-site"; input.value = s.id;
      input.checked = settings.mainSite === s.id;
      input.addEventListener("change", () => {
        settings.mainSite = s.id;
        storageSet(SETTINGS_KEY, settings);
        renderList();
      });
      const text = document.createElement("span");
      text.innerHTML = "<b></b> <span class=\"hint\"></span>";
      text.querySelector("b").textContent = s.name;
      text.querySelector(".hint").textContent = s.note;
      label.append(input, text);
      box.append(label);
    }
  }
  const naverAppBox = $("#naver-app");
  naverAppBox.addEventListener("change", () => {
    settings.naverApp = naverAppBox.checked;
    storageSet(SETTINGS_KEY, settings);
    renderList();
  });
  $("#toast-close").addEventListener("click", () => { $("#toast").hidden = true; });

  $("#menu-btn").addEventListener("click", () => {
    renderSiteChoice();
    naverAppBox.checked = settings.naverApp;
    menu.showModal();
  });
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
          id: uid(),
          name: x.name.trim().slice(0, 40),
          query: String(x.query || x.name).trim().slice(0, 100),
          memo: String(x.memo || "").slice(0, 100),
          opened: null,
        }));
      if (!confirm(`${clean.length}개 재료를 가져올까요? 지금 목록은 바뀝니다.`)) return;
      items = clean; save(); renderList(); menu.close();
    } catch {
      alert("파일을 읽을 수 없습니다. 이 앱에서 내보낸 파일인지 확인하세요.");
    } finally {
      e.target.value = "";
    }
  });

  renderList();
})();
