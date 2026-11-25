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

  /* Brand marks: the same table and files as Lynxce's apps (keyword → assets/models/<brand>.svg).
     Longer keywords win; short ones must start a word; the display name is checked before the id. */
  const BRANDS = [
    ["deepseek", ["deepseek"]],
    ["qwen", ["qwen", "通义", "tongyi", "wan", "万相", "z-image", "zimage"]],
    ["glm", ["glm", "智谱", "zhipu", "cogview", "cogvideo"]],
    ["kimi", ["kimi", "moonshot"]],
    ["minimax", ["minimax"]],
    ["hailuo", ["hailuo", "海螺"]],
    ["doubao", ["doubao", "豆包", "seedream", "seedance", "seededit"]],
    ["jimeng", ["jimeng", "即梦"]],
    ["anthropic", ["claude"]],
    ["openai", ["gpt-image", "gpt", "openai", "o1", "o3", "o4", "dall-e"]],
    ["sora", ["sora"]],
    ["gemini", ["gemini", "nano banana", "nano-banana", "veo", "imagen"]],
    ["kling", ["kling", "可灵"]],
    ["vidu", ["vidu"]],
    ["agnes", ["agnes"]],
    ["grok", ["grok"]],
    ["xiaomi", ["mimo", "xiaomi"]],
    ["hunyuan", ["hy3", "hunyuan", "混元"]],
    ["happyhorse", ["happyhorse"]],
    ["midjourney", ["midjourney", "mj"]],
    ["suno", ["suno"]],
    ["flux", ["flux", "bfl"]],
    ["ideogram", ["ideogram"]],
    ["recraft", ["recraft"]],
    ["runway", ["runway", "gen-3", "gen-4"]],
    ["pika", ["pika"]],
    ["luma", ["luma", "ray", "dream machine"]],
    ["stability", ["stable diffusion", "sd3", "sdxl", "stability"]],
    ["pixverse", ["pixverse", "爱诗"]],
  ];
  const BRAND_RULES = BRANDS.flatMap(([brand, keys]) => keys.map((key) => ({ key, brand }))).sort((a, b) => b.key.length - a.key.length);
  const WORD_START_KEYS = new Set(["o1", "o3", "o4", "wan", "veo", "hy3", "mj", "ray", "sd3", "bfl"]);
  /* Black marks get a white tile in dark mode. */
  const DARK_MARKS = new Set(["openai", "grok", "flux", "midjourney", "pika", "runway", "recraft", "ideogram", "suno", "kimi", "agnes"]);
  const keyMatches = (key, text) => {
    if (!WORD_START_KEYS.has(key)) return text.includes(key);
    for (let from = 0; ; ) {
      const at = text.indexOf(key, from);
      if (at < 0) return false;
      if (at === 0 || !/[\p{L}\p{N}]/u.test(text[at - 1])) return true;
      from = at + key.length;
    }
  };
  /* Brand of a model from its display name, then its id, then the provider label. */
  const modelBrand = (...texts) => {
    for (const raw of texts) {
      const text = String(raw || "").toLowerCase();
      if (!text) continue;
      const rule = BRAND_RULES.find((r) => keyMatches(r.key, text));
      if (rule) return rule.brand;
    }
    return texts.join(" ").toLowerCase().includes("google") ? "google" : null;
  };
  const brandIcon = (...texts) => {
    const brand = modelBrand(...texts);
    const mark = document.createElement("span");
    mark.setAttribute("aria-hidden", "true");
    if (!brand) {
      mark.className = "model-icon letter";
      const name = String(texts.find(Boolean) || "");
      mark.textContent = ([...name].find((c) => /[\p{L}\p{N}]/u.test(c)) || "AI").toUpperCase();
      return mark;
    }
    mark.className = "model-icon" + (DARK_MARKS.has(brand) ? " dark-mark" : "");
    const img = document.createElement("img");
    img.src = `assets/models/${brand}.svg`;
    img.alt = "";
    img.width = 20;
    img.height = 20;
    img.loading = "lazy";
    mark.append(img);
    return mark;
  };

  /* The catalog lists a model once per route (supplier or compatible entry). The table shows it once,
     grouped by brand; its routes become 线路 1/2/3, most capable first, then cheapest upstream. */
  const nameKey = (name) => String(name || "").toLowerCase().replace(/[\s\-_]+/g, " ").trim();
  const isCompat = (m) => /兼容入口/.test(m.modelName || "");
  const costRank = (m) => (typeof m.routeCostRank === "number" && m.routeCostRank >= 0 ? m.routeCostRank : Infinity);
  const capability = (m) => (m.supportsImage ? 1 : 0) + (m.supportsThinking ? 1 : 0);
  const compareRoutes = (a, b) =>
    Number(isCompat(a)) - Number(isCompat(b)) || capability(b) - capability(a) || (costRank(a) === costRank(b) ? 0 : costRank(a) < costRank(b) ? -1 : 1);
  const routeKey = (route) => route.routeId || route.modelId;
  function groupTextModels(models) {
    const families = new Map();
    const choices = new Map();
    for (const m of models) {
      if (m.accessible === false) continue;
      const family = modelBrand(m.modelName, m.modelId, m.providerLabel) || "other";
      const key = family + "\u0000" + nameKey(m.modelName);
      let choice = choices.get(key);
      if (!choice) {
        choice = { key, name: m.modelName || m.modelId || "", routes: [] };
        choices.set(key, choice);
        if (!families.has(family)) families.set(family, []);
        families.get(family).push(choice);
      }
      choice.routes.push(m);
    }
    const out = [];
    for (const [family, list] of families) if (family !== "other") out.push(...list);
    out.push(...(families.get("other") || []));
    for (const choice of out) choice.routes.sort(compareRoutes);
    return out;
  }
  /* Which route each merged row shows, by row key (kept across language and tab switches). */
  const routePick = new Map();

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
  let liveCatalog = false;
  let ratesVisible = false;
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

  function updateBilling(card, plan) {
    const amount = card.querySelector(".amount");
    const renew = card.querySelector(".renew");
    const yearly = cycle === "year" && plan.yearly;
    amount.replaceChildren(node("span", "currency", "¥"), node("strong", "", num(yearly ? plan.yearly : plan.monthly)));
    if (plan.monthly) amount.append(node("small", "", yearly ? t("/年", "/yr") : t("/月", "/mo")));
    if (!plan.monthly) renew.textContent = t("免费", "Free");
    else if (yearly) {
      renew.replaceChildren(node("s", "", money(plan.monthly * 12)), document.createTextNode(
        " · " + t(`折合 ${money(Math.round(plan.yearly / 12))}/月`, `${money(Math.round(plan.yearly / 12))}/mo`) +
        " · " + t("手动续费", "renew by hand"),
      ));
    } else renew.textContent = t("到期前 3 天提醒，手动续费", "Reminder 3 days before it ends; renew by hand");
  }

  function renderPlans() {
    const box = $("#plans");
    if (!box || !pricing) return;
    const expanded = new Set([...box.querySelectorAll("details[open]")].map((details) => details.dataset.plan));
    box.replaceChildren(
      ...pricing.plans.map((plan) => {
        const card = node("article", "plan" + (plan.tag ? " hot" : ""));
        const header = node("div", "plan-heading");
        header.append(node("h3", "", pick(plan.name)));
        if (plan.tag) header.append(node("span", "tag", pick(plan.tag)));
        card.append(header);

        card.append(node("div", "amount"), node("div", "renew"));
        updateBilling(card, plan);

        const credits = node("div", "credits");
        const main = node("div", "row");
        if (plan.creditsNote) main.append(node("span", "", pick(plan.creditsNote)));
        else {
          main.append(node("span", "", t(`每月 ${num(plan.credits)} 积分`, `${num(plan.credits)} credits a month`)));
          main.append(node("em", "", t("1 个月有效", "valid 1 month")));
        }
        credits.append(main);
        if (plan.bonus) credits.append(node("div", "row gift", pick(plan.bonus)));
        card.append(credits);

        const button = node(plan.monthly === 0 ? "a" : "button", "btn " + (plan.tag ? "btn-primary" : "btn-ghost"));
        if (plan.monthly === 0) {
          button.textContent = t("免费开始", "Start free");
          button.href = "https://bot.lynxce.cn";
        } else {
          button.type = "button";
          button.disabled = !(pricing.membershipOpen && window.OctopAuth.config.checkoutEnabled);
          button.dataset.checkout = "member";
          if (button.disabled) button.classList.add("disabled");
          button.textContent = button.disabled
            ? t("即将开通", "Coming soon")
            : t("去收银台选套餐", "Choose a plan at checkout");
        }
        card.append(button);

        const highlights = node("ul", "perks plan-highlights");
        const details = node("details", "plan-details");
        details.dataset.plan = plan.id;
        details.open = expanded.has(plan.id);
        details.append(node("summary", "", t("全部权益", "All benefits")));
        const perks = node("ul", "perks");
        perks.append(perkRow(t("文本模型", "Text models"), t("全部可用模型", "All available models")));
        const imageRow = perkRow(t("作图", "Images"), pick(plan.image));
        const videoRow = perkRow(t("做视频", "Videos"), pick(plan.video));
        imageRow.className = "plan-image";
        videoRow.className = "plan-video";
        perks.append(imageRow, videoRow);
        for (const [key, value] of plan.perks) {
          const row = perkRow(t(...PERK_LABELS[key]), pick(value));
          if (key === "support" && value && value.zh === "社群") {
            // Opens the WeChat community QR (site.js handles [data-community]).
            const join = node("button", "link-btn", pick(value));
            join.type = "button";
            join.dataset.community = "";
            row.querySelector("b").replaceChildren(join);
          }
          if (["cloudBots", "computers", "storage"].includes(key)) highlights.append(row);
          else perks.append(row);
        }
        perks.append(perkRow(t("本机 Bot", "Local Bots"), t("不限、不扣积分", "Unlimited, no credits")));
        details.append(perks);
        card.append(highlights, details);
        return card;
      }),
    );
    updateEstimates();
  }

  function updateEstimates() {
    if (!pricing) return;
    const m = media();
    document.querySelectorAll("#plans .plan").forEach((card, index) => {
      const plan = pricing.plans[index];
      const images = num(Math.floor(plan.credits / m.perImage));
      const videos = num(Math.floor(plan.credits / (m.perSecond * VIDEO_SECONDS)));
      card.querySelector(".plan-image b").textContent = pick(plan.image) +
        (m.perImage ? t(` · 约 ${images} 张`, ` · about ${images}`) : "");
      card.querySelector(".plan-video b").textContent = pick(plan.video) +
        (m.perSecond ? t(` · 约 ${videos} 条 ${VIDEO_SECONDS} 秒视频`, ` · about ${videos} × ${VIDEO_SECONDS}s`) : "");
    });
    updatePlanNote(m);
  }

  function updatePlanNote(m) {
    const note = $("#plans-note");
    if (note) {
      note.textContent = m.imageName
        ? t(
            `月度积分 1 个月有效，年付一次付清、积分按月到账。作图和视频数量按当前默认模型（作图 ${m.imageName}，视频 ${m.videoName}）的单价换算，以实际消耗为准。`,
            `Monthly credits last one month; yearly plans are paid once and credits arrive monthly. Image and video counts use the current default models (${m.imageName}, ${m.videoName}) and are estimates.`,
          )
        : t("月度积分 1 个月有效，年付一次付清、积分按月到账。", "Monthly credits last one month; yearly plans are paid once and credits arrive monthly.");
      note.textContent += " " + t("会员积分仅限 Octop 使用。", "Membership credits are for Octop Bot only.");
      if (cycle === "year") note.textContent += " " + t("年付升档请联系客服。", "Contact support to upgrade a yearly plan.");
    }
  }

  /* ---------- packs ---------- */
  function renderPacks() {
    const box = $("#packs");
    if (!box || !pricing) return;
    if (!box.childElementCount) box.append(
      ...pricing.packs.map((yuan) => {
        const b = node("button", "pack");
        b.type = "button";
        b.dataset.yuan = String(yuan);
        b.append(node("b", "", money(yuan)), node("span"));
        return b;
      }),
    );
    for (const button of box.children) {
      const amount = Number(button.dataset.yuan);
      const credits = num(amount * pricing.creditsPerYuan);
      button.setAttribute("aria-pressed", String(!customAmount && amount === pack));
      button.querySelector("span").textContent = t(`${credits} 积分`, `${credits} credits`);
    }
    const { min, max } = pricing.customPack;
    const custom = Number(customAmount);
    const customOk = customAmount !== "" && Number.isInteger(custom) && custom >= min && custom <= max;
    const yuan = customAmount ? (customOk ? custom : null) : pack;
    $("#pack-price").textContent = yuan === null ? "—" : money(yuan);
    $("#pack-credits").textContent = yuan === null ? "—" : t(`${num(yuan * pricing.creditsPerYuan)} 积分`, `${num(yuan * pricing.creditsPerYuan)} credits`);
    $("#pack-days").textContent = t("到账即用，可与会员叠加", "Ready right away; stacks with a membership");
    $("#custom-hint").textContent =
      customAmount && !customOk
        ? t(`请输入 ${min}–${num(max)} 之间的整数`, `Enter a whole number from ${min} to ${num(max)}`)
        : "";
    const buy = $("#pack-buy");
    const cfg = window.OctopAuth.config;
    // The custom amount shows only once Lynxce's cashier takes amountYuan.
    const customRow = $("#custom-amount")?.closest(".pack.custom");
    if (customRow) customRow.hidden = !cfg.checkoutAmount;
    // Until the cashier can preselect (packageId / amountYuan), the buyer picks the amount there.
    const preselect = customAmount ? cfg.checkoutAmount : cfg.checkoutPackageId;
    if (pricing.packsOpen && cfg.checkoutEnabled && yuan !== null) {
      buy.textContent = preselect
        ? t(`${money(yuan)} 立即购买`, `Buy for ${money(yuan)}`)
        : t("去收银台选择金额", "Choose an amount at checkout");
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
  // Lynxce publishes these amounts per million tokens already, for this specific route.
  function rateDescription(route) {
    let schedule = (route.description || "").split("峰谷计费：").slice(1).join("").trim();
    let prices = route.pricingDescription;
    if (en()) {
      prices = prices.replace(
        /^每百万 Token 积分价：空闲输入 ([\d.]+)、输出 ([\d.]+)、缓存命中 ([\d.]+)；高峰输入 ([\d.]+)、输出 ([\d.]+)、缓存命中 ([\d.]+)。$/,
        "Credits per million tokens. Off-peak input $1, output $2, cache hit $3. Peak input $4, output $5, cache hit $6.",
      );
      schedule = schedule
        .replace("中国法定节假日全天为空闲；", "Chinese public holidays are off-peak all day. ")
        .replace(/北京时间周一至周五 ([\d:–]+)、([\d:–]+) 为高峰，其余时间（含周末）为空闲。/, "Peak hours are Monday–Friday, $1 and $2 Beijing time. All other times, including weekends, are off-peak.")
        .replace("按每次调用开始时的时段计费。", " The rate is set when the call starts.");
    }
    return [prices, schedule].filter(Boolean).join(" ");
  }

  function renderRates() {
    if (!ratesVisible) return;
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
      [t("云电脑磁盘", "Computer disk"), t(`计费启用后为 ${r.diskPerGbDay} 积分/GB·天`, `When disk billing is enabled: ${r.diskPerGbDay} credits per GB per day`)],
    ];
    $("#rates").replaceChildren(
      ...rates.map(([name, text]) => {
        const div = node("div", "rate");
        div.append(node("b", "", name), node("span", "", text));
        return div;
      }),
    );
    document.querySelectorAll("#model-tabs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tab === modelTab)));
    $("#catalog-source").textContent = !catalog ? "" : liveCatalog
      ? t("灵策实时价目，表中单价为本次查询时的价格。", "Live Lynxce prices at the time of this lookup.")
      : t("灵策价目快照。表中单价为保存时的价格，分时线路按调用时适用的费率结算。", "Saved Lynxce prices. The table shows rates at the time of capture. Time-based rates apply when a call starts.");
    const head = $("#model-head");
    const body = $("#model-body");
    const cells = (brand, ...values) => {
      const tr = node("tr");
      tr.append(
        ...values.map((v, i) => {
          const td = node("td", i ? "num" : "model-name");
          if (i === 0) {
            const cell = node("div", "model-cell");
            cell.append(brandIcon(...brand), node("span", "", v));
            td.append(cell);
          }
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
        ...groupTextModels(catalog?.textModels || []).flatMap((choice) => {
          const route = choice.routes.find((r) => routeKey(r) === routePick.get(choice.key)) || choice.routes[0];
          const tr = cells([choice.name, route.modelId, route.providerLabel], choice.name, perMillion(route.creditsPerKInputTokens), perMillion(route.creditsPerKOutputTokens));
          if (choice.routes.length > 1) {
            const lines = node("span", "model-lines");
            lines.setAttribute("role", "group");
            lines.setAttribute("aria-label", t("线路", "Routes"));
            choice.routes.forEach((r, i) => {
              const b = node("button", "", t(`线路 ${i + 1}`, `Route ${i + 1}`));
              b.type = "button";
              b.dataset.choice = choice.key;
              b.dataset.route = routeKey(r);
              b.setAttribute("aria-pressed", String(r === route));
              b.title = t(
                `输入 ${perMillion(r.creditsPerKInputTokens)} · 输出 ${perMillion(r.creditsPerKOutputTokens)}${r.supportsImage ? " · 识图" : ""}${r.supportsThinking ? " · 思考" : ""}`,
                `Input ${perMillion(r.creditsPerKInputTokens)} · output ${perMillion(r.creditsPerKOutputTokens)}${r.supportsImage ? " · vision" : ""}${r.supportsThinking ? " · thinking" : ""}`,
              );
              lines.append(b);
            });
            tr.querySelector(".model-cell").append(lines);
          }
          if (!route.pricingDescription) return [tr];
          const detailRow = node("tr");
          const detail = node("td", "muted", rateDescription(route));
          detail.colSpan = 3;
          detailRow.append(detail);
          return [tr, detailRow];
        }),
      );
    } else if (modelTab === "image") {
      head.replaceChildren(...[t("模型", "Model"), t("积分 / 张", "Credits / image")].map((h) => node("th", "", h)));
      body.replaceChildren(...(catalog?.imageModels || []).map((x) => cells([x.displayName, x.modelId, x.provider], x.displayName || "", x.pricing?.creditsPerImage != null ? String(x.pricing.creditsPerImage) : "—")));
    } else {
      head.replaceChildren(...[t("模型", "Model"), t("积分 / 秒（按分辨率）", "Credits / second (by resolution)")].map((h) => node("th", "", h)));
      body.replaceChildren(
        ...(catalog?.videoModels || []).map((x) => {
          const tiers = x.pricing?.videoPricingTiers;
          const text = tiers ? Object.entries(tiers).map(([res, v]) => `${res} ${v}`).join(" · ") : x.pricing?.unitCredits != null ? String(x.pricing.unitCredits) : "—";
          return cells([x.displayName, x.modelId, x.provider], x.displayName || "", text);
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
  let currentView = null;
  function showView(view, animate = true) {
    const changed = currentView !== view;
    document.querySelectorAll("#price-tabs button").forEach((b) => {
      const selected = b.dataset.view === view;
      b.setAttribute("aria-selected", String(selected));
      b.tabIndex = selected ? 0 : -1;
    });
    for (const name of Object.keys(VIEW_HASH)) {
      const panel = $("#v-" + name);
      panel.hidden = name !== view;
      panel.classList.remove("pricing-enter");
      if (name === view && changed && animate) {
          panel.classList.add("pricing-enter");
      }
    }
    currentView = view;
  }

  document.addEventListener("click", (e) => {
    const tab = e.target.closest("#price-tabs button");
    if (tab) {
      showView(tab.dataset.view);
      history.replaceState(null, "", VIEW_HASH[tab.dataset.view] || location.pathname + location.search);
    }
    const c = e.target.closest("#cycle button");
    if (c && cycle !== c.dataset.cycle) {
      cycle = c.dataset.cycle;
      document.querySelectorAll("#cycle button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.cycle === cycle)));
      if (pricing) {
        document.querySelectorAll("#plans .plan").forEach((card, index) => updateBilling(card, pricing.plans[index]));
        updatePlanNote(media());
      }
    }
    const p = e.target.closest("button.pack[data-yuan]");
    if (p) {
      pack = Number(p.dataset.yuan);
      customAmount = "";
      $("#custom-amount").value = "";
      renderPacks();
    }
    const line = e.target.closest(".model-lines button");
    if (line) {
      routePick.set(line.dataset.choice, line.dataset.route);
      renderRates();
      return;
    }
    const m = e.target.closest("#model-tabs button");
    if (m) {
      modelTab = m.dataset.tab;
      renderRates();
    }
    const checkout = e.target.closest('#pack-buy, [data-checkout="member"]');
    if (checkout) {
      e.preventDefault();
      const membership = checkout.dataset.checkout === "member";
      const auth = window.OctopAuth;
      const open = membership ? pricing?.membershipOpen : pricing?.packsOpen;
      if (!open || !auth.config.checkoutEnabled || checkout.disabled || checkout.classList.contains("disabled")) return;
      if (!auth.requireLogin(membership ? "/pricing.html" : "/pricing.html#credits")) return;
      checkoutBody(auth, membership).then((body) => auth.api("/api/billing/recharge/checkout-link", { method: "POST", body })).then((data) => {
        const url = new URL(data.url);
        if (url.origin !== "https://admin.lynxce.cn" || url.pathname !== "/recharge" || url.username || url.password) throw new Error("Invalid checkout URL");
        url.searchParams.set("tab", membership ? "member" : "boost");
        location.assign(url.href);
      }).catch(() => { alert(t("无法打开收银台，请稍后重试。", "Unable to open checkout. Please try again.")); });
    }
    if (e.target.closest("a.disabled")) e.preventDefault();
  });
  /* checkout-link takes site and returnUrl, plus either packageId (Lynxce's pack with the same
     price, from its octop_bot catalog) or amountYuan (custom amount, 10–5000), never both.
     Each is sent only once its switch is on; without them the cashier asks for the amount. */
  async function checkoutBody(auth, membership) {
    const body = { site: "octopbot", returnUrl: "https://octop-bot.lynxce.cn/pay/result.html" };
    if (membership) return body;
    const cfg = auth.config;
    const custom = Number(customAmount);
    if (customAmount) {
      if (cfg.checkoutAmount && Number.isInteger(custom) && custom >= 10 && custom <= 5000) body.amountYuan = custom;
      return body;
    }
    if (!cfg.checkoutPackageId) return body;
    try {
      const data = await auth.api("/api/billing/recharge/packages?product=octop_bot");
      const hit = (data?.packages || []).find((p) => Number(p.amountCents) === pack * 100);
      if (hit && typeof hit.id === "string") body.packageId = hit.id;
    } catch (_) {
      /* No preselection: the cashier still works. */
    }
    return body;
  }

  $("#custom-amount")?.addEventListener("input", (e) => {
    customAmount = e.target.value.trim();
    renderPacks();
  });
  function switchWithKeyboard(e) {
    const buttons = [...e.currentTarget.querySelectorAll("button")];
    const index = buttons.indexOf(e.target);
    if (index < 0) return;
    let next;
    if (e.key === "ArrowRight") next = (index + 1) % buttons.length;
    else if (e.key === "ArrowLeft") next = (index + buttons.length - 1) % buttons.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = buttons.length - 1;
    else return;
    e.preventDefault();
    buttons[next].focus();
    buttons[next].click();
  }
  $("#price-tabs").addEventListener("keydown", switchWithKeyboard);
  $("#cycle").addEventListener("keydown", switchWithKeyboard);
  document.addEventListener("langchange", () => {
    renderAll();
  });
  window.addEventListener("hashchange", () => {
    const view = Object.keys(VIEW_HASH).find((name) => VIEW_HASH[name] === location.hash);
    if (view) showView(view);
  });
  showView(Object.keys(VIEW_HASH).find((name) => VIEW_HASH[name] === location.hash) || "plans", false);
  window.OctopAuth.ready.then(async () => {
    await window.OctopAuth.redeemHash("recharge");
    if (pricing && window.OctopAuth.config.checkoutEnabled) renderPlans();
    renderPacks();
  });

  const getJson = (url, timeoutMs = 8000) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    return fetch(url, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .finally(() => clearTimeout(timer));
  };
  async function loadPlans() {
    try {
      pricing = await getJson("data/pricing.json?v=2");
      renderAll();
    } catch {
      const retry = node("button", "btn btn-ghost", t("重新加载套餐", "Reload plans"));
      retry.type = "button";
      retry.addEventListener("click", loadPlans, { once: true });
      $("#plans").replaceChildren(retry);
    }
  }

  loadPlans();
  // The local snapshot supplies estimates without waiting for the cross-origin catalog.
  const localCatalog = getJson("data/pricing-catalog.json").then((body) => {
    catalog = body.data;
    updateEstimates();
  }).catch(() => {});

  async function showRates() {
    ratesVisible = true;
    await localCatalog;
    renderRates();
    try {
      const live = await getJson(CATALOG_URL, 5000);
      if (live?.code === 0 && Array.isArray(live.data?.textModels)) {
        liveCatalog = true;
        catalog = live.data;
        updateEstimates();
        renderRates();
      }
    } catch {
      // The local snapshot remains available.
    }
  }
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      showRates();
    }, { rootMargin: "320px" });
    observer.observe($("#rates"));
  } else {
    showRates();
  }
})();
