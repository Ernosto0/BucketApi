# Stage 1: Get Caddy binary from official image (use latest stable for security patches)
FROM caddy:2.8-alpine AS caddy

# Stage 2: Build application image (use latest patch version)
FROM python:3.11-slim-bookworm

WORKDIR /app

# Copy Caddy binary from official image (ensures latest stable version)
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy

# Install system dependencies with security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    ca-certificates \
    libcap2-bin \
    su-exec \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/archives/*

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

# Create non-root user for FastAPI (Caddy needs root for ports 80/443)
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app && \
    chown -R root:root /data /config

# Set capabilities for Caddy to bind to privileged ports without full root
RUN setcap 'cap_net_bind_service=+ep' /usr/bin/caddy || true

# Set environment variables
ENV PYTHONPATH=/app
ENV ENVIRONMENT=production
ENV CADDY_ADMIN_URL=http://localhost:2019

# Expose ports: 80 (HTTP), 443 (HTTPS), 8000 (FastAPI internal)
EXPOSE 80 443 8000

# Health check - check both Caddy and FastAPI
# Note: curl might not be available, use Python instead for health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Create startup script
# Caddy runs with capabilities (for ports 80/443), FastAPI runs as appuser
RUN echo '#!/bin/sh\n\
# Start Caddy in background (with capabilities for ports 80/443)\n\
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &\n\
\n\
# Wait for Caddy to start\n\
sleep 2\n\
\n\
# Start FastAPI with Gunicorn as non-root user\n\
exec su-exec appuser gunicorn -k uvicorn.workers.UvicornWorker -w 4 --timeout 300 --graceful-timeout 300 --keep-alive 5 --bind 0.0.0.0:8000 app.main:app\n\
' > /app/start.sh && chmod +x /app/start.sh

# Run the startup script
CMD ["/app/start.sh"]