/* Bot market: list and detail views from market/catalog.json (exported from the app). */
(() => {
  const WEB_APP = "https://bot.lynxce.cn/octop-bot/market/";
  const DESKTOP = "octop-bot://market/";
  const root = document.documentElement;
  const $ = (s, el = document) => el.querySelector(s);
  const homeParts = document.querySelectorAll("[data-market-home]");
  const list = $(".market-list");
  const detail = $(".market-detail");
  const tabs = $(".market-tabs");
  const search = $(".market-search input");
  const dialog = $(".market-dialog");
  let data = null;
  let tab = "all";

  const lang = () => (root.dataset.lang === "en" ? "en" : "zh");
  const tx = (v) => (v && typeof v === "object" ? v[lang()] : v || "");
  const t = (zh, en) => (lang() === "en" ? en : zh);
  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const PALETTE = {
    red: "#ff6b5e", orange: "#ff9a3c", green: "#3fcf8e", blue: "#4b9dff", violet: "#9b7bff",
    yellow: "#ffd23f", cyan: "#2ec5d3", magenta: "#e2589c", brown: "#b07a4f", gray: "#9a9a9a",
    rose: "#ff7d9c", sky: "#7cc4ff", tangerine: "#ff8a3d", cobalt: "#3a5bff", charcoal: "#45464c",
  };

  function avatar(tpl, size) {
    if (tpl.avatar)
      return `<span class="m-avatar" style="--s:${size}px"><img src="${esc(tpl.avatar)}" alt="" loading="lazy" width="${size}" height="${size}"></span>`;
    const c = PALETTE[tpl.look.color] || tpl.look.color;
    return `<span class="m-avatar" style="--s:${size}px"><i style="background:${esc(c)}"></i></span>`;
  }

  function card(tpl) {
    return `<article class="m-card">
      <a class="m-card-main" href="?bot=${encodeURIComponent(tpl.slug)}" data-open="${esc(tpl.slug)}">
        ${avatar(tpl, 60)}
        <span class="m-card-text">
          <strong>${esc(tx(tpl.name))}</strong>
          <small>${t("Octop Bot 官方", "By Octop Bot")}</small>
          <span>${esc(tx(tpl.tagline))}</span>
        </span>
      </a>
      <button class="btn btn-ghost btn-sm m-add" type="button" data-add="${esc(tpl.slug)}" aria-label="${esc(t("添加 ", "Add ") + tx(tpl.name))}">${t("添加", "Add")}</button>
    </article>`;
  }

  function grid(items) {
    return `<div class="m-grid">${items.map(card).join("")}</div>`;
  }

  function renderTabs() {
    const items = [
      { id: "all", name: t("全部", "All") },
      { id: "featured", name: t("精选", "Featured") },
      ...data.categories.map((c) => ({ id: c.id, name: tx(c.name) })),
    ];
    tabs.innerHTML = items
      .map(
        (c) =>
          `<button type="button" role="tab" class="m-tab" data-tab="${c.id}" aria-selected="${c.id === tab}">${esc(c.name)}</button>`,
      )
      .join("");
  }

  function renderList() {
    const q = search.value.trim().toLowerCase();
    const shown = data.templates.filter(
      (x) =>
        !q ||
        [x.name.zh, x.name.en, x.tagline.zh, x.tagline.en].some((s) => s.toLowerCase().includes(q)),
    );
    if (!shown.length) {
      list.innerHTML = `<p class="m-empty">${t("没有找到匹配的 Bot。", "No Bots match your search.")}</p>`;
      return;
    }
    if (q) {
      list.innerHTML = `<section class="m-block">${grid(shown)}</section>`;
      return;
    }
    let html = "";
    if (tab === "all" || tab === "featured") {
      html += `<section class="m-block"><header><h2 class="h2">${t("精选", "Featured")}</h2><p>${t(
        "Octop Bot 团队挑出来的几个常用岗位。",
        "A few common roles picked by the Octop Bot team.",
      )}</p></header>${grid(shown.filter((x) => x.featured))}</section>`;
    }
    if (tab !== "featured") {
      for (const c of data.categories) {
        if (tab !== "all" && tab !== c.id) continue;
        const items = shown.filter((x) => x.category === c.id);
        if (items.length)
          html += `<section class="m-block" id="${c.id}"><header><h2 class="h2">${esc(tx(c.name))}</h2><p>${esc(
            tx(c.blurb),
          )}</p></header>${grid(items)}</section>`;
      }
    }
    list.innerHTML = html;
  }

  function section(icon, title, hint, body) {
    return `<section class="m-section"><h2>${icon}${esc(title)}</h2>${hint ? `<p class="m-hint">${esc(hint)}</p>` : ""}${body}</section>`;
  }
  const ul = (items) => `<ul>${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>`;
  const ICON = {
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/></svg>',
    rules: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 7 2 2 4-4M3 17l2 2 4-4M13 6h8M13 12h8M13 18h8"/></svg>',
    memory: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5V5a2 2 0 0 1 2-2h14v16H6.5a2.5 2.5 0 0 0 0 5H20"/></svg>',
    skill: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    plug: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/></svg>',
  };

  function renderDetail(slug) {
    const x = data.templates.find((v) => v.slug === slug);
    if (!x) {
      detail.innerHTML = `<p class="m-empty">${t("没有这个 Bot。", "This Bot doesn't exist.")} <a class="link" href="market.html">${t("返回 Bot 市场", "Back to the Bot Market")}</a></p>`;
      return;
    }
    document.title = `${tx(x.name)} · ${t("Bot 市场", "Bot Market")} · Octop Bot`;
    const cat = data.categories.find((c) => c.id === x.category);
    const parts = [
      section(ICON.chat, t("可以这样开始", "Ways to start"), "", `<div class="m-starters">${tx(x.starters).map((s) => `<span>${esc(s)}</span>`).join("")}</div>`),
      section(ICON.rules, t("工作守则", "Working rules"), "", `<p class="m-role">${esc(tx(x.role))}</p>${ul(tx(x.instructions))}`),
      section(ICON.memory, t("已经知道的事", "What it already knows"), t("导入后写进这个 Bot 的记忆，每次对话都会参考。", "Written into the Bot's memory and used in every conversation."), ul(tx(x.memories))),
    ];
    if (x.skills.length)
      parts.push(
        section(
          ICON.skill,
          t("技能", "Skills"),
          t("遇到对应的事情时按这些步骤做。", "Playbooks it follows for these jobs."),
          x.skills
            .map(
              (s) =>
                `<details class="m-item"><summary><strong>${esc(tx(s.name))}</strong><span>${esc(tx(s.summary))}</span></summary><div class="m-steps">${esc(tx(s.body))}</div></details>`,
            )
            .join(""),
        ),
      );
    if (x.routines.length)
      parts.push(
        section(
          ICON.clock,
          t("例行任务", "Routines"),
          t("定时自动运行，导入时可以逐个选择开不开。", "Run on a schedule; choose which to turn on when you import."),
          x.routines
            .map((r) => `<div class="m-item"><strong>${esc(tx(r.name))} <em>${esc(tx(r.when))}</em></strong><span>${esc(tx(r.prompt))}</span></div>`)
            .join(""),
        ),
      );
    if (x.integrations.length)
      parts.push(
        section(
          ICON.plug,
          t("建议连接", "Suggested connections"),
          t("连接后能直接读写对应的应用，不连接也能用。", "Connect these so it can work in those apps directly. It works without them too."),
          `<div class="m-chips">${x.integrations.map((i) => `<span><i style="background:${esc(i.color || "")}"></i>${esc(tx(i.name))}</span>`).join("")}</div>`,
        ),
      );
    detail.innerHTML = `
      <a class="m-back link" href="market.html" data-home>← ${t("Bot 市场", "Bot Market")}</a>
      <div class="m-hero">
        ${avatar(x, 120)}
        <div>
          <span class="eyebrow">${esc(tx(cat && cat.name))}</span>
          <h1 class="h2">${esc(tx(x.name))}</h1>
          <small>${t("Octop Bot 官方", "By Octop Bot")}</small>
          <p class="m-tagline">${esc(tx(x.tagline))}</p>
          <p>${esc(tx(x.description))}</p>
          <div class="m-actions">
            <button class="btn btn-primary" type="button" data-add="${esc(x.slug)}">${t("导入到 Octop Bot", "Import into Octop Bot")}</button>
          </div>
        </div>
      </div>
      <div class="m-sections">${parts.join("")}</div>`;
  }

  function route() {
    const slug = new URLSearchParams(location.search).get("bot");
    homeParts.forEach((el) => (el.hidden = Boolean(slug)));
    detail.hidden = !slug;
    if (slug) renderDetail(slug);
    else {
      document.title = t("Bot 市场 · Octop Bot", "Bot Market · Octop Bot");
      renderTabs();
      renderList();
    }
  }

  function go(url) {
    history.pushState(null, "", url);
    route();
    window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
  }

  function openImport(slug) {
    const x = data.templates.find((v) => v.slug === slug);
    if (!x) return;
    $(".market-dialog-head").innerHTML = `${avatar(x, 52)}<strong>${esc(tx(x.name))}</strong>`;
    $('[data-target="web"]').href = WEB_APP + encodeURIComponent(slug) + "/import";
    $('[data-target="desktop"]').href = DESKTOP + encodeURIComponent(slug);
    if (dialog.showModal) dialog.showModal();
    else location.href = WEB_APP + encodeURIComponent(slug) + "/import";
  }

  document.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]");
    if (add) {
      e.preventDefault();
      openImport(add.dataset.add);
      return;
    }
    const open = e.target.closest("[data-open]");
    if (open && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      go("?bot=" + encodeURIComponent(open.dataset.open));
      return;
    }
    if (e.target.closest("[data-home]") && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      go("market.html");
      return;
    }
    const tb = e.target.closest("[data-tab]");
    if (tb) {
      tab = tb.dataset.tab;
      renderTabs();
      renderList();
    }
  });
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close();
    if (e.target.closest(".market-choice")) setTimeout(() => dialog.close(), 300);
  });
  search.addEventListener("input", renderList);
  window.addEventListener("popstate", route);
  document.addEventListener("langchange", () => data && route());

  fetch("market/catalog.json?v=1")
    .then((r) => r.json())
    .then((json) => {
      data = json;
      route();
    })
    .catch(() => {
      list.innerHTML = `<p class="m-empty">${t("Bot 市场暂时打不开，请稍后再试。", "The Bot Market couldn't load. Please try again later.")}</p>`;
    });
})();
