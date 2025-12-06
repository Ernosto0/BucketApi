#!/bin/sh
# Railway-compatible startup script for Caddy + FastAPI

echo "🚀 Starting Caddy + FastAPI..."

# Start Caddy in background
# Caddy will bind to ports 80/443 (requires capabilities set in Dockerfile)
echo "📦 Starting Caddy reverse proxy..."
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
CADDY_PID=$!

# Wait for Caddy to start and bind to ports
echo "⏳ Waiting for Caddy to initialize..."
sleep 3

# Verify Caddy is running
if ! kill -0 $CADDY_PID 2>/dev/null; then
    echo "❌ Caddy failed to start! Check logs above."
    echo "💡 Common issues:"
    echo "   - Ports 80/443 may not be available"
    echo "   - Caddyfile syntax error (check: caddy validate --config /etc/caddy/Caddyfile)"
    exit 1
fi

echo "✅ Caddy started successfully (PID: $CADDY_PID)"
echo "🌐 Caddy listening on ports 80 (HTTP) and 443 (HTTPS)"

# Start FastAPI with Gunicorn as non-root user
echo "🐍 Starting FastAPI application..."
exec gosu appuser gunicorn -k uvicorn.workers.UvicornWorker -w 4 \
    --timeout 300 --graceful-timeout 300 --keep-alive 5 \
    --bind 0.0.0.0:8000 app.main:app

