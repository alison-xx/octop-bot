/* Account data is rendered as text; API shapes are mapped at the boundary. */
(() => {
  "use strict";
  const auth = window.OctopAuth;
  const content = document.getElementById("account-content");
  const notice = document.getElementById("account-notice");
  const shell = document.getElementById("account-shell");
  const shanghaiMonth = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).format(new Date());
  let month = shanghaiMonth();
  let orderPage = 1;
  let page = 1;
  let category = "全部";
  let dimension = "逐笔";
  let trend = null;
  let mode = "每日";
  let renderId = 0;
  let sessionId = 0;
  let ledgerRequestId = 0;
  auth.onChange((session, changed) => {
    if (!changed) return;
    sessionId++;
    renderId++;
    ledgerRequestId++;
    content.replaceChildren();
    trend = null; page = 1; orderPage = 1; month = shanghaiMonth();
    if (session) { if (!shell.hidden) route(); return; }
    shell.hidden = true;
    location.href = "/login.html?next=/account.html";
  });
  const translations = {
    "概览": "Overview", "用量明细": "Usage", "订单与发票": "Orders & invoices", "账号与安全": "Account & security", "登录设备": "Devices", "我的 Bot 与下载": "My Bots & downloads",
    "积分余额": "Credit balance", "当前套餐": "Current plan", "本月已用": "Used this month", "加载中…": "Loading…", "查看明细": "View usage", "查看套餐": "View plans", "积分活动": "Credit activity",
    "每日": "Daily", "每周": "Weekly", "累计": "Cumulative", "暂无用量数据": "No usage data", "接口尚未提供完整一年数据，以上统计仅覆盖已返回的日期。": "A full year of data is not available; statistics cover only the dates returned.", "点按方块查看用量": "Select a cell to see usage", "少": "Less", "多": "More",
    "全部": "All", "文本对话": "Text chat", "作图": "Images", "做视频": "Video", "云电脑": "Cloud computer", "云电脑磁盘": "Cloud computer disk", "作图 / 视频（未区分）": "Images / video (unspecified)", "其他": "Other",
    "上个月": "Previous month", "下个月": "Next month", "用量流水": "Usage history", "时间": "Time", "类别": "Category", "模型 / 内容": "Model / content", "积分": "Credits", "当前页没有记录。": "No records on this page.", "导出 CSV": "Export CSV", "上一页": "Previous", "下一页": "Next", "筛选、分组和导出仅包含当前页。": "Filtering, grouping and export cover the current page.",
    "订单": "Orders", "发票申请": "Invoice requests", "订单号": "Order number", "内容": "Type", "金额": "Amount", "状态": "Status", "仅显示最近 100 条订单。": "Only the latest 100 orders are shown.", "抬头": "Invoice title", "暂无可申请开票的订单。": "No orders are eligible for invoicing.", "申请开票": "Request invoice", "收起申请": "Close form", "退款请联系客服。": "Contact support for refunds.", "加入社群": "Join the community",
    "选择订单": "Select order", "发票类型": "Invoice type", "增值税普通发票": "Standard VAT invoice", "增值税专用发票": "Special VAT invoice", "发票抬头": "Invoice title", "税号": "Tax number", "收票邮箱": "Invoice email", "注册地址": "Registered address", "电话": "Phone", "开户行": "Bank name", "银行账号": "Bank account", "提交开票申请": "Submit invoice request", "确认提交该订单的开票申请？请先核对发票信息。": "Submit an invoice request for this order? Please check the invoice details first.",
    "绑定情况": "Linked accounts", "项目": "Item", "手机": "Phone", "邮箱": "Email", "已绑定": "Linked", "未绑定": "Not linked", "接口未提供": "Not available", "修改密码、换绑和注销需要重新验证，请前往灵策账号设置。": "To change your password, linked accounts or close your account, verify your identity in Lynxce account settings.", "前往灵策账号设置 ↗": "Open Lynxce account settings ↗", "已登记设备": "Registered devices", "设备": "Device", "平台": "Platform", "最近活动": "Last active", "网页登录不会单独列出。移除设备或全部下线需要重新验证，请前往灵策账号设置操作。": "Web logins are not listed separately. To remove devices or sign out everywhere, verify your identity in Lynxce account settings.",
    "在网页版继续使用": "Continue on the web", "用灵策账号在网页版使用协同 Bot。": "Use collaborative Bots on the web with your Lynxce account.", "打开网页版 ↗": "Open web app ↗", "下载客户端": "Download the app", "查看下载": "View downloads", "本机 Bot 只保存在你的设备上。": "Local Bots are saved only on your device.", "个人中心即将开放": "Account center coming soon", "加载失败，请稍后重试。": "Could not load. Please try again later."
  };
  const tr = (text) => document.documentElement.dataset.lang === "en" ? (translations[text] || text) : text;
  const label = (value, names) => Object.hasOwn(names, value) ? tr(names[value]) : value;
  Object.assign(translations, { "已支付": "Paid", "待支付": "Pending payment", "已取消": "Cancelled", "已退款": "Refunded", "失败": "Failed", "积分充值": "Credit recharge", "会员": "Membership", "待处理": "Pending", "已开票": "Issued", "已拒绝": "Rejected" });
  Object.assign(translations, {
    "逐笔": "Transactions", "按类别": "By category", "按模型": "By model", "当前页分组": "Group current page", "套餐": "Membership", "Octop Bot 会员": "Octop Bot membership",
    "查看订单": "View orders", "到期时间": "Expires", "未订阅会员": "No membership", "月付": "Monthly", "年付": "Yearly",
    "体验": "Trial", "标准": "Standard", "进阶": "Plus", "专业": "Pro", "卓越": "Max", "已到期": "Expired", "未生效": "Inactive",
    "选择续费或换档方案": "View renewal and plan options", "年付升档请联系客服。": "Contact support to upgrade a yearly plan.",
    "Octop Bot 可用积分": "Credits available in Octop Bot", "通用积分": "Shared credits", "Octop 专属积分": "Octop-only credits",
    "未来 30 天到期": "Expiring in 30 days", "先使用最早到期的积分。": "Credits expiring soonest are used first.",
    "买加油包": "View credit packs", "账号用量包含其他灵策产品。": "Account usage includes other Lynxce products.",
    "账号订单包含其他灵策产品。发票按当前组织显示。": "Orders include other Lynxce products. Invoices are for the current organization.",
    "本页已支付": "Paid on this page", "可开票": "Eligible for invoice", "已开票金额": "Invoiced amount",
    "可开票金额统计最近 100 笔符合条件的订单，已开票金额统计最近 200 条申请。": "Eligible amounts cover the latest 100 qualifying orders. Invoiced amounts cover the latest 200 requests.",
    "查看发票": "View invoice", "处理说明": "Details", "微信": "WeChat", "已关闭": "Closed",
    "批量申请会为每笔订单分别提交。": "Each selected order gets a separate invoice request.",
    "请选择需要开票的订单。": "Select orders to invoice.", "确认提交所选订单的开票申请？": "Submit an invoice request for each selected order?",
    "部分订单未确认提交，请刷新申请记录后重试。": "Some requests could not be confirmed. Refresh the records before retrying.",
    "刷新申请记录": "Refresh requests", "累计支付": "Total paid", "套餐状态暂无法查询，可在订单中查看购买记录。": "Membership status is unavailable. View your orders for purchase history."
  });
  const orderStatus = (v) => label(v, { paid: "已支付", pending: "待支付", cancelled: "已关闭", expired: "已关闭", refunded: "已退款", failed: "失败" });
  const orderType = (v) => label(v, { recharge: "积分充值", subscription: "会员" });
  const invoiceStatus = (v) => label(v, { pending: "待处理", issued: "已开票", rejected: "已拒绝", cancelled: "已取消" });
  const dateTime = (v) => {
    if (!v) return "—";
    const date = new Date(v);
    if (Number.isNaN(date.getTime())) return v;
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date).map(({ type, value }) => [type, value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  };
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = tr(String(text)); if (cls) n.className = cls; return n; };
  const add = (parent, ...nodes) => { parent.append(...nodes); return parent; };
  const link = (text, href, cls = "account-button") => { const a = el("a", text, cls); a.href = href; return a; };
  const button = (text, fn) => { const b = el("button", text, "account-button"); b.type = "button"; b.addEventListener("click", fn); return b; };
  const card = (title) => add(el("div", null, "account-card"), el("h3", title));
  const value = (v) => v == null ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
  const items = (response) => Array.isArray(response?.items) ? response.items : [];
  const fail = (parent, error) => add(parent, el("p", error?.message || tr("加载失败，请稍后重试。"), "account-error"));
  const request = async (path, parent) => { const id = sessionId; try { const data = await auth.api(path); return id === sessionId ? data : null; } catch (e) { if (id === sessionId) fail(parent, e); return null; } };
  const table = (headers, rows) => {
    const wrap = el("div", null, "account-table-wrap"), t = el("table"), head = el("thead"), row = el("tr"), body = el("tbody");
    headers.forEach((h) => row.append(el("th", h))); head.append(row);
    rows.forEach((cells) => { const tr = el("tr"); cells.forEach((v) => { const td = el("td"); td.append(v instanceof Node ? v : document.createTextNode(v == null ? "—" : String(v))); tr.append(td); }); body.append(tr); });
    add(t, head, body); return add(wrap, t);
  };
  // Current upstream omits metadata.type from ledger entries; never guess media categories.
  function mapLedger(x) {
    const type = x.subjectType, media = x.metadata?.type;
    const appCategory = type === "app" && ({ "云电脑": "云电脑", "Cloud Computer": "云电脑", "octop-compute": "云电脑", "云电脑磁盘": "云电脑磁盘", "Cloud Computer Disk": "云电脑磁盘", "octop-disk": "云电脑磁盘" })[x.model];
    const kind = appCategory || (type === "media" ? ({ image: "作图", video: "做视频" }[media] || "作图 / 视频（未区分）") : ({ model: "文本对话", computer: "云电脑", cloud_computer: "云电脑", disk: "云电脑磁盘", cloud_computer_disk: "云电脑磁盘" }[type] || "其他"));
    return { date: x.createdAt || "", kind, model: x.model || "—", credits: x.creditsUsed };
  }
  function mapTrend(data) {
    if (!Array.isArray(data?.days) || !Array.isArray(data?.credits)) return [];
    return data.days.map((date, i) => ({ date: String(date).slice(0, 10), credits: Number(data.credits[i]) || 0 }));
  }
  function ledgerPath(yearMonth, currentPage, size) {
    const [year, number] = yearMonth.split("-").map(Number);
    const last = new Date(Date.UTC(year, number, 0)).getUTCDate();
    const query = new URLSearchParams({ from: yearMonth + "-01T00:00:00+08:00", to: yearMonth + "-" + last + "T23:59:59.999+08:00", page: currentPage, pageSize: size });
    return "/api/user/usage-ledger?" + query;
  }
  function showBalance(box, q) {
    box.append(el("strong", value(q.availableCredits ?? q.creditsRemaining), "account-number"));
    if (q.availableCredits != null) {
      const lots = q.octopCredits;
      const expiring = lots ? lots.expiring : [];
      box.append(table(["类别", "积分"], [
        [tr("通用积分"), value(q.creditsRemaining)], [tr("Octop 专属积分"), value(lots ? lots.available : 0)],
        [tr("未来 30 天到期"), value(Array.isArray(expiring) ? expiring.reduce((sum, lot) => sum + lot.units, 0) : null)]
      ]));
      box.append(el("p", "先使用最早到期的积分。", "account-muted"));
    }
    add(box, link("查看明细", "#usage"), link("买加油包", "/pricing.html#credits"));
  }
  async function membership(box) {
    const id = renderId;
    let data;
    try { data = await auth.api("/api/user/octop-bot/membership"); } catch (_) { /* May be unavailable during the API rollout. */ }
    if (id !== renderId) return;
    const sub = data?.product === "octop_bot" ? data.subscription : undefined;
    if (sub === null) {
      box.append(el("strong", "未订阅会员", "account-number"));
    } else if (typeof sub?.active === "boolean") {
      const tiers = { trial: "体验", standard: "标准", plus: "进阶", pro: "专业", max: "卓越" };
      const name = Object.hasOwn(tiers, sub.tier) ? tr(tiers[sub.tier]) : sub.planName || tr("Octop Bot 会员");
      const status = sub.active ? name : name + " · " + tr(sub.status === "expired" ? "已到期" : sub.status === "cancelled" ? "已取消" : "未生效");
      box.append(el("strong", status, "account-number"));
      if (sub.period === "monthly" || sub.period === "yearly") box.append(el("span", sub.period === "monthly" ? "月付" : "年付"));
      if (sub.currentPeriodEnd) box.append(el("p", tr("到期时间") + " · " + dateTime(sub.currentPeriodEnd)));
      if (sub.active && sub.period === "yearly") {
        const support = button("加入社群", () => {}); support.setAttribute("data-community", "");
        add(box, el("p", "年付升档请联系客服。", "account-muted"), support);
      }
    } else {
      box.append(el("p", "套餐状态暂无法查询，可在订单中查看购买记录。", "account-muted"));
    }
    add(box, link("查看订单", "#orders"), link(sub?.active ? "选择续费或换档方案" : "查看套餐", "/pricing.html"));
  }
  async function planPage(root) {
    const box = card("Octop Bot 会员"); root.append(box);
    await membership(box);
  }
  async function overview(root) {
    const id = renderId;
    const cards = el("div", null, "account-stats"); root.append(cards);
    const balance = card("Octop Bot 可用积分"), plan = card("Octop Bot 会员"), used = card("本月已用"); add(cards, balance, plan, used);
    const activity = card("积分活动"); root.append(activity);
    used.append(el("p", "账号用量包含其他灵策产品。", "account-muted"));
    const [q, ledger, t] = await Promise.all([request("/api/user/quota", balance), request(ledgerPath(shanghaiMonth(), 1, 1), used), request("/api/user/usage-trend?days=365", activity), membership(plan)]);
    if (id !== renderId) return;
    if (q) showBalance(balance, q);
    if (ledger?.summary) {
      used.append(el("strong", value(ledger.summary.totalCredits), "account-number"));
      const group = ledger.summary.categories;
      if (group) used.append(table(["类别", "积分"], [["文本对话", group.chat], ["作图", group.image], ["做视频", group.video], ["其他", group.other]].map(([name, amount]) => [tr(name), value(amount)])));
    }
    if (t) { trend = mapTrend(t); drawActivity(activity); }
  }
  function drawActivity(box) {
    box.replaceChildren(el("h3", "积分活动"));
    const tabs = el("div", null, "account-controls"); ["每日", "每周", "累计"].forEach((m) => { const b = button(m, () => { mode = m; drawActivity(box); }); b.setAttribute("aria-pressed", String(mode === m)); tabs.append(b); }); box.append(tabs);
    if (!trend.length) { box.append(el("p", "暂无用量数据")); return; }
    let total = 0, days = 0, streak = 0, longest = 0;
    trend.forEach((d) => { total += d.credits; if (d.credits > 0) { days++; longest = Math.max(longest, ++streak); } else streak = 0; });
    box.append(el("p", document.documentElement.dataset.lang === "en" ? `${value(trend.length)} days of data · ${value(total)} credits used · ${value(days)} active days · longest streak ${value(longest)} days` : `已提供 ${value(trend.length)} 天数据 · 消耗 ${value(total)} 积分 · 使用 ${value(days)} 天 · 最长连续 ${value(longest)} 天`, "account-muted"));
    if (trend.length < 365) box.append(el("p", "接口尚未提供完整一年数据，以上统计仅覆盖已返回的日期。", "account-muted"));
    const scroll = el("div", null, "heat-scroll"), graph = el("div", null, mode === "每日" ? "heat-grid" : "heat-bars");
    const values = mode === "每日" ? trend : mode === "累计" ? trend.map((d, i) => ({ date: d.date, credits: trend.slice(0, i + 1).reduce((sum, x) => sum + x.credits, 0) })) : trend.reduce((arr, d) => { const day = new Date(`${d.date}T00:00:00Z`); day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7); const week = day.toISOString().slice(0, 10); if (!arr.length || arr[arr.length - 1].date !== week) arr.push({ date: week, credits: 0 }); arr[arr.length - 1].credits += d.credits; return arr; }, []);
    const max = Math.max(1, ...values.map((d) => d.credits));
    if (mode === "每日") { const day = new Date(`${trend[0].date}T00:00:00Z`).getUTCDay(); for (let i = 0; i < (day + 6) % 7; i++) graph.append(el("span")); }
    const hint = el("p", "点按方块查看用量", "account-muted");
    values.forEach((d) => { const label = `${d.date}: ${value(d.credits)} ${tr("积分")}${mode === "每周" ? tr("（所在周）") : mode === "累计" ? tr("（累计）") : ""}`; const cell = button("", () => { hint.textContent = label; }); cell.className = "heat-cell"; cell.title = label; cell.setAttribute("aria-label", label); cell.dataset.level = d.credits > 0 ? String(Math.max(1, Math.ceil(d.credits / max * 4))) : "0"; if (mode !== "每日") cell.style.height = `${Math.max(2, d.credits / max * 120)}px`; graph.append(cell); });
    const legend = el("div", null, "heat-legend"); legend.append(el("span", "少"));
    for (let i = 0; i <= 4; i++) { const swatch = el("span", null, "heat-cell"); swatch.dataset.level = String(i); swatch.setAttribute("aria-hidden", "true"); legend.append(swatch); }
    legend.append(el("span", "多")); add(scroll, graph); add(box, scroll, legend, hint);
  }
  async function usage(root) {
    const requestId = ++ledgerRequestId;
    const currentPage = page;
    let ledger = [];
    const controls = el("div", null, "account-controls"); root.append(controls);
    const monthText = month;
    const shift = (n) => { const [y, m] = month.split("-").map(Number); month = new Date(Date.UTC(y, m - 1 + n, 1)).toISOString().slice(0, 7); page = 1; route(); };
    add(controls, button("上个月", () => shift(-1)), el("strong", monthText), button("下个月", () => shift(1)));
    const filter = el("select"); filter.setAttribute("aria-label", tr("按类别筛选当前页")); ["全部", "文本对话", "作图", "做视频", "云电脑", "云电脑磁盘", "作图 / 视频（未区分）", "其他"].forEach((v) => { const o = el("option", v); o.value = v; filter.append(o); }); filter.value = category; filter.addEventListener("change", () => { category = filter.value; showRows(); }); controls.append(filter);
    const groupBy = el("select"); groupBy.setAttribute("aria-label", tr("当前页分组"));
    for (const name of ["逐笔", "按类别", "按模型"]) {
      const option = el("option", name); option.value = name; groupBy.append(option);
    }
    groupBy.value = dimension;
    groupBy.addEventListener("change", () => { dimension = groupBy.value; showRows(); }); controls.append(groupBy);
    const rowsBox = card("用量流水"); root.append(rowsBox);
    root.prepend(el("p", "账号用量包含其他灵策产品。", "account-muted"));
    const data = await request(ledgerPath(monthText, currentPage, 20), rowsBox);
    if (!data || requestId !== ledgerRequestId) return; ledger = items(data).map(mapLedger);
    function currentRows() {
      const rows = ledger.filter(x => category === "全部" || x.kind === category);
      if (dimension === "逐笔") {
        return [["时间", "类别", "模型 / 内容", "积分"].map(tr), ...rows.map(x => [dateTime(x.date), tr(x.kind), x.model, value(x.credits)])];
      }
      const sums = new Map();
      for (const row of rows) {
        const key = dimension === "按模型" ? row.model : tr(row.kind);
        sums.set(key, (sums.get(key) || 0) + row.credits);
      }
      return [[tr(dimension === "按模型" ? "模型 / 内容" : "类别"), tr("积分")], ...Array.from(sums, ([key, sum]) => [key, value(sum)])];
    }
    function showRows() {
      const [headers, ...rows] = currentRows();
      rowsBox.replaceChildren(el("h3", "用量流水"), table(headers, rows));
      if (!rows.length) rowsBox.append(el("p", "当前页没有记录。", "account-muted"));
    }
    showRows();
    controls.append(button("导出 CSV", () => { const dataRows = currentRows(); const csv = dataRows.map((row) => row.map((cell) => { let s = String(cell ?? ""); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return '"' + s.replace(/"/g, '""') + '"'; }).join(",")).join("\r\n"); const url = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" })); const a = link("下载", url); a.download = `usage-${monthText}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }));
    const pagination = el("div", null, "account-controls"); const prev = button("上一页", () => { page--; route(); }), next = button("下一页", () => { page++; route(); }); prev.disabled = currentPage <= 1; next.disabled = currentPage >= (data.pagination?.totalPages || 1); add(pagination, prev, el("span", document.documentElement.dataset.lang === "en" ? `Page ${value(currentPage)}` : `第 ${value(currentPage)} 页`), next); root.append(pagination, el("p", "筛选、分组和导出仅包含当前页。", "account-muted"));
  }
  async function orders(root) {
    const id = renderId;
    root.append(el("p", "账号订单包含其他灵策产品。发票按当前组织显示。", "account-muted"));
    const orderBox = card("订单"), invoiceBox = card("发票申请"); add(root, orderBox, invoiceBox);
    const [ordersData, eligible, requests] = await Promise.all([request(`/api/user/purchase-orders?page=${orderPage}&pageSize=100`, orderBox), request("/api/user/invoice-requests/orders", invoiceBox), request("/api/user/invoice-requests", invoiceBox)]);
    if (id !== renderId) return;
    if (ordersData) orderBox.append(table(["订单号", "时间", "内容", "金额", "状态"], items(ordersData).map((x) => [x.outTradeNo || x.id, dateTime(x.createdAt), orderType(x.orderType), x.amountYuan == null ? "—" : `¥${value(x.amountYuan)}`, orderStatus(x.status)])));
    const available = items(eligible).filter((x) => x.canApply);
    const amount = (rows) => "¥" + value(rows.reduce((sum, row) => sum + Math.round(row.amountYuan * 100), 0) / 100);
    if (ordersData) {
      const pages = ordersData.pagination?.totalPages || 1;
      const sumLabel = pages > 1 ? "本页已支付" : "累计支付";
      orderBox.insertBefore(el("p", tr(sumLabel) + " · " + amount(items(ordersData).filter(x => x.status === "paid"))), orderBox.children[1]);
      if (pages > 1) {
        const prev = button("上一页", () => { orderPage--; route(); }), next = button("下一页", () => { orderPage++; route(); });
        prev.disabled = orderPage <= 1; next.disabled = orderPage >= pages;
        add(orderBox, prev, el("span", ` ${orderPage} / ${pages} `), next);
      }
    }
    if (eligible) invoiceBox.append(el("p", tr("可开票") + " · " + amount(available)));
    if (requests) {
      invoiceBox.append(el("p", tr("已开票金额") + " · " + amount(items(requests).filter(x => x.status === "issued"))));
      invoiceBox.append(table(["订单", "时间", "抬头", "金额", "状态", "处理说明"], items(requests).map(x => {
        let detail = x.rejectReason || x.invoiceNumber;
        if (x.status === "issued" && /^https:\/\//i.test(x.invoiceUrl || "")) {
          detail = link(x.invoiceNumber || "查看发票", x.invoiceUrl);
          detail.rel = "noreferrer"; detail.target = "_blank";
        }
        return [x.orderId, dateTime(x.createdAt), x.title, "¥" + value(x.amountYuan), invoiceStatus(x.status), detail];
      })));
    }
    invoiceBox.append(el("p", "可开票金额统计最近 100 笔符合条件的订单，已开票金额统计最近 200 条申请。", "account-muted"));
    if (eligible && !available.length) invoiceBox.append(el("p", "暂无可申请开票的订单。", "account-muted"));
    if (available.length) {
      const form = invoiceForm(invoiceBox, available);
      form.hidden = true;
      const toggle = button("申请开票", () => { form.hidden = !form.hidden; toggle.textContent = tr(form.hidden ? "申请开票" : "收起申请"); toggle.setAttribute("aria-expanded", String(!form.hidden)); });
      toggle.setAttribute("aria-expanded", "false"); invoiceBox.insertBefore(toggle, form);
    }
    const note = el("p", "退款请联系客服。", "account-muted"), community = button("加入社群", () => {}); community.setAttribute("data-community", ""); note.append(community); root.append(note);
  }
  function invoiceForm(parent, orders) {
    const form = el("form", null, "account-form"), orderList = el("fieldset");
    orderList.append(el("legend", "选择订单"));
    orders.forEach((order) => {
      const input = el("input"); input.type = "checkbox"; input.name = "orderId"; input.value = order.orderId;
      input.checked = orders.length === 1;
      const label = el("label"); label.append(input, document.createTextNode(` ${order.outTradeNo || order.orderId} · ¥${value(order.amountYuan)}`)); orderList.append(label);
    });
    form.append(orderList, el("p", "批量申请会为每笔订单分别提交。", "account-muted"));
    const field = (label, name, type = "text", required = true) => { const l = el("label", label), i = el("input"); i.name = name; i.type = type; i.required = required; l.append(i); form.append(l); return i; };
    const typeLabel = el("label", "发票类型"), type = el("select"); type.name = "invoiceType"; [["normal", "增值税普通发票"], ["special", "增值税专用发票"]].forEach(([v, label]) => { const o = el("option", label); o.value = v; type.append(o); }); typeLabel.append(type); form.append(typeLabel);
    field("发票抬头", "title"); const tax = field("税号", "taxNumber"); tax.pattern = "[A-Za-z0-9]{15,20}"; field("收票邮箱", "email", "email");
    const extra = [["注册地址", "address"], ["电话", "phone"], ["开户行", "bankName"], ["银行账号", "bankAccount"]].map(([label, name]) => field(label, name, "text", false));
    type.addEventListener("change", () => extra.forEach((input) => { input.required = type.value === "special"; }));
    const submit = el("button", "提交开票申请", "account-button"); submit.type = "submit"; form.append(submit);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submit.disabled) return;
      const data = new FormData(form), ids = data.getAll("orderId");
      if (!ids.length) { alert(tr("请选择需要开票的订单。")); return; }
      if (!confirm(tr("确认提交所选订单的开票申请？") + " (" + ids.length + ")")) return;
      const id = renderId, session = sessionId;
      const fields = Object.fromEntries(data);
      submit.disabled = true;
      try {
        for (const orderId of ids) {
          if (id !== renderId || session !== sessionId) return;
          await auth.api("/api/user/invoice-requests", { method: "POST", body: { ...fields, orderId } });
        }
        if (id === renderId) route();
      } catch (error) {
        if (id !== renderId) return;
        fail(form, error);
        form.append(el("p", "部分订单未确认提交，请刷新申请记录后重试。"), button("刷新申请记录", route));
      }
    });
    parent.append(form); return form;
  }
  async function security(root) {
    const box = card("绑定情况"); root.append(box);
    const [p, account] = await Promise.all([request("/api/user/profile", box), request("/api/user/account", box)]); if (!p) return;
    const bound = (v) => tr(v === true ? "已绑定" : v === false ? "未绑定" : "接口未提供");
    box.append(table(["项目", "状态"], [["手机", account?.phoneMasked || bound(account ? false : null)], ["邮箱", p.emailBound ? p.email || tr("已绑定") : bound(p.emailBound)], ["微信", bound(p.wechatBound)], ["WorkBuddy", bound(p.workbuddyBound)]]));
    add(box, el("p", "修改密码、换绑和注销需要重新验证，请前往灵策账号设置。", "account-muted"), link("前往灵策账号设置 ↗", "https://admin.lynxce.cn"));
  }
  async function devices(root) {
    const box = card("已登记设备"); root.append(box); const data = await request("/api/user/login-devices", box); if (!data) return;
    const list = Array.isArray(data.devices) ? data.devices : [];
    box.append(table(["设备", "平台", "最近活动"], list.map((d) => [d.deviceName || d.name || tr("设备"), d.platform, dateTime(d.lastSeenAt)])));
    add(box, el("p", "网页登录不会单独列出。移除设备或全部下线需要重新验证，请前往灵策账号设置操作。", "account-muted"), link("前往灵策账号设置 ↗", "https://admin.lynxce.cn"));
  }
  function bots(root) { const box = card("在网页版继续使用"); add(box, el("p", "用灵策账号在网页版使用协同 Bot。"), link("打开网页版 ↗", "https://bot.lynxce.cn")); const downloads = card("下载客户端"); add(downloads, el("p", "macOS、Windows、Android 和 iPhone"), link("查看下载", "download.html")); add(root, box, downloads, el("p", "本机 Bot 只保存在你的设备上。", "account-muted")); }
  function route() {
    if (!auth.session()) return;
    ledgerRequestId++;
    const id = ++renderId; const name = location.hash.slice(1) || "overview"; const pages = { overview: ["概览", overview], plan: ["套餐", planPage], usage: ["用量明细", usage], orders: ["订单与发票", orders], security: ["账号与安全", security], devices: ["登录设备", devices], bots: ["我的 Bot 与下载", bots] }; const [title, render] = Object.hasOwn(pages, name) ? pages[name] : pages.overview;
    document.querySelectorAll("[data-section]").forEach((a) => { if (a.dataset.section === (Object.hasOwn(pages, name) ? name : "overview")) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    const root = el("div"); root.append(el("h1", title)); content.replaceChildren(root); Promise.resolve(render(root)).catch((e) => { if (id === renderId) fail(root, e); });
  }
  async function init() {
    const hasCode = /^#(?:code|ticket)=/.test(location.hash);
    if (hasCode && !(await auth.redeemHash("account"))) {
      location.replace("/login.html?next=" + encodeURIComponent("/account.html"));
      return;
    }
    await auth.ready;
    if (!auth.config.loginEnabled) { notice.textContent = tr("个人中心即将开放"); return; }
    if (!auth.requireLogin('/account.html' + location.hash)) return;
    notice.hidden = true; shell.hidden = false; window.addEventListener("hashchange", route);
    function refresh() {
      if (shell.hidden || document.hidden || !["", "#", "#overview", "#plan", "#orders"].includes(location.hash)) return;
      if (!content.querySelector("form:not([hidden]), form button[type=submit]:disabled")) route();
    }
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("pageshow", event => { if (event.persisted) refresh(); });
    route();
  }
  Object.assign(translations, { "会过期": "Expiring", "永久": "Permanent", "（所在周）": " (week)", "（累计）": " (cumulative)", "按类别筛选当前页": "Filter current page by category" });
  document.addEventListener("langchange", () => { if (!shell.hidden) route(); else if (!auth.config.loginEnabled) notice.textContent = tr("个人中心即将开放"); });
  init();
})();
