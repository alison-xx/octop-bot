# Octop Bot 插件路线（issue #28 路线调整）

> 状态：用户已批准（2026-11-25），按 §3 分批推进。
> 前一版路线见 `octop-bot-upstream-sync.md`：终点是“pip 装 `octop` + 一个通过 `octop.extensions` 入口接入的 `octop_bot` Python 包”。本文把终点改成用户拍板的形态。

## 0. 结论

1. **终点**：装官方 Octop，再装一个「Octop Bot」插件。Bot 自己的后端、数据表、配置、文案和界面都在这个插件里。fork 仓库只留插件源码、桌面壳、手机端和官网，不再带 `src/octop`。
2. **在官方插件机制上补能力。** 现在的插件一个只能做一件事：工具、技能、模型调用前后的 hook、IM 通道，四选一，界面也只能渲染工具结果。Bot 需要的服务端能力要逐项补成“插件能力”提给上游。
3. **已合进上游的 #3129 不白做。** 它是服务端扩展的运行时：启停钩子、挂路由、免登录路径。插件路线只把装载方式从“pip 包 + entry point”换成“插件压缩包 + `plugin.yaml` 声明”，下面挂的还是同一套钩子。所以在途的 #3130、#3131、#3141、#3142 都能直接改成“插件能力”继续推，不需要撤回任何 PR。
4. **第一批是“插件清单 v2 + 插件携带系统配置”**（2026-11-25 用户确认）。一个插件可以声明多种能力；插件不写代码，就能在清单里带上模型供应商预设、供应商、默认模型和白名单内的系统设置，装上或启用即生效。服务端能力（插件注册扩展对象，交给 #3129 的加载器）后移到 P2。清单给以后的主题（P7）留好位置。

## 1. 官方插件机制现在能做什么

代码：`src/octop/infra/agents/plugins/`（Octop 侧：安装、市场、启用、界面文件），`octop_harness.plugins`（harness 侧：清单、`PluginContext`、注册表）。说明文档：上游 `docs/plugin-package.md`、`docs/plugin-channels.md`。

| 方面 | 现状 |
|---|---|
| 分发 | ZIP 或目录，装到 `~/.octop/plugins/<id>/`；支持从市场、URL、本地文件安装；限制压缩包 100 MiB、解压后 64 MiB、最多 2000 个文件 |
| 清单 | `plugin.yaml`，必填 `id`、`version`；`kind` 只能是 `tool` / `skill` / `hook` / `channel` 之一，缺省 `tool` |
| 入口 | `setup(ctx)`。**只能调用和 `kind` 对应的注册方法**，别的方法会抛 `ValueError`（`octop_harness/plugins/context.py`） |
| 能力 | `ctx.tool(...)` 工具、`ctx.skills(dir)` 技能、`ctx.middleware(...)` 模型调用前后的中间件、`ctx.channel(...)` IM 通道 |
| 依赖 | `requires` 和 `requirements.txt` 在加载时用 pip 安装 |
| 启用 | 全局开关 `plugins.enabled`；工具在每个 Agent 上默认开，Agent 可以单独关 |
| 界面 | `ui.entry` 指向预构建的 ESM，只能 `registerRenderer` 渲染工具返回的卡片，**不能加页面或导航项** |
| 生命周期 | 安装 / 卸载 / 启停都能热加载；启动时 `load_installed()` 在打开数据库之前执行 |
| 预装 | `bundled/` 目录加 `seed_bundled()`，产品可以随安装包带插件 |

结论：现在的插件只能挂在 Agent 运行时上，服务端（路由、数据表、账号、存储、配置、页面）一项都装不下。

## 2. 装下 Bot 需要补的能力

下表“Bot 现在怎么做”指 fork 里对上游文件的改动（详见 `octop-bot-upstream-sync.md` §1：改了 64 个上游后端文件、约 30 处挂钩点，另有 54 个上游前端文件）。

| 能力 | Bot 用在哪 | 上游落点 | 状态 |
|---|---|---|---|
| **多能力清单** | 一个插件同时带工具、技能、hook 等 | harness `PluginManifest` / `PluginContext` | 已提 [octop-harness#303](https://github.com/TencentCloud/octop-harness/pull/303)（P1） |
| **系统配置** | 灵策供应商预设和供应商、默认模型、默认时区等 | Octop `PluginManager` 在安装、启用、启动时应用清单里的 `config` | P1 |
| 服务端入口 | 全部 `bot_*` 路由、灵策登录、AGS 云电脑管理器、群聊恢复任务 | 插件交出扩展对象，Octop 并进 #3129 的 `load_extensions()` | P2（代码已写好，未提交） |
| 启停钩子、路由、免登录路径 | 同上 | #3129 的 `on_startup` / `on_shutdown` / `configure_app` / `public_paths` | **已合**；P2 让插件也能用 |
| 主题 | Bot 的配色、Logo、产品名、登录页 | 清单里的 `theme`，dashboard 读取 | P7 |
| 数据表 | 群聊、草稿、头像照片等 6 张表（现在是 `027_bot_groups`） | 扩展迁移的独立命名空间 | #3130 在评审 |
| 数据访问 | Bot 的仓库类 | `RepoBundle.extension(name)` | #3131 在评审 |
| 文案 | 约 90 个中英文 key | `i18n_bundles()` | #3141 在评审 |
| 模型供应商预设 | 灵策智算预设排第一 | `provider_presets()` | #3141 在评审 |
| 免审批工具、侧栏项、内部会话渠道 | 设备工具、`octop-bot` 导航、`octop_bot_group` 渠道 | #3141 的另外三个钩子 | #3141 在评审 |
| Agent 策略 | 私密 Bot 不共享、不可删、对其他 Agent 隐藏；云租户固定存储后端 | `normalize_agent_config` 等四个钩子 | #3142 在评审 |
| 错误码 | 15 个 `BOT_*` / `LYNXCE_*` | `ErrorCode` 是 `StrEnum`，运行时不能扩展，需要字符串错误码注册表 | 待提（P3） |
| 存储后端类型 | `bot_cloud`（对象存储 + 云电脑） | `resolve_agent_backend_spec` 加一个“类型 → 解析函数”注册表；用户策略别名 | 待提（P3） |
| 模型路由 | 灵策账号的个人模型、积分不足的错误分类 | `resolve_user_model` / `classify_turn_error`（原 E8） | 待提（P4） |
| 每个 Agent 的运行配置 | Bot 专属工具、中间件、审批项、Chief 引导 | `harness_config(row, cfg)` 在 `_build_harness_config` 末尾（原 E7） | 待提（P4） |
| 轮次路由 | 群聊里同一 Agent 换一个运行实例 | `route_turn`（原 E8） | 待提（P4），需要先和上游讨论 |
| 登录方式 | 灵策账号登录（验证码、密码、扫码） | SSO 提供方注册表 `build_adapters()` 现在是写死的 4 个；能用 OAuth 跳转的部分走它，其余走插件路由 | 待提（P5） |
| 安装向导与更新 | 免向导口令首登、Bot 自带更新源 | `setup_flavor` / `update_provider`（原 E11） | 待提（P5） |
| 页面 | 整个 Bot 客户端（`pages/OctopBot`，135 个文件） | 插件带一个独立的前端应用，Octop 在 `/plugins/<id>/app/` 托管它的静态文件，并在侧栏加一个入口；登录态沿用 Octop 的 token | 待提（P6） |
| 版本约束 | 插件只能装在兼容的 Octop 上 | `plugin.yaml` 加 `octop: ">=x.y"`，不满足就拒绝加载 | 并入 P1 |

不进插件、也不提给上游的：桌面壳（`desktop/`）、手机端（`mobile/`）、官网、fnOS 包。桌面版和 Docker 镜像改成“官方 Octop + 预装 Bot 插件”，用 `bundled/` 预装的机制。

## 3. 分批提给上游

每一批一个 PR，标题统一写“plugins can …”，说明里交代：插件怎么声明这项能力、Octop 在哪里调用它、为什么不能用现有能力做。

### P1 插件清单 v2 + 系统配置（最先做）

- `plugin.yaml` 新增 `capabilities` 列表，一个插件可以声明多种能力；只写 `kind` 的老插件不受影响。harness 部分已提 [TencentCloud/octop-harness#303](https://github.com/TencentCloud/octop-harness/pull/303)。宿主自定义的能力由插件用 `ctx.provide(name, obj)` 交给宿主。
- 加 `octop` 版本约束字段，不满足就拒绝安装。
- 新增 `config` 能力，清单里直接写，不需要代码：

```yaml
capabilities: [config, tool, skill]
octop: ">=1.4"
config:
  provider_presets: [...]             # 模型供应商预设，排在选择列表最前；不覆盖 Octop 自带的同 id 预设
  providers:                          # 安装时按预设建好供应商；不带密钥，由管理员填写
    - { preset: lynxce, name: lynxce }
  default_model: lynxce/deepseek-v3   # 实例还没有默认模型时才设置
  settings:                           # 白名单内的系统设置
    default_timezone: Asia/Shanghai
theme: ...                            # 预留给 P7
```

- 规则：插件给的是默认值，管理员说了算。只在当前值还是 Octop 默认值时写入，并记下插件改过哪些；管理员之后的修改以管理员为准；卸载插件不回滚这些设置。
- 设置白名单：默认时区、上传大小上限、浏览器空闲超时、对外访问地址。数据库、TLS、登录安全、JWT 一律不允许插件改。
- 预装插件（桌面版、Docker 的 bundled 预装）在首次启动时应用。
- 插件详情里列出“此插件会配置哪些项”。
- 涉及的仓库：octop-harness（清单、上下文），Octop（插件管理器、配置应用、供应商预设合并、插件接口和管理页、文档）。

### P2 服务端能力与存储

- 新增 `server` 能力：`setup(ctx)` 里调用 `ctx.provide("server", obj)` 交出扩展对象，Octop 把启动时已加载插件的对象并进 #3129 的 `load_extensions()`，和 entry point 装进来的扩展同等对待。
- 启动后再安装、启用、停用或升级这类插件，要重启才生效，插件列表标出“重启后生效”。插件本来就在进程里执行代码，`server` 不增加权限，所以不另设管理员确认，改为在列表里标出能力。
- 卸载不删数据表，和卸载插件不删工作区一致。
- #3130、#3131 改成插件能力：扩展对象提供 `migrations()` / `repos(db)`，命名空间默认用插件 id。代码基本不动，改标题、说明和文档示例。

### P3 配置贡献

- #3141 改成插件能力，内容不变。
- 新提两项：字符串错误码注册表（插件声明错误码、HTTP 状态和文案），以及存储后端类型注册表（类型 → 解析函数，加上用户策略里的别名）。

### P4 Agent 与回合

- #3142 改成插件能力。
- 新提每个 Agent 的运行配置钩子（原 E7）和模型路由 / 错误分类钩子（原 E8）。
- 轮次路由先在 issue 里和上游讨论形态，再写代码。

### P5 账号与安装

- SSO 提供方注册表开放给插件。
- 安装向导形态和更新源（原 E11）。

### P6 界面

- 插件自带的独立前端应用：由 Octop 托管静态文件，加侧栏入口，沿用 Octop 的登录态。
- Bot 客户端整体搬进插件，上游 dashboard 原样当管理后台。fork 里改过的 54 个上游前端文件随之还原。

### P7 主题

- 清单里的 `theme`：配色、Logo、产品名、登录页文案和图片。dashboard 启动时读取当前启用插件的主题。
- 同一时间只能有一个主题生效；多个插件都带主题时，由管理员选择。

## 4. 现有上游 PR 怎么处理

| PR | 内容 | 处理 |
|---|---|---|
| #3129 | `octop.extensions` 加载器、启停钩子、路由、免登录路径 | **已合**。它是插件服务端能力的运行时，P2 在它上面接插件 |
| #3130 | 扩展自带迁移（独立命名空间） | **继续推，改说明**：写明“插件和扩展都用它”，命名空间默认取插件 id。仍然最急，因为下游 026 撞号就是它要解决的问题 |
| #3131 | 扩展仓库 `RepoBundle.extension(name)` | **继续推，改说明**，同上 |
| #3141 | 文案、模型供应商预设、免审批工具、侧栏项、内部会话渠道 | **继续推，改标题和说明**为插件能力 |
| #3142 | Agent 配置、共享、删除、对其他 Agent 隐藏 | **继续推，改标题和说明**为插件能力 |
| #3128 | `octop_api` 工具（Agent 以对话用户身份调 API） | **照常推**。它是通用功能，对应 issue #28 第三条，和插件路线无关；Bot 插件以后直接复用 |
| #1287 | 个性化页只显示自己的专家 | **照常推**，通用修复 |
| #3053 | 知识库复用已启用的 embedding / rerank 模型 | **照常推**，通用修复 |

没有需要撤回的 PR。改说明的四个（#3130、#3131、#3141、#3142）等 P1 提交后统一改，说明里引用 P1，让评审一眼看出这是同一条线。#3130、#3131 归到 P2，#3141 归到 P3，#3142 归到 P4。

## 5. 风险和待定

- **服务端能力的权限。** 带 `server` 能力的插件能加免登录路由、建表。不过插件本来就在 Octop 进程里执行代码，`server` 并不增加权限，所以 P2 只在插件列表里标出能力，市场上架时也要标出来。这一条上游可能有不同意见，以上游为准。
- **系统配置的边界。** 插件只能改白名单内的设置，而且只写默认值。上游如果希望连默认值也要管理员确认，再加一步确认。
- **只能重启生效。** 服务端能力不做热插拔。对 Bot 来说可以接受，桌面版和 Docker 都是预装的。
- **依赖安装。** Bot 后端依赖腾讯云 SDK 等，`requires` 在加载时用 pip 安装，离线的桌面版可能装不上。桌面版要把依赖随插件预先装好，这一条在 fork 侧解决，不需要上游配合。
- **体积。** Bot 后端加上构建好的前端，预计在 64 MiB 的解压上限以内，P6 动手前再实测。
- **octop-harness 也要提 PR。** P1 的清单和上下文改在 harness 仓库，按那边的 `AGENTS.md` 走。

## 6. 文档和看板的改动

- `octop-bot-upstream-sync.md`：
  - §0 第 1 条的终点改为“官方 Octop + Octop Bot 插件”。
  - §2 的 E1–E11 表保留，加一列“对应插件批次 P1–P6”。
  - §7 路线的 S1–S4 改为 P1–P6 加最终切换，并在开头链接本文。
  - §6 的“fork 只加不改”规矩不变。
- 看板「上游协同」那一行改为：`插件路线：方案待批（docs/octop-bot-plugin-route.md）；7 个上游 PR 等评审，批准后 #3130 #3131 #3141 #3142 改成插件能力的说明`，状态写“等批准”。
