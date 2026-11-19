# Octop Bot

<img src="dashboard/src/assets/avatars/octop-mascot.webp" width="88" alt="Octop Bot 的八爪鱼助手 Chief" />

Octop Bot 是基于 Octop 的独立 Electron 桌面客户端。你可以和八爪鱼助手 Chief 私聊，让它创建有不同分工的 Bot，或把几位成员拉进同一个群聊协作。连接灵策智算账号后，还可以把任务交给云端，在另一台电脑上接着聊。

**Windows x64 下载**　[安装程序](https://github.com/alison-xx/octop-bot/releases/download/octop-bot-v1.0.3-beta.7/Octop-Bot-Setup-1.0.3-beta.7-x64.exe) · [免安装 ZIP](https://github.com/alison-xx/octop-bot/releases/download/octop-bot-v1.0.3-beta.7/Octop-Bot-1.0.3-beta.7-x64.zip) · [版本说明与校验值](https://github.com/alison-xx/octop-bot/releases)

## 第一次使用

1. 打开 Octop Bot，点击「开始使用」。选择「灵策智算账号」、其他模型来源，或者「稍后配置」。本机聊天需要先连接可用模型。
2. 选择灵策时，在系统浏览器完成账号授权，回到客户端选定聊天模型。模型调用使用该账号的积分和额度。
3. 给 Chief 发一句「帮我建一个自媒体团队，安排选题策划、文案写作和视觉设计」。使用支持工具调用的模型时，Chief 可以创建成员并组建群聊。打开群聊后，可以直接发需求，也可以用 `@` 指定成员。

## 日常操作

| 想做什么 | 从哪里开始 |
| --- | --- |
| 整理通讯录 | 右键空白处新建分组。右键 Bot 或群聊可以移入已有分组，或为当前条目建组。 |
| 找回对话 | 按 `Ctrl+K` 搜索团队，切到「历史私聊」可按标题或消息内容查找。 |
| 调整 Bot | 点击私聊顶部的名字，修改角色、头像或聊天模型。Chief 和角色头像支持动效，并跟随系统的减少动态效果设置。 |
| 换电脑接着聊 | 打开通讯录底部的「云端工作区」，登录灵策账号。在另一台电脑登录同一账号，打开原云端会话即可继续。 |
| 关机后执行任务 | 在「云端工作区 → 云端定时任务」设定指令和时间。灵策调度器执行后，可点「打开结果并续聊」。 |

云端工作区首次使用时需要单独登录。现有本机私聊可以在 Bot 资料里选择「把当前私聊带到云端」，预览并确认要带入的文字。云端任务使用账号的权限、模型和积分。已经在本机运行的定时任务要转到云端时，先暂停原任务，再选择「用此配置创建云端任务」。

Windows 独立版默认把本机数据保存在 `%USERPROFILE%\.octop-bot`。更多操作见[使用指南](docs/octop-bot.md)。

## 从源码启动 Windows 客户端

准备 Git、uv、Node.js 24 和 pnpm 12.15.0。在 PowerShell 中运行以下命令。

```powershell
git clone https://github.com/alison-xx/octop-bot.git
cd octop-bot
uv sync --frozen --python 3.12 --extra browser --extra computer-use --extra desktop
npm --prefix dashboard ci
pnpm --dir desktop/src install --frozen-lockfile
.\desktop\src\scripts\run-dev.ps1 -Bot
```

脚本会构建 Electron 并启动本地 Octop 服务和前端开发服务器。开发版使用独立的数据目录 `desktop/src/.dev-runtime/windows/bot-home`。

## 构建 Windows x64 安装包

在已安装上述依赖的 Windows x64 环境中，从仓库根目录运行以下命令。

```powershell
uv run --frozen python desktop/src/scripts/package-bot-windows.py
```

构建脚本会编译前端、构建本仓库的 Octop wheel，并把 Python 运行时一起打包。安装程序、免安装 ZIP 和解包后的客户端位于 `desktop/src/release/octop-bot/`。安装版和免安装版均可直接在 Windows 上运行。

发布带 Authenticode 签名的版本时，在运行打包命令前将环境变量 `OCTOP_BOT_SIGN_CERT_SHA1` 设为发布者在 Windows 证书存储中的签名证书指纹。打包程序使用 SHA-256 和 RFC 3161 时间戳签署客户端、卸载程序和安装程序。

## 源码与许可

| 目录 | 内容 |
| --- | --- |
| [desktop/src](desktop/src/) | Electron 主进程、预加载脚本、启动与打包 |
| [dashboard/src/pages/OctopBot](dashboard/src/pages/OctopBot/) | 通讯录、角色、群聊、账号与云端工作区界面 |
| [src/octop](src/octop/) | Python 服务、会话、定时调度与灵策接口 |
| [tests](tests/) | 后端单元与集成测试 |

本项目基于 [TencentCloud/Octop](https://github.com/TencentCloud/Octop/tree/976803d6292dfb2e28e525823aa28d2e33a755a8)，保留上游提交历史和 [MIT 许可证](LICENSE)。角色图形和部分内容渲染代码的来源与许可分别见 [DS Bot 声明](dashboard/public/licenses/ds-bot.txt)和 [Deep View 声明](dashboard/public/licenses/deep-view.txt)。
