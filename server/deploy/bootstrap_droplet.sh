#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   sudo bash bootstrap_droplet.sh \
#     --repo https://github.com/YOUR_ORG/IFC-ECS.git \
#     --domain your.domain.com \
#     --data-root /opt/ifc-ecs-data
#
# Notes:
# - Run as root (sudo).
# - If you use a mounted DO Block Storage volume, pass it as --data-root.

REPO_URL=""
DOMAIN=""
DATA_ROOT="/opt/ifc-ecs-data"
APP_ROOT="/opt/ifc-ecs"
APP_USER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_URL="$2"
      shift 2
      ;;
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --data-root)
      DATA_ROOT="$2"
      shift 2
      ;;
    --app-root)
      APP_ROOT="$2"
      shift 2
      ;;
    --user)
      APP_USER="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: sudo bash bootstrap_droplet.sh --repo <git_url> --domain <domain_or_ip> [--data-root <path>] [--app-root <path>] [--user <linux_user>]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$REPO_URL" || -z "$DOMAIN" ]]; then
  echo "Error: --repo and --domain are required."
  echo "Use --help for usage."
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Error: run this script with sudo/root."
  exit 1
fi

if [[ -z "$APP_USER" ]]; then
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    APP_USER="${SUDO_USER}"
  else
    APP_USER="root"
  fi
fi

echo "[1/9] Installing packages..."
apt update
apt install -y docker.io docker-compose-plugin nginx git ufw curl
systemctl enable --now docker

echo "[2/9] Preparing application directories..."
mkdir -p "$APP_ROOT"
chown -R "$APP_USER":"$APP_USER" "$APP_ROOT"

mkdir -p "$DATA_ROOT/uploads" "$DATA_ROOT/data"
chown -R "$APP_USER":"$APP_USER" "$DATA_ROOT"

echo "[3/9] Cloning or updating repository..."
if [[ -d "$APP_ROOT/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_ROOT" fetch --all
  sudo -u "$APP_USER" git -C "$APP_ROOT" pull --ff-only
else
  rm -rf "$APP_ROOT"
  mkdir -p "$APP_ROOT"
  chown -R "$APP_USER":"$APP_USER" "$APP_ROOT"
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_ROOT"
fi

DEPLOY_DIR="$APP_ROOT/server/deploy"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
NGINX_TEMPLATE="$DEPLOY_DIR/nginx/ifc-ecs.conf"
NGINX_SITE="/etc/nginx/sites-available/ifc-ecs"
SYSTEMD_TEMPLATE="$DEPLOY_DIR/systemd/ifc-ecs-docker.service"
SYSTEMD_UNIT="/etc/systemd/system/ifc-ecs-docker.service"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Error: missing compose file at $COMPOSE_FILE"
  exit 1
fi

echo "[4/9] Updating Docker Compose volume paths..."
sed -i "s|/opt/ifc-ecs-data/uploads|$DATA_ROOT/uploads|g" "$COMPOSE_FILE"
sed -i "s|/opt/ifc-ecs-data/data|$DATA_ROOT/data|g" "$COMPOSE_FILE"

echo "[5/9] Building and starting Docker service..."
cd "$DEPLOY_DIR"
docker compose up -d --build

echo "[6/9] Installing Nginx site config..."
cp "$NGINX_TEMPLATE" "$NGINX_SITE"
sed -i "s|YOUR_DOMAIN_OR_IP|$DOMAIN|g" "$NGINX_SITE"
if [[ ! -L /etc/nginx/sites-enabled/ifc-ecs ]]; then
  ln -s "$NGINX_SITE" /etc/nginx/sites-enabled/ifc-ecs
fi
if [[ -L /etc/nginx/sites-enabled/default ]]; then
  rm -f /etc/nginx/sites-enabled/default
fi
nginx -t
systemctl restart nginx

echo "[7/9] Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "[8/9] Enabling systemd autostart for Docker stack..."
cp "$SYSTEMD_TEMPLATE" "$SYSTEMD_UNIT"
# Ensure the unit points to the current app path
sed -i "s|WorkingDirectory=/opt/ifc-ecs/server/deploy|WorkingDirectory=$DEPLOY_DIR|g" "$SYSTEMD_UNIT"
systemctl daemon-reload
systemctl enable ifc-ecs-docker.service
systemctl restart ifc-ecs-docker.service

echo "[9/9] Verification..."
sleep 2
curl -fsS http://127.0.0.1:5000/api/status || true

echo ""
echo "Deployment completed."
echo "App URL: http://$DOMAIN/"
echo "Viewer:  http://$DOMAIN/viewer"
echo "Status:  http://$DOMAIN/api/status"
echo "Data root: $DATA_ROOT"
echo ""
echo "Useful commands:"
echo "  docker compose -f $COMPOSE_FILE ps"
echo "  docker compose -f $COMPOSE_FILE logs -f ifc-ecs"
echo "  systemctl status ifc-ecs-docker.service"
