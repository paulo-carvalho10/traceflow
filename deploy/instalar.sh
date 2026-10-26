#!/usr/bin/env bash
# Prepara um servidor Ubuntu novo e sobe o TraceFlow inteiro (D69). Pode rodar de novo: o que já
# está feito é pulado, e o .env existente nunca é trocado.
#
#   curl -fsSL https://raw.githubusercontent.com/paulo-carvalho10/traceflow/main/deploy/instalar.sh | bash
#
# Na Oracle Cloud, as portas 80 e 443 também precisam estar liberadas na lista de segurança da
# rede (VCN), pelo painel: o firewall da máquina é só a segunda porta.
set -euo pipefail

REPO=https://github.com/paulo-carvalho10/traceflow.git
DIR="$HOME/traceflow"

echo "== 1. Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

echo "== 2. Firewall da máquina: 80 e 443"
# as imagens Ubuntu da Oracle fecham tudo menos o SSH no iptables
for port in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
done
if command -v netfilter-persistent >/dev/null; then sudo netfilter-persistent save; fi

echo "== 3. O código"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO" "$DIR"; fi
cd "$DIR"

echo "== 4. Os segredos (.env)"
if [ ! -f .env ]; then
  ip=$(curl -fsS https://api.ipify.org)
  umask 077  # só o dono lê
  cat > .env <<EOF
TRACEFLOW_SITE=${ip//./-}.sslip.io
POSTGRES_PASSWORD=$(openssl rand -hex 24)
TRACEFLOW_JWT_SECRET=$(openssl rand -hex 32)
TRACEFLOW_DEMO_INGEST_KEY=tf_$(openssl rand -hex 4)_$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')
EOF
fi
grep TRACEFLOW_SITE .env

echo "== 5. Subindo (a primeira vez constrói as imagens: uns 10 minutos)"
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml ps
echo "Pronto: https://$(grep TRACEFLOW_SITE .env | cut -d= -f2)"
