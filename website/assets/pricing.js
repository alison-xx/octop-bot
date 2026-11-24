/* Octop Bot website — pricing page. Plans and packs come from data/pricing.json (the finalized
   prices); model prices come live from Lynxce's public catalog, with data/pricing-catalog.json as
   the fallback. Everything is built with DOM nodes and textContent. */
(() => {
  "use strict";

  const root = document.documentElement;
  const $ = (sel) => document.querySelector(sel);
  const CATALOG_URL = "https://api.lynxce.cn/api/models/pricing-catalog";
  const VIDEO_SECONDS = 6;
  const PERK_LABELS = {
    cloudBots: ["协同 Bot", "Cloud Bots"],
    groups: ["群聊", "Group chats"],
    devices: ["同步设备", "Synced devices"],
    computers: ["云电脑", "Cloud computers"],
    storage: ["云端文件", "Cloud files"],
    schedules: ["定时任务", "Scheduled tasks"],
    priority: ["排队优先", "Priority"],
    support: ["支持", "Support"],
  };

  /* Brand marks, the same files the apps use. DeepSeek shows the generic mark, as in the Bot apps;
     brands without a file get their first letter. */
  const BRAND_ICONS = [
    [/qwen|通义|千问|dashscope|阿里/i, "dashscope.png"],
    [/glm|智谱|zhipu/i, "zhipu.png"],
    [/kimi|月之暗面|moonshot/i, "moonshot.webp"],
    [/minimax|海螺/i, "minimax.png"],
    [/豆包|doubao|seed|字节|火山|volc/i, "volces.svg"],
    [/openai|gpt/i, "openai.png"],
    [/deepseek/i, "custom-provider.svg"],
  ];
  const brandIcon = (...names) => {
    const text = names.filter(Boolean).join(" ");
    const hit = BRAND_ICONS.find(([re]) => re.test(text));
    if (hit) {
      const img = document.createElement("img");
      img.className = "model-icon";
      img.src = "assets/models/" + hit[1];
      img.alt = "";
      img.width = 20;
      img.height = 20;
      img.loading = "lazy";
      return img;
    }
    const letter = document.createElement("span");
    letter.className = "model-icon letter";
    letter.textContent = (names.find(Boolean) || "?").trim().charAt(0).toUpperCase();
    letter.setAttribute("aria-hidden", "true");
    return letter;
  };

  const en = () => root.dataset.lang === "en";
  const t = (zh, enText) => (en() ? enText : zh);
  const pick = (value) => (value && typeof value === "object" ? (en() ? value.en : value.zh) : String(value ?? ""));
  const num = (n) => Number(n).toLocaleString("en-US");
  const money = (n) => "¥" + num(n);
  const node = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };

  let pricing = null;
  let catalog = null;
  let cycle = "month";
  let pack = 50;
  let customAmount = "";

  /* ---------- media unit prices (the default image and video models are the first listed) ---------- */
  function media() {
    const image = catalog?.imageModels?.[0];
    const video = catalog?.videoModels?.[0];
    return {
      imageName: image?.displayName || "",
      perImage: Number(image?.pricing?.creditsPerImage) || 0,
      videoName: video?.displayName || "",
      perSecond: Number(video?.pricing?.unitCredits) || 0,
      tiers: video?.pricing?.videoPricingTiers || {},
    };
  }

  /* ---------- plans ---------- */
  function perkRow(label, value) {
    const li = node("li");
    li.append(node("span", "", label), node("b", "", value));
    return li;
  }

  function renderPlans() {
    const box = $("#plans");
    if (!box || !pricing) return;
    const m = media();
    box.replaceChildren(
      ...pricing.plans.map((plan) => {
        const card = node("article", "plan" + (plan.tag ? " hot" : ""));
        if (plan.tag) card.append(node("span", "tag", pick(plan.tag)));
        card.append(node("h3", "", pick(plan.name)));

        const amount = node("div", "amount");
        const yearly = cycle === "year" && plan.yearly;
        amount.append(document.createTextNode(plan.monthly === 0 ? "¥0" : money(yearly ? plan.yearly : plan.monthly)));
        if (plan.monthly) amount.append(node("small", "", yearly ? t("/年", "/yr") : t("/月", "/mo")));
        card.append(amount);

        const renew = node("div", "renew");
        if (plan.monthly === 0) renew.textContent = t("免费", "Free");
        else if (yearly) {
          renew.append(
            node("s", "", money(plan.monthly * 12)),
            document.createTextNode(
              " · " + t(`折合 ${money(Math.round(plan.yearly / 12))}/月`, `${money(Math.round(plan.yearly / 12))}/mo`) +
                " · " + t("手动续费", "renew by hand"),
            ),
          );
        } else renew.textContent = t("到期前 3 天提醒，手动续费", "Reminder 3 days before it ends; renew by hand");
        card.append(renew);

        const credits = node("div", "credits");
        const main = node("div", "row");
        if (plan.creditsNote) main.append(node("span", "", "✦ " + pick(plan.creditsNote)));
        else {
          main.append(node("span", "", "✦ " + t(`${num(plan.credits)} 积分每月`, `${num(plan.credits)} credits a month`)));
          main.append(node("em", "", t("1 个月有效", "valid 1 month")));
        }
        credits.append(main);
        if (plan.bonus) credits.append(node("div", "row gift", "🎁 " + pick(plan.bonus)));
        card.append(credits);

        const button = node("a", "btn " + (plan.tag ? "btn-primary" : "btn-ghost"));
        if (plan.monthly === 0) {
          button.textContent = t("免费开始", "Start free");
          button.href = "https://bot.lynxce.cn";
        } else if (pricing.membershipOpen) {
          button.textContent = t(`开通${pick(plan.name)}版`, `Get ${pick(plan.name)}`);
          button.href = "#";
        } else {
          button.textContent = t("即将开通", "Coming soon");
          button.setAttribute("aria-disabled", "true");
          button.classList.add("disabled");
        }
        card.append(button);

        const perks = node("ul", "perks");
        perks.append(perkRow(t("文本模型", "Text models"), t("全部可用模型", "All available models")));
        const images = m.perImage ? Math.floor(plan.credits / m.perImage) : null;
        const videos = m.perSecond ? Math.floor(plan.credits / (m.perSecond * VIDEO_SECONDS)) : null;
        perks.append(
          perkRow(
            t("作图", "Images"),
            pick(plan.image) + (images !== null ? t(` · 约 ${num(images)} 张`, ` · about ${num(images)}`) : ""),
          ),
          perkRow(
            t("做视频", "Videos"),
            pick(plan.video) +
              (videos !== null
                ? t(` · 约 ${num(videos)} 条 ${VIDEO_SECONDS} 秒视频`, ` · about ${num(videos)} × ${VIDEO_SECONDS}s`)
                : ""),
          ),
        );
        for (const [key, value] of plan.perks) {
          const row = perkRow(t(...PERK_LABELS[key]), pick(value));
          if (key === "support" && value && value.zh === "社群") {
            // Opens the WeChat community QR (site.js handles [data-community]).
            const join = node("button", "link-btn", pick(value));
            join.type = "button";
            join.dataset.community = "";
            row.querySelector("b").replaceChildren(join);
          }
          perks.append(row);
        }
        perks.append(perkRow(t("本机 Bot", "Local Bots"), t("不限、不扣积分", "Unlimited, no credits")));
        card.append(perks);
        return card;
      }),
    );
    const note = $("#plans-note");
    if (note) {
      note.textContent = m.imageName
        ? t(
            `月度积分 1 个月有效，年付一次付清、积分按月到账。作图和视频数量按当前默认模型（作图 ${m.imageName}，视频 ${m.videoName}）的单价换算，以实际消耗为准。`,
            `Monthly credits last one month; yearly plans are paid once and credits arrive monthly. Image and video counts use the current default models (${m.imageName}, ${m.videoName}) and are estimates.`,
          )
        : t("月度积分 1 个月有效，年付一次付清、积分按月到账。", "Monthly credits last one month; yearly plans are paid once and credits arrive monthly.");
    }
    document.querySelectorAll("#cycle button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.cycle === cycle)));
  }

  /* ---------- packs ---------- */
  function renderPacks() {
    const box = $("#packs");
    if (!box || !pricing) return;
    box.replaceChildren(
      ...pricing.packs.map((yuan) => {
        const b = node("button", "pack");
        b.type = "button";
        b.dataset.yuan = String(yuan);
        b.setAttribute("aria-pressed", String(!customAmount && yuan === pack));
        b.append(node("b", "", money(yuan)), node("span", "", "✦ " + t(`${num(yuan * pricing.creditsPerYuan)} 积分`, `${num(yuan * pricing.creditsPerYuan)} credits`)));
        return b;
      }),
    );
    const { min, max } = pricing.customPack;
    const custom = Number(customAmount);
    const customOk = customAmount !== "" && Number.isInteger(custom) && custom >= min && custom <= max;
    const yuan = customAmount ? (customOk ? custom : null) : pack;
    $("#pack-price").textContent = yuan === null ? "—" : money(yuan);
    $("#pack-credits").textContent = yuan === null ? "—" : t(`${num(yuan * pricing.creditsPerYuan)} 积分`, `${num(yuan * pricing.creditsPerYuan)} credits`);
    $("#pack-days").textContent = t(`${pricing.packValidDays} 天`, `${pricing.packValidDays} days`);
    $("#custom-hint").textContent =
      customAmount && !customOk
        ? t(`请输入 ${min}–${num(max)} 之间的整数`, `Enter a whole number from ${min} to ${num(max)}`)
        : "";
    const buy = $("#pack-buy");
    if (pricing.packsOpen && yuan !== null) {
      buy.textContent = t(`${money(yuan)} 立即购买`, `Buy for ${money(yuan)}`);
      buy.removeAttribute("aria-disabled");
      buy.classList.remove("disabled");
    } else {
      buy.textContent = t("即将开通", "Coming soon");
      buy.setAttribute("aria-disabled", "true");
      buy.classList.add("disabled");
    }
  }

  /* ---------- unit prices and model price table ---------- */
  let modelTab = "text";
  function renderRates() {
    if (!pricing) return;
    const m = media();
    const r = pricing.rates;
    const rates = [
      [t("文本对话", "Text"), t("按模型价目，每百万 token 计", "Per million tokens, by model")],
      [t("作图", "Images"), m.perImage ? t(`${m.imageName}：${m.perImage} 积分/张`, `${m.imageName}: ${m.perImage} credits per image`) : "—"],
      [
        t("做视频", "Videos"),
        m.perSecond
          ? t(`${m.videoName}：768p ${m.perSecond} 积分/秒`, `${m.videoName}: ${m.perSecond} credits per second at 768p`) +
            (m.tiers["1080p"] ? t(`，1080p ${m.tiers["1080p"]} 积分/秒`, `, ${m.tiers["1080p"]} at 1080p`) : "")
          : "—",
      ],
      [t("云电脑", "Cloud computer"), t(`标准 ${r.computerStandardPerMinute} 积分/分钟，专业 ${r.computerProPerMinute} 积分/分钟`, `Standard ${r.computerStandardPerMinute}, Pro ${r.computerProPerMinute} credits per minute`)],
      [t("云电脑磁盘", "Computer disk"), t(`${r.diskPerGbDay} 积分/GB·天`, `${r.diskPerGbDay} credits per GB per day`)],
    ];
    $("#rates").replaceChildren(
      ...rates.map(([name, text]) => {
        const div = node("div", "rate");
        div.append(node("b", "", name), node("span", "", text));
        return div;
      }),
    );
    document.querySelectorAll("#model-tabs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tab === modelTab)));
    const head = $("#model-head");
    const body = $("#model-body");
    const cells = (brand, ...values) => {
      const tr = node("tr");
      tr.append(
        ...values.map((v, i) => {
          const td = node("td", i ? "num" : "model-name");
          if (i === 0) td.append(brandIcon(...brand), document.createTextNode(v));
          else td.textContent = v;
          return td;
        }),
      );
      return tr;
    };
    const perMillion = (v) => (typeof v === "number" ? num(Math.round(v * 1000 * 100) / 100) : "—");
    if (modelTab === "text") {
      head.replaceChildren(...[t("模型", "Model"), t("输入 / 百万 token", "Input / 1M tokens"), t("输出 / 百万 token", "Output / 1M tokens")].map((h) => node("th", "", h)));
      body.replaceChildren(
        ...(catalog?.textModels || []).map((x) =>
          cells([x.providerLabel, x.modelName], `${x.modelName || ""}${x.providerLabel ? " · " + x.providerLabel : ""}`, perMillion(x.creditsPerKInputTokens), perMillion(x.creditsPerKOutputTokens)),
        ),
      );
    } else if (modelTab === "image") {
      head.replaceChildren(...[t("模型", "Model"), t("积分 / 张", "Credits / image")].map((h) => node("th", "", h)));
      body.replaceChildren(...(catalog?.imageModels || []).map((x) => cells([x.provider, x.displayName], x.displayName || "", x.pricing?.creditsPerImage != null ? String(x.pricing.creditsPerImage) : "—")));
    } else {
      head.replaceChildren(...[t("模型", "Model"), t("积分 / 秒（按分辨率）", "Credits / second (by resolution)")].map((h) => node("th", "", h)));
      body.replaceChildren(
        ...(catalog?.videoModels || []).map((x) => {
          const tiers = x.pricing?.videoPricingTiers;
          const text = tiers ? Object.entries(tiers).map(([res, v]) => `${res} ${v}`).join(" · ") : x.pricing?.unitCredits != null ? String(x.pricing.unitCredits) : "—";
          return cells([x.provider, x.displayName], x.displayName || "", text);
        }),
      );
    }
  }

  function renderAll() {
    renderPlans();
    renderPacks();
    renderRates();
  }

  /* ---------- views: plans or packs ---------- */
  const VIEW_HASH = { plans: "", packs: "#credits", enterprise: "#enterprise" };
  function showView(view) {
    document.querySelectorAll("#price-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === view)));
    for (const name of Object.keys(VIEW_HASH)) $("#v-" + name).hidden = name !== view;
  }

  document.addEventListener("click", (e) => {
    const tab = e.target.closest("#price-tabs button");
    if (tab) {
      showView(tab.dataset.view);
      history.replaceState(null, "", VIEW_HASH[tab.dataset.view] || location.pathname + location.search);
    }
    const c = e.target.closest("#cycle button");
    if (c) {
      cycle = c.dataset.cycle;
      renderPlans();
    }
    const p = e.target.closest(".pack");
    if (p) {
      pack = Number(p.dataset.yuan);
      customAmount = "";
      $("#custom-amount").value = "";
      renderPacks();
    }
    const m = e.target.closest("#model-tabs button");
    if (m) {
      modelTab = m.dataset.tab;
      renderRates();
    }
    if (e.target.closest("a.disabled")) e.preventDefault();
  });
  $("#custom-amount")?.addEventListener("input", (e) => {
    customAmount = e.target.value.trim();
    renderPacks();
  });
  document.addEventListener("langchange", renderAll);
  showView(location.hash === "#credits" ? "packs" : location.hash === "#enterprise" ? "enterprise" : "plans");

  const getJson = (url, timeoutMs = 8000) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    return fetch(url, { cache: "no-cache", signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .finally(() => clearTimeout(timer));
  };
  // Plans render as soon as the finalized prices arrive; image and video counts fill in when the
  // model prices do (live, or the bundled copy if Lynxce is slow or unreachable).
  getJson("data/pricing.json").then((plans) => {
    pricing = plans;
    renderAll();
  });
  getJson(CATALOG_URL, 5000)
    .then((body) => (body && body.code === 0 && body.data ? body.data : Promise.reject("bad")))
    .catch(() => getJson("data/pricing-catalog.json").then((body) => body.data))
    .then((models) => {
      catalog = models;
      renderAll();
    })
    .catch(() => {});
})();
