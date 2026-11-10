#!/usr/bin/env bash
# ==============================================================================
# uninstall.sh - Uninstaller for Additional-Monitor-Brightness-Control-Widget
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}${BOLD}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}${BOLD}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*"; }

# Handle arguments
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    cat << EOF
Usage: ./uninstall.sh

Stops and disables the systemd user service, removes installed binaries,
and cleans up runtime sockets and cache.
EOF
    exit 0
fi

echo -e "${BOLD}==================================================================${NC}"
echo -e "${BOLD} Additional Monitor Brightness Control Widget - Uninstaller       ${NC}"
echo -e "${BOLD}==================================================================${NC}"

# 1. Stop & Disable systemd user service
info "Stopping and disabling systemd user service..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop hypr-monitor-dimmer.service 2>/dev/null || true
    systemctl --user disable hypr-monitor-dimmer.service 2>/dev/null || true
fi

# 2. Terminate running dimmer daemon instances
info "Stopping any running daemon processes..."
pkill -f "hypr-monitor-dimmer.py" 2>/dev/null || true

# 3. Remove systemd user unit file
SERVICE_FILE="${HOME}/.config/systemd/user/hypr-monitor-dimmer.service"
if [[ -f "$SERVICE_FILE" ]]; then
    rm -f "$SERVICE_FILE"
    ok "Removed ${SERVICE_FILE}"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload
    fi
fi

# 4. Remove binaries
info "Removing installed binaries..."
rm -f "${HOME}/.local/bin/hypr-monitor-dimmer.py"
rm -f "${HOME}/.local/bin/hypr-brightness.sh"

if [[ -w "/usr/local/bin" ]]; then
    rm -f "/usr/local/bin/hypr-monitor-dimmer.py"
    rm -f "/usr/local/bin/hypr-brightness.sh"
fi

ok "Removed script binaries."

# 5. Clean up temporary files & sockets
info "Cleaning up runtime sockets and cache..."
rm -f "/tmp/.ext_dimmer.sock"
rm -f "/tmp/.ext_brightness"
rm -f "/tmp/.ext_brightness.tmp."*

ok "Cleanup completed."
echo
echo -e "${GREEN}${BOLD}Uninstallation finished successfully!${NC}"
echo
