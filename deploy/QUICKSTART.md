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

## Security Checklist

- [ ] Changed all default passwords
- [ ] Using full JWT for Supabase service role key
- [ ] RabbitMQ not exposed to internet (only via internal network)
- [ ] ML service behind reverse proxy with SSL
- [ ] Firewall configured (only ports 80, 443, 22 open)
- [ ] SSH key authentication enabled, password auth disabled
- [ ] Regular backups configured

## Support

For detailed documentation, see [README.deployment.md](../README.deployment.md).

For issues, check logs and review troubleshooting section.
