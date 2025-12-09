#!/bin/bash
# DigitalOcean Deployment Script for BucketAPI

set -e  # Exit on error

echo "🚀 Starting BucketAPI Deployment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root or with sudo${NC}"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker not found. Installing...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo -e "${YELLOW}Docker Compose not found. Installing...${NC}"
    apt update
    apt install -y docker-compose
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}.env file not found. Creating template...${NC}"
    cat > .env << EOF
# MongoDB
MONGODB_URL=mongodb+srv://username:password@cluster.mongodb.net/
MONGODB_DB_NAME=bucketapi_db

# Main Domain
MAIN_DOMAIN=bucketapi.com

# Caddy Email (for Let's Encrypt)
CADDY_EMAIL=admin@bucketapi.com

# Add your other environment variables here
EOF
    echo -e "${RED}Please edit .env file with your actual values before continuing!${NC}"
    exit 1
fi

# Stop existing container if running
if [ "$(docker ps -q -f name=bucketapi)" ]; then
    echo -e "${YELLOW}Stopping existing container...${NC}"
    docker stop bucketapi || true
    docker rm bucketapi || true
fi

# Build Docker image
echo -e "${GREEN}Building Docker image...${NC}"
docker build -t bucketapi:latest .

# Run container
echo -e "${GREEN}Starting container...${NC}"
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

# Wait for container to start
echo -e "${YELLOW}Waiting for services to start...${NC}"
sleep 5

# Check container status
if [ "$(docker ps -q -f name=bucketapi)" ]; then
    echo -e "${GREEN}✅ Container started successfully!${NC}"
    echo ""
    echo "Container logs:"
    docker logs bucketapi --tail 20
    echo ""
    echo -e "${GREEN}Deployment complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Check logs: docker logs -f bucketapi"
    echo "2. Test health: curl http://localhost/health"
    echo "3. Configure DNS to point to this server's IP"
else
    echo -e "${RED}❌ Container failed to start!${NC}"
    echo "Check logs: docker logs bucketapi"
    exit 1
fi


