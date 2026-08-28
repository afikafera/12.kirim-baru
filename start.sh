#!/bin/bash
echo "========================================"
echo " Technical Research Assistant - Startup"
echo "========================================"

cd ~/research-assistant
source venv/bin/activate

echo ""
echo "[1/3] Starting Docker containers..."
docker compose up -d postgres qdrant open-webui
sleep 5

echo "[2/3] Checking Langfuse..."

./venv/bin/python - <<'PY_LANGFUSE'
import os
from config import load_config

load_config()

required = [
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
]

missing = [k for k in required if not os.environ.get(k)]

if missing:
    print("❌ Langfuse config missing:", ", ".join(missing))
    raise SystemExit(1)

from langfuse import get_client

client = get_client()

if not client.auth_check():
    print("❌ Langfuse authentication failed")
    raise SystemExit(1)

print("✅ Langfuse     : Ready")
PY_LANGFUSE

if [ $? -ne 0 ]; then
    echo "❌ Startup stopped: Langfuse preflight failed"
    exit 1
fi

echo "[3/3] Starting FastAPI..."
sudo pkill uvicorn 2>/dev/null
sleep 1
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
sleep 3

echo "[3/3] Verifying services..."
echo ""

# Cek PostgreSQL
if docker compose ps | grep research-db | grep -q Up; then
    echo "✅ PostgreSQL : Running"
else
    echo "❌ PostgreSQL : Not running"
fi

# Cek Qdrant
if docker compose ps | grep research-qdrant | grep -q Up; then
    echo "✅ Qdrant      : Running"
else
    echo "❌ Qdrant      : Not running"
fi

# Cek Open WebUI
if docker compose ps | grep research-webui | grep -q Up; then
    echo "✅ Open WebUI  : Running"
else
    echo "❌ Open WebUI  : Not running"
fi

# Cek FastAPI
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ FastAPI     : Running"
else
    echo "❌ FastAPI     : Not running"
fi

echo ""
echo "========================================"
echo " Akses Open WebUI: http://192.168.68.102:8080"
echo "========================================"
