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

- Don't expose RabbitMQ ports (5672, 15672) to the internet
- Use internal Docker networks
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


## Manual supabase stuff
1. Prod URL and redirect URLs in auth settings of supabase dashboard
2. Email templates
```
-- Reset password
{{ .ConfirmationURL }}&redirect_to={{ .SiteURL }}/reset-password
```
