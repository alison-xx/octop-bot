(async () => {
  let statusCopy = null;
  const setStatus = (zh, en) => { statusCopy = [zh, en]; renderStatus(); };
  function renderStatus() { if (statusCopy) document.getElementById("status").textContent = document.documentElement.dataset.lang === "en" ? statusCopy[1] : statusCopy[0]; }
  document.addEventListener("langchange", renderStatus);
  const a = window.OctopAuth, params = new URLSearchParams(location.search), state = params.get("state"), code = params.get("code");
  const expected = sessionStorage.getItem("ob-wechat-state"), next = a.safePath(sessionStorage.getItem("ob-wechat-next"));
  sessionStorage.removeItem("ob-wechat-state"); sessionStorage.removeItem("ob-wechat-next"); history.replaceState(null, "", location.pathname);
  const status = document.getElementById("status"), retry = document.getElementById("retry"), headers = { "X-Lynxce-Client": "web", "X-Lynxce-Signup-Site": "octop-bot" };
  try {
    if (!state || state !== expected || !code) throw new Error("扫码已失效，请重新扫码。");
    const data = await a.api("/api/auth/wechat-web/login", { method: "POST", auth: false, headers, body: { code, state } });
    if (!data.needBindPhone) { a.setSession(data); location.assign(next); return; }
    setStatus("请先绑定手机号。", "Please bind your phone number."); document.getElementById("bind").hidden = false;
    document.getElementById("send").addEventListener("click", async () => { try { await a.api("/api/auth/phone-code", { method: "POST", auth: false, headers, body: { phone: document.getElementById("phone").value } }); setStatus("验证码已发送。", "Verification code sent."); } catch (_) { setStatus("发送失败，请重试。", "Could not send the code. Please try again."); } });
    document.getElementById("bind").addEventListener("submit", async (event) => { event.preventDefault(); try { const result = await a.api("/api/auth/wechat-web/bind-phone", { method: "POST", auth: false, headers, body: { bindToken: data.bindToken, phone: document.getElementById("phone").value, code: document.getElementById("code").value } }); a.setSession(result); location.assign(next); } catch (_) { setStatus("绑定失败，请重试。", "Could not bind your phone. Please try again."); } });
  } catch (_) { setStatus("扫码已失效，请重新扫码。", "The scan has expired. Please try again."); retry.hidden = false; }
})();
