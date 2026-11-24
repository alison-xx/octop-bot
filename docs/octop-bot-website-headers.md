# Octop Bot 官网：响应头、日志和登录上线前检查

官网的登录会话存放在浏览器里（正常登录存 localStorage，一次性码换来的会话存 sessionStorage）。因此打开登录开关之前，下面三条必须全部做完，再由安全岗确认（#73 的安全评审）。

## 1. CSP 和响应头（nginx）

在 `http` 上下文里设置：

```nginx
map $uri $octop_referrer_policy {
    default "strict-origin-when-cross-origin";
    ~^/(account\.html|pricing\.html|login\.html)$ "no-referrer";
    ~^/(pay|auth|oauth)/ "no-referrer";
}

# 登录回调带着一次性的码（微信 ?code=&state=，WorkBuddy 在灵策切到 # 之前是 ?code=）。
# 这几个路径的访问日志只记路径，不记 query。
map $uri $octop_log_args {
    default 1;
    ~^/(auth|oauth|pay)/ 0;
    ~^/(account|pricing|login)\.html$ 0;
}
log_format octop_site '$remote_addr - [$time_local] "$request_method $uri" $status $body_bytes_sent "$http_user_agent"';
```

在官网的 `server` 块里设置（`add_header` 要放在同一层，避免被 location 里的 `add_header` 覆盖掉）：

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; connect-src 'self' https://api.lynxce.cn https://dl.lynxce.cn https://api.github.com; img-src 'self' data: https:; media-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" always;
add_header Referrer-Policy $octop_referrer_policy always;
add_header X-Content-Type-Options "nosniff" always;

# 带码的页面不进普通访问日志；需要排查时用 octop_site 格式（只记路径）。
access_log <普通日志> combined if=$octop_log_args;
```

- `script-src 'self'`：只允许本站的脚本，不允许内联脚本和第三方脚本。`style-src` 留着 `'unsafe-inline'`，是因为页面里有 `style=""` 属性；这不影响脚本。
- 上线顺序：先把 `Content-Security-Policy` 换成 `Content-Security-Policy-Report-Only` 部署，打开首页、定价、登录、个人中心、下载、Bot 市场、更新日志几个页面，看浏览器控制台有没有 CSP 报错。没有报错就换成正式的 `Content-Security-Policy`，再验一遍。
- `website/film-src/` 是宣传片源码，不上线，部署时不要上传。

## 2. 不引入第三方脚本

- 官网的页面只能加载本站的脚本：不加统计、客服、广告，也不从 CDN 引库。需要用第三方库时，下载到仓库里由本站提供，并且要经过评审。
- `tests/unit/website/test_static_policy.py` 在 CI 里检查：`website/`（`film-src/` 除外）的页面里不能有内联 `<script>`、外部域名的脚本，也不能有 `on*=` 事件属性。
- CSP 的 `script-src 'self'` 在浏览器这一层也会拦住第三方脚本。

## 3. 用真实账号验证时

- 用浏览器的无痕窗口，验证完就关掉。不打开开发者工具的「网络」面板录屏，也不截带地址栏的图。
- 微信、WorkBuddy 回调页的地址会在页面加载时立刻被清掉；截图只截页面内容，不截地址栏。
- 不把令牌、码、`ob-auth` 的内容贴进聊天、工单、PR 或日志。
- 服务器上的访问日志按第 1 节的配置不记录带码路径的 query。验证完后，抽查一次日志里没有 `code=`。

## 4. 打开登录开关

三条都做完、安全岗确认之后，把 `website/data/auth.json` 的 `loginEnabled` 改成 `true`（走前端档提交和上线）。然后请用户各扫一次微信、走一次 WorkBuddy 登录，结果报给总管。
