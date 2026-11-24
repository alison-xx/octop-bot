# Octop Bot 与官方 Octop 共轨方案（issue #28）

> 状态：进行中（2026-11-24 更新）。对应 [issue #28](https://github.com/alison-xx/octop-bot/issues/28)。腾讯云 Token 消耗接入在另一条线上做，本文不涉及。

## 0. 结论先行

1. **终点是“官方 pip 包 + Bot 扩展包”。** 本仓库不再带一份 `src/octop` 拷贝。改为依赖 PyPI 上的 `octop==x.y`，Bot 层做成独立包 `octop_bot`，通过官方的扩展点接入。桌面、iOS、Android、官网和 fnOS 包照旧放在本仓库。
2. **先和上游对齐扩展点，再搬家。** 上游目前只有 harness 级插件（`tool` / `skill` / `hook` / `channel`），没有服务端扩展点，账号、路由、数据表、启动钩子都挂不上去。所以先向 TencentCloud/Octop 提扩展点 PR。fork 里用同一份代码过渡，等上游发版后删掉 vendored 的 `src/octop`。
3. **前端拆成独立 Bot SPA。** `pages/OctopBot` 和它改过的 Chat 组件搬进本仓库自己的 Vite 应用，由 `octop_bot` 挂载提供。上游 dashboard 原样保留，当管理后台用。
4. **在飞分支先收口再搬。** 现有 p0–p5、cvm、media、device、cards 等分支合进 main 之后，再从 main 一次性搬目录，免得和十几条并行分支大面积冲突。在这之前只做三件事：上游扩展点、上游通用修复、第三条的 Skill 安全调用。

## 1. 现状（fork 点 976803d6 → main a474b57d）

| 部分 | 规模 | 去向 |
|------|------|------|
| 新增后端文件 | 70 个，约 1.3 万行（`bot_*` 路由、`infra/bot_groups`、`infra/cloud`、`infra/auth/lynxce*`、`agents/bot_*` 等） | 原样搬进 `octop_bot` |
| 改过的上游后端文件 | 64 个，约 30 处挂钩点；`infra/agents/manager.py` 一个文件就 +478 行 | 每处挂钩要么提成上游通用修复，要么换成扩展点调用 |
| 迁移 `027_bot_groups`（原 026） | 6 张表 | 上游已发 `026_invite_redemptions`，已在 #39 改为 027 过渡。#3130 合并后改成 `octop_bot` 命名空间下的 `001_bot_groups`，已有数据库的表靠 `IF NOT EXISTS` 原样接管 |
| 新增前端文件 | 183 个（其中 `pages/OctopBot` 135 个） | 独立 Bot SPA |
| 改过的上游前端文件 | 54 个（Chat、Experts、Settings/Models、locales） | 拷进 Bot SPA 维护，上游那份还原 |
| desktop / mobile / website / fnos | 各自独立 | 不变 |

## 2. 上游扩展点

所有扩展点都挂在同一个对象上，通过 `importlib.metadata` 的 entry point 组 `octop.extensions` 发现：

```toml
# octop_bot 的 pyproject.toml
[project.entry-points."octop.extensions"]
octop_bot = "octop_bot.extension:extension"
```

按迁移的紧迫程度分批提给上游。每批一个 PR，只解决一类问题：

| 批次 | 扩展点 | 上游调用位置 | 覆盖的 Bot 代码 |
|------|--------|--------------|-----------------|
| E1 地基 | `load_extensions()`；`on_startup(server)` / `on_shutdown(server)`；`configure_app(app, server)`；`public_paths()` | `OctopServer` 启停、`build_app` 末尾、`deps._JWT_EXEMPT_*`、`setup_lockdown` | 全部 `bot_*` 路由和 `auth_lynxce`、AGS 电脑管理器、群聊恢复任务、免登录路径 |
| E2 存储 | `migrations() -> ExtensionMigrations(namespace, dir)`，独立水位表 `_extension_schema`（已提交 [TencentCloud/Octop#3130](https://github.com/TencentCloud/Octop/pull/3130)）；`repos(db)` → `RepoBundle.extension(name)`（已提交 [TencentCloud/Octop#3131](https://github.com/TencentCloud/Octop/pull/3131)） | `run_migrations` 之后、`RepoBundle.build` | 026 的 6 张表、Bot 仓库类 |
| E5 静态贡献 | `i18n_bundles`、`provider_presets`、`backend_kinds`、`thread_channels`、`error_codes`、`hitl_excluded_tools`、`nav_keys` | 各自的注册表 | 灵策预设、`bot_cloud` 后端、群聊线程渠道、`BOT_*` 错误码、文案 |
| E6 Agent 策略 | `normalize_agent_config`、`can_share`、`before_delete`、`peer_visible`、`host_files_allowed`、`browser_profile`、删除事件 | `AgentManager` 创建/合并/共享/删除、团队、媒体导入 | 私密 Bot、云租户工作区、每个 Bot 独立浏览器档案 |
| E7 运行配置 | `harness_config(row, cfg, ctx) -> cfg` | `AgentManager._build_harness_config` 末尾 | Bot 工具、中间件、审批项、Chief 引导 |
| E8 回合 | `prepare_turn`、`route_turn`、`resolve_user_model`、`classify_turn_error` | 处理器与 `AgentManager.stream/call/resume/cancel` | 群聊回合、个人账号模型、灵策积分不足等错误 |
| E9 / E10 / E11 | `wrap_channel_processor`；`on_turn_state`；`setup_flavor` / `update_provider` | 网关、历史投影、安装向导和更新 | 群聊 IM、压缩边界、免密安装和 Bot 自带更新 |

E1 已合入上游 [TencentCloud/Octop#3129](https://github.com/TencentCloud/Octop/pull/3129)（`docs/extensions.md` 是接口说明；评审后补了启动失败时按逆序回滚已启动扩展）。E5 的 i18n、供应商预设、HITL 排除工具、侧栏键、虚拟渠道五项已提交 [TencentCloud/Octop#3141](https://github.com/TencentCloud/Octop/pull/3141)；错误码（`StrEnum` 无法运行时扩展）和存储后端类型（需要 resolver 函数）另行讨论。E6 的配置规范化、共享检查、删除检查、对其他 Agent 隐藏四个钩子已提交 [TencentCloud/Octop#3142](https://github.com/TencentCloud/Octop/pull/3142)；删除时跳过清理、浏览器档案、宿主文件开关、线程分享规则不适合简单钩子，留到后续批次。如果上游对某一批有不同看法，以上游的形态为准，fork 跟着改。

## 3. 可直接提给上游的通用修复

和 Bot 无关、上游可以原样收下的改动，按“一个问题一个 PR”提交（流程见 `upstream-octop-prs` 的约定：`alison-xx/Octop` fork，分支基于 `upstream/develop`）：

逐条核对后的结论（2026-11-24）：

| # | 改动 | 结论 |
|---|------|------|
| 1 | 头像替换：先写新文件再删旧文件 | 已提 [TencentCloud/Octop#3116](https://github.com/TencentCloud/Octop/pull/3116) |
| 2 | HITL“本会话全部允许”只包连接器写操作 | 不提。上游每次接入连接器会把已有审批判断再包一层，但每层查的是同一个放行表，行为不变，拿不出具体 bug |
| 3 | 历史投影隐藏 `read_file` 附带的媒体伪用户消息 | 已提 [TencentCloud/Octop#3132](https://github.com/TencentCloud/Octop/pull/3132)。上游可复现：Agent 读图后，这一轮的提问和工具步骤从历史里丢失，刷新后多出一条带图的假用户消息 |
| 4 | `HEAD /workspace/download` 返回文件大小 | 不提。上游没有调用方，实现靠整份下载算大小 |
| 5 | 用户接管浏览器时暂停 `browser_use` | 暂缓。fork 里只对 Bot 专属浏览器档案生效，上游版本需要重新设计 |
| 6 | HITL 不可绕过标记改结构字段 | 不提。fork 的改动只是加了 Bot 自己的标记，归入扩展点 |
| 7 | `next_run_time`、`disable(reason=)` | 不提。上游没有调用方，跟随用到它们的扩展点一起提 |
| 8 | 余额不足的稳定错误码 | 不提。上游已有 `INSUFFICIENT_BALANCE` 文案分类，剩下的部分只服务灵策积分 |
| 9 | 附件文本工具挪到 `infra/` | 不提。上游没有 `infra` → `api` 的反向依赖，只有 fork 需要 |
| 10 | `filesystem` / `voice` 权限点 | 暂缓。属于权限策略调整，要先和上游讨论 |
| 11 | 压缩边界随投影历史记录 | 暂缓。改为走 E10 扩展点 |

Windows `npx` 那条已经作为 #3115 合进上游，下次同步上游时 fork 里的那份就消失了。

## 4. 第三条：Skill 安全调用 Octop API

已作为上游 PR 实现：`octop_api` 工具，[TencentCloud/Octop#3128](https://github.com/TencentCloud/Octop/pull/3128)。

- **身份识别**：取当前回合 `configurable.user` / `agent_id`。这两个值由 Octop 设置，模型改不了。
- **凭证封装**：每次调用签一个 120 秒的 `agent` 用途 JWT，绑定该用户当前的密码版本和 MFA 版本，改密码后立即失效。token 只在进程内用，不进入模型上下文。
- **边界**：API 只在 `agent_request_allowed()` 范围内接受这种 token。登录、密码、MFA、安装向导、TLS、安全设置、终端、内部 MCP 一律拒绝；不传 method/path 的调用方（WebSocket 等）也拒绝。管理员同样受这个限制。
- **API 调用**：通过 `httpx.ASGITransport` 直接调用本进程里的 app，不走端口，也不涉及 TLS。
- **审批**：GET 直接执行；POST / PUT / PATCH / DELETE 一律走工具审批，全局关闭 HITL 时也一样。
- **Skill**：内置的 `octop-assistant` 改为优先用 `octop_api`，只有它做不到的事（备份、Ollama、升级）才回退到 CLI。

Bot 层后续的“对话里创建 Bot”等能力直接复用这个工具，不再单独发 token。

## 5. 腾讯云整合（第四条）

云电脑已经在用腾讯云 AGS（见 `octop-bot-cloud-plan.md`）。部署资源和 Token 消耗的迁移由另一条线负责。本方案只约定一点：腾讯云相关的通用能力（例如 E2B 兼容沙箱后端）放进 `octop-harness`，账号和计费相关的放在 `octop_bot`，不放进上游 Octop。

## 6. 和上游长期同步的规矩

1. **fork 只加不改。** 搬家之后，`octop_bot` 只能通过扩展点接入。需要改上游行为时，要么给上游提通用修复，要么给扩展点提新方法，不在 fork 里打补丁。
2. **上游版本钉死、定期升级。** `pyproject.toml` 里写 `octop==x.y.z`。上游每次发版后，开一条 `chore/bump-octop-x.y.z` 分支跑全量测试再合并。
3. **双向同步。** 在 Bot 里发现的通用问题，修复先提给上游，fork 里临时带着，上游合并后删掉。
4. **迁移号不再碰上游。** Bot 的表全部走 E2 的独立命名空间。

## 7. 路线

| 阶段 | 内容 | 依赖 |
|------|------|------|
| S0（完成） | E1 地基 #3129 已合；通用修复 #3115–#3125、#3132、#1284、#2023 已合；`octop_api` 工具 #3128 按评审修改中 | 无 |
| S1（进行中） | 上游 PR：E2 存储（#3130 迁移、#3131 仓库）、E5 #3141、E6 #3142 | 上游评审 |
| S2 | 在飞分支全部合进 main；fork 同步 `upstream/develop`；用 fork 内的扩展点把 Bot 代码搬进 `octop_bot` | 在飞分支收口 |
| S3 | E7–E11 上游 PR；Bot SPA 独立 | S2 |
| S4 | 上游发版带齐扩展点后，删除 vendored 的 `src/octop`，改为依赖 PyPI 的 `octop` | 上游发版 |
