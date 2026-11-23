const stages = [
  {
    room: ["Chief 私聊", "Chat with Chief"],
    messages: [
      ["person", "帮我建一个内容工作室。新品下周上线，我需要选题策划和文案写作。", "Build me a content studio. Our product launches next week. I need a planner and a writer."],
      ["chief", "我建好了「内容工作室」，也把选题策划和文案写作拉进了群。来群里聊聊这次新品吧。", "Your Content studio is ready. I’ve brought the planner and writer into the group. Let’s brief them there."]
    ]
  },
  {
    room: ["内容工作室", "Content studio"],
    messages: [
      ["chief", "@选题策划 先定一个切入点。@文案写作 接着用这个角度写开头。", "@Planner, pick an angle. @Writer, use it to draft the opening."],
      ["planner", "从一个具体场景切入：发布前一天，团队还在三个窗口里来回找文件。", "Start the day before launch, with the team hunting through three windows for the right file."],
      ["writer", "开头草稿：「明天就上线了。海报在群里，定稿在邮件里，改过的标题又去哪了？」", "Opening draft: “We launch tomorrow. The poster’s in chat, the final copy’s in email. Where did that revised headline go?”"]
    ]
  },
  {
    room: ["内容工作室 · 团队汇总", "Content studio · Team summary"],
    messages: [
      ["chief", "大家选定了「发布前一天」这个场景。首段已有草稿，下一段可以接团队如何在同一个群里交接文件。", "We agreed on the day-before-launch angle. The opening is drafted. The next paragraph can show the team handing off files in a single group chat."],
      ["person", "保留这个开头。下一版加上设计师交付海报的例子。", "Keep that opening. In the next draft, add an example of the designer handing over the poster."]
    ]
  }
];
const names = { person:["你","You"], chief:["Chief","Chief"], planner:["选题策划","Planner"], writer:["文案写作","Writer"] };
const controls = [...document.querySelectorAll("[data-stage]")];
const translations = [];
for (const [attribute, property] of [["data-en","textContent"], ["data-aria-en","aria-label"], ["data-alt-en","alt"]]) {
  for (const node of document.querySelectorAll("[" + attribute + "]")) {
    const zh = property === "textContent" ? node.textContent : node.getAttribute(property);
    translations.push({ node, property, zh, en:node.getAttribute(attribute) });
  }
}
const preferencesBar = document.querySelector(".prefs");
const pickers = [...preferencesBar.querySelectorAll("[data-pref]")];
let openPicker = null;
function closePreferenceMenu(restoreFocus = false) {
  if (!openPicker) return;
  const trigger = openPicker.querySelector(".pref-trigger");
  trigger.setAttribute("aria-expanded", "false");
  openPicker.querySelector(".pref-menu").hidden = true;
  openPicker = null;
  if (restoreFocus) trigger.focus();
}
function openPreferenceMenu(picker) {
  closePreferenceMenu();
  openPicker = picker;
  picker.querySelector(".pref-trigger").setAttribute("aria-expanded", "true");
  picker.querySelector(".pref-menu").hidden = false;
  picker.querySelector('[aria-checked="true"]').focus({preventScroll:true});
}
for (const picker of pickers) {
  const trigger = picker.querySelector(".pref-trigger");
  const options = [...picker.querySelectorAll("[data-value]")];
  trigger.addEventListener("click", () => {
    if (openPicker === picker) closePreferenceMenu(true);
    else openPreferenceMenu(picker);
  });
  trigger.addEventListener("keydown", event => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    openPreferenceMenu(picker);
  });
  options.forEach((option,index) => {
    option.addEventListener("click", () => {
      sitePreferences.set(picker.dataset.pref, option.dataset.value);
      closePreferenceMenu(true);
    });
    option.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        event.preventDefault();
        closePreferenceMenu(true);
        return;
      }
      const next = {ArrowDown:(index+1)%options.length, ArrowUp:(index+options.length-1)%options.length, Home:0, End:options.length-1}[event.key];
      if (next !== undefined) {
        event.preventDefault();
        options[next].focus();
      }
    });
  });
}
document.addEventListener("pointerdown", event => {
  if (openPicker && !preferencesBar.contains(event.target)) closePreferenceMenu();
});
document.addEventListener("focusin", event => {
  if (openPicker && !openPicker.contains(event.target)) closePreferenceMenu();
});
const video = document.getElementById("intro-video");
const chapterButtons = [...document.querySelectorAll("[data-seek]")];
const tourButtons = [...document.querySelectorAll("[data-view]")];
const screenImage = document.getElementById("screen-shot");
const lightbox = document.getElementById("lightbox");
const captions = {
  team: ["Chief 在群里交代周末城市指南的任务。调研、编辑和设计三位成员在同一段对话中接手。", "Chief briefs the City Desk on a weekend guide. Research, editorial and design pick up their assignments in the same conversation."],
  groups: ["右键分组标题，可以调整成员和顺序，也可以用组里的 Bot 发起群聊。", "Open the group menu to organise members, reorder the directory or start a chat with the bots in that group."],
  cloud: ["晨间选题简报安排在工作日 08:30。任务运行后，可以打开结果续聊，也可以暂停下次执行。", "The morning pitch brief runs at 08:30 on weekdays. Open a completed result to continue the conversation, or pause future runs."],
  guide: ["在新手引导里挑一个起点，把示例带到 Chief 私聊，改好任务再发送。", "Pick a starting point in the guide. Open the example in your chat with Chief, edit the brief and send it when ready."]
};
let view = "team";
let stage = 0;
let currentLanguage;
function showView() {
  const caption = captions[view][Number(currentLanguage === "en")];
  const selected = tourButtons.find(button => button.dataset.view === view);
  screenImage.src = "assets/screen-" + view + "-" + currentLanguage + ".webp";
  screenImage.alt = caption;
  document.getElementById("screen-caption").textContent = caption;
  document.getElementById("shot-title").textContent = selected.querySelector("b").textContent;
  tourButtons.forEach(button => button.setAttribute("aria-pressed", String(button === selected)));
  if (lightbox.open) lightbox.querySelector("img").src = screenImage.src;
}
function showChapter() {
  const active = chapterButtons.filter(button => video.currentTime >= Number(button.dataset.seek)).at(-1);
  chapterButtons.forEach(button => button.setAttribute("aria-current", button === active ? "step" : "false"));
}
function drawStage() {
  const en = currentLanguage === "en";
  const index = Number(en);
  const sample = stages[stage];
  document.getElementById("room").textContent = sample.room[index];
  const rows = sample.messages.map(([role, zh, english]) => {
    const row = document.createElement("div");
    row.className = "message";
    const avatar = document.createElement("span");
    avatar.className = "avatar " + role;
    avatar.setAttribute("aria-hidden", "true");
    if (role === "chief") {
      const img = new Image();
      img.src = "assets/chief.webp";
      img.alt = "";
      avatar.append(img);
    } else {
      const shape = {planner:"sparkle", writer:"heart"}[role];
      if (shape) {
        avatar.innerHTML = '<svg viewBox="0 0 100 100"><use href="#bot-' + shape + '"/></svg>';
      } else {
        avatar.textContent = en ? "Y" : "你";
      }
    }
    const content = document.createElement("div");
    const sender = document.createElement("b");
    sender.textContent = names[role][index];
    const bubble = document.createElement("p");
    bubble.textContent = en ? english : zh;
    content.append(sender,bubble);
    row.append(avatar,content);
    return row;
  });
  document.getElementById("conversation").replaceChildren(...rows);
  controls.forEach((button, i) => button.setAttribute("aria-pressed", String(i === stage)));
  document.querySelectorAll(".progress i").forEach((dot,i) => dot.classList.toggle("active", i <= stage));
  document.querySelector("#next-stage span").textContent = stage === stages.length - 1 ? (en ? "Start again" : "重新体验") : (en ? "Next stage" : "下一阶段");
}
function refresh() {
  const {language} = sitePreferences.resolve();
  for (const picker of pickers) {
    for (const option of picker.querySelectorAll("[data-value]")) {
      option.setAttribute("aria-checked", String(option.dataset.value === sitePreferences.values[picker.dataset.pref]));
    }
  }
  if (language === currentLanguage) return;
  const position = video.currentTime;
  const resume = !video.paused && !video.ended;
  const showCaptions = video.textTracks[0]?.mode === "showing";
  currentLanguage = language;
  translations.forEach(({node,property,zh,en}) => {
    const value = language === "en" ? en : zh;
    if (property === "textContent") node.textContent = value;
    else node.setAttribute(property,value);
  });
  const en = language === "en";
  document.getElementById("lang-value").textContent = en ? "EN" : "中文";
  document.title = en ? "Octop Bot · Your AI team" : "Octop Bot · 你的 AI 团队";
  document.querySelector('meta[name="description"]').content = en ? "Meet Chief, your octopus assistant. Build an AI team with one prompt and share work in a group chat." : "认识 Octop Bot 和你的八爪鱼助手 Chief。用一句话组建 AI 团队，在群聊里分工、交接、汇总。";
  video.poster = "media/intro-" + language + ".webp";
  video.src = "media/intro-" + language + ".mp4?v=2";
  const track = document.createElement("track");
  track.kind = "captions";
  track.srclang = en ? "en" : "zh";
  track.label = en ? "English" : "简体中文";
  track.src = "media/intro-" + language + ".vtt";
  track.default = showCaptions;
  video.replaceChildren(track);
  if (position > 0 && !video.ended) video.currentTime = position;
  if (resume) video.play().catch(() => {});
  showView();
  showChapter();
  drawStage();
}
controls.forEach((button, i) => button.addEventListener("click", () => { stage = i; drawStage(); }));
document.getElementById("next-stage").addEventListener("click", () => { stage = (stage + 1) % stages.length; drawStage(); });
window.addEventListener("sitepreferenceschange", refresh);
document.getElementById("watch").addEventListener("click", () => video.play().catch(() => {}));
chapterButtons.forEach(button => button.addEventListener("click", () => {
  video.currentTime = Number(button.dataset.seek);
  video.play().catch(() => {});
}));
video.addEventListener("timeupdate", showChapter);
tourButtons.forEach(button => button.addEventListener("click", () => {
  view = button.dataset.view;
  showView();
}));
document.querySelector(".location-choice fieldset").addEventListener("change", event => {
  const selectedPanel = event.target.getAttribute("aria-controls");
  document.querySelectorAll(".location-result article").forEach(panel => {panel.hidden = panel.id !== selectedPanel;});
});
document.querySelectorAll("[data-open-view]").forEach(link => link.addEventListener("click", () => {
  view = link.dataset.openView;
  showView();
}));
document.getElementById("zoom-shot").addEventListener("click", () => {
  const image = lightbox.querySelector("img");
  image.src = screenImage.src;
  image.alt = screenImage.alt;
  lightbox.showModal();
});
document.getElementById("close-shot").addEventListener("click", () => lightbox.close());
lightbox.addEventListener("click", event => {
  if (event.target !== lightbox) return;
  const rect = lightbox.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) lightbox.close();
});
const navLinks = [...document.querySelectorAll(".bar nav a[href^='#']")];
const observedSections = navLinks.map(link => document.querySelector(link.hash));
function highlightSection() {
  const offset = document.querySelector("header").offsetHeight + 80;
  const active = observedSections.find(section => {
    const bounds = section.getBoundingClientRect();
    return bounds.top <= offset && bounds.bottom > offset;
  });
  for (const link of navLinks) {
    if (active && link.hash === "#" + active.id) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}
const observer = new IntersectionObserver(highlightSection, {rootMargin:"-18% 0px -60% 0px"});
observedSections.forEach(section => observer.observe(section));
refresh();
