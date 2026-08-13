#!/bin/bash
set -e

PROJECT_DIR="/home/ubuntu/Addy-TheVoiceAssistant"
BACKEND_DIR="$PROJECT_DIR/backend"
VENV_DIR="$BACKEND_DIR/venv"

echo "=== Addy Safe Deployment ==="
cd "$PROJECT_DIR"

# Save previous commit hash for rollback
PREV_COMMIT=$(git rev-parse HEAD)
echo "Current commit: $PREV_COMMIT"

# Pull latest changes
echo "Fetching latest changes..."
git fetch origin
git checkout main
git reset --hard origin/main

# Update dependencies
echo "Updating python dependencies..."
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -r "$BACKEND_DIR/requirements.txt"

# Validate syntax/imports
echo "Validating syntax and imports..."
python -c "import sys, glob, py_compile; [py_compile.compile(f) for f in glob.glob('$BACKEND_DIR/app/**/*.py', recursive=True)]" || {
    echo "❌ Syntax validation failed! Rolling back to $PREV_COMMIT..."
    git reset --hard $PREV_COMMIT
    exit 1
}

# Run test suite
echo "Running pytest..."
cd "$BACKEND_DIR"
if ! PYTHONPATH=. pytest; then
    echo "❌ Tests failed! Rolling back to $PREV_COMMIT..."
    git reset --hard $PREV_COMMIT
    exit 1
fi

# Restart Systemd service
echo "Restarting addy.service..."
sudo systemctl restart addy.service

# Update Nginx Configuration
echo "Updating Nginx configuration..."
sudo cp "$PROJECT_DIR/deploy/nginx/api.adarshsingh.in.conf" /etc/nginx/sites-available/
sudo systemctl reload nginx

# Wait and perform health check
echo "Waiting for service to start..."
sleep 3

echo "Running health check..."
HEALTH_RESP=$(curl -s http://127.0.0.1:8001/api/health || echo "FAILED")
echo "Health Response was: $HEALTH_RESP" > "$PROJECT_DIR/diag.txt"
sudo journalctl -u addy.service -n 50 --no-pager >> "$PROJECT_DIR/diag.txt"
systemctl is-active hermes-gateway >> "$PROJECT_DIR/diag.txt" || true
systemctl status hermes-gateway --no-pager >> "$PROJECT_DIR/diag.txt" || true

if [[ "$HEALTH_RESP" == *"\"status\":\"ok\""* ]]; then
    echo "✅ Addy voice assistant deployed and healthy!"
    echo "Health response: $HEALTH_RESP"
else
    echo "❌ Health check failed! Skipping rollback for diagnostics..."
    # git reset --hard $PREV_COMMIT
    # sudo systemctl restart addy.service
    # exit 1
fi
