#!/bin/bash
# Build the Octop Bot cloud-computer image on a fresh Tencent Cloud CVM (Ubuntu 22.04).
#
# The result serves the same desktop API as AGS's OSWorld sandboxes, so Octop's computer
# driver talks to both the same way:
#   - an XFCE desktop on display :0 (TigerVNC's Xvnc, VNC on 127.0.0.1:5900), 1920x1080
#   - OSWorld's desktop server on 127.0.0.1:5000 (/execute, /screenshot, /accessibility, ...)
#   - everything runs as `user`, workspace /home/user/workspace
#   - nginx on 443 is the only way in: TLS with a per-instance certificate and a per-instance
#     access token (X-Access-Token), both written by the instance's first-boot user data.
#     /p/5000/ goes to the desktop server, /p/8080/ to the VNC WebSocket bridge.
# Run as root. Ends by clearing cloud-init so each instance made from the image runs its own
# user data.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
  xfce4 xfce4-terminal xfce4-goodies dbus-x11 tigervnc-standalone-server tigervnc-common \
  x11-utils x11-xserver-utils xclip xdotool scrot wmctrl \
  python3-pip python3-dev python3-tk python3-venv python3-pyatspi gir1.2-atspi-2.0 at-spi2-core \
  nginx git curl wget unzip ca-certificates \
  fonts-noto-cjk fonts-noto-color-emoji language-pack-zh-hans \
  libreoffice-calc libreoffice-writer libreoffice-impress

# A browser: Chrome when Google's download host is reachable, else Firefox ESR.
if wget -q -T 60 -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; then
  apt-get install -y /tmp/chrome.deb
  rm -f /tmp/chrome.deb
else
  add-apt-repository -y ppa:mozillateam/ppa
  apt-get update
  apt-get install -y firefox-esr
fi

# The desktop user. It may use sudo: the computer is the Bot's own VM.
id user >/dev/null 2>&1 || useradd -m -s /bin/bash user
echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-octop-user
chmod 440 /etc/sudoers.d/90-octop-user
install -d -o user -g user /home/user/workspace /home/user/.octop /home/user/.octop/runs

# OSWorld's desktop server (the same one AGS's OSWorld sandboxes run).
git clone --depth 1 https://github.com/xlang-ai/OSWorld /opt/osworld || \
  git clone --depth 1 https://gitee.com/mirrors/OSWorld /opt/osworld
pip3 install -i https://mirrors.cloud.tencent.com/pypi/simple \
  flask pyautogui python-xlib lxml requests numpy pynput psutil pyperclip
# pyautogui's Linux screenshots need Pillow >= 9.2; Ubuntu's own python3-pil is 9.0, and pip
# leaves an apt package alone unless told to install over it.
pip3 install -i https://mirrors.cloud.tencent.com/pypi/simple --ignore-installed "pillow>=10"
python3 -c "import PIL; assert tuple(map(int, PIL.__version__.split('.')[:2])) >= (9, 2), PIL.__version__"
chown -R user:user /opt/osworld

cat > /etc/systemd/system/octop-vnc.service <<'EOF'
[Unit]
Description=Octop desktop (Xvnc :0, VNC on 127.0.0.1:5900)
After=network.target
[Service]
User=user
Environment=HOME=/home/user
ExecStart=/usr/bin/Xvnc :0 -geometry 1920x1080 -depth 24 -rfbport 5900 -localhost yes -SecurityTypes None -AlwaysShared
Restart=always
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/octop-session.service <<'EOF'
[Unit]
Description=Octop XFCE session on :0
After=octop-vnc.service
Requires=octop-vnc.service
[Service]
User=user
Environment=HOME=/home/user DISPLAY=:0 XDG_SESSION_TYPE=x11
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/dbus-launch --exit-with-session /usr/bin/startxfce4
Restart=always
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/octop-desktop-server.service <<'EOF'
[Unit]
Description=OSWorld desktop server on 127.0.0.1:5000
After=octop-session.service
[Service]
User=user
WorkingDirectory=/home/user
Environment=HOME=/home/user DISPLAY=:0 XAUTHORITY=/home/user/.Xauthority XDG_SESSION_TYPE=x11
ExecStartPre=/bin/sleep 4
ExecStart=/usr/bin/python3 /opt/osworld/desktop_env/server/main.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF

# nginx: the only way in. The first-boot user data writes /etc/octop/{token,cert.pem,key.pem}
# and renders /etc/nginx/conf.d/octop.conf from this template.
install -d -m 700 /etc/octop
cat > /etc/octop/nginx.conf.template <<'EOF'
map $http_upgrade $octop_connection { default upgrade; '' close; }
server {
    listen 443 ssl;
    ssl_certificate /etc/octop/cert.pem;
    ssl_certificate_key /etc/octop/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 512m;
    if ($http_x_access_token != "__TOKEN__") { return 403; }
    location /p/5000/ {
        proxy_pass http://127.0.0.1:5000/;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_request_buffering off;
    }
    location /p/8080/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $octop_connection;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
    location / { return 404; }
}
EOF
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable octop-vnc octop-session octop-desktop-server nginx

# Each instance made from this image runs its own user data on first boot.
cloud-init clean --logs || true
rm -f /etc/octop/token /etc/octop/cert.pem /etc/octop/key.pem /etc/nginx/conf.d/octop.conf
apt-get clean
echo OCTOP_IMAGE_READY
