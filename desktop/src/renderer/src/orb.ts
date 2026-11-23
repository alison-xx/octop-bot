import mascot from "./assets/orb-bubble.png";
import "./orb.css";

const button = document.querySelector("button")!;
const chinese = navigator.language.toLowerCase().startsWith("zh");
document.documentElement.lang = chinese ? "zh-CN" : "en";
button.title = chinese
  ? "Octop Bot · 点击打开快捷菜单，拖动调整位置"
  : "Octop Bot · Click for shortcuts, drag to move";
button.setAttribute("aria-label", button.title);
button.querySelector("img")!.src = mascot;
const orb = window.botOrb!;
let start: { id: number; x: number; y: number } | null = null;
let dragged = false;
button.onpointerdown = (event) => {
  if (event.button !== 0 || start) return;
  button.setPointerCapture(event.pointerId);
  start = { id: event.pointerId, x: event.screenX, y: event.screenY };
  dragged = false;
  orb.pointer("start");
};
button.onpointermove = (event) => {
  if (event.pointerId !== start?.id || !start) return;
  const dx = event.screenX - start.x;
  const dy = event.screenY - start.y;
  if (!dragged && Math.hypot(dx, dy) < 4) return;
  dragged = true;
  button.dataset.dragging = "true";
  orb.pointer("move", dx, dy);
};
button.onlostpointercapture = () => {
  start = null;
  delete button.dataset.dragging;
  orb.pointer("end");
};
button.onclick = (event) => {
  if (!dragged || event.detail === 0) orb.pointer("menu");
};
button.oncontextmenu = (event) => {
  event.preventDefault();
  orb.pointer("menu");
};
