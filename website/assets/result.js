(async () => {
  let statusCopy = null;
  const setStatus = (zh, en) => { statusCopy = [zh, en]; renderStatus(); };
  function renderStatus() { if (statusCopy) document.getElementById("status").textContent = document.documentElement.dataset.lang === "en" ? statusCopy[1] : statusCopy[0]; }
  document.addEventListener("langchange", renderStatus);
  const a = window.OctopAuth, params = new URLSearchParams(location.search), status = document.getElementById("status");
  const from = a.from(params.get("from")), order = params.get("order");
  const back = document.getElementById("return");
  if (from) { back.href = from === "web" ? "https://bot.lynxce.cn" : "octop-bot://recharge/done"; back.hidden = false; }
  document.getElementById("orders").hidden = false;
  document.getElementById("retry").href = "/login.html?next=" + encodeURIComponent(a.safePath(location.pathname + location.search));
  await a.ready;
  if (!a.session()) { setStatus("登录后查看结果", "Sign in to view the result"); document.getElementById("retry").hidden = false; return; }
  if (!order || params.get("recharge") !== "paid") { setStatus("支付已取消或失败。", "Payment was cancelled or failed."); return; }
  const deadline = Date.now() + 60000;
  async function check() {
    try {
      const data = await a.api("/api/user/purchase-orders/" + encodeURIComponent(order) + "/status");
      const result = data.order || data;
      if (data.paid || result.status === "paid") {
        const quota = await a.api("/api/user/quota");
        const fmt = (v) => (Number.isFinite(Number(v)) && v !== null && v !== "" ? Number(v).toLocaleString("en-US") : "—");
        const added = fmt(result.credits ?? result.creditAmount);
        const left = fmt(quota.creditsRemaining ?? quota.balance ?? quota.remaining);
        setStatus(`支付成功。到账 ${added} 积分，当前余额 ${left}。`, `Payment successful. ${added} credits added; current balance: ${left}.`); return;
      }
      if (["cancelled", "canceled", "failed", "closed", "expired"].includes(result.status)) { setStatus("支付已取消或失败。", "Payment was cancelled or failed."); return; }
      if (Date.now() >= deadline) { setStatus("仍在处理中，请稍后在个人中心查看。", "Still processing. Please check your account later."); return; }
      setStatus("支付处理中…", "Payment is processing…"); setTimeout(check, 3000);
    } catch (_) { setStatus("无法查询订单，请稍后在个人中心查看。", "Could not check the order. Please check your account later."); }
  }
  check();
})();
