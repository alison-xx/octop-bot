/* Shared Lynxce session for website pages. */
(() => {
  "use strict";
  const defaults = { apiBase: "https://api.lynxce.cn", loginEnabled: false, methods: {}, checkoutEnabled: false, oneTimeCodeEnabled: false };
  const listeners = new Set();
  let current = null;
  let limited = false;
  let refreshPromise = null;
  try { current = JSON.parse(sessionStorage.getItem("ob-limited-auth") || localStorage.getItem("ob-auth") || "null"); limited = !!sessionStorage.getItem("ob-limited-auth"); } catch (_) {}
  const auth = { config: defaults };
  const notify = () => listeners.forEach((fn) => fn(auth.session()));
  auth.ready = fetch(new URL("../data/auth.json", document.currentScript.src)).then((r) => { if (!r.ok) throw new Error("config"); return r.json(); }).then((config) => { auth.config = { ...defaults, ...config }; }).catch(() => {});
  auth.safePath = (value) => {
    if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u001f]/.test(value) || /^\/login/i.test(value) || /%5c|%2f|%0[0-9a-f]|%1[0-9a-f]/i.test(value)) return "/";
    try { const url = new URL(value, location.origin); return url.origin === location.origin && !url.pathname.startsWith("//") && !/^\/login/i.test(url.pathname) ? url.pathname + url.search + url.hash : "/"; } catch (_) { return "/"; }
  };
  auth.from = (value) => ["desktop", "web", "android"].includes(value) ? value : null;
  auth.session = () => current && current.token ? { token: current.token, user: current.user || null } : null;
  auth.setSession = (data, restricted = false) => {
    const token = data.accessToken || data.token;
    if (!token) throw Object.assign(new Error("Missing access token"), { code: "invalid_session" });
    current = { token, refreshToken: data.refreshToken || null, user: data.user || null };
    limited = restricted;
    sessionStorage.removeItem("ob-limited-auth");
    if (restricted) { sessionStorage.setItem("ob-limited-auth", JSON.stringify(current)); } else { localStorage.setItem("ob-auth", JSON.stringify(current)); }
    notify();
  };
  auth.logout = () => { current = null; limited = false; localStorage.removeItem("ob-auth"); sessionStorage.removeItem("ob-limited-auth"); notify(); };
  auth.onChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
  auth.requireLogin = (next) => { if (auth.session()) return true; location.href = "/login.html?next=" + encodeURIComponent(auth.safePath(next)); return false; };
  async function request(path, options = {}, retry = true) {
    await auth.ready;
    if (!path.startsWith("/api/") || path.startsWith("//") || path.includes("\\")) throw Object.assign(new Error("Invalid API path"), { code: "invalid_path" });
    const base = new URL(auth.config.apiBase);
    if (base.origin !== "https://api.lynxce.cn" && !(base.protocol === "http:" && base.hostname === "127.0.0.1")) throw Object.assign(new Error("Invalid API origin"), { code: "invalid_origin" });
    const headers = new Headers(options.headers || {});
    headers.set("X-Lynxce-App", "octopbot");
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
    const accessToken = options.auth !== false ? current?.token : null;
    if (accessToken) headers.set("Authorization", "Bearer " + accessToken);
    const response = await fetch(new URL(path, base.origin), { method: options.method || "GET", headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), redirect: "error" });
    let payload = {}; try { payload = await response.json(); } catch (_) {}
    if (response.status === 401 && options.auth !== false && current && retry) {
      if (current.token !== accessToken) return request(path, options, false);
      if (!refreshPromise) refreshPromise = (async () => {
        if (!current.refreshToken || limited) throw new Error("No refresh token");
        let tokens;
        try { tokens = await request("/api/auth/refresh", { method: "POST", auth: false, body: { refreshToken: current.refreshToken } }, false); }
        catch (error) { auth.logout(); throw error; }
        auth.setSession({ ...tokens, user: current.user });
      })().finally(() => { refreshPromise = null; });
      await refreshPromise;
      return request(path, options, false);
    }
    if (!response.ok || (payload.code !== undefined && payload.code !== 0)) {
      const detail = payload.error || payload;
      throw Object.assign(new Error(detail.message || "Request failed"), { code: detail.code || response.status });
    }
    return payload.data === undefined ? payload : payload.data;
  }
  auth.api = request;
  auth.redeemHash = async () => {
    await auth.ready;
    const match = location.hash.match(/^#(?:ticket|code)=([^&]+)$/);
    if (!match) return false;
    const code = decodeURIComponent(match[1]);
    history.replaceState(null, "", location.pathname + location.search);
    if (!auth.config.oneTimeCodeEnabled) return false;
    try { const data = await request("/api/auth/login-codes/redeem", { method: "POST", auth: false, body: { code } }); auth.setSession(data, true); return true; } catch (_) { return false; }
  };
  window.OctopAuth = auth;
})();
