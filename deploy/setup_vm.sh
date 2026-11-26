#!/usr/bin/env bash
# Prepara uma VM Ubuntu 24.04 do zero para o fundo (idempotente).
# Pre-requisitos manuais: .env copiado para ~/monitor-acoes e Tailscale logado.
set -euo pipefail
sudo timedatectl set-timezone America/Sao_Paulo
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
echo 'vm.swappiness=20' | sudo tee /etc/sysctl.d/99-swap.conf >/dev/null && sudo sysctl -q -p /etc/sysctl.d/99-swap.conf
sudo DEBIAN_FRONTEND=noninteractive apt-get -y -qq install git python3-venv python3-pip sqlite3 rsync
cd ~/monitor-acoes
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt pytest
.venv/bin/python -c "from fundo import db; db.inicializar(); print('banco ok')"
chmod +x deploy/backup.sh
