# DigitalOcean Durable Deployment (Droplet + Docker)

This runbook deploys `server/server.py` with durable file storage.

## Quick start (automated)

On a fresh Ubuntu Droplet, run:

    sudo apt update
    sudo apt install -y git
    git clone https://github.com/YOUR_ORG/IFC-ECS.git
    cd IFC-ECS/server/deploy
    sudo bash bootstrap_droplet.sh --repo https://github.com/YOUR_ORG/IFC-ECS.git --domain YOUR_DOMAIN_OR_IP --data-root /opt/ifc-ecs-data

If using a mounted DO Block Storage volume, replace `--data-root /opt/ifc-ecs-data` with your mount path, for example `--data-root /mnt/ifcdata`.

## 1) Create Droplet

- Ubuntu 22.04 LTS
- Size: start at 2 vCPU / 4 GB RAM if processing IFCs
- Add SSH key
- Optional but recommended: attach a DigitalOcean Block Storage volume

## 2) SSH and install prerequisites

    sudo apt update
    sudo apt install -y docker.io docker-compose-plugin nginx git ufw
    sudo systemctl enable --now docker

## 3) Clone the repo

    sudo mkdir -p /opt/ifc-ecs
    sudo chown $USER:$USER /opt/ifc-ecs
    cd /opt/ifc-ecs
    git clone https://github.com/YOUR_ORG/IFC-ECS.git .

## 4) Prepare durable storage directories

If using root disk:

    sudo mkdir -p /opt/ifc-ecs-data/uploads /opt/ifc-ecs-data/data
    sudo chown -R $USER:$USER /opt/ifc-ecs-data

If using a mounted DO Volume (example mount at /mnt/ifcdata):

    sudo mkdir -p /mnt/ifcdata/uploads /mnt/ifcdata/data
    sudo chown -R $USER:$USER /mnt/ifcdata

Then edit deploy/docker-compose.yml and replace:
- /opt/ifc-ecs-data/uploads
- /opt/ifc-ecs-data/data

with your mounted volume paths.

## 5) Build and start app

    cd /opt/ifc-ecs/server/deploy
    docker compose up -d --build
    docker compose ps

## 6) Configure Nginx reverse proxy

    sudo cp /opt/ifc-ecs/server/deploy/nginx/ifc-ecs.conf /etc/nginx/sites-available/ifc-ecs

Edit server_name in /etc/nginx/sites-available/ifc-ecs to your domain or Droplet IP.

    sudo ln -s /etc/nginx/sites-available/ifc-ecs /etc/nginx/sites-enabled/ifc-ecs
    sudo nginx -t
    sudo systemctl restart nginx

## 7) Open firewall

    sudo ufw allow OpenSSH
    sudo ufw allow 'Nginx Full'
    sudo ufw --force enable

## 8) Enable auto-start at boot (systemd)

    sudo cp /opt/ifc-ecs/server/deploy/systemd/ifc-ecs-docker.service /etc/systemd/system/ifc-ecs-docker.service
    sudo systemctl daemon-reload
    sudo systemctl enable ifc-ecs-docker.service
    sudo systemctl start ifc-ecs-docker.service

## 9) Verify

    curl http://127.0.0.1:5000/api/status
    docker compose logs -f ifc-ecs

Public URLs:
- http://YOUR_DOMAIN_OR_IP/
- http://YOUR_DOMAIN_OR_IP/viewer
- http://YOUR_DOMAIN_OR_IP/api/status

## 10) Add TLS (recommended)

    sudo apt install -y certbot python3-certbot-nginx
    sudo certbot --nginx -d YOUR_DOMAIN

## Durable storage check

1. Upload a file from the UI.
2. Confirm files exist in your durable folders:

    ls -la /opt/ifc-ecs-data/uploads
    ls -la /opt/ifc-ecs-data/data

3. Reboot Droplet:

    sudo reboot

4. Re-check data and API status after reboot.
