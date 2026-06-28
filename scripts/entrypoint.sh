#!/bin/sh
# Betbot entrypoint — runs the requested service.
# Usage: entrypoint.sh {bot|dashboard}
set -e

SERVICE="${1:-bot}"

echo "=========================================="
echo "Betbot entrypoint — service: $SERVICE"
echo "PWD: $(pwd)"
echo "=========================================="

echo "Filesystem check:"
ls -la /app/ 2>/dev/null || echo "  /app/ NOT FOUND"
echo "---"
ls -la /app/dashboard/ 2>/dev/null || echo "  /app/dashboard/ NOT FOUND"
echo "---"
ls -la /app/betbot/ 2>/dev/null || echo "  /app/betbot/ NOT FOUND"
echo "=========================================="

case "$SERVICE" in
    bot)
        echo "Starting bot scheduler..."
        exec python -m betbot.main
        ;;
    dashboard)
        if [ ! -f /app/dashboard/app.py ]; then
            echo "FATAL: /app/dashboard/app.py not found"
            echo "Files in /app/:"
            find /app -maxdepth 2 -type f 2>/dev/null | head -30
            exit 1
        fi
        echo "Starting Streamlit dashboard on :8501..."
        exec streamlit run /app/dashboard/app.py \
            --server.port=8501 \
            --server.address=0.0.0.0 \
            --server.headless=true \
            --server.runOnSave=false \
            --browser.gatherUsageStats=false
        ;;
    setup)
        echo "Running setup (fetch CSVs + train ML)..."
        exec python -m betbot.cli setup
        ;;
    bash|sh)
        exec /bin/sh
        ;;
    *)
        echo "Unknown service: $SERVICE (use bot|dashboard|setup|bash)"
        exec "$@"
        ;;
esac
