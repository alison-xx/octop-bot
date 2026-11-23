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
  root.dataset.os = os;

  const formatSize = (bytes) => `${(bytes / 1e6).toFixed(0)} MB`;
  const assetUrl = (release, asset) => `${DOWNLOAD_BASE}${release.version}/${asset.name}`;
  const pick = (release, platform, kind) =>
    release.assets.find((a) => a.platform === platform && (!kind || a.kind === kind));

  const OS_ICON = {
    win: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 5.1 10.4 4v7.2H3V5.1Zm0 13.8 7.4 1.1v-7.1H3v6Zm8.3 1.2L21 21.5v-8.6h-9.7v7.2ZM11.3 3.9v7.3H21V2.5l-9.7 1.4Z"/></svg>',
    mac: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16.4 12.6c0-2.4 2-3.6 2.1-3.7-1.1-1.7-2.9-1.9-3.5-1.9-1.5-.2-2.9.9-3.7.9-.8 0-1.9-.9-3.2-.8-1.6 0-3.1 1-4 2.4-1.7 3-.4 7.4 1.2 9.8.8 1.2 1.8 2.5 3 2.4 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8c1.3 0 2.2-1.2 3-2.4.9-1.4 1.3-2.7 1.3-2.8 0 0-2.6-1-2.6-3.9ZM14 5.4c.7-.8 1.1-1.9 1-3-1 0-2.1.7-2.8 1.5-.6.7-1.2 1.8-1 2.9 1.1.1 2.1-.6 2.8-1.4Z"/></svg>',
  };
  const ARROW =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12m0 0-5-5m5 5 5-5M5 20h14"/></svg>';

  function primaryChoice(release) {
    if (os === "win") {
      const a = pick(release, "win32", "installer");
      return a && { href: assetUrl(release, a), label: t("下载 Windows 版", "Download for Windows"), sub: `x64 · ${formatSize(a.size)}`, icon: OS_ICON.win };
    }
    if (os === "mac") {
      const a = pick(release, "darwin");
      return a && { href: assetUrl(release, a), label: t("下载 macOS 版", "Download for Mac"), sub: `${t("Apple 芯片", "Apple silicon")} · ${formatSize(a.size)}`, icon: OS_ICON.mac };
    }
    return null;
  }

  function renderPrimary(release) {
    const choice = primaryChoice(release);
    $$("[data-download-primary]").forEach((btn) => {
      if (choice) {
        btn.href = choice.href;
        btn.setAttribute("download", "");
        btn.innerHTML = `${choice.icon}<span>${choice.label}</span>`;
      } else {
        btn.href = "download.html";
        btn.removeAttribute("download");
        btn.innerHTML = `${ARROW}<span>${t("选择版本下载", "Choose a download")}</span>`;
      }
    });
    $$("[data-download-note]").forEach((el) => {
      el.textContent = choice
        ? `${t("版本", "Version")} ${release.version} · ${choice.sub} · ${t("免费开源", "Free & open source")}`
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
      <a class="btn ${recommended ? "btn-primary" : "btn-ghost"} btn-sm" href="${assetUrl(release, asset)}" download>${ARROW}<span>${t("下载", "Download")}</span></a>
      <div class="sha"><span>SHA-256</span><code title="${asset.sha256}">${asset.sha256}</code><button class="copy" type="button" data-copy="${asset.sha256}">${t("复制", "Copy")}</button></div>
    </div>`;
  }

  function renderPlatforms(release) {
    const box = $("#platforms");
    if (!box) return;
    const win = pick(release, "win32", "installer");
    const zip = pick(release, "win32", "portable");
    const mac = pick(release, "darwin");
    const cards = [];
    if (win || zip) {
      cards.push(`<article class="platform${os === "win" ? " detected" : ""}">
        <div class="platform-head">${OS_ICON.win}<div><h3 class="h3">Windows</h3><small class="muted">Windows 10 / 11 · x64</small></div>${os === "win" ? `<span class="badge">${t("你的系统", "Your system")}</span>` : ""}</div>
        <div class="files">
          ${win ? fileRow(release, win, t("安装版", "Installer"), "EXE", true) : ""}
          ${zip ? fileRow(release, zip, t("免安装版", "Portable"), t("ZIP · 解压即用", "ZIP · unzip and run"), false) : ""}
        </div></article>`);
    }
    if (mac) {
      cards.push(`<article class="platform${os === "mac" ? " detected" : ""}">
        <div class="platform-head">${OS_ICON.mac}<div><h3 class="h3">macOS</h3><small class="muted">${t("Apple 芯片（M 系列）", "Apple silicon (M-series)")}</small></div>${os === "mac" ? `<span class="badge">${t("你的系统", "Your system")}</span>` : ""}</div>
        <div class="files">${fileRow(release, mac, t("磁盘映像", "Disk image"), "DMG · arm64", true)}</div>
        <p class="muted" style="font-size:14px">${t("暂不支持 Intel 芯片的 Mac。", "Intel-based Macs are not supported yet.")}</p>
      </article>`);
    }
    box.innerHTML = cards.join("");
  }

  function renderHistory(releases) {
    const box = $("#history");
    if (!box) return;
    box.innerHTML = releases
      .map(
        (r, i) => `<article class="release reveal in">
        <div><h3>${r.version}${i === 0 ? ` <span class="badge" style="vertical-align:middle">${t("最新", "Latest")}</span>` : ""}</h3><time datetime="${r.date}">${r.date}</time></div>
        <div><ul>${(r.notes[lang] || r.notes.zh || []).map((n) => `<li>${n}</li>`).join("")}</ul>
        <p style="margin-top:16px"><a class="link" href="${DOWNLOAD_BASE}${r.version}/SHA256SUMS.txt">${t("该版本全部安装包的 SHA-256", "SHA-256 for every package in this release")} <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17 17 7M8 7h9v9"/></svg></a></p></div>
      </article>`,
      )
      .join("");
  }

  let releasesData = null;
  function renderReleases() {
    if (!releasesData) return;
    const latest = releasesData.releases[0];
    renderPrimary(latest);
    renderPlatforms(latest);
    renderHistory(releasesData.releases);
  }
  if ($("[data-download-primary], #platforms, #history")) {
    fetch("releases.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        releasesData = data;
        renderReleases();
      })
      .catch(() => {
        /* static fallbacks in the HTML stay usable */
      });
    document.addEventListener("langchange", renderReleases);
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const done = () => {
      btn.classList.add("done");
      btn.textContent = t("已复制", "Copied");
      toast(t("校验值已复制", "Checksum copied"));
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
