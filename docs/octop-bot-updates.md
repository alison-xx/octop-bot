# Octop Bot 更新机制与发版

所有 Octop Bot 客户端都从同一份签名清单得知新版本：

- 清单：`https://dl.lynxce.cn/releases/octop-bot/manifest.json`
- 签名：同目录的 `manifest.json.sig`（Ed25519，对清单文件的原始字节签名）

客户端内置公钥，签名对不上就当作检查失败，不会下载任何安装包。安装包本身还要和清单里的 SHA-256 一致才会安装。

## 各端现在的行为

| 端 | 行为 |
|---|---|
| 桌面 Windows / macOS | 启动 30 秒后检查一次，之后每 6 小时一次。发现新版就在后台下载并校验，校验通过后发一条系统通知「Octop Bot X 已准备好，点击重启更新」，托盘和 macOS 应用菜单里出现「重启以更新到 X」。点了才安装：Windows 静默运行 NSIS 安装包（`/S --updated --force-run`）并重新打开；macOS 打开 dmg，拖进「应用程序」即可（安装包签名公证之后再改成后台替换）。随时可以从菜单「检查更新…」手动检查，弹窗里显示更新说明。 |
| 网页版 / NAS | 不再从 PyPI 自升级（那里的 `octop` 是上游产品）。`/api/update/status` 读同一份清单，返回最新版本、镜像 `ghcr.io/alison-xx/octop-bot:nas-<版本>` 和升级步骤（飞牛应用中心更新，或 `docker pull` 后 `docker compose up -d`）。`/api/update/upgrade` 直接拒绝。 |
| Android | 启动 10 秒后检查一次，回到前台时如果距上次检查超过 24 小时再查一次。有新版时首页顶部出一条可关闭的横幅，「设置 → 关于」的版本行显示「有新版本 X」。点「更新」在后台下载 APK，显示进度，校验 SHA-256，再确认安装包的签名证书和已安装版本一致，然后调起系统安装（第一次会引导打开「允许安装未知应用」）。 |
| iOS | 同样的检查时机。有新版时首页横幅和「设置 → 关于」提示，点「更新」打开清单里的 App Store / TestFlight 链接。苹果不允许 App 自己下载安装新版本。 |

用户不会被打断：检查、下载都在后台，只有点通知、菜单或「更新」按钮才安装。当前版本低于清单里的最低版本时，提示措辞更强，但仍可以「稍后」。

### 桌面端「关于与更新」

Octop Bot 设置页有一块「关于与更新」：当前版本、状态（已是最新 / 正在检查 / 正在下载 X / X 已准备好 / 有新版本 X / 检查失败）、「检查更新」按钮，准备好时显示「重启并更新」，以及两个开关：

- **自动下载更新**（默认开）：关闭后只检查、不下载，有新版时通知「有新版本 X」，点「下载并更新」才下载。
- **接收测试版**（默认关）：打开后也跟随 `beta` 通道。

### 手机端的设置

「设置 → 关于」：版本行右侧显示状态，下面是「检查更新」和「接收测试版」开关（默认关）。Android 在下载时显示进度条，失败时可以重试。首页横幅关闭后，同一版本不再出现。

## 清单格式

```json
{
  "schema": 1,
  "product": "octop-bot",
  "channels": {
    "stable": {
      "version": "1.0.4",
      "tag": "octop-bot-v1.0.4",
      "date": "2026-11-30",
      "notes": { "zh": "……", "en": "……" },
      "notes_url": "https://octop-bot.lynxce.cn/download.html",
      "min_supported": "1.0.3",
      "rollout": 100,
      "assets": {
        "win_x64": { "name": "Octop-Bot-Setup-1.0.4-x64.exe", "url": "https://dl.lynxce.cn/releases/octop-bot/1.0.4/Octop-Bot-Setup-1.0.4-x64.exe", "sha256": "…", "size": 123 },
        "mac_arm": { "…": "…" },
        "android": { "name": "octop-bot-0.2.0.apk", "url": "https://dl.lynxce.cn/releases/octop-bot/1.0.4/octop-bot-0.2.0.apk", "sha256": "…", "size": 123, "version": "0.2.0", "version_code": 2, "min_version_code": 1 },
        "ios": { "url": "App Store / TestFlight 链接", "version": "0.2.0", "min_version": "0.1.0" }
      },
      "nas": { "image": "ghcr.io/alison-xx/octop-bot:nas-1.0.4" }
    },
    "beta": { "…": "同上" }
  }
}
```

- `version` 用产品版本号（与 `pyproject.toml` 一致，如 `1.0.4b1`）。客户端把 `1.0.4b1` 和 `1.0.4-beta.1` 视为同一个版本，`beta.10` 排在 `beta.9` 之后。
- 桌面安装包的键：`win_x64`、`win_arm`、`mac_arm`、`mac_intel`。脚本按文件名自动识别（`Setup…x64.exe`、`Setup…arm64.exe`、`mac…arm64.dmg`、`mac…x64.dmg`、`.apk`、`.fpk`）。Windows 免安装版 `…x64.zip` 记为 `win_x64_zip`，只给官网下载页用，客户端更新只认安装包。
- 官网下载页（octop-bot.lynxce.cn/download.html）直接读这份清单并验签：清单里的稳定版就是页面上的当前版本，测试版更新时页面会多一行「测试版 X 已发布」，手机端和 NAS 有安装包时各多一张卡片。没有清单或验签失败时，页面退回到网站目录里的 `releases.json`。更新日志里更早的版本也来自 `releases.json`。
- 手机端有自己的版本号（现在是 0.1.0），所以 `android` 和 `ios` 带各自的 `version`。Android 用 `version_code`（整数，和 `build.gradle.kts` 一致）判断新旧，系统也靠它决定能否覆盖安装；iOS 用 `version`（和 `MARKETING_VERSION` 一致）比较。`min_version_code` / `min_version` 是手机端的最低版本，低于它时措辞更强。
- 签名：iOS 用 CryptoKit 的 Ed25519 验签；Android 用内置的纯 Kotlin Ed25519 实现（系统的 Ed25519 只支持钥匙串里的私钥，不能校验外部公钥），所有 Android 版本都验签。安装包还要匹配 SHA-256，而且 Android 只允许安装和现有版本同一签名证书的 APK。Android 只从 `dl.lynxce.cn` 下载。
- 下载地址只接受 `https://dl.lynxce.cn` 和上游的 `https://download.octop.cloud`。
- `rollout`（0–100）是灰度比例。每台设备有一个随机安装 ID，同一版本始终落在同一个桶里。
- 设置里「只接收稳定版」（默认开启）时只看 `stable`；关闭后看 `stable` 和 `beta` 里更高的那个。

## 发版步骤

1. 打 tag `octop-bot-v<版本>`，按原流程构建各平台安装包和 NAS 镜像。
2. 把安装包上传到 `https://dl.lynxce.cn/releases/octop-bot/<版本>/`，本地留一份同样的文件夹（下面的 `dist/<版本>`）。
3. 先发到测试通道，保留稳定通道原样：

   ```bash
   uv run python scripts/octop_bot_manifest.py build --version 1.0.4b1 --channel beta --dist dist/1.0.4b1 --previous https://dl.lynxce.cn/releases/octop-bot/manifest.json --out out/
   ```

   更新说明默认取 `CHANGELOG.md` 里 `## [1.0.4b1]` 一节（中文），英文用 `--notes-en` 传入。需要强提醒老版本时加 `--min-supported 1.0.3`。第一次发布时没有旧清单，去掉 `--previous`。

   手机端：APK 放进 `dist/<版本>` 一起上传，并传 `--android-version 0.2.0 --android-version-code 2`（可选 `--android-min-version-code 1`）；iOS 传 `--ios-url <商店链接> --ios-version 0.2.0`（可选 `--ios-min-version 0.1.0`）。
4. 校验后上传 `out/manifest.json` 和 `out/manifest.json.sig` 到 `https://dl.lynxce.cn/releases/octop-bot/`（两个文件一起换）：

   ```bash
   uv run python scripts/octop_bot_manifest.py verify out/manifest.json
   ```

5. 测试通道没问题后，把它提升为稳定版，可以先灰度：

   ```bash
   uv run python scripts/octop_bot_manifest.py promote --manifest https://dl.lynxce.cn/releases/octop-bot/manifest.json --rollout 20 --out out/
   ```

   观察一段时间后用 `--rollout 100` 再执行一次。每次都要重新上传清单和签名。

## mac 签名与公证（待办）

macOS 安装包现在没有签名（`electron-builder.config.ts` 里 `identity: null`），所以只能下载 dmg 让用户拖进「应用程序」。要做到和 Windows 一样后台替换，需要：

1. Apple Developer Program 账号，在开发者后台创建「Developer ID Application」证书，导入发版机的钥匙串。
2. 为公证准备 App Store Connect API Key（或 Apple ID + App 专用密码）。
3. 在 `electron-builder.config.ts` 去掉 `identity: null`、打开 `hardenedRuntime`，配置 `notarize`，并补上需要的 entitlements。
4. 签名后，更新器在 macOS 上可以换成下载 zip 原地替换 `.app` 再重启。

## 回滚

客户端只会升级、不会降级。发现问题时：

1. 立刻把出问题的通道 `rollout` 改成 0（重新 `build` 或 `promote` 一次），没更新的设备就不会再收到它。
2. 修复后发一个更高的版本号。已经装了问题版本的设备会正常升级到修复版。

## 签名密钥

- 私钥只在发版机上：`~/.octop-bot-release/manifest-ed25519.pem`（权限 600），不进仓库，也不要发到聊天或工单里。
- **请立刻备份到安全的地方**（例如密码管理器的安全笔记）。丢了它就无法再签发清单，已安装的客户端只认这把钥匙对应的公钥，换钥匙需要先发一个内置新公钥的版本，而且要等用户装上它。
- 公钥写在 `scripts/octop_bot_manifest.py`、`desktop/src/main/update/bot-feed.ts` 和 `src/octop/infra/setup/bot_release.py` 里，三处必须一致。

## 已安装的老版本

1.0.3-beta.7 和 1.0.3-beta.8 的桌面版没有接入这套机制，不会自己检查更新。这些用户需要手动下载安装一次带自动更新的版本，之后就会自动收到更新。可以通过官网下载页、用户群和邮件通知他们。
