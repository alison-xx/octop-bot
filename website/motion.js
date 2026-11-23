(() => {
  const header = document.querySelector("body > header");
  const art = document.querySelector(".hero-art");
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)");

  if (header) {
    const line = document.createElement("span");
    line.className = "reading-line";
    line.setAttribute("aria-hidden", "true");
    header.append(line);

    // Let the compositor follow the scroll position on supporting browsers.
    if (!CSS.supports("animation-timeline: scroll(root block)")) {
      let scheduled = 0;
      function paint() {
        scheduled = 0;
        const distance = document.documentElement.scrollHeight - innerHeight;
        const value = distance > 0 ? Math.min(1, Math.max(0, scrollY / distance)) : 0;
        line.style.transform = "scaleX(" + value + ")";
      }
      function queuePaint() {
        if (!scheduled && !document.hidden) scheduled = requestAnimationFrame(paint);
      }
      addEventListener("scroll", queuePaint, { passive: true });
      addEventListener("resize", queuePaint);
      document.addEventListener("visibilitychange", queuePaint);
      if ("ResizeObserver" in window) new ResizeObserver(queuePaint).observe(document.body);
      queuePaint();
    }
  }
  if (!art) return;

  let frame = 0;
  let pointerX = 0;
  let pointerY = 0;
  function paintArt() {
    frame = 0;
    const rect = art.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = Math.max(-1, Math.min(1, 2 * (pointerX - rect.left) / rect.width - 1));
    const y = Math.max(-1, Math.min(1, 2 * (pointerY - rect.top) / rect.height - 1));
    art.style.setProperty("--art-x", (7 * x).toFixed(2) + "px");
    art.style.setProperty("--art-y", (5 * y).toFixed(2) + "px");
    art.classList.add("is-tracking");
  }
  function move(event) {
    if (event.pointerType === "touch" || document.hidden) return;
    pointerX = event.clientX;
    pointerY = event.clientY;
    if (!frame) frame = requestAnimationFrame(paintArt);
  }
  function reset() {
    cancelAnimationFrame(frame);
    frame = 0;
    art.classList.remove("is-tracking");
    art.style.removeProperty("--art-x");
    art.style.removeProperty("--art-y");
  }
  function configure() {
    reset();
    art.removeEventListener("pointermove", move);
    if (finePointer.matches && !reduceMotion.matches && !document.hidden) {
      art.addEventListener("pointermove", move, { passive: true });
    }
  }
  art.classList.add("motion-art");
  art.addEventListener("pointerleave", reset);
  art.addEventListener("pointercancel", reset);
  document.addEventListener("visibilitychange", configure);
  finePointer.addEventListener("change", configure);
  reduceMotion.addEventListener("change", configure);
  configure();
})();
