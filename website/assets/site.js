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
    mobileNav.inert = !open;
    mobileNav.classList.toggle("open", open);
    menuBtn.setAttribute("aria-expanded", String(open));
  }
  setMenu(false);
  menuBtn?.addEventListener("click", () =>
    setMenu(menuBtn.getAttribute("aria-expanded") !== "true"),
  );
  mobileNav?.addEventListener("click", (e) => {
    if (e.target.closest("a")) setMenu(false);
  });
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && mobileNav?.classList.contains("open")) {
      setMenu(false);
      menuBtn.focus();
    }
  });

  document.addEventListener("pointerdown", (e) => {
    if (mobileNav?.classList.contains("open") && !mobileNav.contains(e.target) && !menuBtn.contains(e.target)) setMenu(false);
  });
  header?.addEventListener("focusout", (e) => {
    if (e.relatedTarget && !header.contains(e.relatedTarget)) setMenu(false);
  });
  matchMedia("(max-width: 1180px)").addEventListener("change", () => setMenu(false));
  addEventListener("pageshow", () => setMenu(false));

  const helpMenus = $$(".nav-more");
  function setHelp(menu, open) {
    menu.classList.toggle("open", open);
    $("button", menu).setAttribute("aria-expanded", String(open));
  }
  helpMenus.forEach((menu) => {
    const button = $("button", menu);
    button.addEventListener("click", () => setHelp(menu, !menu.classList.contains("open")));
    menu.addEventListener("pointerenter", (e) => {
      if (e.pointerType === "mouse") setHelp(menu, true);
    });
    menu.addEventListener("pointerleave", () => {
      if (!menu.contains(document.activeElement)) setHelp(menu, false);
    });
    menu.addEventListener("focusout", (e) => {
      if (!menu.contains(e.relatedTarget)) setHelp(menu, false);
    });
  });
  document.addEventListener("click", (e) => {
    helpMenus.forEach((menu) => {
      if (!menu.contains(e.target)) setHelp(menu, false);
    });
  });
  addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    helpMenus.forEach((menu) => {
      if (menu.classList.contains("open")) {
        setHelp(menu, false);
        $("button", menu).focus();
      }
    });
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

  /* WeChat community QR: footer, Help menu, phone menu, changelog and pricing all open it. */
  const community = $("#community");
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-community]");
    if (!trigger || !community) return;
    e.preventDefault();
    if (mobileNav?.contains(trigger)) menuBtn.focus();
    setMenu(false);
    community.dataset.kind = trigger.dataset.community === "business" ? "business" : "community";
    openDialog(community);
  });

  const lightbox = $("#lightbox");
  if (lightbox) $$("[data-zoom]").forEach((shot) => {
    shot.tabIndex = 0;
    shot.setAttribute("role", "button");
    shot.setAttribute("aria-haspopup", "dialog");
    shot.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      shot.click();
    });
  });
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

  function wireTabKeys(tabs) {
    tabs.forEach((tab, i) => tab.addEventListener("keydown", (e) => {
      const target = {
        ArrowLeft: tabs[(i - 1 + tabs.length) % tabs.length],
        ArrowRight: tabs[(i + 1) % tabs.length],
        Home: tabs[0],
        End: tabs[tabs.length - 1],
      }[e.key];
      if (!target) return;
      e.preventDefault();
      target.focus();
      target.click();
    }));
  }

  /* ---------------- Showcase tabs ---------------- */
  $$("[data-showcase]").forEach((box) => {
    const img = $("img", box);
    const caption = $(".showcase-caption", box);
    const tabs = $$("[role=tab]", box);
    let current = tabs.find((tab) => tab.getAttribute("aria-selected") === "true") || tabs[0];
    let swapTimer;
    const show = (tab, animate) => {
      clearTimeout(swapTimer);
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
        caption.textContent = lang === "en" ? tab.dataset.captionEn : tab.dataset.caption;
        img.classList.remove("swap");
      };
      if (animate && !reduceMotion) {
        img.classList.add("swap");
        swapTimer = setTimeout(apply, 180);
      } else apply();
    };
    tabs.forEach((tab) => tab.addEventListener("click", () => show(tab, true)));
    wireTabKeys(tabs);
    document.addEventListener("langchange", () => show(current, false));
    show(current, false);
  });

  /* ---------------- Downloads ---------------- */
  const appleMobile = /iPhone|iPad|iPod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  function detectOS() {
    const ua = navigator.userAgent;
    const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (appleMobile || /Android/i.test(ua)) return "mobile";
    if (/Win/i.test(platform) || /Windows/i.test(ua)) return "win";
    if (/Mac/i.test(platform) || /Mac OS X/i.test(ua)) return "mac";
    if (/Linux/i.test(platform)) return "linux";
    return "other";
  }
  const os = detectOS();
  const phone = /Android/i.test(navigator.userAgent) ? "android" : appleMobile ? "ios" : null;
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
    web: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3Z"/></svg>',
    nas: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3.5" y="4" width="17" height="7" rx="2"/><rect x="3.5" y="13" width="17" height="7" rx="2"/><path d="M7.5 7.5h.01M7.5 16.5h.01M11 7.5h6M11 16.5h6"/></svg>',
  };
  const ARROW =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12m0 0-5-5m5 5 5-5M5 20h14"/></svg>';
  const OUT =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17 17 7M8 7h9v9"/></svg>';
  const WEB_APP = "https://bot.lynxce.cn";
  const IOS_STORE_URL = "https://apps.apple.com/app/id6838257776";

  /* A release can skip a platform (say, no Windows build). Offer that platform's newest package instead. */
  function releaseWith(test) {
    const list = site ? [site.latest, ...site.history].filter((r) => r.channel === "stable") : [];
    return list.find((r) => r.assets.some(test) || (test.nas && r.nas && r.nas.image)) || null;
  }
  const versionTag = (r) => ` · ${t("正式版", "Stable")} ${esc(r.version)}`;
  const isWin = (a) => a.platform === "win32";
  const isMac = (a) => a.platform === "darwin";
  const isAndroid = (a) => a.platform === "android";
  const isNas = Object.assign((a) => a.platform === "nas", { nas: true });

  function iosVersion() {
    const listed = (asset) => asset.platform === "ios" && asset.url === IOS_STORE_URL && asset.appVersion;
    return releaseWith(listed)?.assets.find(listed)?.appVersion;
  }

  function primaryChoice() {
    if (phone === "ios") {
      return { href: IOS_STORE_URL, external: true, label: t("前往 App Store 下载", "Download on the App Store"), sub: "iPhone · iPad", icon: OS_ICON.phone, version: iosVersion() };
    }
    const release = releaseWith(os === "win" ? isWin : os === "mac" ? isMac : isAndroid);
    if (!release) return null;
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
    return null;
  }

  function renderPrimary(release) {
    const choice = primaryChoice();
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
        btn.href = $("#platforms") ? "#platforms-section" : "download.html";
        btn.removeAttribute("download");
        btn.innerHTML = `${ARROW}<span>${t("选择版本下载", "Choose a download")}</span>`;
      }
    });
    $$("[data-download-note]").forEach((el) => {
      el.textContent = choice
        ? `${choice.version ? `${t("版本", "Version")} ${choice.version} · ` : ""}${choice.sub} · ${t("免费开源", "Free & open source")}`
        : os === "mobile"
          ? t("手机也可以用浏览器登录灵策账号，继续云端对话。", "Sign in with Lynxce in your mobile browser to continue a cloud chat.")
          : t("Windows x64 · Apple 芯片 Mac · Android APK", "Windows x64 · Apple silicon Mac · Android APK");
    });
    if (!release) return;
    $$("[data-version]").forEach((el) => (el.textContent = release.version));
    $$("[data-release-date]").forEach((el) => (el.textContent = release.date));
  }

  function fileRow(release, asset, title, meta, recommended) {
    const key = [asset.platform, asset.kind, asset.arch].filter(Boolean).join("-");
    return `<div class="file" data-package="${esc(key)}">
      <div><b>${title}${recommended ? ` <span class="badge" style="margin-left:6px">${t("推荐", "Recommended")}</span>` : ""}</b><small>${meta} · ${formatSize(asset.size)}</small></div>
      <a class="btn ${recommended ? "btn-primary" : "btn-ghost"} btn-sm" href="${esc(assetUrl(release, asset))}" download>${ARROW}<span>${t("下载", "Download")}</span></a>
      <div class="sha"><span>SHA-256</span><code title="${esc(asset.sha256)}">${esc(asset.sha256)}</code><button class="copy" type="button" data-copy="${esc(asset.sha256)}">${t("复制", "Copy")}</button></div>
    </div>`;
  }

  const card = (key, icon, title, sub, body, detected) => `<article class="platform${detected ? " detected" : ""}" data-platform="${key}">
        <div class="platform-head">${icon}<div><h3 class="h3">${title}</h3><small class="muted">${sub}</small></div>${detected ? `<span class="badge">${t("你的系统", "Your system")}</span>` : ""}</div>
        ${body}</article>`;

  let platformRefreshPending = false;
  function renderPlatforms(latest, beta) {
    const box = $("#platforms");
    if (!box) return;
    // Keep the pressed link or button in the DOM through its activation.
    if ($("a:active, button:active", box)) {
      platformRefreshPending = true;
      return;
    }
    platformRefreshPending = false;
    const winRel = releaseWith(isWin);
    const macRel = releaseWith(isMac);
    const androidRel = releaseWith(isAndroid);
    const nasRel = releaseWith(isNas) || latest;
    const win = winRel && pick(winRel, "win32", "installer", "x64");
    const winArm = winRel && pick(winRel, "win32", "installer", "arm64");
    const zip = winRel && pick(winRel, "win32", "portable");
    const mac = macRel && pick(macRel, "darwin", null, "arm64");
    const intel = macRel && pick(macRel, "darwin", null, "x64");
    const apk = androidRel && pick(androidRel, "android");
    const storeVersion = iosVersion();
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
    cards.push(
      card(
        "ios",
        OS_ICON.phone,
        "iOS / iPadOS",
        "iPhone · iPad",
        `<div class="files"><div class="file"><div><b>App Store</b>${storeVersion ? `<small>${esc(storeVersion)}</small>` : ""}</div><a class="btn ${phone === "ios" ? "btn-primary" : "btn-ghost"} btn-sm" href="${IOS_STORE_URL}"><span>${t("前往 App Store 下载", "Download on the App Store")}</span>${OUT}</a></div></div>`,
        phone === "ios",
      ),
    );
    if (apk) {
      cards.push(
        card(
          "android",
          OS_ICON.phone,
          "Android",
          apk.appVersion ? `APK · ${esc(apk.appVersion)}` : "APK",
          `<div class="files">${fileRow(androidRel, apk, "Android", "APK", phone === "android")}</div>`,
          phone === "android",
        ),
      );
    }
    cards.push(
      card(
        "web",
        OS_ICON.web,
        t("网页版", "Web"),
        t("Chrome、Edge、Safari 等浏览器", "Any modern browser"),
        `<div class="files">
          <div class="file"><div><b>bot.lynxce.cn</b><small>${t("用灵策智算账号登录", "Sign in with your Lynxce account")}</small></div><a class="btn btn-ghost btn-sm" href="${WEB_APP}"><span>${t("打开网页版", "Open web app")}</span>${OUT}</a></div>
        </div><p class="muted" style="font-size:14px">${t("不用安装，打开浏览器就能用。", "Nothing to install. It runs in your browser.")}</p>`,
        false,
      ),
    );
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
    const focused = $(":focus", box);
    const packageKey = focused?.closest("[data-package]")?.dataset.package;
    box.innerHTML = cards.join("");
    if (focused) {
      const replacement = $$("a, button", box).find((control) => {
        if (control.tagName !== focused.tagName) return false;
        if (packageKey) return control.closest("[data-package]")?.dataset.package === packageKey;
        return focused.href ? control.href === focused.href : control.dataset.copy === focused.dataset.copy;
      });
      replacement?.focus({ preventScroll: true });
    }
    $$("[data-intel-note]").forEach((el) => (el.hidden = Boolean(intel)));
  }

  function renderHistory(releases) {
    const box = $("#history");
    if (!box) return;
    box.innerHTML = releases
      .map((r) => {
        const notes = (r.notes[lang] && r.notes[lang].length ? r.notes[lang] : r.notes.zh) || [];
        const badge = r.channel === "beta" ? t("测试版", "Beta") : t("正式版", "Stable");
        return `<article class="release reveal in">
        <div><h3>${esc(r.version)} <span class="badge neutral">${badge}</span></h3><time datetime="${esc(r.date)}">${esc(r.date)}</time></div>
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
  function mergeReleases(manifestReleases, data) {
    /* The site archive controls which package platforms are visible, including signed assets. */
    const hidden = new Set(data.hidden || []);
    const fromManifest = manifestReleases.map((r) => ({ ...r, assets: r.assets.filter((a) => !hidden.has(a.platform)) }));
    const fromList = (data.releases || []).map((r) => {
      const assets = r.assets.filter((a) => !hidden.has(a.platform));
      const live = fromManifest.find((entry) => entry.version === r.version);
      return live ? { ...r, channel: live.channel, assets: [...live.assets, ...assets] } : { ...r, assets };
    });
    const stable = fromManifest.find((r) => r.channel === "stable");
    const beta = fromManifest.find((r) => r.channel === "beta");
    const latest = stable || fromList.find((r) => r.channel === "stable") || beta || fromList[0];
    if (!latest) return null;
    const seen = new Set();
    /* For a version in both, keep the hand-written bilingual notes from releases.json. */
    const history = [...fromList, ...fromManifest]
      .filter((r) => !seen.has(r.version) && seen.add(r.version))
      .sort((a, b) => compareVersions(b.version, a.version));
    return { latest, beta: beta && (!stable || compareVersions(beta.version, stable.version) > 0) ? beta : null, history, hidden };
  }

  async function loadReleases(onAvailable) {
    let manifestReleases = [];
    let archive = null;
    let loaded = null;
    function update() {
      // The site archive can hide even a signed package. Wait for its policy or a failed lookup.
      if (!archive) return;
      loaded = mergeReleases(manifestReleases, archive);
      if (loaded) onAvailable?.(loaded);
    }
    const live = loadManifest().catch(() => null).then((list) => {
      if (!list?.length) return;
      manifestReleases = list.map((r) => ({ ...r, live: true }));
      update();
    });
    const listed = fetch("releases.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
      .then((data) => {
        archive = {
          releases: Array.isArray(data?.releases) ? data.releases : [],
          hidden: Array.isArray(data?.hidden) ? data.hidden : [],
        };
        update();
      });
    await Promise.all([live, listed]);
    return loaded;
  }

  let site = null;
  function renderReleases() {
    if (!site) {
      if (phone === "ios") renderPrimary(null);
      return;
    }
    renderPrimary(site.latest);
    renderPlatforms(site.latest, site.beta);
    renderHistory(site.history);
  }
  if ($("#platforms")) {
    const finishPress = () => {
      if (!platformRefreshPending) return;
      platformRefreshPending = false;
      requestAnimationFrame(() => renderPlatforms(site.latest, site.beta));
    };
    for (const event of ["pointerup", "pointercancel", "keyup", "blur"]) window.addEventListener(event, finishPress);
  }
  if ($("[data-download-primary], #platforms, #history")) {
    renderReleases();
    loadReleases((loaded) => {
      site = loaded;
      renderReleases();
    });
    document.addEventListener("langchange", renderReleases);
  }

  /* ---------------- Changelog page ---------------- */
  /* The admin console publishes changelog.json next to the signed manifest. Until it does, the page
     shows the same history as the download page (manifest + releases.json). */
  const CHANGELOG_URL = `${DOWNLOAD_BASE}changelog.json`;
  const PLATFORM_NAMES = [
    ["darwin", "macOS", "macOS"],
    ["win32", "Windows", "Windows"],
    ["linux", "Linux", "Linux"],
    ["ios", "iPhone", "iPhone"],
    ["android", "Android", "Android"],
    ["web", "网页版", "Web"],
    ["server", "服务器", "Server"],
    ["nas", "NAS", "NAS"],
  ];
  const ITEM_TYPES = {
    highlight: ["亮点", "Highlight"],
    new: ["新增", "New"],
    improved: ["改进", "Improved"],
    fixed: ["修复", "Fixed"],
  };
  const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  const isText = (v) => typeof v === "string" && v.trim() !== "";

  function changelogFromAdmin(data) {
    if (!data || data.schemaVersion !== 2 || data.product !== "octop-bot" || !Array.isArray(data.releases)) return null;
    const hidden = new Set(data.hidden || []);
    const releases = data.releases
      .filter(
        (r) =>
          r &&
          isText(r.version) &&
          ["stable", "beta"].includes(r.channel) &&
          DATE_PATTERN.test(r.date) &&
          Array.isArray(r.items) &&
          r.items.every((i) => i && isText(i.zh) && isText(i.en)),
      )
      .map((r) => ({
        version: displayVersion(r.version),
        channel: r.channel,
        date: r.date,
        title: r.title && isText(r.title.zh) && isText(r.title.en) ? r.title : null,
        lines: {
          zh: r.items.map((i) => ({ type: ITEM_TYPES[i.type] ? i.type : null, text: i.zh })),
          en: r.items.map((i) => ({ type: ITEM_TYPES[i.type] ? i.type : null, text: i.en })),
        },
        platforms: (Array.isArray(r.platforms) ? r.platforms : []).filter((p) => !hidden.has(p)),
      }));
    return releases.length ? releases.sort((a, b) => compareVersions(b.version, a.version)) : null;
  }

  function changelogFromHistory(loaded) {
    if (!loaded) return null;
    return loaded.history.map((r) => ({
      version: r.version,
      channel: r.channel,
      date: r.date,
      title: null,
      lines: {
        zh: (r.notes.zh || []).map((text) => ({ type: null, text })),
        en: (r.notes.en || []).map((text) => ({ type: null, text })),
      },
      platforms: [...new Set((r.assets || []).map((a) => a.platform))].filter((p) => !loaded.hidden.has(p)),
    }));
  }

  function formatDay(day) {
    const [y, m, d] = day.split("-").map(Number);
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return t(`${y} 年 ${m} 月 ${d} 日`, `${months[m - 1]} ${d}, ${y}`);
  }

  const changelogList = $("#changelog-list");
  if (changelogList) {
    let releases = null;
    let platform = "all";
    const filterBox = $("#changelog-filter");
    /* Text from changelog.json and the release lists is only ever set with textContent. */
    const node = (tag, className, text) => {
      const el = document.createElement(tag);
      if (className) el.className = className;
      if (text !== undefined) el.textContent = text;
      return el;
    };
    const empty = (zh, en) => node("p", "cl-empty", t(zh, en));
    const render = () => {
      if (!releases) return;
      const present = PLATFORM_NAMES.filter(([key]) => releases.some((r) => r.platforms.includes(key)));
      if (!present.some(([key]) => key === platform)) platform = "all";
      filterBox.replaceChildren(
        ...[["all", "全部", "All"], ...present].map(([key, zh, en]) => {
          const btn = node("button", "", t(zh, en));
          btn.type = "button";
          btn.dataset.platform = key;
          btn.setAttribute("aria-pressed", String(key === platform));
          return btn;
        }),
      );
      const shown = releases.filter((r) => platform === "all" || r.platforms.includes(platform));
      $("#changelog-count").textContent = t(`共 ${shown.length} 个版本`, `${shown.length} releases`);
      if (!shown.length) {
        changelogList.replaceChildren(empty("这个平台还没有更新记录。", "No releases for this platform yet."));
        return;
      }
      changelogList.replaceChildren(
        ...shown.map((r) => {
          const article = node("article", "cl-release");
          article.id = "v" + r.version;
          const time = node("time", "", formatDay(r.date));
          time.dateTime = r.date;
          const body = node("div");
          const heading = node("h2", "cl-version", r.version);
          if (r === releases[0]) heading.append(node("span", "badge", t("最新", "Latest")));
          heading.append(
            node("span", "badge neutral", r.channel === "beta" ? t("测试版", "Beta") : t("正式版", "Stable")),
          );
          body.append(heading);
          if (r.title) body.append(node("p", "cl-title", r.title[lang] || r.title.zh));
          const list = node("ul");
          for (const line of r.lines[lang].length ? r.lines[lang] : r.lines.zh) {
            const item = node("li");
            if (line.type) {
              const tag = node("span", "cl-type", t(...ITEM_TYPES[line.type]));
              tag.dataset.type = line.type;
              item.append(tag);
            }
            item.append(document.createTextNode(line.text));
            list.append(item);
          }
          body.append(list);
          const names = PLATFORM_NAMES.filter(([key]) => r.platforms.includes(key));
          if (names.length) {
            const box = node("div", "cl-platforms");
            box.append(...names.map(([, zh, en]) => node("span", "", t(zh, en))));
            body.append(box);
          }
          article.append(time, body);
          return article;
        }),
      );
    };
    filterBox.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-platform]");
      if (!btn) return;
      platform = btn.dataset.platform;
      render();
    });
    fetch(CHANGELOG_URL, { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(changelogFromAdmin)
      .catch(() => null)
      .then((admin) => admin || loadReleases().then(changelogFromHistory))
      .then((list) => {
        releases = list && list.length ? list : null;
        if (releases) render();
        else
          changelogList.replaceChildren(
            empty("暂时读不到更新日志，请稍后再试。", "The changelog could not be loaded. Please try again later."),
          );
      });
    document.addEventListener("langchange", render);
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
      tabs.forEach((tab) => {
        const active = tab.dataset.panel === id;
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
      });
      panels.forEach((panel) => (panel.hidden = panel.id !== id));
    };
    tabs.forEach((tab) => tab.addEventListener("click", () => select(tab.dataset.panel)));
    wireTabKeys(tabs);
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
    document.addEventListener("langchange", apply);
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

/* Shared account navigation. */
(() => {
  const auth = window.OctopAuth;
  if (!auth) return;
  const tools = document.querySelector(".header-tools"), mobile = document.querySelector(".mobile-nav");
  const zh = () => document.documentElement.dataset.lang !== "en";
  let profile = null, quota = null, generation = 0;
  function label(cn, en) { return zh() ? cn : en; }
  const accountIdentity = document.getElementById("account-identity");
  function displayName(session) {
    return [profile?.displayName, profile?.name, profile?.nickname, session.user?.displayName, session.user?.name, session.user?.nickname]
      .find(value => typeof value === "string" && value.trim())?.trim() || label("账号", "Account");
  }
  function avatar(session, name) {
    const node = document.createElement("span"); node.className = "auth-avatar"; node.setAttribute("aria-hidden", "true");
    const initial = typeof Intl.Segmenter === "function"
      ? new Intl.Segmenter().segment(name)[Symbol.iterator]().next().value.segment
      : Array.from(name)[0];
    node.textContent = initial;
    const source = profile ? profile.avatarUrl : session.user?.avatarUrl;
    if (!source) return node;
    try {
      const url = new URL(source);
      if (url.protocol !== "https:" || url.username || url.password) return node;
    } catch (_) { return node; }
    const img = document.createElement("img");
    img.alt = ""; img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => { node.textContent = initial; }, { once: true });
    img.src = source;
    node.replaceChildren(img);
    return node;
  }
  function identity(session, name) {
    const row = document.createElement("div"); row.className = "auth-identity";
    const text = document.createElement("strong"); text.textContent = name;
    row.append(avatar(session, name), text); return row;
  }
  function render() {
    const session = auth.session();
    document.querySelectorAll(".auth-nav").forEach((el) => el.remove());
    const name = session ? displayName(session) : "";
    if (accountIdentity) accountIdentity.replaceChildren(...(session ? [identity(session, name)] : []));
    if (!session && !auth.config.loginEnabled) return;
    for (const parent of [tools, mobile]) {
      if (!parent) continue;
      const box = document.createElement("div"); box.className = "auth-nav";
      if (!session) {
        const login = document.createElement("a"); login.href = "/login.html?next=" + encodeURIComponent(auth.safePath(location.pathname + location.search + location.hash)); login.textContent = label("登录", "Sign in"); box.append(login);
      } else {
        const details = document.createElement("details"), summary = document.createElement("summary");
        const balance = document.createElement("span"); const left = quota?.availableCredits ?? quota?.creditsRemaining; balance.textContent = `✦ ${Number.isFinite(left) ? left.toLocaleString("en-US") : "—"}`;
        summary.setAttribute("aria-label", label("账号菜单", "Account menu") + " · " + name);
        summary.append(avatar(session, name), balance); details.append(summary);
        const menu = document.createElement("div"); menu.className = "auth-menu";
        const account = document.createElement("a"); account.href = "/account.html"; account.textContent = label("个人中心", "Account");
        const logout = document.createElement("button"); logout.type = "button"; logout.textContent = label("退出登录", "Sign out"); logout.addEventListener("click", () => { profile = null; quota = null; auth.logout(); });
        menu.append(identity(session, name), account, logout); details.append(menu); box.append(details);
      }
      if (parent === tools) parent.insertBefore(box, parent.querySelector(".btn-primary")); else parent.prepend(box);
    }
  }
  async function update(changed = false) {
    const id = ++generation;
    if (changed) { profile = null; quota = null; }
    render();
    const session = auth.session();
    if (!session) return;
    const profileRequest = session.scope === "recharge" ? null : auth.api("/api/user/profile", { cache: "no-store" });
    const results = await Promise.allSettled([profileRequest, auth.api("/api/user/quota")]);
    // Reading the session can synchronously notify us of a newer sign-in.
    if (!auth.session() || id !== generation) return;
    if (results[0].status === "fulfilled") profile = results[0].value;
    if (results[1].status === "fulfilled") quota = results[1].value;
    render();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && auth.session()) update(); });
  window.addEventListener("pageshow", event => { if (event.persisted && auth.session()) update(); });
  auth.onChange((_session, changed) => update(changed)); document.addEventListener("langchange", render); auth.ready.then(() => update(true));
})();
