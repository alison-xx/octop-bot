/* Octop Bot website — shared behaviour for every page. No dependencies. */
(() => {
  "use strict";

  const root = document.documentElement;
  const $ = (sel, scope = document) => scope.querySelector(sel);
  const $$ = (sel, scope = document) => Array.from(scope.querySelectorAll(sel));
  const store = {
    get(key) {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(key, value);
      } catch {
        /* private mode: preference lasts for this page only */
      }
    },
  };
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const DOWNLOAD_BASE = "https://dl.lynxce.cn/releases/octop-bot/";

  /* ---------------- Language ---------------- */
  let lang = root.dataset.lang === "en" ? "en" : "zh";
  const ATTRS = ["aria-label", "placeholder", "alt", "title", "content"];

  function t(zh, en) {
    return lang === "en" ? en : zh;
  }

  function applyLang(next) {
    lang = next;
    root.dataset.lang = next;
    root.lang = next === "en" ? "en" : "zh-CN";
    $$("[data-en]").forEach((el) => {
      if (el.dataset.zh === undefined) el.dataset.zh = el.innerHTML;
      el.innerHTML = next === "en" ? el.dataset.en : el.dataset.zh;
    });
    ATTRS.forEach((attr) => {
      const key = "en" + attr.replace(/(^|-)(\w)/g, (_, __, c) => c.toUpperCase());
      $$(`[data-${"en-" + attr}]`).forEach((el) => {
        const zhKey = "zh" + key.slice(2);
        if (el.dataset[zhKey] === undefined) el.dataset[zhKey] = el.getAttribute(attr) || "";
        el.setAttribute(attr, next === "en" ? el.dataset[key] : el.dataset[zhKey]);
      });
    });
    $$("[data-lang-src]").forEach((el) => {
      el.src = el.dataset.langSrc.replace("{lang}", next);
    });
    $$(".lang-btn").forEach((btn) => {
      btn.textContent = next === "en" ? "中文" : "EN";
      btn.setAttribute("aria-label", next === "en" ? "切换到中文" : "Switch to English");
    });
    document.dispatchEvent(new CustomEvent("langchange"));
  }

  $$(".lang-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      const next = lang === "en" ? "zh" : "en";
      store.set("ob-lang", next);
      applyLang(next);
    }),
  );

  /* ---------------- Theme ---------------- */
  const THEMES = ["system", "light", "dark"];
  const themeIcons = {
    system:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="13" rx="2.5"/><path d="M8 21h8M12 17v4"/></svg>',
    light:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/></svg>',
    dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/></svg>',
  };
  let theme = THEMES.includes(store.get("ob-theme")) ? store.get("ob-theme") : "system";

  function applyTheme(next) {
    theme = next;
    if (next === "system") delete root.dataset.theme;
    else root.dataset.theme = next;
    $$(".theme-btn").forEach((btn) => {
      btn.innerHTML = themeIcons[next];
      const label = {
        system: t("外观：跟随系统", "Appearance: system"),
        light: t("外观：浅色", "Appearance: light"),
        dark: t("外观：深色", "Appearance: dark"),
      }[next];
      btn.setAttribute("aria-label", label);
      btn.title = label;
    });
  }
  $$(".theme-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
      store.set("ob-theme", next);
      applyTheme(next);
    }),
  );
  document.addEventListener("langchange", () => applyTheme(theme));

  /* ---------------- Header & mobile nav ---------------- */
  const header = $(".header");
  const onScroll = () => header && header.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const menuBtn = $(".menu-btn");
  const mobileNav = $(".mobile-nav");
  function setMenu(open) {
    if (!menuBtn || !mobileNav) return;
    mobileNav.classList.toggle("open", open);
    menuBtn.setAttribute("aria-expanded", String(open));
  }
  menuBtn?.addEventListener("click", () =>
    setMenu(menuBtn.getAttribute("aria-expanded") !== "true"),
  );
  mobileNav?.addEventListener("click", (e) => {
    if (e.target.closest("a")) setMenu(false);
  });
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") setMenu(false);
  });

  /* ---------------- Toast ---------------- */
  let toastTimer;
  function toast(message) {
    let el = $(".toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "toast";
      el.setAttribute("role", "status");
      document.body.append(el);
    }
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 1800);
  }

  /* ---------------- Reveal on scroll ---------------- */
  const revealer =
    "IntersectionObserver" in window && !reduceMotion
      ? new IntersectionObserver(
          (entries) =>
            entries.forEach((entry) => {
              if (entry.isIntersecting) {
                entry.target.classList.add("in");
                revealer.unobserve(entry.target);
              }
            }),
          { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
        )
      : null;
  $$(".reveal").forEach((el) => {
    // Content already on screen animates in right away instead of waiting for the observer.
    // Measuring forces the hidden starting style, so the transition still plays.
    if (!revealer || el.getBoundingClientRect().top < innerHeight * 0.96) el.classList.add("in");
    else revealer.observe(el);
  });

  /* ---------------- Bot crew (same shapes as the app) ---------------- */
  const SHAPES = {
    orb: ["M50 8a42 42 0 1 1 0 84a42 42 0 1 1 0-84z", [[57, 31, 9, 20], [70, 27, 9, 20]]],
    heart: [
      "M50 90C28 78 8 62 8 40C8 24 20 12 34 12C42 12 47 16 50 22C53 16 58 12 66 12C80 12 92 24 92 40C92 62 72 78 50 90Z",
      [[52, 42, 9, 19], [65, 39, 9, 19]],
    ],
    sparkle: [
      "M50 6C61 6 61 29 69 37C77 45 94 39 94 50C94 61 77 55 69 63C61 71 61 94 50 94C39 94 39 71 31 63C23 55 6 61 6 50C6 39 23 45 31 37C39 29 39 6 50 6Z",
      [[45, 46, 8, 17], [57, 43, 8, 17]],
    ],
    drop: [
      "M28 11C43 4 85 29 91 48C97 67 71 93 45 93C20 93 7 77 9 54C11 33 16 16 28 11Z",
      [[47, 40, 9, 19], [60, 37, 9, 19]],
    ],
    cloud: [
      "M26 80C12 80 5 68 9 57C3 46 10 32 24 32C26 18 42 11 55 19C63 9 82 13 84 30C96 34 98 51 89 59C93 71 85 81 72 80Z",
      [[52, 46, 9, 19], [65, 43, 9, 19]],
    ],
    bean: [
      "M19 29C30 16 70 16 84 29C96 40 95 62 82 73C68 85 32 85 18 73C5 62 7 40 19 29Z",
      [[57, 40, 9, 19], [70, 37, 9, 19]],
    ],
  };
  const INKS = {
    ink: ["var(--ink)", "var(--bg)"],
    red: ["#f2484f", "#fff"],
    orange: ["#f58714", "#fff"],
    blue: ["#1b7afc", "#fff"],
    violet: ["#844ff9", "#fff"],
    green: ["#11af98", "#fff"],
  };

  function botSvg(shape, ink) {
    const [body, eyes] = SHAPES[shape] || SHAPES.orb;
    const [fill, eyeFill] = INKS[ink] || INKS.ink;
    const eyeRects = eyes
      .map(
        ([cx, cy, w, h]) =>
          `<rect x="${cx - w / 2}" y="${cy - h / 2}" width="${w}" height="${h}" rx="${w / 2}" transform="rotate(-25 ${cx} ${cy})" fill="${eyeFill}"/>`,
      )
      .join("");
    return `<svg viewBox="0 0 100 100" aria-hidden="true"><path d="${body}" fill="${fill}"/><g class="eyes"><g class="lids">${eyeRects}</g></g></svg>`;
  }

  $$("[data-bot]").forEach((el) => {
    const [shape, ink] = el.dataset.bot.split(":");
    el.innerHTML = botSvg(shape, ink);
  });

  const crewBots = $$(".crew .bot");
  if (crewBots.length && !reduceMotion) {
    let pending = false;
    let px = innerWidth / 2;
    let py = innerHeight / 3;
    const look = () => {
      pending = false;
      crewBots.forEach((bot) => {
        const box = bot.getBoundingClientRect();
        const dx = px - (box.left + box.width / 2);
        const dy = py - (box.top + box.height / 2);
        const dist = Math.hypot(dx, dy) || 1;
        const k = Math.min(1, dist / 400);
        const eyes = bot.querySelector(".eyes");
        if (eyes) eyes.style.transform = `translate(${((dx / dist) * 6 * k).toFixed(2)}px, ${((dy / dist) * 5 * k).toFixed(2)}px)`;
      });
    };
    addEventListener(
      "pointermove",
      (e) => {
        px = e.clientX;
        py = e.clientY;
        if (!pending) {
          pending = true;
          requestAnimationFrame(look);
        }
      },
      { passive: true },
    );
  }

  /* ---------------- Hero window: flatten on scroll ---------------- */
  const heroWindow = $(".hero .window");
  if (heroWindow && !reduceMotion) {
    let ticking = false;
    const update = () => {
      ticking = false;
      const top = heroWindow.getBoundingClientRect().top;
      const p = Math.min(1, Math.max(0, 1 - (top - 80) / (innerHeight * 0.7)));
      heroWindow.style.setProperty("--tilt", `${(14 * (1 - p)).toFixed(2)}deg`);
      heroWindow.style.setProperty("--zoom", (0.94 + 0.06 * p).toFixed(3));
    };
    addEventListener(
      "scroll",
      () => {
        if (!ticking) {
          ticking = true;
          requestAnimationFrame(update);
        }
      },
      { passive: true },
    );
    update();
  }

  /* ---------------- Dialogs: lightbox & film ---------------- */
  function openDialog(dialog) {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }
  $$("dialog.modal").forEach((dialog) => {
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog || e.target.closest(".modal-close")) dialog.close();
    });
    dialog.addEventListener("close", () => dialog.querySelector("video")?.pause());
  });

  const lightbox = $("#lightbox");
  document.addEventListener("click", (e) => {
    const shot = e.target.closest("[data-zoom]");
    if (!shot || !lightbox) return;
    const img = $("img", lightbox);
    img.src = shot.currentSrc || shot.src;
    img.alt = shot.alt;
    openDialog(lightbox);
  });

  const film = $("#film");
  $$("[data-film]").forEach((btn) =>
    btn.addEventListener("click", () => {
      if (!film) return;
      const video = $("video", film);
      const want = `media/intro-${lang}.mp4?v=2`;
      if (!video.currentSrc.endsWith(want)) {
        video.innerHTML = `<source src="${want}" type="video/mp4"><track kind="captions" src="media/intro-${lang}.vtt?v=2" srclang="${lang === "en" ? "en" : "zh"}" label="${t("中文字幕", "English captions")}" default>`;
        video.poster = `media/intro-${lang}.webp?v=2`;
        video.load();
      }
      openDialog(film);
      video.play().catch(() => {});
    }),
  );

  /* ---------------- Promo spot ---------------- */
  $$("[data-promo]").forEach((box) => {
    const video = $("video", box);
    const sound = $("[data-promo-sound]", box);
    let visible = false;
    const withSound = () => box.hasAttribute("data-sound");
    const sync = () => {
      if (visible && (!reduceMotion || withSound())) video.play().catch(() => {});
      else video.pause();
    };
    const muteLoop = () => {
      box.removeAttribute("data-sound");
      video.muted = true;
      video.loop = true;
      video.controls = false;
      sync();
    };
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(
        ([entry]) => {
          visible = entry.isIntersecting;
          sync();
        },
        { threshold: 0.35 },
      ).observe(box);
    }
    sound?.addEventListener("click", () => {
      box.setAttribute("data-sound", "");
      video.muted = false;
      video.loop = false;
      video.controls = true;
      video.currentTime = 0;
      video.play().catch(() => {});
    });
    video.addEventListener("click", () => {
      if (video.controls) return;
      if (video.paused) video.play().catch(() => {});
      else video.pause();
    });
    video.addEventListener("ended", muteLoop);
    document.addEventListener("langchange", muteLoop);
  });

  /* ---------------- Showcase tabs ---------------- */
  $$("[data-showcase]").forEach((box) => {
    const img = $("img", box);
    const caption = $(".showcase-caption", box);
    const tabs = $$("[role=tab]", box);
    let current = tabs.find((tab) => tab.getAttribute("aria-selected") === "true") || tabs[0];
    const show = (tab, animate) => {
      current = tab;
      tabs.forEach((other) => {
        const on = other === tab;
        other.setAttribute("aria-selected", String(on));
        other.tabIndex = on ? 0 : -1;
      });
      const src = `assets/screen-${tab.dataset.shot}-${lang}.webp`;
      const apply = () => {
        img.src = src;
        img.alt = tab.dataset[lang === "en" ? "altEn" : "alt"] || "";
        caption.innerHTML = lang === "en" ? tab.dataset.captionEn : tab.dataset.caption;
        img.classList.remove("swap");
      };
      if (animate && !reduceMotion) {
        img.classList.add("swap");
        setTimeout(apply, 180);
      } else apply();
    };
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => show(tab, true));
      tab.addEventListener("keydown", (e) => {
        const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        const next = tabs[(i + step + tabs.length) % tabs.length];
        next.focus();
        show(next, true);
      });
    });
    document.addEventListener("langchange", () => show(current, false));
    show(current, false);
  });

  /* ---------------- Downloads ---------------- */
  function detectOS() {
    const ua = navigator.userAgent;
    const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (/iPhone|iPad|iPod|Android/i.test(ua)) return "mobile";
    if (/Win/i.test(platform) || /Windows/i.test(ua)) return "win";
    if (/Mac/i.test(platform) || /Mac OS X/i.test(ua)) return "mac";
    if (/Linux/i.test(platform)) return "linux";
    return "other";
  }
  const os = detectOS();
  const phone = /Android/i.test(navigator.userAgent) ? "android" : /iPhone|iPad|iPod/i.test(navigator.userAgent) ? "ios" : null;
  root.dataset.os = os;

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const formatSize = (bytes) => `${(bytes / 1e6).toFixed(0)} MB`;
  const assetUrl = (release, asset) => asset.url || `${DOWNLOAD_BASE}${release.version}/${asset.name}`;
  const pick = (release, platform, kind, arch) =>
    release.assets.find((a) => a.platform === platform && (!kind || a.kind === kind) && (!arch || a.arch === arch));

  /* The signed release manifest the apps update from (docs/octop-bot-updates.md). */
  const MANIFEST_URL = (() => {
    const local = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) && new URLSearchParams(location.search).get("manifest");
    return local || `${DOWNLOAD_BASE}manifest.json`;
  })();
  /* Raw Ed25519 public key of the release signing key, the same one the apps carry. */
  const MANIFEST_KEY = "jfzS5kpiVxqx/79rU5tYno7Js31ezDt05RmrmXnRTa0=";
  const DOWNLOAD_HOST = new URL(DOWNLOAD_BASE).host;
  const ASSET_KINDS = {
    win_x64: { platform: "win32", arch: "x64", kind: "installer" },
    win_x64_zip: { platform: "win32", arch: "x64", kind: "portable" },
    win_arm: { platform: "win32", arch: "arm64", kind: "installer" },
    mac_arm: { platform: "darwin", arch: "arm64", kind: "dmg" },
    mac_intel: { platform: "darwin", arch: "x64", kind: "dmg" },
    android: { platform: "android", kind: "apk" },
    fnos: { platform: "nas", kind: "fpk" },
  };
  const PRE = { a: "alpha", b: "beta", rc: "rc" };

  /* "1.0.4b1" (Python style, used in the manifest) → "1.0.4-beta.1" (used on the site and in file names). */
  const displayVersion = (v) =>
    String(v).replace(/^(\d+(?:\.\d+)*)(a|b|rc)(\d+)$/, (_, base, pre, n) => `${base}-${PRE[pre]}.${n}`);

  function compareVersions(a, b) {
    const parse = (v) => {
      const [base, pre = ""] = displayVersion(v).split("-");
      const [stage = "", n = "0"] = pre.split(".");
      return { nums: base.split(".").map(Number), stage: pre ? ["alpha", "beta", "rc"].indexOf(stage) : 9, n: Number(n) };
    };
    const x = parse(a);
    const y = parse(b);
    for (let i = 0; i < Math.max(x.nums.length, y.nums.length); i++) {
      const d = (x.nums[i] || 0) - (y.nums[i] || 0);
      if (d) return d;
    }
    return x.stage - y.stage || x.n - y.n;
  }

  const onHost = (url) => {
    try {
      return new URL(url).host === DOWNLOAD_HOST;
    } catch {
      return false;
    }
  };

  /* Release notes come from CHANGELOG Markdown; keep the bullet lines as plain text. */
  function noteLines(markdown) {
    const lines = String(markdown || "")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#"));
    const bullets = lines.filter((l) => /^([-*]|\d+\.)\s/.test(l));
    return (bullets.length ? bullets : lines).map((l) =>
      l
        .replace(/^([-*]|\d+\.)\s+/, "")
        .replace(/\*\*(.+?)\*\*/g, "$1")
        .replace(/`([^`]+)`/g, "$1"),
    );
  }

  function fromChannel(channel, entry) {
    const assets = [];
    for (const [key, a] of Object.entries(entry.assets || {})) {
      if (key === "ios") {
        if (/^https:\/\//.test(a.url || "")) assets.push({ platform: "ios", kind: "store", url: a.url, appVersion: a.version });
        continue;
      }
      if (ASSET_KINDS[key] && onHost(a.url)) assets.push({ ...ASSET_KINDS[key], ...a, appVersion: a.version });
    }
    return {
      version: displayVersion(entry.version),
      channel,
      date: entry.date,
      notes: { zh: noteLines(entry.notes && entry.notes.zh), en: noteLines(entry.notes && entry.notes.en) },
      nas: entry.nas,
      assets,
    };
  }

  const b64 = (s) => Uint8Array.from(atob(s.trim()), (c) => c.charCodeAt(0));
  async function loadManifest() {
    const get = (url, as) =>
      fetch(url, { cache: "no-cache" }).then((r) => (r.ok ? r[as]() : Promise.reject(new Error(`HTTP ${r.status}`))));
    const [body, signature] = await Promise.all([get(MANIFEST_URL, "arrayBuffer"), get(`${MANIFEST_URL}.sig`, "text")]);
    let key = null;
    try {
      key = await crypto.subtle.importKey("raw", b64(MANIFEST_KEY), { name: "Ed25519" }, false, ["verify"]);
    } catch {
      /* No Ed25519 in this browser's WebCrypto. The apps still verify before installing. */
    }
    if (key && !(await crypto.subtle.verify({ name: "Ed25519" }, key, b64(signature), body))) {
      throw new Error("manifest signature does not match");
    }
    const manifest = JSON.parse(new TextDecoder().decode(body));
    if (manifest.product !== "octop-bot") throw new Error("not the Octop Bot manifest");
    return ["stable", "beta"]
      .filter((name) => manifest.channels && manifest.channels[name])
      .map((name) => fromChannel(name, manifest.channels[name]));
  }

  const OS_ICON = {
    win: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 5.1 10.4 4v7.2H3V5.1Zm0 13.8 7.4 1.1v-7.1H3v6Zm8.3 1.2L21 21.5v-8.6h-9.7v7.2ZM11.3 3.9v7.3H21V2.5l-9.7 1.4Z"/></svg>',
    mac: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16.4 12.6c0-2.4 2-3.6 2.1-3.7-1.1-1.7-2.9-1.9-3.5-1.9-1.5-.2-2.9.9-3.7.9-.8 0-1.9-.9-3.2-.8-1.6 0-3.1 1-4 2.4-1.7 3-.4 7.4 1.2 9.8.8 1.2 1.8 2.5 3 2.4 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8c1.3 0 2.2-1.2 3-2.4.9-1.4 1.3-2.7 1.3-2.8 0 0-2.6-1-2.6-3.9ZM14 5.4c.7-.8 1.1-1.9 1-3-1 0-2.1.7-2.8 1.5-.6.7-1.2 1.8-1 2.9 1.1.1 2.1-.6 2.8-1.4Z"/></svg>',
    phone:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="6" y="2.5" width="12" height="19" rx="3"/><path d="M10.5 18.5h3"/></svg>',
    nas: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3.5" y="4" width="17" height="7" rx="2"/><rect x="3.5" y="13" width="17" height="7" rx="2"/><path d="M7.5 7.5h.01M7.5 16.5h.01M11 7.5h6M11 16.5h6"/></svg>',
  };
  const ARROW =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12m0 0-5-5m5 5 5-5M5 20h14"/></svg>';
  const OUT =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17 17 7M8 7h9v9"/></svg>';
  const storeName = (url) => (/testflight\.apple\.com/.test(url) ? "TestFlight" : "App Store");

  /* A release can skip a platform (say, no Windows build). Offer that platform's newest package instead. */
  function releaseWith(test) {
    const list = site ? [site.latest, ...site.history] : [];
    return list.find((r) => r.assets.some(test) || (test.nas && r.nas && r.nas.image)) || null;
  }
  const versionTag = (r) => (site && r !== site.latest && r.version !== site.latest.version ? ` · ${t("版本", "Version")} ${esc(r.version)}` : "");
  const isWin = (a) => a.platform === "win32";
  const isMac = (a) => a.platform === "darwin";
  const isPhone = (a) => a.platform === "android" || a.platform === "ios";
  const isNas = Object.assign((a) => a.platform === "nas", { nas: true });

  function primaryChoice(latest) {
    const release = releaseWith(os === "win" ? isWin : os === "mac" ? isMac : isPhone) || latest;
    if (os === "win") {
      const a = pick(release, "win32", "installer", "x64");
      return a && { href: assetUrl(release, a), label: t("下载 Windows 版", "Download for Windows"), sub: `x64 · ${formatSize(a.size)}`, icon: OS_ICON.win, version: release.version };
    }
    if (os === "mac") {
      const a = pick(release, "darwin", null, "arm64");
      return a && { href: assetUrl(release, a), label: t("下载 macOS 版", "Download for Mac"), sub: `${t("Apple 芯片", "Apple silicon")} · ${formatSize(a.size)}`, icon: OS_ICON.mac, version: release.version };
    }
    if (phone === "android") {
      const a = pick(release, "android");
      return a && { href: assetUrl(release, a), label: t("下载 Android 版", "Download for Android"), sub: `APK · ${formatSize(a.size)}`, icon: OS_ICON.phone, version: a.appVersion };
    }
    if (phone === "ios") {
      const a = pick(release, "ios");
      return a && { href: a.url, external: true, label: t("下载 iPhone 版", "Get it for iPhone"), sub: storeName(a.url), icon: OS_ICON.phone, version: a.appVersion };
    }
    return null;
  }

  function renderPrimary(release) {
    const choice = primaryChoice(release);
    $$("[data-download-primary]").forEach((btn) => {
      btn.removeAttribute("target");
      btn.removeAttribute("rel");
      if (choice) {
        btn.href = choice.href;
        if (choice.external) {
          btn.removeAttribute("download");
          btn.target = "_blank";
          btn.rel = "noopener";
        } else btn.setAttribute("download", "");
        btn.innerHTML = `${choice.icon}<span>${choice.label}</span>`;
      } else {
        btn.href = "download.html";
        btn.removeAttribute("download");
        btn.innerHTML = `${ARROW}<span>${t("选择版本下载", "Choose a download")}</span>`;
      }
    });
    $$("[data-download-note]").forEach((el) => {
      el.textContent = choice
        ? `${t("版本", "Version")} ${choice.version} · ${choice.sub} · ${t("免费开源", "Free & open source")}`
        : os === "mobile"
          ? t("Octop Bot 是桌面客户端，请在 Windows 或 Mac 电脑上下载。", "Octop Bot is a desktop app. Download it on a Windows PC or a Mac.")
          : t("提供 Windows x64 和 Apple 芯片 Mac 版本。", "Available for Windows x64 and Macs with Apple silicon.");
    });
    $$("[data-version]").forEach((el) => (el.textContent = release.version));
    $$("[data-release-date]").forEach((el) => (el.textContent = release.date));
  }

  function fileRow(release, asset, title, meta, recommended) {
    return `<div class="file">
      <div><b>${title}${recommended ? ` <span class="badge" style="margin-left:6px">${t("推荐", "Recommended")}</span>` : ""}</b><small>${meta} · ${formatSize(asset.size)}</small></div>
      <a class="btn ${recommended ? "btn-primary" : "btn-ghost"} btn-sm" href="${esc(assetUrl(release, asset))}" download>${ARROW}<span>${t("下载", "Download")}</span></a>
      <div class="sha"><span>SHA-256</span><code title="${esc(asset.sha256)}">${esc(asset.sha256)}</code><button class="copy" type="button" data-copy="${esc(asset.sha256)}">${t("复制", "Copy")}</button></div>
    </div>`;
  }

  const card = (key, icon, title, sub, body, detected) => `<article class="platform${detected ? " detected" : ""}" data-platform="${key}">
        <div class="platform-head">${icon}<div><h3 class="h3">${title}</h3><small class="muted">${sub}</small></div>${detected ? `<span class="badge">${t("你的系统", "Your system")}</span>` : ""}</div>
        ${body}</article>`;

  function renderPlatforms(latest, beta) {
    const box = $("#platforms");
    if (!box) return;
    const winRel = releaseWith(isWin) || latest;
    const macRel = releaseWith(isMac) || latest;
    const phoneRel = releaseWith(isPhone) || latest;
    const nasRel = releaseWith(isNas) || latest;
    const win = pick(winRel, "win32", "installer", "x64");
    const winArm = pick(winRel, "win32", "installer", "arm64");
    const zip = pick(winRel, "win32", "portable");
    const mac = pick(macRel, "darwin", null, "arm64");
    const intel = pick(macRel, "darwin", null, "x64");
    const apk = pick(phoneRel, "android");
    const ios = pick(phoneRel, "ios");
    const fpk = pick(nasRel, "nas");
    const image = nasRel.nas && nasRel.nas.image;
    const cards = [];
    if (win || winArm || zip) {
      cards.push(
        card(
          "win",
          OS_ICON.win,
          "Windows",
          `${winArm ? "Windows 10 / 11 · x64 · ARM64" : "Windows 10 / 11 · x64"}${versionTag(winRel)}`,
          `<div class="files">
          ${win ? fileRow(winRel, win, t("安装版", "Installer"), "EXE · x64", true) : ""}
          ${zip ? fileRow(winRel, zip, t("免安装版", "Portable"), t("ZIP · 解压即用", "ZIP · unzip and run"), false) : ""}
          ${winArm ? fileRow(winRel, winArm, t("安装版（ARM）", "Installer (ARM)"), "EXE · arm64", false) : ""}
        </div>`,
          os === "win",
        ),
      );
    }
    if (mac || intel) {
      cards.push(
        card(
          "mac",
          OS_ICON.mac,
          "macOS",
          `${intel ? t("Apple 芯片和 Intel 芯片", "Apple silicon and Intel") : t("Apple 芯片（M 系列）", "Apple silicon (M-series)")}${versionTag(macRel)}`,
          `<div class="files">
          ${mac ? fileRow(macRel, mac, t("Apple 芯片", "Apple silicon"), "DMG · arm64", true) : ""}
          ${intel ? fileRow(macRel, intel, t("Intel 芯片", "Intel"), "DMG · x64", !mac) : ""}
        </div>${intel ? "" : `<p class="muted" style="font-size:14px">${t("暂不支持 Intel 芯片的 Mac。", "Intel-based Macs are not supported yet.")}</p>`}`,
          os === "mac",
        ),
      );
    }
    if (apk || ios) {
      const version = (apk || ios).appVersion;
      cards.push(
        card(
          "phone",
          OS_ICON.phone,
          t("手机", "Phone"),
          `${[apk && "Android", ios && "iPhone"].filter(Boolean).join(" · ")}${version ? ` · ${t("版本", "Version")} ${esc(version)}` : ""}`,
          `<div class="files">
          ${apk ? fileRow(phoneRel, apk, "Android", "APK", phone === "android") : ""}
          ${
            ios
              ? `<div class="file"><div><b>iPhone / iPad</b><small>${storeName(ios.url)}</small></div><a class="btn ${phone === "ios" ? "btn-primary" : "btn-ghost"} btn-sm" href="${esc(ios.url)}" target="_blank" rel="noopener"><span>${t("前往获取", "Get it")}</span>${OUT}</a></div>`
              : ""
          }
        </div><p class="muted" style="font-size:14px">${t("手机端连接你电脑或 NAS 上的 Octop Bot 使用。", "The phone app connects to Octop Bot on your computer or NAS.")}</p>`,
          os === "mobile",
        ),
      );
    }
    if (fpk || image) {
      cards.push(
        card(
          "nas",
          OS_ICON.nas,
          "NAS",
          t("飞牛 fnOS · Docker", "fnOS · Docker"),
          `<div class="files">
          ${fpk ? fileRow(nasRel, fpk, t("飞牛 fnOS 应用", "fnOS app"), "FPK", true) : ""}
          ${
            image
              ? `<div class="file"><div><b>Docker</b><small><code>${esc(image)}</code></small></div><button class="copy" type="button" data-copy="docker pull ${esc(image)}" data-toast="${t("命令已复制", "Command copied")}">${t("复制", "Copy")}</button></div>`
              : ""
          }
        </div><p style="font-size:14px"><a class="link" style="display:inline" href="https://github.com/alison-xx/octop-bot/blob/main/docs/octop-bot-nas.md">${t("NAS 安装说明", "NAS install guide")} ↗</a></p>`,
          false,
        ),
      );
    }
    if (beta) {
      const links = [
        [pick(beta, "win32", "installer", "x64"), "Windows"],
        [pick(beta, "darwin", null, "arm64"), "macOS"],
      ]
        .filter(([a]) => a)
        .map(([a, name]) => `<a class="link" style="display:inline" href="${esc(assetUrl(beta, a))}" download>${name}</a>`)
        .join(" · ");
      if (links) {
        cards.push(
          `<p class="muted beta-note" style="grid-column:1/-1;text-align:center;font-size:14px">${t("测试版", "Beta")} <b>${esc(beta.version)}</b> ${t("已发布，可以抢先体验：", "is out if you want to try it early:")} ${links} · <a class="link" style="display:inline" href="#changelog">${t("更新说明", "What's new")}</a></p>`,
        );
      }
    }
    box.innerHTML = cards.join("");
    $$("[data-intel-note]").forEach((el) => (el.hidden = Boolean(intel)));
  }

  function renderHistory(releases) {
    const box = $("#history");
    if (!box) return;
    box.innerHTML = releases
      .map((r, i) => {
        const notes = (r.notes[lang] && r.notes[lang].length ? r.notes[lang] : r.notes.zh) || [];
        const badge =
          i === 0
            ? ` <span class="badge" style="vertical-align:middle">${t("最新", "Latest")}</span>`
            : r.channel === "beta" && r.live
              ? ` <span class="badge neutral" style="vertical-align:middle">${t("测试版", "Beta")}</span>`
              : "";
        return `<article class="release reveal in">
        <div><h3>${esc(r.version)}${badge}</h3><time datetime="${esc(r.date)}">${esc(r.date)}</time></div>
        <div><ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
        ${
          r.tag
            ? `<p style="margin-top:16px"><a class="link" href="https://github.com/alison-xx/octop-bot/releases/tag/${esc(r.tag)}">${t("该版本的全部安装包和 SHA-256", "Every package and SHA-256 for this release")} ${OUT}</a></p>`
            : r.live
              ? ""
              : `<p style="margin-top:16px"><a class="link" href="${DOWNLOAD_BASE}${esc(r.version)}/SHA256SUMS.txt">${t("该版本全部安装包的 SHA-256", "SHA-256 for every package in this release")} ${OUT}</a></p>`
        }</div>
      </article>`;
      })
      .join("");
  }

  /* The manifest decides the current version; releases.json keeps older releases for the changelog
     and stands in while no manifest is published. The static HTML is the last fallback. */
  let site = null;
  function renderReleases() {
    if (!site) return;
    renderPrimary(site.latest);
    renderPlatforms(site.latest, site.beta);
    renderHistory(site.history);
  }
  if ($("[data-download-primary], #platforms, #history")) {
    const live = loadManifest()
      .then((list) => list.map((r) => ({ ...r, live: true })))
      .catch(() => []);
    const listed = fetch("releases.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => data.releases)
      .catch(() => []);
    Promise.all([live, listed]).then(([fromManifest, fromList]) => {
      const stable = fromManifest.find((r) => r.channel === "stable");
      const beta = fromManifest.find((r) => r.channel === "beta");
      const latest = stable || beta || fromList[0];
      if (!latest) return;
      const seen = new Set();
      /* For a version in both, keep the hand-written bilingual notes from releases.json. */
      const history = [...fromList, ...fromManifest]
        .filter((r) => !seen.has(r.version) && seen.add(r.version))
        .sort((a, b) => compareVersions(b.version, a.version));
      site = { latest, beta: stable && beta && compareVersions(beta.version, stable.version) > 0 ? beta : null, history };
      renderReleases();
    });
    document.addEventListener("langchange", renderReleases);
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const done = () => {
      btn.classList.add("done");
      btn.textContent = t("已复制", "Copied");
      toast(btn.dataset.toast || t("校验值已复制", "Checksum copied"));
      setTimeout(() => {
        btn.classList.remove("done");
        btn.textContent = t("复制", "Copy");
      }, 1600);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(btn.dataset.copy).then(done, () => {});
  });

  /* ---------------- Install steps tabs (download page) ---------------- */
  $$("[data-steps]").forEach((box) => {
    const tabs = $$("[role=tab]", box);
    const panels = $$("[role=tabpanel]", box);
    const select = (id) => {
      tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.panel === id)));
      panels.forEach((panel) => (panel.hidden = panel.id !== id));
    };
    tabs.forEach((tab) => tab.addEventListener("click", () => select(tab.dataset.panel)));
    select(os === "mac" ? "steps-mac" : "steps-win");
  });

  /* ---------------- FAQ search & filters ---------------- */
  const faq = $(".faq");
  if (faq) {
    const input = $("#faq-search");
    const buttons = $$(".filters button");
    const empty = $(".faq-empty");
    let category = "all";
    const apply = () => {
      const q = (input?.value || "").trim().toLowerCase();
      let shown = 0;
      $$("details", faq).forEach((item) => {
        const hit =
          (category === "all" || item.dataset.cat === category) &&
          (!q || item.textContent.toLowerCase().includes(q));
        item.hidden = !hit;
        if (hit) shown++;
      });
      if (empty) empty.hidden = shown > 0;
    };
    input?.addEventListener("input", apply);
    buttons.forEach((btn) =>
      btn.addEventListener("click", () => {
        category = btn.dataset.cat;
        buttons.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        apply();
      }),
    );
    if (location.hash) {
      const target = document.getElementById(location.hash.slice(1));
      if (target && target.tagName === "DETAILS") target.open = true;
    }
  }

  /* ---------------- Sub-navigation scroll spy (features page) ---------------- */
  const subLinks = $$(".subnav a[href^='#']");
  if (subLinks.length && "IntersectionObserver" in window) {
    const map = new Map(subLinks.map((a) => [a.getAttribute("href").slice(1), a]));
    const spy = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          subLinks.forEach((a) => a.classList.remove("active"));
          const link = map.get(entry.target.id);
          if (link) {
            link.classList.add("active");
            link.scrollIntoView({ block: "nearest", inline: "center", behavior: reduceMotion ? "auto" : "smooth" });
          }
        }),
      { rootMargin: "-45% 0px -50% 0px" },
    );
    map.forEach((_, id) => {
      const section = document.getElementById(id);
      if (section) spy.observe(section);
    });
  }

  /* ---------------- GitHub stars ---------------- */
  function formatStars(n) {
    return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 1 : 2).replace(/\.?0+$/, "")}k` : String(n);
  }
  const starEls = $$("[data-stars]");
  const repos = [...new Set(starEls.map((el) => el.dataset.stars))];
  repos.forEach((repo) => {
    const show = (n) => starEls.filter((el) => el.dataset.stars === repo).forEach((el) => (el.textContent = formatStars(n)));
    const key = `ob-stars:${repo}`;
    let cached = null;
    try {
      cached = JSON.parse(localStorage.getItem(key) || "null");
    } catch (e) {
      /* storage unavailable */
    }
    if (cached && typeof cached.n === "number") show(cached.n);
    if (cached && Date.now() - cached.at < 6 * 3600 * 1000) return;
    const ctrl = "AbortController" in window ? new AbortController() : null;
    if (ctrl) setTimeout(() => ctrl.abort(), 5000);
    fetch(`https://api.github.com/repos/${repo}`, { signal: ctrl && ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        if (typeof data.stargazers_count !== "number") return;
        show(data.stargazers_count);
        try {
          localStorage.setItem(key, JSON.stringify({ n: data.stargazers_count, at: Date.now() }));
        } catch (e) {
          /* storage unavailable */
        }
      })
      .catch(() => {
        /* keep the number baked into the HTML */
      });
  });

  /* ---------------- Misc ---------------- */
  $$("[data-year]").forEach((el) => (el.textContent = new Date().getFullYear()));

  applyTheme(theme);
  applyLang(lang);
  root.classList.remove("i18n-wait");
  root.dataset.ready = "1";
})();
