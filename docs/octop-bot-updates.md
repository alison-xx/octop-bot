# Octop Bot 更新机制与发版

所有 Octop Bot 客户端都从同一份签名清单得知新版本：

- 清单：`https://dl.lynxce.cn/releases/octop-bot/manifest.json`
- 签名：同目录的 `manifest.json.sig`（Ed25519，对清单文件的原始字节签名）

客户端内置公钥，签名对不上就当作检查失败，不会下载任何安装包。安装包本身还要和清单里的 SHA-256 一致才会安装。

## 各端现在的行为

| 端 | 行为 |
|---|---|
| 桌面 Windows / macOS | 启动 30 秒后检查一次，之后每 6 小时一次。发现新版就在后台下载并校验，校验通过后发一条系统通知「Octop Bot X 已准备好，点击重启更新」，托盘和 macOS 应用菜单里出现「重启以更新到 X」。点了才安装：Windows 静默运行 NSIS 安装包（`/S --updated --force-run`）并重新打开；macOS 打开 dmg，拖进「应用程序」即可。dmg 已签名并公证，Gatekeeper 直接放行；后台原地替换 `.app` 还没做。随时可以从菜单「检查更新…」手动检查，弹窗里显示更新说明。 |
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
- 桌面安装包的键：`win_x64`、`win_arm`、`mac_arm`、`mac_intel`。脚本按文件名自动识别（`Setup…x64.exe`、`Setup…arm64.exe`、`mac…arm64.dmg`、`mac…x64.dmg`、`.apk`、`.fpk`）。
- 手机端有自己的版本号（现在是 0.1.0），所以 `android` 和 `ios` 带各自的 `version`。Android 用 `version_code`（整数，和 `build.gradle.kts` 一致）判断新旧，系统也靠它决定能否覆盖安装；iOS 用 `version`（和 `MARKETING_VERSION` 一致）比较。`min_version_code` / `min_version` 是手机端的最低版本，低于它时措辞更强。
- 签名：iOS 用 CryptoKit 的 Ed25519 验签；Android 用内置的纯 Kotlin Ed25519 实现（系统的 Ed25519 只支持钥匙串里的私钥，不能校验外部公钥），所有 Android 版本都验签。安装包还要匹配 SHA-256，而且 Android 只允许安装和现有版本同一签名证书的 APK。Android 只从 `dl.lynxce.cn` 下载。
- 下载地址只接受 `https://dl.lynxce.cn` 和上游的 `https://download.octop.cloud`。
- `rollout`（0–100）是灰度比例。每台设备有一个随机安装 ID，同一版本始终落在同一个桶里。
- 设置里「只接收稳定版」（默认开启）时只看 `stable`；关闭后看 `stable` 和 `beta` 里更高的那个。

## 发版步骤

1. 打 tag `octop-bot-v<版本>`，构建各平台安装包和 NAS 镜像：
   - Windows：在 x64 Windows 上 `pnpm run package:bot:win`（`desktop/src`）。
   - macOS：在 Apple 芯片 Mac 上 `pnpm run package:bot:mac`（`desktop/src`），或者推 tag 后用「Octop Bot macOS」工作流打。脚本会签名、公证、钉票据并核对，任何一项不过就失败，产物是 `desktop/src/release/octop-bot/Octop-Bot-<版本>-mac-arm64.dmg`。不要上传 `--unsigned` 打出来的包。
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

## mac 签名与公证

Octop Bot 的 mac 安装包用 `Developer ID Application: Lynxce Technologies Pty Ltd (F7URANQHX7)` 签名，开启 hardened runtime，再交给苹果公证。`.app` 和 dmg 都钉上了公证票据，离线也能通过 Gatekeeper，用户打开 dmg 时不会再看到「无法验证开发者」。更新器下载的就是同一个 dmg，清单里的 SHA-256 对应签名公证后的文件。

打包脚本是 `desktop/src/scripts/package-bot-mac.py`，配置在 `desktop/src/electron-builder.bot.cjs` 的 `mac` / `dmg` 两节。整个流程：

1. 用 uv 管理的 CPython 3.12.13 和 `uv.lock` 装出内置运行时（与 Windows 版相同的 extras），检查没有链接 Homebrew 的原生库。
2. electron-builder 给 `.app` 里每个 Mach-O 文件签名（Electron 框架、helper、Python 解释器、143 个 `.so`、37 个 `.dylib`、Playwright 的 `node`、`cua-driver`），都带 hardened runtime 和安全时间戳。运行时里的数据文件（botocore 的 `.json.gz`、图片、字体、Windows DLL、静态库）不签，见 `MAC_DATA_FILES`。
3. electron-builder 公证 `.app` 并钉票据，再用它生成 dmg 并签名。
4. 脚本公证 dmg 并钉票据。
5. 核对：`codesign --verify --deep --strict`、`spctl -a -vvv`（`.app`）、`spctl -a -vvv -t install`（dmg）都要显示 `source=Notarized Developer ID`，`xcrun stapler validate` 两个都要通过。还会用包里的 Python 导入 `octop` 等模块，确认它们都来自包内。

Python 运行时按 `PYTHONPYCACHEPREFIX` 把字节码写到数据目录（`~/.octop-bot/pyc`），不会改动已签名的包。

### entitlements

`desktop/src/build/entitlements.bot.mac.plist` 同时用于主程序和所有内嵌的可执行文件：

| entitlement | 为什么需要 |
|---|---|
| `com.apple.security.cs.allow-jit` | Electron 和 Playwright 自带的 Node 都要 V8 JIT |
| `com.apple.security.cs.allow-unsigned-executable-memory` | Python 的 ctypes / cffi 扩展用 libffi 生成闭包 |
| `com.apple.security.cs.disable-library-validation` | Octop 运行时会按需安装 Python 包（`runtime_packages.py`），这些原生模块不是我们签的 |
| `com.apple.security.device.audio-input` | 语音输入。没有它 hardened runtime 会直接拒绝麦克风 |

### 本机打包

需要：Apple 芯片 Mac、Node 24、pnpm、uv，钥匙串里有上面那张 Developer ID Application 证书，还有一份 notarytool 钥匙串配置。默认用 `lynxce-notary`（和灵策智算同一个 Apple 团队，发版机上已经存好）。

```bash
(cd dashboard && npm ci)
cd desktop/src && pnpm install --frozen-lockfile
pnpm run package:bot:mac
```

整次大约 20～40 分钟，其中两次公证各 2～15 分钟。其他参数：`--notary-profile <名字>`（或环境变量 `OCTOP_BOT_NOTARY_PROFILE`）换公证配置，`--dir` 只出 `.app`，`--prepare` 只准备运行时，`--unsigned` 打一个不签名的试用包（Gatekeeper 会拦，不能发布）。

换一台电脑打包时，先导入证书（从原来的 Mac 在「钥匙串访问」里把证书连同私钥导出成 .p12，双击导入），再存一次公证配置，推荐用 App Store Connect API Key（App Store Connect →「用户和访问」→「集成」→「App Store Connect API」→ 团队密钥，角色选「开发者」）：

```bash
xcrun notarytool store-credentials octop-bot-notary --key <AuthKey_XXXXXXXXXX.p8 路径> --key-id <Key ID> --issuer <Issuer ID>
xcrun notarytool history --keychain-profile octop-bot-notary
```

然后打包时加 `--notary-profile octop-bot-notary`。也可以用 Apple ID：`xcrun notarytool store-credentials octop-bot-notary --apple-id <Apple ID> --team-id F7URANQHX7`，它会在终端里提示输入 App 专用密码。密码和 .p8 都不要写进仓库或发到聊天里。

公证没通过时，脚本会打印提交 ID，用 `xcrun notarytool log <提交 ID> --keychain-profile lynxce-notary` 看原因，最常见的是某个新加的原生文件没签上。

### CI

`.github/workflows/octop-bot-mac.yml`（推 `octop-bot-v*` tag 或手动运行）在 `macos-15` 上跑同一个脚本，产物作为 artifact 上传，下载后按上面的发版步骤放到 `dl.lynxce.cn`。需要在仓库「Settings → Secrets and variables → Actions」里配置：

| Secret | 内容 |
|---|---|
| `MAC_CERT_P12_BASE64` | Developer ID Application 证书和私钥导出的 .p12，`base64 -i cert.p12` 的输出 |
| `MAC_CERT_PASSWORD` | 导出 .p12 时设的密码 |
| `APPLE_API_KEY_P8_BASE64` | App Store Connect API Key（`AuthKey_XXXXXXXXXX.p8`），`base64 -i AuthKey_XXXXXXXXXX.p8` 的输出 |
| `APPLE_API_KEY_ID` | 这把 Key 的 Key ID |
| `APPLE_API_ISSUER` | Issuer ID |

缺任何一个工作流都会在第一步报错退出。CI 只支持 API Key 公证。Windows 客户端不在这个工作流里，仍按原方式打包；继承自上游的 `octop-desktop.yml` 打的是上游 Octop 应用，没有改。

### 还没做

签名之后，更新器可以改成下载 zip、原地替换 `.app` 再重启，和 Windows 一样不用用户拖拽。现在仍是打开 dmg。

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
