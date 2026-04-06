# Quick Start - Production Deployment

This is a condensed guide for deploying to production. For full details, see [../README.deployment.md](../README.deployment.md).

## Prerequisites Checklist

- [ ] Ubuntu server with NVIDIA GPU
- [ ] NVIDIA drivers installed (`nvidia-smi` works)
- [ ] Docker installed
- [ ] nvidia-docker2 installed
- [ ] Production Supabase project created

## Deployment in 5 Steps

### 1. Server Setup (One-time)

```bash
# Install NVIDIA Docker support
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt update && sudo apt install -y nvidia-docker2
sudo systemctl restart docker

# Verify GPU access
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### 2. Clone Repository

```bash
git clone https://github.com/yourusername/textbook-tts.git
cd textbook-tts
```

### 3. Configure Environment

```bash
# Create production environment file
cp .env.production.example .env.production

# Edit with your values
nano .env.production
```

**Critical values to set:**
- `POSTGRES_HOST` - Your PostgreSQL server
- `POSTGRES_PASSWORD` - Strong password
- `SUPABASE_URL` - Production Supabase URL
- `SUPABASE_SERVICE_ROLE_KEY` - Full JWT token (not shortened format!)
- `RABBITMQ_PASS` - Strong password

### 4. Deploy

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

### 5. Verify

```bash
# Check services are running
docker compose -f docker-compose.prod.yml ps

# Test API endpoint
curl http://localhost:8001/health

# Check logs
docker compose -f docker-compose.prod.yml logs -f
```

## Optional: Set Up Reverse Proxy

### Install Nginx

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

### Configure

```bash
# Copy and edit nginx config
sudo cp deploy/nginx.conf /etc/nginx/sites-available/ml-service
sudo nano /etc/nginx/sites-available/ml-service

# Update: server_name, ssl_certificate paths

# Enable site
sudo ln -s /etc/nginx/sites-available/ml-service /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Get SSL Certificate

```bash
sudo certbot --nginx -d your-domain.com
```

## Common Commands

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f ml-service

# Restart services
docker compose -f docker-compose.prod.yml restart

# Stop services
docker compose -f docker-compose.prod.yml down

# Update deployment
git pull origin main && ./deploy/deploy.sh

# Check GPU usage
watch -n 1 nvidia-smi
```

## Troubleshooting Quick Checks

### Service won't start
```bash
docker compose -f docker-compose.prod.yml logs ml-service
```

### Can't connect to database
```bash
docker exec -it ml-service-prod env | grep POSTGRES
docker exec -it ml-service-prod psql -U postgres -h $POSTGRES_HOST
```

### RabbitMQ issues
```bash
docker compose -f docker-compose.prod.yml logs rabbitmq
docker exec -it rabbitmq-prod rabbitmq-diagnostics status
```

### GPU not accessible
```bash
# Check NVIDIA runtime
docker info | grep nvidia

# Test GPU in container
docker exec -it ml-service-prod nvidia-smi
```

## Optional: DigitalOcean Autoscaler

The autoscaler creates/destroys DO droplets to handle queue backlogs for CPU workers (fast-parser, datalab-parser, converter). GPU parsing always stays local.

### Prerequisites

- DigitalOcean account with API token
- An SSH key added to your DO account (get fingerprint from DO dashboard)
- `ufw` installed and enabled (deploy.sh auto-adds the port 5672 rule)

### Setup

**1. Configure env vars** (`MAIN_HOST_IP` is required — it's your server's public IP so droplets can reach RabbitMQ):

```bash
# In .env.production:
DIGITALOCEAN_API_TOKEN=your-do-api-token
DO_REGION=nyc3                              # match your server's region
DO_SSH_KEY_FINGERPRINT=ab:cd:ef:...        # from DO dashboard
MAIN_HOST_IP=1.2.3.4                       # this server's public IP
AUTOSCALER_MONTHLY_COST_CAP=50             # hard spend cap in USD
```

**2. Bake worker snapshots** (one-time, re-run if worker code changes):

```bash
./autoscaler/snapshot_bake.sh
# Prints snapshot IDs — copy them into .env.production:
DO_FAST_PARSER_SNAPSHOT_ID=123456789
DO_DATALAB_PARSER_SNAPSHOT_ID=123456790
DO_CONVERTER_SNAPSHOT_ID=123456791
```

**3. Deploy** — the autoscaler container starts automatically when `DIGITALOCEAN_API_TOKEN` and `MAIN_HOST_IP` are set:

```bash
./deploy/deploy.sh
```

**4. Verify**:

```bash
# Check autoscaler logs
docker compose -f docker-compose.prod.yml logs -f autoscaler

# Check Prometheus metrics (port 9095 inside ml_network)
# or view in Grafana → autoscaler dashboard

# Manually trigger scale-up test (flood a queue, watch logs)
docker compose -f docker-compose.prod.yml logs -f autoscaler | grep "SCALE"
```

### Snapshot rebuild

Re-run `./autoscaler/snapshot_bake.sh` whenever worker Dockerfiles or Python source changes. `deploy.sh` checks for this automatically and prompts if a rebuild is needed. After a rebuild, update the snapshot IDs in `.env.production` and redeploy.

### Troubleshooting

```bash
# Autoscaler can't reach RabbitMQ management API
docker exec autoscaler-prod curl -s http://rabbitmq-prod:15672/api/healthchecks/node

# DO droplets not connecting (check MAIN_HOST_IP and ufw rule)
sudo ufw status | grep 5672
nc -zv $MAIN_HOST_IP 5672

# Orphaned droplets (autoscaler reconciles on restart)
docker compose -f docker-compose.prod.yml restart autoscaler
```

## Security Checklist

- [ ] Changed all default passwords
- [ ] Using full JWT for Supabase service role key
- [ ] RabbitMQ port 5672 open only for autoscaler droplets (secured by RABBITMQ_USER/PASS + ufw)
- [ ] ML service behind reverse proxy with SSL
- [ ] Firewall configured (only ports 80, 443, 22 open)
- [ ] SSH key authentication enabled, password auth disabled
- [ ] Regular backups configured

## Support

For detailed documentation, see [README.deployment.md](../README.deployment.md).

For issues, check logs and review troubleshooting section.
