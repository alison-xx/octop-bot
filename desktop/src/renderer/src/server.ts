import "./server.css";

const zh = navigator.language.toLowerCase().startsWith("zh");
document.documentElement.lang = zh ? "zh-CN" : "en";
const t = zh
  ? {
      title: "连接到自建服务器",
      hint: "填写你自建 Octop 服务器的公网地址。连接后 Octop Bot 会重新打开，并在那台服务器上登录。",
      placeholder: "https://octop.example.com",
      connect: "连接",
      checking: "正在检查…",
      cancel: "取消",
      local: "改用本机服务",
      empty: "请填写服务器地址。",
      invalid: "地址格式不对，请填写类似 https://octop.example.com 的地址。",
      insecure: "公网地址需要使用 HTTPS；局域网地址可以用 http://。",
      unreachable: "连接不上这个地址，请确认服务器已启动，且这台电脑能访问。",
      "not-octop": "这个地址上没有找到 Octop 服务器。",
      loopback: "这是这台电脑自己的地址。要用这台电脑，请点「使用本机服务」。",
    }
  : {
      title: "Connect to your own server",
      hint: "Enter the public address of your Octop server. Octop Bot reopens and signs in there.",
      placeholder: "https://octop.example.com",
      connect: "Connect",
      checking: "Checking…",
      cancel: "Cancel",
      local: "Use this computer's service",
      empty: "Enter the server address.",
      invalid: "That doesn't look like an address. Try https://octop.example.com.",
      insecure: "Public addresses need HTTPS; http:// works only on your local network.",
      unreachable: "Couldn't reach that address. Check the server is running and reachable from this computer.",
      "not-octop": "No Octop server was found at that address.",
      loopback: "That's this computer's own address. To use this computer, choose the local service instead.",
    };

const bridge = window.octopServer!;
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const form = $<HTMLFormElement>("form");
const address = $<HTMLInputElement>("address");
const error = $<HTMLParagraphElement>("error");
const connect = $<HTMLButtonElement>("connect");
const local = $<HTMLButtonElement>("local");
const recent = $<HTMLUListElement>("recent");

$("title").textContent = t.title;
$("hint").textContent = t.hint;
address.placeholder = t.placeholder;
connect.textContent = t.connect;
$("cancel").textContent = t.cancel;
local.textContent = t.local;

$("cancel").onclick = () => bridge.close();
document.onkeydown = (event) => {
  if (event.key === "Escape") bridge.close();
};
address.oninput = () => {
  error.textContent = "";
};
local.onclick = () => {
  local.disabled = true;
  void bridge.useLocal();
};

form.onsubmit = async (event) => {
  event.preventDefault();
  connect.disabled = true;
  connect.textContent = t.checking;
  error.textContent = "";
  const result = await bridge.connect(address.value);
  if (!result.ok) {
    error.textContent = (t as Record<string, string>)[result.reason] ?? t.unreachable;
    connect.disabled = false;
    connect.textContent = t.connect;
    address.focus();
  }
};

void bridge.state().then(({ current, recent: origins }) => {
  local.hidden = current === null;
  address.value = current ?? "";
  for (const origin of origins) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = origin;
    button.onclick = () => {
      address.value = origin;
      form.requestSubmit();
    };
    item.append(button);
    recent.append(item);
  }
});
