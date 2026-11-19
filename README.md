# Octop Bot

[简体中文](README.md) · [English](README_EN.md) · [产品官网](https://octop-bot.lynxce.cn/)

Octop Bot 是一款运行在 Windows 和 Apple Silicon Mac 上的桌面应用。告诉八爪鱼助手 Chief 你想完成什么，它可以创建分工不同的 Bot，让它们在同一个群里接力工作。你也可以只和一位成员长聊，或者把适合在云端执行的任务交给灵策。

在 **30 秒产品短片**里看 Chief 如何拉上策划与写手，为读书会定下一句招募文案。可以看[中文短片](https://octop-bot.lynxce.cn/media/intro-zh.mp4)、[英文短片](https://octop-bot.lynxce.cn/media/intro-en.mp4)，也可以亲自切换[交互演示](https://octop-bot.lynxce.cn/#demo)中的协作阶段。

## 客户端下载 · 1.0.3-beta.7

| 平台 | 安装包 | 校验 |
| --- | --- | --- |
| Windows x64 | [安装版 EXE](https://octop-bot.lynxce.cn/downloads/1.0.3-beta.7/Octop-Bot-Setup-1.0.3-beta.7-x64.exe) · [免安装 ZIP](https://octop-bot.lynxce.cn/downloads/1.0.3-beta.7/Octop-Bot-1.0.3-beta.7-x64.zip) | [SHA-256 校验值](https://octop-bot.lynxce.cn/downloads/1.0.3-beta.7/SHA256SUMS.txt) |
| macOS Apple Silicon（M 系列芯片） | [磁盘映像 DMG](https://github.com/alison-xx/octop-bot/releases/download/octop-bot-v1.0.3-beta.7-macos/Octop-Bot-1.0.3-beta.7-mac-arm64.dmg) | [SHA-256 校验值](https://github.com/alison-xx/octop-bot/releases/download/octop-bot-v1.0.3-beta.7-macos/Octop-Bot-1.0.3-beta.7-mac-arm64.dmg.sha256) · [版本说明](https://github.com/alison-xx/octop-bot/releases/tag/octop-bot-v1.0.3-beta.7-macos) |

Windows 可按安装向导操作，或完整解压 ZIP 后打开文件夹里的 `Octop Bot.exe`。Mac 打开 DMG，把 **Octop Bot** 拖入「应用程序」后启动。两个平台的安装包都内置了 Python 和本地 Octop 服务。

![Octop Bot 群聊实拍。Chief 把一份周末城市指南交给调研、编辑和设计三位成员。](https://octop-bot.lynxce.cn/assets/screen-team-zh.webp)

*截图来自 Windows 客户端。文中的城市编辑部、聊天和云端任务均为演示数据。*

## 第一次使用

1. **打开工作区。** 首次启动后点击「开始使用」。进入本机工作区，你会在团队通讯录里看到自己的 Chief。
2. **连接聊天模型。** 选择「灵策智算账号」，在系统浏览器完成授权，返回客户端选择并保存一个可用模型。使用模型时，灵策会从这个账号扣除积分。也可以选择「其他模型来源」，连接自己的云服务、自定义兼容地址或本机模型。「稍后配置」可以先浏览团队，发消息前再连接模型。
3. **如果还没有灵策账号，** 点击「注册灵策智算账号」，在官网选择「注册」标签。完成后回到客户端，按原来的入口登录或授权。[灵策账号官网](https://admin.lynxce.cn/profile/login)
4. **把第一条消息交给 Chief。** 新手引导会带你认识私聊、分组和云端工作区。选择建团队、做计划或分配工作的示例，点「在 Chief 对话中编辑」。修改草稿后点发送。以后可从通讯录底部的「账号与模型 → 新手引导」重新打开。

![首次使用引导，可选择一个示例交给 Chief。](https://octop-bot.lynxce.cn/assets/screen-guide-zh.webp)

连接灵策后，可在「账号与模型」查看积分余额。点「充值」会在系统浏览器打开该账号的灵策充值页。如果以前仅授权过聊天，第一次充值时点「授权充值」，在灵策确认后即可继续。重新绑定账号后，请从该账号可用的聊天模型中选一个并保存。返回客户端会刷新余额，也可以点余额旁的刷新图标。

如果想试试截图里的城市编辑部，可以把这段文字贴给 Chief，再换成你自己的项目。自动建队需要使用支持工具调用的模型。

> 请帮我创建「周末城市指南」群。邀请一位调研员核对路线，一位编辑写开篇，一位设计师画地图。第一期是 90 分钟的河岸散步，请先给我三个候选站点。

## 让团队一起工作

| 你想做什么 | 从哪里开始 |
| --- | --- |
| 和某位 Bot 继续聊 | 单击通讯录成员即可恢复最近私聊。点击对话顶部的名字可打开资料，调整头像、角色或模型。工作中可用 `/side` 私下追问。 |
| 让几位成员一起交付 | 在「＋」中新建群聊，或请 Chief 建群。在群中发需求，用 `@` 点名成员。复杂任务可以在 Goal 里约定验收条件、阶段和负责人。 |
| 整理项目成员 | 右键通讯录空白处新建分组或批量移组；右键成员可移入已有分组。右键分组标题可以改名、设置颜色、调整顺序，或用组内 Bot 发起群聊。解散分组会保留成员和聊天。 |
| 找回上次说过的话 | 按 `Ctrl+K`（Mac 用 `⌘K`）搜索成员和分组。切到「历史私聊」，输入标题或消息关键词，可回到原会话。 |

![编辑与设计分组的右键菜单，可整理成员、用组内 Bot 发起群聊、调整顺序或解散分组。](https://octop-bot.lynxce.cn/assets/screen-groups-zh.webp)

### 换成自己的项目

| 工作场景 | 可以怎样开场 | 最后看什么 |
| --- | --- | --- |
| 项目复盘 | 在群里附上会议记录，让记录员摘出决定和待办，复核员核对负责人和日期。 | 得到一张带原文依据的清单，材料未写清的事项标为「待确认」。 |
| 工作日晨会 | 把最新工作记录交给简报 Bot，在它的资料面板设置工作日定时任务，分别整理昨日进展、今日优先和待跟进问题。 | 读完简报可以继续追问。本机调度需要 Octop 服务运行；云端调度需要配置云端可读的材料。 |

[到官网复制完整场景提示词](https://octop-bot.lynxce.cn/#scenarios)。

## 关机后继续工作

打开通讯录底部的**云端工作区**，单独登录灵策账号。这里可以新建云端会话，或设置定时任务。在另一台电脑上登录同一灵策账号，即可查看已接收任务的状态和结果，并继续对话。云端可用的模型、权限和积分取决于当前账号。工作区顶部显示当前云端账号的积分，点「充值」可为这个账号充值。

- **带上已有会话。** 在本机 Bot 的私聊中点击顶部名字，选择「把当前私聊带到云端」。先预览，再确认。一次最多带入最近 20 条可见文字，附件、工具记录和思考过程留在本机。
- **安排定时任务。** 在「云端定时任务」填写指令和时间。电脑关机后，已保存的云端任务仍按配置的时区执行。任务完成后，点「打开结果并续聊」。
- **把本机任务转到云端。** 先在 Bot 资料的「定时任务」里暂停原任务，再选「用此配置创建云端任务」，核对指令与时间后保存。本机文件、脚本和已安装的应用留在这台电脑上。依赖这些资源的任务应在本机运行，并保持电脑唤醒、Octop Bot 在后台运行。

![云端定时任务实拍，展示晨间选题简报、周五路线校对和已暂停的读者来信整理。](https://octop-bot.lynxce.cn/assets/screen-cloud-zh.webp)

Windows 独立版默认将本机工作区保存在 `%USERPROFILE%\.octop-bot`。群文件、共享笔记、头像设置和电脑控制等操作见[使用指南](docs/octop-bot.md)。

## 从源码运行

准备 Git、uv、Node.js 24 和 pnpm 12.15.0。在 Windows PowerShell 中运行以下命令。

```powershell
git clone https://github.com/alison-xx/octop-bot.git
cd octop-bot
uv sync --frozen --python 3.12 --extra browser --extra computer-use --extra desktop
npm --prefix dashboard ci
pnpm --dir desktop/src install --frozen-lockfile
.\desktop\src\scripts\run-dev.ps1 -Bot
```

脚本构建 Electron，并启动本地 Octop 服务和前端开发服务器。开发版使用独立数据目录 `desktop/src/.dev-runtime/windows/bot-home`。

### 构建 Windows x64 安装包

在已装好上述依赖的 Windows x64 环境中，从仓库根目录运行以下命令。

```powershell
uv run --frozen python desktop/src/scripts/package-bot-windows.py
```

脚本编译前端、构建 Octop wheel，并随包附上 Python 运行时。安装程序、免安装 ZIP 和解包后的客户端位于 `desktop/src/release/octop-bot/`。发布带 Authenticode 签名的版本时，先把环境变量 `OCTOP_BOT_SIGN_CERT_SHA1` 设置为发布者在 Windows 证书存储中的证书指纹。打包程序使用 SHA-256 和 RFC 3161 时间戳签署客户端、卸载程序和安装程序。

## 源码与许可

| 目录 | 内容 |
| --- | --- |
| [desktop/src](desktop/src/) | Electron 主进程、预加载脚本、启动与打包 |
| [dashboard/src/pages/OctopBot](dashboard/src/pages/OctopBot/) | 通讯录、群聊、账号与云端工作区界面 |
| [src/octop](src/octop/) | Python 服务、会话、定时调度与灵策接口 |
| [tests](tests/) | 后端单元与集成测试 |

项目保留上游 Octop 的提交历史和 MIT 许可证。部分角色图形改编自 DS Bot，公式渲染使用了 Deep View 的代码。[上游 Octop](https://github.com/TencentCloud/Octop/tree/976803d6292dfb2e28e525823aa28d2e33a755a8) · [MIT 许可证](LICENSE) · [DS Bot 声明](dashboard/public/licenses/ds-bot.txt) · [Deep View 声明](dashboard/public/licenses/deep-view.txt)
