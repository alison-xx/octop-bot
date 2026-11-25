# Octop Bot 官网响应头

先部署以下报告模式并观察一天，确认没有 CSP 报错后，将 `Content-Security-Policy-Report-Only` 改为 `Content-Security-Policy`。按部署环境配置报告收集和其他必要的响应头。

```nginx
add_header Content-Security-Policy-Report-Only "script-src 'self'; connect-src 'self' https://dl.lynxce.cn https://api.lynxce.cn https://api.github.com; img-src 'self' data: https:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;

# 使用下方 map 区分路径，避免丢失其他 add_header。
```

在 `http` 上下文设置：

```nginx
map $uri $octop_referrer_policy {
    default "";
    ~^/(account\.html|pricing\.html|login\.html)$ "no-referrer";
    ~^/(pay|auth|oauth)/ "no-referrer";
}
```

在同一层与 CSP 一起配置，避免 nginx 的 `add_header` 继承规则覆盖其他响应头：

```nginx
add_header Referrer-Policy $octop_referrer_policy always;
```

`website/film-src/` 是宣传片源码，不属于线上静态站；部署时不要上传 `film-src/`。
