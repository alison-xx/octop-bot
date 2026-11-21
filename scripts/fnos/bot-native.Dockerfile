# syntax=docker/dockerfile:1
# Build-time inputs only. The exported FPK runs on fnOS with its Python 3.12 app.
ARG BOT_IMAGE=scratch
ARG FNPACK_PLATFORM=linux/amd64
FROM ${BOT_IMAGE} AS release
FROM --platform=${FNPACK_PLATFORM} debian:bookworm-slim AS pack
ADD --checksum=sha256:54b97fa7b70968c4d05c79840f5daeff508957d0bb2062fdb0376d00d9615c93 https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-amd64 /usr/local/bin/fnpack
COPY fnos/bot-native/ /package/
COPY fnos/native/ICON*.PNG LICENSE /package/
COPY fnos/native/app/ui/images/ /package/app/ui/images/
COPY scripts/fnos/common.sh /package/cmd/
COPY scripts/fnos/store_version.sh /tmp/
ARG TARGETARCH
RUN --mount=from=release,source=/app,target=/release bash -eu <<'BUILD'
case "$TARGETARCH" in
    amd64) platform=x86 ;;
    arm64) platform=arm ;;
    *) exit 1 ;;
esac
version=$(sed -nE 's/^version = "([^"]+)".*/\1/p' /release/pyproject.toml | head -1)
sed -i 's/\r$//' /tmp/store_version.sh /package/cmd/*
store_version=$(bash /tmp/store_version.sh "$version")
sed -i "s/^version=.*/version=$store_version/;s/^platform=.*/platform=$platform/" /package/manifest

# The release installs Octop in editable mode. Relocate the actual application
# (including the Bot dashboard) and the locked wheels into the fnOS payload.
app=/package/app
sp="$app/site-packages"
cp -a /release/.venv/lib/python3.12/site-packages "$sp"
cp -a /release/src/octop "$sp/octop"
test -f "$sp/octop-$version.dist-info/METADATA"
test -s "$sp/octop/dashboard/index.html"
rm -f "$sp"/_editable_impl_octop.pth "$sp"/_virtualenv.{pth,py}
find "$sp" -type d -name __pycache__ -prune -exec rm -rf {} +
mkdir "$app/bin"
for script in /release/.venv/bin/*; do
    [[ -f "$script" && ! -L "$script" ]] || continue
    if grep -q '^#!/app/.venv/bin/python' "$script"; then
        sed '1c#!/usr/bin/env python3.12' "$script" > "$app/bin/${script##*/}"
        chmod 755 "$app/bin/${script##*/}"
    fi
done
test -x "$app/bin/octop"
cd /package/cmd
for phase in install upgrade uninstall config; do
    for hook in init callback; do printf '#!/bin/sh\nexit 0\n' > "${phase}_${hook}"; done
done
printf '#!/bin/sh\nexec "$(dirname "$0")/main" prepare\n' > install_callback
cp install_callback upgrade_callback
chmod 755 /usr/local/bin/fnpack /package/cmd/*
mkdir /output
cd /output
fnpack build --directory /package
mv octop-bot-native.fpk "Octop-Bot-fnos-native-$TARGETARCH-$version.fpk"
BUILD

FROM scratch
COPY --from=pack /output/ /
