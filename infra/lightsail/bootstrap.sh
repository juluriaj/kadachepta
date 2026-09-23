#!/usr/bin/env bash
# First-boot script for the Lightsail instance (passed as user-data by provision.sh).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl git unattended-upgrades fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

# Docker Engine + Compose plugin from Docker's repository.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ubuntu

# Swap helps the 4-8 GB bundles during image builds.
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p /srv/kathachepta && chown ubuntu:ubuntu /srv/kathachepta
sudo -u ubuntu git clone https://github.com/juluriaj/kadachepta.git /srv/kathachepta || true
