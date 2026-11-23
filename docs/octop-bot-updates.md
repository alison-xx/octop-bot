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
| 手机 | 第二期接入（Android 应用内更新、iOS 跳转商店提示）。 |

用户不会被打断：检查、下载都在后台，只有点通知或菜单才安装。当前版本低于清单里的 `min_supported` 时，提示措辞更强，但仍可以「稍后」。

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
        "android": { "…": "…" },
        "ios": { "url": "App Store / TestFlight 链接" }
      },
      "nas": { "image": "ghcr.io/alison-xx/octop-bot:nas-1.0.4" }
    },
    "beta": { "…": "同上" }
  }
}
```

- `version` 用产品版本号（与 `pyproject.toml` 一致，如 `1.0.4b1`）。客户端把 `1.0.4b1` 和 `1.0.4-beta.1` 视为同一个版本，`beta.10` 排在 `beta.9` 之后。
- 桌面安装包的键：`win_x64`、`win_arm`、`mac_arm`、`mac_intel`。脚本按文件名自动识别（`Setup…x64.exe`、`Setup…arm64.exe`、`mac…arm64.dmg`、`mac…x64.dmg`、`.apk`、`.fpk`）。
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
4. 校验后上传 `out/manifest.json` 和 `out/manifest.json.sig` 到 `https://dl.lynxce.cn/releases/octop-bot/`（两个文件一起换）：

   ```bash
   uv run python scripts/octop_bot_manifest.py verify out/manifest.json
   ```

5. 测试通道没问题后，把它提升为稳定版，可以先灰度：

   ```bash
   uv run python scripts/octop_bot_manifest.py promote --manifest https://dl.lynxce.cn/releases/octop-bot/manifest.json --rollout 20 --out out/
   ```

   观察一段时间后用 `--rollout 100` 再执行一次。每次都要重新上传清单和签名。

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
