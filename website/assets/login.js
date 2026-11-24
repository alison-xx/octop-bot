(() => {
  "use strict";
  const a = window.OctopAuth, $ = (id) => document.getElementById(id);
  const next = a.safePath(new URLSearchParams(location.search).get("next"));
  let mode = "code", needsPassword = false, remaining = 0, errorCopy = null;
  const en = () => document.documentElement.dataset.lang === "en";
  const text = (zh, english) => en() ? english : zh;
  function render() {
    if (errorCopy) $("login-error").textContent = text(...errorCopy);
    $("code-field").hidden = mode === "password";
    $("password-field").hidden = mode === "code" && !needsPassword;
    $("forgot").hidden = mode !== "password";
    $("switch-mode").textContent = mode === "password" ? text("没有账号或忘了密码？用验证码登录", "No account or forgot your password? Use a code") : text("用密码登录", "Use a password");
    $("send-code").textContent = remaining ? text(`${remaining} 秒后重试`, `Try again in ${remaining}s`) : text("获取验证码", "Get code");
  }
  const type = () => $("account").value.trim().includes("@") ? "email" : "phone";
  const fail = (error) => { errorCopy = error.code === "signup_password_required" ? ["首次登录请设置密码。", "Set a password for your first sign-in."] : error.copy || ["请求失败，请检查输入后重试。", "Request failed. Check your details and try again."]; render(); };
  $("switch-mode").addEventListener("click", () => { mode = mode === "password" ? "code" : "password"; needsPassword = false; render(); });
  $("forgot").addEventListener("click", () => { mode = "reset"; needsPassword = true; render(); });
  $("send-code").addEventListener("click", async () => {
    if (remaining) return;
    const kind = type(), value = $("account").value.trim();
    try {
      if (!a.config.methods[kind]) throw Object.assign(new Error(), { copy: ["该登录方式暂不可用", "This sign-in method is unavailable"] });
      await a.api(`/api/auth/${kind}-code`, { method: "POST", auth: false, headers: { "X-Lynxce-Signup-Site": "octop-bot" }, body: { [kind]: value } });
      remaining = 60; render(); const timer = setInterval(() => { remaining--; render(); if (!remaining) clearInterval(timer); }, 1000);
    } catch (error) { fail(error); }
  });
  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault(); errorCopy = null; $("login-error").textContent = "";
    const kind = type(), value = $("account").value.trim();
    const body = mode === "password" ? { account: value, password: $("password").value } : { [kind]: value, code: $("code").value, ...((needsPassword || mode === "reset") ? { password: $("password").value } : {}) };
    if (body.password !== undefined && body.password.length < 8) { fail({ copy: ["密码至少需要 8 位", "Password must be at least 8 characters"] }); return; }
    try { if (!a.config.methods[mode === "password" ? "password" : kind]) throw Object.assign(new Error(), { copy: ["该登录方式暂不可用", "This sign-in method is unavailable"] }); const result = await a.api(`/api/auth/${mode === "password" ? "password" : kind}-login`, { method: "POST", auth: false, headers: { "X-Lynxce-Signup-Site": "octop-bot" }, body }); a.setSession(result); location.assign(next); }
    catch (error) { if (error.code === "signup_password_required") { needsPassword = true; render(); } fail(error); }
  });
  const updates = [
    ["运营：本周内容已排好", "Operations: this week's content is scheduled"],
    ["行政：会议安排已整理", "Admin: the meeting schedule is ready"],
    ["客服：客户问题已回复", "Support: customer questions answered"],
    ["财务：本月报销差异已标出", "Finance: expense discrepancies flagged"],
  ];
  let active = 0;
  function renderTeam() {
    document.querySelectorAll(".login-avatar").forEach((avatar, index) => avatar.classList.toggle("on", index === active));
    $("team-update").textContent = text(...updates[active]);
  }
  renderTeam();
  setInterval(() => { active = (active + 1) % updates.length; renderTeam(); }, 4000);
  document.addEventListener("langchange", () => { render(); renderTeam(); });
  a.ready.then(async () => {
    $("closed").hidden = a.config.loginEnabled; $("login-content").hidden = !a.config.loginEnabled;
    $("return-hint").hidden = !next.startsWith("/pricing");
    if (!a.config.loginEnabled) return;
    for (const method of ["wechat", "workbuddy"]) {
      if (!a.config.methods[method]) continue;
      try { const endpoint = method === "wechat" ? "/api/auth/wechat-web/config?site=octop-bot" : "/api/oauth/workbuddy/config?site=octop-bot"; const data = await a.api(endpoint, { auth: false, headers: { "X-Lynxce-Client": "web" } }); if (!data.enabled) continue; $(method).hidden = false; $("other-methods").hidden = false;
        $(method).addEventListener("click", () => {
          if (method === "wechat") { sessionStorage.setItem("ob-wechat-state", data.state); sessionStorage.setItem("ob-wechat-next", next); const url = new URL("https://open.weixin.qq.com/connect/qrconnect"); url.search = new URLSearchParams({ appid: data.appId, redirect_uri: data.redirectUri, response_type: "code", scope: "snsapi_login", state: data.state }); location.assign(url.href + "#wechat_redirect"); }
          else { const bytes = crypto.getRandomValues(new Uint8Array(32)); const nonce = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); sessionStorage.setItem("ob-workbuddy-login", JSON.stringify({ nonce, timestamp: Date.now() })); const url = new URL("/api/oauth/workbuddy/start", a.config.apiBase); url.search = new URLSearchParams({ site: "octop-bot", signupSite: "octop-bot", returnTo: next, clientState: nonce }); location.assign(url.href); }
        });
      } catch (_) {}
    }
  });
})();
