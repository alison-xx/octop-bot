(async () => {
  const auth = window.OctopAuth;
  const params = new URLSearchParams(location.search);
  const from = auth.from(params.get("from"));
  const order = params.get("order");
  const back = document.getElementById("return");
  const retry = document.getElementById("retry");
  let copy;
  const render = () => {
    document.getElementById("status").textContent = copy[document.documentElement.dataset.lang === "en" ? 1 : 0];
  };
  function show(zh, en) { copy = [zh, en]; render(); }
  document.addEventListener("langchange", () => { if (copy) render(); });
  if (from) {
    back.href = from === "web" ? "https://bot.lynxce.cn" : "octop-bot://recharge/done";
    back.hidden = false;
    document.getElementById("app-help").hidden = from === "web";
  }
  document.getElementById("orders").hidden = false;
  retry.href = "/login.html?next=" + encodeURIComponent(auth.safePath(location.pathname + location.search));
  const signIn = () => { show("登录后查看结果", "Sign in to view the result"); retry.hidden = false; };
  await auth.ready;
  if (!auth.session()) { signIn(); return; }
  let stopped = false;
  auth.onChange((session, changed) => {
    if (!changed) return;
    stopped = true; signIn();
    if (session) location.reload();
  });
  if (!order) {
    show("没有可查询的订单，请到个人中心查看购买记录。", "No order was returned. Check your purchase history in your account.");
    return;
  }
  const deadline = Date.now() + 60000;
  async function check() {
    if (stopped) return;
    try {
      const data = await auth.api("/api/user/purchase-orders/" + encodeURIComponent(order) + "/status");
      if (stopped) return;
      const result = data.order;
      if (result.status === "refunded") { show("订单已退款。", "This order was refunded."); return; }
      if (["cancelled", "failed", "closed", "expired"].includes(result.status)) {
        show("订单已关闭或支付失败。", "The order was closed or payment failed."); return;
      }
      if (result.status === "paid") {
        if (result.needsManualRefund || result.entitlementSyncState === "blocked") {
          show("付款已确认，权益未发放，请联系客服。", "Payment confirmed. Contact support about the unfulfilled order."); return;
        }
        if (result.orderType !== "subscription" || result.entitlementSyncState === "synced") {
          const pack = result.orderType === "recharge" && Number.isFinite(result.credits);
          const zh = pack ? `支付成功，到账 ${result.credits.toLocaleString("en-US")} 积分。` : "付款已确认。";
          const en = pack ? `Payment successful. ${result.credits.toLocaleString("en-US")} credits added.` : "Payment confirmed.";
          show(zh, en);
          try {
            const q = await auth.api("/api/user/quota");
            const left = q.availableCredits ?? q.creditsRemaining;
            if (!stopped && Number.isFinite(left)) {
              const balance = left.toLocaleString("en-US");
              show(zh + ` Octop Bot 可用余额为 ${balance}。`, en + ` Available in Octop Bot: ${balance} credits.`);
            }
          } catch (_) { /* An unavailable balance does not change the confirmed payment. */ }
          return;
        }
        show("付款已确认，会员权益同步中。", "Payment confirmed. Membership is syncing.");
      } else {
        show("支付处理中…", "Payment is processing…");
      }
      if (Date.now() >= deadline) {
        show(result.status === "paid" ? "已付款，请稍后在个人中心查看权益。" : "仍在处理中，请稍后在个人中心查看。",
          result.status === "paid" ? "Payment confirmed. Check your membership later in your account." : "Still processing. Check your account later.");
      } else { setTimeout(check, 3000); }
    } catch (_) { if (!stopped) show("无法查询订单，请稍后在个人中心查看。", "Could not check the order. Check your account later."); }
  }
  await check();
})();
