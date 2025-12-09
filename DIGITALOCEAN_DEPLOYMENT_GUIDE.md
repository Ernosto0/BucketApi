# DigitalOcean Deployment Guide with Caddy

## Overview

This guide will help you deploy your AI-Powered API Generator to DigitalOcean with Caddy handling automatic SSL/TLS for dynamic custom domains.

## Prerequisites

- DigitalOcean account (sign up at https://www.digitalocean.com)
- Domain name (for your main app)
- Basic knowledge of Linux commands
- SSH key pair (we'll generate if needed)

## Step 1: Create DigitalOcean Droplet

### 1.1 Create New Droplet

1. Log in to DigitalOcean Dashboard
2. Click **"Create"** → **"Droplets"**
3. Configure:
   - **Image**: Ubuntu 22.04 (LTS)
   - **Plan**: Basic
   - **CPU**: Regular (2 vCPU, 4GB RAM minimum recommended)
   - **Datacenter**: Choose closest to your users
   - **Authentication**: SSH keys (add your SSH key or create new)
   - **Hostname**: `bucketapi` (or your preferred name)
4. Click **"Create Droplet"**

### 1.2 Note Your Droplet IP

After creation, note your droplet's **IP address** (e.g., `157.230.123.45`)

## Step 2: Initial Server Setup

### 2.1 Connect to Your Droplet

```bash
ssh root@YOUR_DROPLET_IP
```

### 2.2 Update System

```bash
apt update && apt upgrade -y
```

### 2.3 Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt install docker-compose -y

# Add your user to docker group (if not root)
usermod -aG docker $USER

# Verify installation
docker --version
docker-compose --version
```

### 2.4 Install Git (if needed)

```bash
apt install git -y
```

## Step 3: Clone Your Repository

### 3.1 Clone Your Code

```bash
# Create app directory
mkdir -p /opt/bucketapi
cd /opt/bucketapi

# Clone your repository
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git .

# OR if using SSH
git clone git@github.com:YOUR_USERNAME/YOUR_REPO.git .
```

### 3.2 Create Environment File

```bash
# Copy example env file
cp .env.example .env  # If you have one
# OR create new .env file
nano .env
```

Add your environment variables:

```bash
# MongoDB
MONGODB_URL=mongodb+srv://username:password@cluster.mongodb.net/
MONGODB_DB_NAME=bucketapi_db

# Main Domain
MAIN_DOMAIN=bucketapi.com

# Caddy Email (for Let's Encrypt)
CADDY_EMAIL=your-email@example.com

# OpenAI/Claude API Keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# OAuth (if using)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...

# Other settings
ENVIRONMENT=production
```

Save and exit (Ctrl+X, Y, Enter)

## Step 4: Configure Firewall

### 4.1 Set Up UFW (Uncomplicated Firewall)

```bash
# Allow SSH
ufw allow 22/tcp

# Allow HTTP
ufw allow 80/tcp

# Allow HTTPS
ufw allow 443/tcp

# Enable firewall
ufw enable

# Check status
ufw status
```

## Step 5: Configure DNS

### 5.1 Point Your Domain to DigitalOcean

1. Go to your domain registrar (GoDaddy, Namecheap, etc.)
2. Update DNS records:
   - **A Record**: `@` → `YOUR_DROPLET_IP`
   - **A Record**: `www` → `YOUR_DROPLET_IP` (optional)

### 5.2 Wait for DNS Propagation

DNS changes can take 5-60 minutes. Check propagation:
```bash
# From your local machine
nslookup bucketapi.com
# OR
dig bucketapi.com
```

## Step 6: Build and Run Docker Container

### 6.1 Build Docker Image

```bash
cd /opt/bucketapi
docker build -t bucketapi:latest .
```

### 6.2 Run Container

```bash
docker run -d \
  --name bucketapi \
  --restart unless-stopped \
  -p 80:80 \
  -p 443:443 \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/generated_apis:/app/generated_apis \
  -v $(pwd)/data:/data \
  bucketapi:latest
```

**Important**: Ports 80 and 443 are exposed so Caddy can handle TLS.

### 6.3 Check Container Status

```bash
docker ps
docker logs bucketapi
```

You should see:
- ✅ Caddy started successfully
- ✅ FastAPI started
- ✅ Listening on ports 80 and 443

## Step 7: Verify Deployment

### 7.1 Test HTTP (should redirect to HTTPS)

```bash
curl http://bucketapi.com/health
```

### 7.2 Test HTTPS

```bash
curl https://bucketapi.com/health
```

First HTTPS request may take 30-60 seconds (Caddy generating SSL certificate).

### 7.3 Check Caddy Logs

```bash
docker logs bucketapi | grep -i caddy
```

## Step 8: Set Up Automatic Updates (Optional)

### 8.1 Create Update Script

```bash
nano /opt/bucketapi/update.sh
```

Add:

```bash
#!/bin/bash
cd /opt/bucketapi
git pull
docker build -t bucketapi:latest .
docker stop bucketapi
docker rm bucketapi
docker run -d \
  --name bucketapi \
  --restart unless-stopped \
  -p 80:80 \
  -p 443:443 \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/generated_apis:/app/generated_apis \
  -v $(pwd)/data:/data \
  bucketapi:latest
```

Make executable:
```bash
chmod +x /opt/bucketapi/update.sh
```

## Step 9: Configure Custom Domains

### 9.1 Add Custom Domain in Your App

1. Go to `https://bucketapi.com`
2. Navigate to API Details → Custom Domains tab
3. Add domain: `loopfeedback.dev`
4. Follow verification instructions

### 9.2 Configure DNS for Custom Domain

At your domain registrar for `loopfeedback.dev`:

1. **Add A Record**:
   - Type: `A`
   - Name: `@`
   - Value: `YOUR_DROPLET_IP`
   - TTL: `300`

2. **Add TXT Record for Verification**:
   - Type: `TXT`
   - Name: `_bucketapi-verify`
   - Value: `[verification token from your app]`
   - TTL: `300`

3. **Verify in Your App**:
   - Go back to your app
   - Click "Verify" on the domain
   - Status should change to "active"

### 9.3 Test Custom Domain

```bash
# Wait for DNS propagation (5-60 minutes)
curl https://loopfeedback.dev/api/api-1764859641148
```

First request takes 30-60 seconds (Caddy generating SSL certificate).

## Step 10: Set Up Monitoring (Optional)

### 10.1 Install Monitoring Tools

```bash
# Install htop for process monitoring
apt install htop -y

# Install fail2ban for security
apt install fail2ban -y
systemctl enable fail2ban
systemctl start fail2ban
```

### 10.2 Set Up Log Rotation

Create log rotation config:

```bash
nano /etc/logrotate.d/bucketapi
```

Add:

```
/opt/bucketapi/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

## Step 11: Backup Strategy

### 11.1 Backup MongoDB

Set up regular MongoDB backups (if using self-hosted MongoDB):

```bash
# Create backup script
nano /opt/bucketapi/backup-mongodb.sh
```

### 11.2 Backup Generated APIs

```bash
# Create backup script
nano /opt/bucketapi/backup-apis.sh
```

Add:

```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf /opt/backups/generated_apis_$DATE.tar.gz /opt/bucketapi/generated_apis
# Keep only last 7 days
find /opt/backups -name "generated_apis_*.tar.gz" -mtime +7 -delete
```

Make executable and add to crontab:

```bash
chmod +x /opt/bucketapi/backup-apis.sh
crontab -e
# Add: 0 2 * * * /opt/bucketapi/backup-apis.sh
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs bucketapi

# Check if ports are in use
netstat -tulpn | grep -E ':(80|443|8000)'

# Restart container
docker restart bucketapi
```

### Caddy Can't Bind to Ports 80/443

```bash
# Check if another service is using ports
sudo lsof -i :80
sudo lsof -i :443

# Stop conflicting services
systemctl stop apache2  # If installed
systemctl stop nginx    # If installed
```

### SSL Certificate Issues

```bash
# Check Caddy logs
docker logs bucketapi | grep -i certificate

# Verify DNS points to your droplet
nslookup bucketapi.com

# Check Caddy storage
docker exec bucketapi ls -la /data/caddy
```

### Can't Access App

1. **Check firewall**:
   ```bash
   ufw status
   ```

2. **Check container**:
   ```bash
   docker ps
   docker logs bucketapi
   ```

3. **Test locally on server**:
   ```bash
   curl http://localhost/health
   curl https://localhost/health
   ```

## Security Best Practices

1. **Use SSH Keys** (not passwords)
2. **Keep system updated**: `apt update && apt upgrade -y`
3. **Use fail2ban** for brute force protection
4. **Regular backups**
5. **Monitor logs**: `docker logs -f bucketapi`
6. **Use strong passwords** for MongoDB and API keys
7. **Limit SSH access** (use firewall rules)

## Cost Estimate

- **Droplet**: $12/month (2 vCPU, 4GB RAM)
- **Domain**: ~$10-15/year
- **Total**: ~$12-15/month

## Next Steps

1. ✅ Deploy to DigitalOcean
2. ✅ Configure DNS
3. ✅ Test main domain
4. ✅ Add custom domains
5. ✅ Set up monitoring
6. ✅ Configure backups

## Support

If you encounter issues:
1. Check Docker logs: `docker logs bucketapi`
2. Check system logs: `journalctl -u docker`
3. Verify DNS: `nslookup your-domain.com`
4. Test ports: `curl http://your-domain.com/health`

Your app should now be running on DigitalOcean with full Caddy support for dynamic custom domains! 🎉


