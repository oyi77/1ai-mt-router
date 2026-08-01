#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="mt5-router"
SERVICE_FILE="$SCRIPT_DIR/mt5-router.service"
TARGET="/etc/systemd/system/$SERVICE_NAME.service"

echo "Installing MT5 Router systemd service..."

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo ./install-service.sh"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/../.env" ]; then
    echo "ERROR: .env not found at $SCRIPT_DIR/../.env"
    echo "Run './setup.sh prod' (or local/dev) first to generate it, then re-run this installer."
    exit 1
fi

cp "$SERVICE_FILE" "$TARGET"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "Service installed and started."
echo "  Status: systemctl status $SERVICE_NAME"
echo "  Logs:   journalctl -u $SERVICE_NAME -f"
