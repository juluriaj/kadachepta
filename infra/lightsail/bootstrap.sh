#!/usr/bin/env bash
# First-boot script for the Lightsail instance (passed as user-data by provision.sh, which saves it as
# /root/kathachepta-bootstrap.sh and runs it with bash). Its output is in /var/log/cloud-init-output.log.
# Safe to run again: sudo bash /root/kathachepta-bootstrap.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# Ubuntu's own updates may hold the apt lock right after boot: wait for it instead of failing.
echo 'DPkg::Lock::Timeout "600";' > /etc/apt/apt.conf.d/90-kathachepta-lock-timeout

apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl git rsync python3 unattended-upgrades fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

# Docker Engine + Compose plugin from Docker's repository; container logs rotate so they can't fill the disk.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
mkdir -p /etc/docker
echo '{"log-driver": "json-file", "log-opts": {"max-size": "20m", "max-file": "5"}}' > /etc/docker/daemon.json
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu

# Swap lets the 1 GB pilot bundle build images (the web app export needs about 2 GB). Builds are slow there
# and the site is sluggish while they run; on the 4 GB plan swap is just a safety net.
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /srv/kathachepta && chown ubuntu:ubuntu /srv/kathachepta
sudo -u ubuntu git clone https://github.com/juluriaj/kadachepta.git /srv/kathachepta || true
echo "KathaChepta bootstrap finished: $(date -u)"
