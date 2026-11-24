(async () => {
  let statusCopy = null;
  const setStatus = (zh, en) => { statusCopy = [zh, en]; renderStatus(); };
  function renderStatus() { if (statusCopy) document.getElementById("status").textContent = document.documentElement.dataset.lang === "en" ? statusCopy[1] : statusCopy[0]; }
  document.addEventListener("langchange", renderStatus);
  // The hand-off code moves from ?code= to #code=; read the hash first, then the query.
  const a = window.OctopAuth, params = new URLSearchParams(location.search), hash = new URLSearchParams(location.hash.slice(1));
  const code = hash.get("code") || params.get("code"), next = a.safePath(params.get("next") || hash.get("next"));
  history.replaceState(null, "", location.pathname);
  let attempt;
  try { attempt = JSON.parse(sessionStorage.getItem("ob-workbuddy-login")); } catch (_) {}
  sessionStorage.removeItem("ob-workbuddy-login");
  if (!attempt || typeof attempt.nonce !== "string" || !attempt.nonce || !Number.isFinite(attempt.timestamp) || Date.now() - attempt.timestamp < 0 || Date.now() - attempt.timestamp > 10 * 60 * 1000) {
    setStatus("这次登录不是从本浏览器发起的，请重新登录", "This sign-in was not started in this browser. Please sign in again.");
    document.getElementById("retry").hidden = false;
    return;
  }
  try {
    if (!code || params.has("error") || hash.has("error")) throw new Error("授权未完成，请重试。");
    const data = await a.api("/api/oauth/workbuddy/session", { method: "POST", auth: false, body: { code, clientState: attempt.nonce }, headers: { "X-Lynxce-Signup-Site": "octop-bot" } });
    a.setSession(data); location.assign(next);
  } catch (err) {
    if (err && err.code === "workbuddy_client_state_mismatch") setStatus("登录已失效，请重新用 WorkBuddy 登录", "This sign-in expired. Please sign in with WorkBuddy again.");
    else setStatus("授权未完成，请重试。", "Authorization was not completed. Please try again.");
    document.getElementById("retry").hidden = false;
  }
})();
