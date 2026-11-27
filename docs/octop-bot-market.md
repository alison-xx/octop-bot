# Bot 市场（Bot Market）

Bot 市场是一组按行业和岗位准备好的 Bot 模板，参考 Grok Bot 的 Marketplace 设计：用户在官网或应用里挑一个模板，一键导入成自己的 Bot，导入后马上能用，之后可以随意修改。

## 用户能看到的地方

| 位置 | 入口 | 做什么 |
|------|------|--------|
| 官网 `octop-bot.lynxce.cn/market.html` | 导航「Bot 市场」 | 浏览、搜索、看详情；「添加 / 导入到 Octop Bot」弹出选择：网页版或桌面客户端 |
| 应用（桌面 / 网页版） | 通讯录顶部商店图标、「+」菜单「从 Bot 市场添加」、新建 Bot 弹窗里的「浏览 Bot 市场」 | `/octop-bot/market` 列表，`/octop-bot/market/<slug>` 详情，`/octop-bot/market/<slug>/import` 直接打开导入弹窗 |
| 桌面深链 | `octop-bot://market/<slug>` | 打开（或唤起）Octop Bot 并进入该模板的导入弹窗；冷启动、已运行、自托管服务器模式都支持。仅打包版注册协议 |

网页版链接是 `https://bot.lynxce.cn/octop-bot/market/<slug>/import`，未登录时先走灵策登录，登录后回到导入弹窗。

## 一个模板包含什么

每个模板是 `src/octop/infra/agents/bot_market/templates/<slug>.json`，所有文字都有 zh / en 两份，格式由 `catalog.py` 的 `Template` 校验：

| 字段 | 导入后落到哪里 |
|------|----------------|
| `category`、`roles` | 所属行业（`categories.json`）和一到三个岗位（`roles.json`），市场按这两个维度筛选；不落到 Bot 上 |
| `name`、`tagline`、`description` | Bot 名字、简介（`description` 列）、首次对话的欢迎语 |
| `role` + `instructions` | Bot 的系统提示词（`system_prompt`），末尾附上技能清单 |
| `memories` | 工作区 `MEMORY.md`（在 harness 默认模板后追加），每个会话都会加载 |
| `skills` | 工作区 `skills/<id>/SKILL.md`（BackendWorkspace 实际放在 `.octop/skills/`） |
| `routines` | 定时任务（cron，`task_type=agent`）；导入弹窗里逐个勾选，`suggested: false` 的默认不勾 |
| `integrations` | 只做建议，导入后提示去「能力 → 连接器」连接；必须是 `infra/connectors/catalog.json` 里的 `kind` |
| `starters` | 工作区 `.octop/manifest.json` 的 `quick_prompts`，首次对话显示为快捷问题 |
| `look` | SVG 角色（形状 + 颜色），用户在外观里关掉照片后显示它 |
| `avatar_subject` | 只给头像生成脚本用 |

导入时语言跟随用户（`Accept-Language`）。同一模板可以导入多次，重名自动加序号。导入记录存在 settings 键 `octop_bot:market:<user_id>:<agent_id>`，用于在市场里显示「打开」。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/octop-bot/market` | 公开。行业分类、岗位和卡片，`?locale=zh|en`；岗位带 `onboarding`（新用户引导里显示的顺序，null 表示只在市场筛选里出现） |
| GET | `/api/octop-bot/market/{slug}` | 公开。详情 |
| GET | `/api/octop-bot/market/{slug}/avatar` | 公开。512px WebP |
| GET | `/api/octop-bot/market-imports` | 需登录。我导入过的模板 → Bot id |
| POST | `/api/octop-bot/market-imports` | 需登录。`{slug, name?, routines?}`，`routines` 为 null 时开启建议的例行任务 |

## 新增或修改模板

1. 写 `templates/<slug>.json`（参考 `store-daily-brief.json`），行业在 `categories.json`，岗位在 `roles.json`。每个行业和每个岗位至少要有 3 个模板（测试会查）。改了已发布模板的内容就把 `version` 加一（头像和官网缓存会刷新）。
2. 生成头像（gpt-image-2.5，灵策接口，统一风格：Bot 的软形状角色 + 斜胶囊眼 + 一个行业道具）：
   ```bash
   LYNXCE_API_KEY=... uv run python scripts/bot_market_avatars.py <slug>
   ```
   已有头像会跳过，`--force` 重画。
3. 官网使用私有发布仓的市场导出工具，从同一版客户端目录生成网站数据。参见[生产发布流程](https://github.com/alison-xx/octop-bot-production#readme)。
4. 跑测试：`uv run pytest tests/unit/agents/test_bot_market_catalog.py tests/integration/test_bot_market.py -q`。

## 内容边界

法务、财务、教育、健身类模板的守则里写明：只提供信息和草稿、不替代执业人士；条文和数据要先用元典或网页搜索核对并标注日期；涉及未成年人时引导思考而不是直接给答案。模板里写到的具体规则和平台数字上线前需要人工复核一遍。
