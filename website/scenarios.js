(() => {
  const section = document.getElementById("scenarios");
  if (!section) return;

  const strings = {
    zh: {
      title: "把自己的任务交给 Bot",
      intro: "选一个工作场景，把提示词带进你的工作区。",
      tabs: "工作场景", deliverable: "交付物", roles: "谁来做", setup: "开始前",
      copy: "复制提示词", copied: "提示词已复制", failed: "请选中上方文字，手动复制。",
      cases: [
        {
          tab: "内容工作室", heading: "把一个选题写成开头",
          deliverable: "三个选题角度，以及一段可继续修改的开场白。",
          roles: "选题策划比较切入点，文案写作根据你选的角度起草，群管理员汇总定稿。",
          setup: "给 Chief 配置支持工具调用的模型，再告诉它你想写给谁看。",
          target: "发给 Chief",
          prompt: "建一个内容工作室群，请选题策划和文案写作加入。我们要给第一次参加读书会的人写招募文案。先提三个切入角度，等我选一个，再围绕它写一段开场白。"
        },
        {
          tab: "项目复盘", heading: "从会议记录里找出下一步",
          deliverable: "一份复盘清单，列出已确认的决定、待办、负责人和仍待确认的问题。",
          roles: "记录员从材料中摘出决定，复核员核对出处，管理员把结果整理到一起。",
          setup: "让 Chief 组建复盘群，加入记录员和复核员。将会议记录作为群附件上传，再发送提示词。",
          target: "发到复盘群",
          prompt: "请记录员从我上传的会议记录中整理决定和待办，并附上对应原句。请复核员核对负责人和日期。材料没写的地方标为待确认，最后由管理员汇总成一张清单。"
        },
        {
          tab: "工作日简报", heading: "每天准备好晨会提纲",
          deliverable: "一份晨会简报，包含昨天的进展、今天的优先事项和需要跟进的问题。",
          roles: "让简报 Bot 担任编辑。你提供最新进展，它按固定格式整理，缺少的信息留给你补充。",
          setup: "在 Bot 资料的「定时任务」选择工作日和时间。本机任务需要服务运行；关机后执行请在云端工作区配置任务，并提供云端可读的材料。",
          target: "填入定时任务",
          prompt: "根据提供给你的最新工作记录，整理一份晨会提纲。按昨日进展、今日优先、待跟进问题分三段，每个要点写成一句话。如没有新的工作记录，请提醒我补充。"
        }
      ]
    },
    en: {
      title: "Put your team to work.",
      intro: "Pick a workflow and take its prompt into your workspace.",
      tabs: "Workflows", deliverable: "What you get", roles: "Who does what", setup: "Before you start",
      copy: "Copy prompt", copied: "Prompt copied", failed: "Select the text above and copy it manually.",
      cases: [
        {
          tab: "Content studio", heading: "Turn an idea into an opening line",
          deliverable: "Three editorial angles and an opening paragraph you can edit.",
          roles: "The planner explores angles, the writer develops your choice, and the group admin brings the draft together.",
          setup: "Connect Chief to a model that supports tool calling. Tell it who you are writing for.",
          target: "Send to Chief",
          prompt: "Create a content studio group with a planner and a writer. We’re recruiting first-time book club members. Suggest three angles, wait for me to pick one, then draft an opening paragraph around it."
        },
        {
          tab: "Project review", heading: "Turn meeting notes into next steps",
          deliverable: "A review sheet with confirmed decisions, actions, owners and open questions.",
          roles: "A note-taker extracts decisions, a reviewer checks them against the source, and the group admin compiles the list.",
          setup: "Ask Chief to create a review group with a note-taker and reviewer. Attach your meeting notes in the group, then send the prompt.",
          target: "Send to the review group",
          prompt: "Ask the note-taker to list decisions and actions from the attached meeting notes, quoting the relevant line for each. Ask the reviewer to check owners and dates. Mark missing details as open, then have the group admin compile one checklist."
        },
        {
          tab: "Weekday briefing", heading: "Have a stand-up brief ready",
          deliverable: "A morning brief covering yesterday’s progress, today’s priorities and follow-up questions.",
          roles: "Give your briefing bot the editor role. You supply progress notes and it turns them into a brief, flagging gaps for you.",
          setup: "In the bot’s scheduled tasks, choose weekdays and a time. Local runs need the service online. For runs while your computer is off, schedule a cloud task and supply materials it can access.",
          target: "Use in a scheduled task",
          prompt: "Turn the latest work notes provided to you into a stand-up brief. Use three sections: yesterday’s progress, today’s priorities and follow-up questions. Write one sentence per item. If there are no new notes, ask me to add them."
        }
      ]
    }
  };
  let selected = 0;
  let currentLanguage;

  const el = (tag, className, content) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content) node.textContent = content;
    return node;
  };

  function select(index) {
    selected = index;
    section.querySelectorAll('[role="tab"]').forEach((tab, i) => {
      const active = i === index;
      tab.setAttribute("aria-selected", String(active));
      tab.classList.toggle("ant-tabs-bar-active", active);
      tab.tabIndex = active ? 0 : -1;
    });
    section.querySelectorAll('[role="tabpanel"]').forEach((panel, i) => {
      panel.hidden = i !== index;
      panel.querySelector('[role="status"]').textContent = "";
    });
  }

  function render() {
    const language = document.documentElement.lang.startsWith("zh") ? "zh" : "en";
    if (currentLanguage === language) return;
    currentLanguage = language;
    const copy = strings[language];
    const head = el("div", "section-head");
    const title = el("h2", "", copy.title);
    title.id = "scenario-heading";
    section.setAttribute("aria-labelledby", title.id);
    head.append(title, el("p", "", copy.intro));
    const tabs = el("div", "scenario-tabs ant-tabs-bar");
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", copy.tabs);
    const panels = copy.cases.map((item, i) => {
      const tab = el("button", "ant-tabs-bar-item ant-tabs-bar-capsule");
      tab.append(el("span", "ant-tabs-bar-capsule-title", item.tab));
      const panel = el("div", "scenario-panel");
      tab.type = "button";
      tab.id = "scenario-tab-" + i;
      panel.id = "scenario-panel-" + i;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", panel.id);
      tabs.append(tab);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      panel.tabIndex = 0;

      const brief = el("div", "scenario-brief");
      const facts = el("dl");
      for (const key of ["deliverable", "roles", "setup"]) {
        const row = el("div");
        row.append(el("dt", "", copy[key]), el("dd", "", item[key]));
        facts.append(row);
      }
      brief.append(el("h3", "", item.heading), facts);
      const sample = el("div", "scenario-sample");
      const prompt = el("blockquote", "", item.prompt);
      const actions = el("div", "scenario-actions");
      const button = el("button", "scenario-copy", copy.copy);
      button.type = "button";
      button.dataset.antButton = "default";
      button.dataset.antSize = "small";
      window.AntMini.button(button);
      const status = el("span", "scenario-status");
      status.setAttribute("role", "status");
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(item.prompt);
          if (selected === i) status.textContent = copy.copied;
        } catch {
          if (selected !== i) return;
          const range = document.createRange();
          range.selectNodeContents(prompt);
          const selection = window.getSelection();
          selection?.removeAllRanges();
          selection?.addRange(range);
          status.textContent = copy.failed;
        }
      });
      actions.append(button, status);
      sample.append(el("h4", "", item.target), prompt, actions);
      panel.append(brief, sample);
      return panel;
    });
    window.AntMini.tabs(tabs, () => selected, select);
    tabs.addEventListener("keydown", event => {
      const count = copy.cases.length;
      const target = { ArrowLeft: (selected + count - 1) % count, ArrowRight: (selected + 1) % count,
        Home: 0, End: count - 1 }[event.key];
      if (target === undefined) return;
      event.preventDefault();
      const nextTab = tabs.querySelectorAll('[role="tab"]')[target];
      nextTab.focus();
      nextTab.click();
    });
    section.replaceChildren(head, tabs, ...panels);
    select(selected);
  }
  window.addEventListener("sitepreferenceschange", render);
  render();
})();
