# Production Deployment Guide

This guide covers deploying the ML Service and RabbitMQ to a self-hosted server.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Server Setup](#server-setup)
- [Deployment Steps](#deployment-steps)
- [Configuration](#configuration)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Security Recommendations](#security-recommendations)
- [Manual supabase stuff](#manual-supabase-stuff)

## Prerequisites

### Hardware Requirements
- **GPU**: NVIDIA GPU with at least 8GB VRAM (16GB+ recommended for production)
- **RAM**: Minimum 16GB (32GB+ recommended)
- **Storage**: 100GB+ SSD (for model caching)
- **CPU**: 4+ cores recommended

### Software Requirements
- Ubuntu 20.04 LTS or newer (or compatible Linux distribution)
- Docker 24.0+ with GPU support
- NVIDIA drivers 525+
- nvidia-docker2
- (Optional) Nginx for reverse proxy
- (Optional) Certbot for SSL certificates

## Server Setup

### 1. Install NVIDIA Drivers

```bash
# Update package list
sudo apt update

# Install NVIDIA drivers
sudo apt install -y ubuntu-drivers-common
sudo ubuntu-drivers autoinstall

# Reboot
sudo reboot

# Verify installation
nvidia-smi
```

### 2. Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in for group changes to take effect
```

### 3. Install NVIDIA Container Toolkit

```bash
# Add NVIDIA repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Install nvidia-docker2
sudo apt update
sudo apt install -y nvidia-docker2

# Restart Docker
sudo systemctl restart docker

# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### 4. Install Nginx (Optional but Recommended)

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

# Configure firewall
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
```

## Deployment Steps

### 1. Clone Repository

```bash
# Clone your repository
git clone https://github.com/yourusername/textbook-tts.git
cd textbook-tts
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.production.example .env.production

# Edit with your production values
nano .env.production
```

**Important configuration values:**
- `POSTGRES_HOST`: Your production PostgreSQL host
- `POSTGRES_PASSWORD`: Strong password
- `SUPABASE_URL`: Your production Supabase URL
- `SUPABASE_SERVICE_ROLE_KEY`: Your production service role key (must be JWT format, not shortened)
- `RABBITMQ_USER` and `RABBITMQ_PASS`: Strong credentials

### 3. Deploy Services

```bash
# Run deployment script
./deploy/deploy.sh
```

The script will:
1. Pull latest code
2. Build Docker images
3. Stop existing containers
4. Start new containers
5. Wait for health checks
6. Verify deployment

### 4. Configure Nginx Reverse Proxy (Optional)

```bash
# Copy nginx configuration
sudo cp deploy/nginx.conf /etc/nginx/sites-available/ml-service

# Update domain name in the file
sudo nano /etc/nginx/sites-available/ml-service

# Create symlink
sudo ln -s /etc/nginx/sites-available/ml-service /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### 5. Set Up SSL Certificate

```bash
# Obtain SSL certificate with Certbot
sudo certbot --nginx -d your-ml-service-domain.com

# Auto-renewal is configured by default
# Test renewal:
sudo certbot renew --dry-run
```

## Configuration

### Environment Variables

See `.env.production.example` for all available configuration options.

### TTS Engine

The converter worker supports two TTS engines, controlled by env vars in `.env.production`:

| Variable | Values | Default |
|---|---|---|
| `TTS_ENGINE` | `supertonic` \| `kitten` | `supertonic` |
| `TTS_DOCKERFILE` | `Dockerfile.supertonic` \| `Dockerfile.kitten` | `Dockerfile.supertonic` |

**Supertonic** (default) — uses `supertone-inc/supertonic` with Supertone voice assets. Higher quality output.

**Kitten** — uses `KittenML/kitten-tts-micro-0.8`. Lightweight fallback, faster build, smaller image.

Both engines expose the same Celery task interface (`convert_to_audio_task`, `synthesize_sentence_task`) on the same queues, so switching engines only requires changing these two env vars and redeploying.

### Resource Limits

Edit `docker-compose.prod.yml` to adjust resource limits:

```yaml
deploy:
  resources:
    limits:
      memory: 16G  # Adjust based on your server
      cpus: '4.0'  # Adjust based on your server
```

### Scaling Celery Workers

To add more Celery workers, modify `ml-service/run.prod.sh`:

```bash
# Change -c 1 to desired number of workers
celery -A ml_worker worker -c 4 --loglevel=info
```

**Note**: Each worker will load models into GPU memory. Monitor VRAM usage.

## Monitoring

### View Logs

```bash
# ML Service logs
docker compose -f docker-compose.prod.yml logs -f ml-service

# RabbitMQ logs
docker compose -f docker-compose.prod.yml logs -f rabbitmq

# All logs
docker compose -f docker-compose.prod.yml logs -f
```

### Check Service Status

```bash
docker compose -f docker-compose.prod.yml ps
```

### RabbitMQ Management UI

Access at: `http://your-server-ip:15672`
- Username: Value of `RABBITMQ_USER` from `.env.production`
- Password: Value of `RABBITMQ_PASS` from `.env.production`

**Security Note**: Consider restricting access via firewall or reverse proxy with authentication.

### GPU Monitoring

```bash
# Real-time GPU monitoring
watch -n 1 nvidia-smi

# Inside container
docker exec -it ml-service-prod nvidia-smi
```

## Troubleshooting

### Service Won't Start

**Check logs:**
```bash
docker compose -f docker-compose.prod.yml logs ml-service
```

**Common issues:**
- NVIDIA runtime not available: Install nvidia-docker2
- Out of memory: Reduce worker count or increase server RAM
- GPU not accessible: Check NVIDIA drivers and docker runtime

### Database Connection Issues

**Verify PostgreSQL connectivity:**
```bash
docker exec -it ml-service-prod psql -U postgres -h your-db-host -p 5432
```

**Check environment variables:**
```bash
docker exec -it ml-service-prod env | grep POSTGRES
```

### RabbitMQ Connection Issues

**Check RabbitMQ is running:**
```bash
docker compose -f docker-compose.prod.yml ps rabbitmq
```

**Test connection:**
```bash
docker exec -it ml-service-prod python -c "from celery import Celery; app = Celery('test', broker='pyamqp://guest@rabbitmq:5672//'); print('Connected!')"
```

### Health Check Failures

**Manually test health endpoint:**
```bash
curl http://localhost:8001/
```

**Check if services are listening:**
```bash
docker exec -it ml-service-prod netstat -tlnp
```

## Security Recommendations

### 1. Secrets Management

**Don't use `.env` files in production!** Instead:
- Use Docker secrets
- Use a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)
- Use environment variables set at container runtime

### 2. Network Security

- Port 15672 (RabbitMQ management UI) must never be exposed — it's bound to localhost only
- Port 5672 (AMQP) is exposed only if using the DO autoscaler, secured by `RABBITMQ_USER`/`RABBITMQ_PASS` + ufw
- Use internal Docker networks for all other inter-service communication
- Put everything behind a reverse proxy with SSL
- Implement rate limiting (shown in nginx.conf)

### 3. Access Control

- Use strong passwords for all services
- Restrict SSH access (use SSH keys, disable password auth)
- Enable firewall (ufw)
- Regularly update packages and Docker images

### 4. Monitoring & Alerts

Consider setting up:
- Prometheus + Grafana for metrics
- Log aggregation (ELK stack, Loki, etc.)
- Uptime monitoring (UptimeRobot, etc.)
- Alert notifications (PagerDuty, Slack, etc.)

### 5. Backup Strategy

Backup these regularly:
- RabbitMQ data volume: `rabbitmq_data`
- Model cache directories: `hf-cache`, `dl-cache`
- Environment configuration files
- Database (PostgreSQL)

```bash
# Backup RabbitMQ data
docker run --rm -v rabbitmq_data:/data -v $(pwd):/backup ubuntu \
  tar czf /backup/rabbitmq-backup-$(date +%Y%m%d).tar.gz /data
```

## Updating

### Update Application Code

```bash
# Pull latest code
git pull origin main

# Rebuild and redeploy
./deploy/deploy.sh
```

### Update Docker Images

```bash
# Pull latest base images
docker compose -f docker-compose.prod.yml pull

# Rebuild
docker compose -f docker-compose.prod.yml build --no-cache

# Restart
docker compose -f docker-compose.prod.yml up -d
```

## Rollback

```bash
# Stop current deployment
docker compose -f docker-compose.prod.yml down

# Checkout previous version
git checkout <previous-commit-hash>

# Redeploy
./deploy/deploy.sh
```

## Performance Tuning

### Gunicorn Workers

Recommended formula: `(2 × CPU cores) + 1`

Edit `ml-service/run.prod.sh`:
```bash
--workers 9  # For 4-core server
```

### Celery Concurrency

- Start with 1 worker per GPU
- Monitor GPU memory usage
- Increase only if VRAM allows

### RabbitMQ

For high throughput, tune RabbitMQ:
```bash
# Add to docker-compose.prod.yml under rabbitmq environment:
- RABBITMQ_VM_MEMORY_HIGH_WATERMARK=0.6
```

## Support

For issues or questions:
1. Check logs first
2. Review this documentation
3. Search existing issues on GitHub
4. Create a new issue with:
   - Error messages
   - Relevant logs
   - System information
   - Steps to reproduce

---


## DigitalOcean Autoscaler

The autoscaler daemon monitors RabbitMQ queue depths and creates/destroys DigitalOcean droplets to scale CPU workers on demand. GPU parsing (`parse_queue`) always stays local. The three scalable worker types are:

| Queue | Worker | Droplet size | Max droplets |
|-------|--------|-------------|-------------|
| `fast_parse_queue` | fast-parser | s-1vcpu-1gb ($6/mo) | 3 |
| `datalab_parse_queue` | datalab-parser | s-1vcpu-1gb ($6/mo) | 3 |
| `convert_queue` | converter (TTS) | s-2vcpu-2gb ($12/mo) | 3 |

The autoscaler runs as a separate Docker container outside the main compose stack, since it needs access to the DO API and manages its own state.

### Prerequisites

- DigitalOcean account and API token
- `doctl` CLI installed locally for baking snapshots (`brew install doctl` / `snap install doctl`)
- SSH key added to your DO account (optional — only needed for debugging into droplets)

### Environment Variables

Add these to `.env.production` (see `.env.production.example` for all options):

```bash
DIGITALOCEAN_API_TOKEN=your-do-api-token
DO_REGION=nyc3                          # should match your server's region
DO_SSH_KEY_FINGERPRINT=ab:cd:ef:...    # from DO dashboard (optional, for debug SSH access)
MAIN_HOST_IP=your-server-ip-or-hostname # public address DO droplets use to reach RabbitMQ
AUTOSCALER_MONTHLY_COST_CAP=50         # hard spend cap in USD
```

### Expose RabbitMQ for DO Droplets

DO droplets connect to RabbitMQ over the internet. Two things needed:

**1. Expose port 5672** in `docker-compose.prod.yml` under the `rabbitmq` service — uncomment this line:

```yaml
# - "${MAIN_HOST_TUN0}:5672:5672"   # Bind AMQP to tun0 only (accessible from remote host)
```

Or bind to all interfaces if you don't have a dedicated interface:

```yaml
- "0.0.0.0:5672:5672"
```

**2. Open the port in ufw:**

```bash
sudo ufw allow 5672/tcp comment "RabbitMQ AMQP - DO autoscaler droplets"
```

Port 5672 is secured by `RABBITMQ_USER`/`RABBITMQ_PASS` credentials — droplets that don't have the credentials can't authenticate.

### Bake Worker Snapshots (One-time Setup)

The autoscaler boots droplets from a pre-baked snapshot that already has Docker and the worker images installed. Build it with:

```bash
# Source env so the script has DO credentials
source .env.production
./autoscaler/snapshot_bake.sh
```

This takes ~10 minutes. When done it prints a snapshot name — get its ID and update `.env.production`:

```bash
doctl compute snapshot list --format ID,Name | grep autoscaler-workers
# Then set in .env.production:
DO_FAST_PARSER_SNAPSHOT_ID=123456789
DO_DATALAB_PARSER_SNAPSHOT_ID=123456789   # same snapshot for all three
DO_CONVERTER_SNAPSHOT_ID=123456789        # WORKER_TYPE env var selects the image at boot
```

Re-run `snapshot_bake.sh` whenever worker Dockerfiles or Python source changes.

### Running the Autoscaler

Build and start the autoscaler container (runs outside the main compose stack, but joins the same network):

```bash
docker build -t autoscaler autoscaler/
docker run -d \
  --name autoscaler-prod \
  --restart unless-stopped \
  --env-file .env.production \
  -e RABBITMQ_MGMT_URL=http://rabbitmq-prod:15672 \
  --network ml_network \
  -v autoscaler_state:/var/lib/autoscaler \
  autoscaler
```

The autoscaler will log scale-up/down events and errors:

```bash
docker logs -f autoscaler-prod
```

To restart after a config change:

```bash
docker rm -f autoscaler-prod
# re-run docker run ... above
```

### Monitoring

The autoscaler exposes Prometheus metrics on port 9095 inside `ml_network`. To scrape them, add to `monitoring/prometheus/prometheus.prod.yml`:

```yaml
- job_name: 'autoscaler'
  static_configs:
    - targets: ['autoscaler-prod:9095']
```

Key metrics:
- `autoscaler_active_droplets{worker_type}` — current live droplets per type
- `autoscaler_scale_events_total{action,worker_type}` — cumulative scale up/down events
- `autoscaler_monthly_cost_usd` — estimated spend this month
- `autoscaler_queue_depth{queue}` — queue depths (mirrored from RabbitMQ)

Email alerts fire on scale events, capacity warnings (queue still deep at max droplets), and cost cap approach. Configure SMTP in `.env.production` (`smtp_*` vars).

### Troubleshooting

**Autoscaler can't reach RabbitMQ management API:**
```bash
docker exec autoscaler-prod curl -s http://rabbitmq-prod:15672/api/healthchecks/node
# If that fails, check autoscaler is on ml_network: docker inspect autoscaler-prod
```

**DO droplets not connecting to RabbitMQ:**
```bash
# Verify port 5672 is open
sudo ufw status | grep 5672
nc -zv $MAIN_HOST_IP 5672

# Check MAIN_HOST_IP is set correctly (must be reachable from the internet)
docker exec autoscaler-prod env | grep MAIN_HOST_IP
```

**Worker on droplet not starting:**
```bash
ssh root@<droplet-ip>
cat /var/log/cloud-init-output.log  # cloud-init startup
docker logs worker                   # worker container logs
```

**Orphaned droplets after autoscaler crash:**
```bash
docker rm -f autoscaler-prod
# re-run docker run ... — autoscaler reconciles state with DO API on startup
```

---

## Manual supabase stuff
0. After starting ML service backend, Enable RLS on the tables that Celery auto-creates
1. Prod URL and redirect URLs in auth settings of supabase dashboard
2. Email templates
```
-- Reset password
{{ .ConfirmationURL }}&redirect_to={{ .SiteURL }}/reset-password
```
