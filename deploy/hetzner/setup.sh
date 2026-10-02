#!/bin/bash
# One-time bootstrap for a fresh Hetzner Ubuntu 24.04 box. Run as root:
#   scp -r deploy/hetzner root@<ip>:/root/ && ssh root@<ip> 'bash /root/hetzner/setup.sh'
# Before running: put the Cloudflare Origin CA cert + key at
# /root/hetzner/origin.pem and /root/hetzner/origin.key.
set -euo pipefail

apt-get update
apt-get install -y python3-venv python3-dev build-essential git ufw \
    debian-keyring debian-archive-keyring apt-transport-https curl

# Caddy (official repo)
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy

# App user, code, venv
id ptd &>/dev/null || useradd -m -s /bin/bash ptd
mkdir -p /var/lib/ptd/athlete_imgs
chown -R ptd:ptd /var/lib/ptd
mkdir -p /opt/ptd && chown ptd:ptd /opt/ptd
[ -d /opt/ptd/.git ] || sudo -u ptd git clone https://github.com/Angus-Toms/Pro-Tri-Data.git /opt/ptd
[ -d /opt/ptd/.venv ] || sudo -u ptd python3 -m venv /opt/ptd/.venv
sudo -u ptd /opt/ptd/.venv/bin/pip install -q -r /opt/ptd/requirements.txt

# ptd can restart its own service from deploy.sh without a password
echo "ptd ALL=(root) NOPASSWD: /bin/systemctl restart ptd" > /etc/sudoers.d/ptd
chmod 440 /etc/sudoers.d/ptd
# deploy.sh ssh's in as ptd with the same key as root
mkdir -p /home/ptd/.ssh && cp /root/.ssh/authorized_keys /home/ptd/.ssh/
chown -R ptd:ptd /home/ptd/.ssh && chmod 700 /home/ptd/.ssh

# systemd + Caddy
cp /root/hetzner/ptd.service /etc/systemd/system/ptd.service
cp /root/hetzner/Caddyfile /etc/caddy/Caddyfile
cp /root/hetzner/origin.pem /root/hetzner/origin.key /etc/caddy/
chown caddy:caddy /etc/caddy/origin.*; chmod 600 /etc/caddy/origin.key
systemctl daemon-reload
systemctl enable --now ptd
systemctl restart caddy

ufw allow OpenSSH; ufw allow 80; ufw allow 443; ufw --force enable

echo "Done. Now scp the DB: ./scripts/deploy.sh --no-git --no-static"
