#!/usr/bin/env bash
# ==============================================================================
# install.sh - Installer for Additional-Monitor-Brightness-Control-Widget
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}${BOLD}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}${BOLD}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*"; }
error() { echo -e "${RED}${BOLD}[ERROR]${NC} $*" >&2; }

# Parse arguments
GLOBAL_INSTALL=false
ENABLE_SERVICE=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --global|--system)
            GLOBAL_INSTALL=true
            shift
            ;;
        --no-service)
            ENABLE_SERVICE=false
            shift
            ;;
        --help|-h)
            cat << EOF
Usage: ./install.sh [OPTIONS]

Options:
  --global, --system   Install binaries to /usr/local/bin (requires sudo)
  --no-service         Do not automatically enable or start the systemd service
  -h, --help           Show this help message
EOF
            exit 0
            ;;
        *)
            warn "Unknown argument: $1"
            shift
            ;;
    esac
done

echo -e "${BOLD}==================================================================${NC}"
echo -e "${BOLD} Additional Monitor Brightness Control Widget - Installer         ${NC}"
echo -e "${BOLD} (KDE-style artificial layer-shell dimmer for Hyprland)           ${NC}"
echo -e "${BOLD}==================================================================${NC}"

# ------------------------------------------------------------------------------
# 1. Dependency & Prerequisite Checks
# ------------------------------------------------------------------------------
info "Checking system prerequisites..."

MISSING_DEPS=()

check_cmd() {
    if command -v "$1" >/dev/null 2>&1; then
        ok "Command found: $1"
    else
        error "Missing command: $1"
        MISSING_DEPS+=("$1")
    fi
}

check_cmd python3
check_cmd brightnessctl
check_cmd socat
check_cmd jq

# Check Python libraries: PyGObject, Gtk 3.0, GtkLayerShell, Cairo
info "Checking Python GObject and GtkLayerShell bindings..."

check_py_module() {
    local check_code="$1"
    local desc="$2"
    if python3 -c "$check_code" >/dev/null 2>&1; then
        ok "Python library OK: $desc"
    else
        error "Missing Python library: $desc"
        MISSING_DEPS+=("$desc")
    fi
}

check_py_module "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" "GTK 3.0 (python-gobject)"
check_py_module "import gi; gi.require_version('GtkLayerShell', '0.1'); from gi.repository import GtkLayerShell" "GtkLayerShell (gtk-layer-shell)"
check_py_module "import cairo" "Cairo (python-cairo)"

if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
    echo
    error "Missing prerequisites detected: ${MISSING_DEPS[*]}"
    echo
    info "Install required dependencies using your distribution's package manager:"
    echo
    echo -e "  ${BOLD}Arch Linux / Manjaro:${NC}"
    echo "    sudo pacman -S gtk-layer-shell python-gobject python-cairo socat jq brightnessctl"
    echo
    echo -e "  ${BOLD}Debian / Ubuntu:${NC}"
    echo "    sudo apt install python3-gi gir1.2-gtk-3.0 libgtk-layer-shell0 gir1.2-gtklayershell-0.1 python3-cairo socat jq brightnessctl"
    echo
    echo -e "  ${BOLD}Fedora:${NC}"
    echo "    sudo dnf install gtk-layer-shell python3-gobject python3-cairo socat jq brightnessctl"
    echo
    echo -e "  ${BOLD}openSUSE:${NC}"
    echo "    sudo zypper install gtk-layer-shell typelib-1_0-GtkLayerShell-0_1 python3-gobject python3-cairo socat jq brightnessctl"
    echo
    exit 1
fi

ok "All prerequisites are satisfied!"

# ------------------------------------------------------------------------------
# 2. File Installation
# ------------------------------------------------------------------------------
if [[ "$GLOBAL_INSTALL" == true || "$EUID" -eq 0 ]]; then
    BIN_DIR="/usr/local/bin"
    EXEC_START="/usr/local/bin/hypr-monitor-dimmer.py"
else
    BIN_DIR="${HOME}/.local/bin"
    EXEC_START="%h/.local/bin/hypr-monitor-dimmer.py"
fi

info "Installing executable scripts to ${BIN_DIR}..."
mkdir -p "$BIN_DIR"

install -m 755 "${SCRIPT_DIR}/bin/hypr-monitor-dimmer.py" "${BIN_DIR}/hypr-monitor-dimmer.py"
install -m 755 "${SCRIPT_DIR}/bin/hypr-brightness.sh" "${BIN_DIR}/hypr-brightness.sh"

ok "Installed ${BIN_DIR}/hypr-monitor-dimmer.py"
ok "Installed ${BIN_DIR}/hypr-brightness.sh"

# Ensure ~/.local/bin is in PATH if installing locally
if [[ "$GLOBAL_INSTALL" != true && ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "~/.local/bin is not in your current PATH."
    warn "Ensure 'export PATH=\"\$HOME/.local/bin:\$PATH\"' is added to your shell profile (~/.bashrc or ~/.zshrc)."
fi

# ------------------------------------------------------------------------------
# 3. Systemd User Service Setup
# ------------------------------------------------------------------------------
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

SERVICE_DEST="${SYSTEMD_USER_DIR}/hypr-monitor-dimmer.service"
info "Installing systemd user service to ${SERVICE_DEST}..."

sed "s|ExecStart=.*|ExecStart=${EXEC_START}|" \
    "${SCRIPT_DIR}/systemd/hypr-monitor-dimmer.service" > "$SERVICE_DEST"

ok "Configured service with ExecStart=${EXEC_START}"

if [[ "$ENABLE_SERVICE" == true ]]; then
    info "Reloading systemd user daemon and enabling service..."
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload
        systemctl --user enable --now hypr-monitor-dimmer.service
        ok "Service 'hypr-monitor-dimmer.service' is enabled and active!"
    else
        warn "systemctl command not found. You can manually launch 'hypr-monitor-dimmer.py' in your Hyprland autostart."
    fi
fi

# ------------------------------------------------------------------------------
# 4. Summary & Next Steps
# ------------------------------------------------------------------------------
echo
echo -e "${GREEN}${BOLD}Installation successfully completed!${NC}"
echo
info "Configuration Examples:"
info "  - Waybar module config: ${SCRIPT_DIR}/waybar/config.jsonc"
info "  - Hyprland keybindings: ${SCRIPT_DIR}/hyprland/hyprland.conf"
echo
info "Quick Test:"
info "  Run '${BIN_DIR}/hypr-brightness.sh --ext-get' to verify external brightness."
info "  Run '${BIN_DIR}/hypr-brightness.sh --ext-inc 5' to test incrementing brightness."
echo
