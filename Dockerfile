# Stage 1: Get Caddy binary from official image
FROM caddy:2-alpine AS caddy

# Stage 2: Build application image
FROM python:3.11-slim

WORKDIR /app

# Copy Caddy binary from official image (ensures latest stable version)
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy Caddyfile
COPY Caddyfile /etc/caddy/Caddyfile

# Create necessary directories
RUN mkdir -p generated_apis static templates /data /config

# Set environment variables
ENV PYTHONPATH=/app
ENV ENVIRONMENT=production
ENV CADDY_ADMIN_URL=http://localhost:2019

# Expose ports: 80 (HTTP), 443 (HTTPS), 8000 (FastAPI internal)
EXPOSE 80 443 8000

# Health check - check both Caddy and FastAPI
HEALTHCHECK --interval=30s --timeout=30s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Create startup script
RUN echo '#!/bin/sh\n\
# Start Caddy in background\n\
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &\n\
\n\
# Wait for Caddy to start\n\
sleep 2\n\
\n\
# Start FastAPI with Gunicorn\n\
exec gunicorn -k uvicorn.workers.UvicornWorker -w 4 --timeout 300 --graceful-timeout 300 --keep-alive 5 --bind 0.0.0.0:8000 app.main:app\n\
' > /app/start.sh && chmod +x /app/start.sh

# Run the startup script
CMD ["/app/start.sh"]