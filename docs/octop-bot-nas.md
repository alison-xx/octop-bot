# 在 Docker 或飞牛 fnOS 上运行 Octop Bot

用浏览器打开 NAS 上的 Octop Bot，即可使用 Chief、专家通讯录、私聊、群聊、文件上传，以及「能力」中的 MCP 连接器、技能、知识库、IM 频道、插件、外部 Agent 和定时任务。首次打开时不需要向导口令或管理员账号：

- **用灵策智算账号登录**：输入灵策账号和密码。首次登录的灵策账号会成为这台 Octop Bot 的主人，以后只能用同一个灵策账号登录。密码只用于向灵策验证身份，不会保存在 NAS 上。
- **自己配置模型**：设置一个登录密码，然后在「账号与模型」连接自己的模型供应商。以后在其他设备打开时输入这个密码。

首次登录即认领实例，请在安装后尽快打开，并只在可信网络中暴露端口。桌面悬浮球、设备自动登录和依赖本机回调的灵策模型授权由 Windows、macOS 客户端提供。

## Docker Compose

在安装了 Docker Engine 和 Compose v2 的主机上，从源码构建并运行。

```sh
git clone https://github.com/alison-xx/octop-bot.git
cd octop-bot
docker compose up --build -d
```

访问 `http://<主机IP>:8090`，用灵策智算账号登录，或设置登录密码后自己配置模型。端口已占用时，可在仓库根目录的 `.env` 中设置 `OCTOP_BOT_PORT=9090`，再执行 `docker compose up -d`。

Compose 将数据库、模型配置、Bot 工作区和附件都写入 `bot-data` 卷。停用可执行 `docker compose down`。更新时在同一目录检出新版，重新执行 `docker compose up --build -d`。备份时先停止服务，再备份整个卷。有新版本时，网页版的「检查更新」会显示版本号、对应的镜像和升级步骤；网页版不会自行从 PyPI 升级。发版与更新机制见 [Octop Bot 更新机制与发版](octop-bot-updates.md)。

## 飞牛应用中心

### 原生版

在飞牛应用中心安装「Python 3.12」，并确认 8091 端口可用。在「手动安装」中选择与设备 CPU 对应的 `Octop-Bot-fnos-native-amd64-<版本>.fpk`（Intel、AMD）或 `Octop-Bot-fnos-native-arm64-<版本>.fpk`（ARM64）。程序、网页和 Python 依赖都在包内，首次启动无需下载镜像。

启动后打开「Octop Bot 原生版」，或访问 `http://<飞牛IP>:8091/octop-bot`，用灵策智算账号登录或设置登录密码。原生版使用独立的数据目录；升级前可停用应用并备份整个 `octop-bot-native/data`。

### Docker 版

1. 在 fnOS 应用中心安装 Docker，确认 8090 端口可用。使用与镜像配套的 `Octop-Bot-fnos-<版本>.fpk`。镜像由飞牛按本机架构拉取；也可以在安装前导入同架构、同标签的镜像。
2. 在应用中心选择「手动安装」，上传 FPK 并启动。在飞牛桌面打开 **Octop Bot**，或访问 `http://<飞牛IP>:8090/octop-bot`。
3. 用灵策智算账号登录，或设置登录密码后自己配置模型。以后用同一个灵策账号或这个密码登录。
4. 升级前停止应用并备份整个 `octop-bot/data`。新版本 FPK 沿用该目录。卸载时如需保留聊天与文件，请保留共享目录。

### 从源码制作 FPK 和离线镜像

在 Linux 仓库根目录运行以下命令。Windows 也可在已启动 Docker Desktop 的 Git Bash 中执行，打包脚本会使用 Linux 容器保留飞牛启动脚本的执行权限。构建机应与目标 NAS 架构相同，或在构建时通过 Docker Buildx 指定目标架构。打包脚本使用[飞牛官方 fnpack](https://developer.fnnas.com/docs/cli/fnpack/)，按照 `pyproject.toml` 中的版本生成 FPK 并锁定镜像标签。

```sh
version=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
arch=$(docker version --format '{{.Server.Arch}}')
OCTOP_BOT_TAG="nas-$version" docker compose build
bash scripts/build-fpk.sh bot
docker save "ghcr.io/alison-xx/octop-bot:nas-$version" | gzip > "dist/Octop-Bot-image-linux-$arch-$version.tar.gz"
```

版本读取命令使用 Python 3.11 或更高版本。把 `dist/` 下的 FPK 和镜像压缩包复制到飞牛，在 Docker 应用导入压缩包或执行 `docker load -i Octop-Bot-image-linux-<架构>-<版本>.tar.gz`，然后手动安装 FPK。已导入匹配镜像时，安装无需从 GHCR 拉取。

仓库的 **Octop Bot NAS** GitHub Actions 工作流会构建并推送 `linux/amd64`、`linux/arm64` 镜像，镜像发布成功后可从同一次运行的 **Octop-Bot-fnOS** 制品下载 FPK。

发布 `octop-bot-v<版本>` 的 GitHub Release（正式版或预发布版）后，该工作流会使用对应提交的 NAS 镜像，自动打包 AMD64 和 ARM64 原生 FPK，上传到该标签的 Release。两份包都构建成功后才开始上传。重跑工作流会补齐缺失的附件，已上传的包会保留。若需手动补发，在 Actions 的 **Octop Bot NAS** 中选择对应版本标签运行。单独的 `-macos` Release 只用于 macOS。

在构建机上可复用已发布镜像内同版本的 Bot 网页、后端和架构专用依赖，分别导出两份原生 FPK。将下面的版本替换为目标 Release 对应的 Python 版本。

```sh
version=1.0.4
for arch in amd64 arm64; do
  docker buildx build --platform "linux/$arch" -f scripts/fnos/bot-native.Dockerfile \
    --build-arg "BOT_IMAGE=ghcr.io/alison-xx/octop-bot:nas-$version" \
    --output type=local,dest=dist .
done
```
