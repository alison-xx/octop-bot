# 在 Docker 或飞牛 fnOS 上运行 Octop Bot

用浏览器打开 NAS 上的 Octop Bot，即可使用 Chief、专家通讯录、私聊、群聊和文件上传。网页使用服务端账号登录，管理员可以在「账号与模型」连接模型供应商。桌面悬浮球、设备自动登录和依赖本机回调的灵策授权由 Windows、macOS 客户端提供。

## Docker Compose

在安装了 Docker Engine 和 Compose v2 的主机上，从源码构建并运行。

```sh
git clone https://github.com/alison-xx/octop-bot.git
cd octop-bot
docker compose up --build -d
docker compose exec bot cat /data/.octop/octop-login.txt
```

访问 `http://<主机IP>:8090`，用最后一条命令显示的口令解锁向导，创建管理员后进入 Bot。端口已占用时，可在仓库根目录的 `.env` 中设置 `OCTOP_BOT_PORT=9090`，再执行 `docker compose up -d`。

Compose 将数据库、模型配置、Bot 工作区和附件都写入 `bot-data` 卷。停用可执行 `docker compose down`。更新时在同一目录检出新版，重新执行 `docker compose up --build -d`。备份时先停止服务，再备份整个卷。

## 飞牛应用中心

1. 在 fnOS 应用中心安装 Docker，确认 8090 端口可用。使用与镜像配套的 `Octop-Bot-fnos-<版本>.fpk`。镜像由飞牛按本机架构拉取；也可以在安装前导入同架构、同标签的镜像。
2. 在应用中心选择「手动安装」，上传 FPK 并启动。在飞牛桌面打开 **Octop Bot**，或访问 `http://<飞牛IP>:8090/octop-bot`。
3. 从应用共享目录 `octop-bot/data/.octop/octop-login.txt` 取得向导口令。也可通过 SSH 运行 `sudo docker exec octop-bot-fnos cat /data/.octop/octop-login.txt`。用该口令在网页上创建管理员，后续使用管理员密码登录。
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
