#!/usr/bin/env bash
# ==============================================================================
# hypr-brightness.sh - Ultra-low-latency brightness client for Hyprland & Waybar
# Controls:
#   - External Monitor: KDE-style artificial layer dimmer (via hypr-monitor-dimmer)
#   - Internal Laptop Display: Hardware backlight (via brightnessctl)
# ==============================================================================

set -o pipefail

# Configuration & Paths
SOCK_PATH="${EXT_DIMMER_SOCK:-/tmp/.ext_dimmer.sock}"
CACHE_FILE="${EXT_DIMMER_CACHE:-/tmp/.ext_brightness}"
DEFAULT_STEP=2
ICON_DIR="${HOME}/.config/swaync/icons"
NOTIFICATION_TAG="brightness_notif"

# Auto-discover Hyprland instance signature if missing
if [[ -z "$HYPRLAND_INSTANCE_SIGNATURE" ]]; then
    RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if [[ -d "${RUNTIME_DIR}/hypr" ]]; then
        HYPRLAND_INSTANCE_SIGNATURE=$(find "${RUNTIME_DIR}/hypr" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | head -n 1)
        export HYPRLAND_INSTANCE_SIGNATURE
    fi
fi

# Ensure dimmer daemon is active and responsive
ensure_daemon() {
    # 1. Check if systemd user unit is running
    if systemctl --user is-active --quiet hypr-monitor-dimmer.service 2>/dev/null; then
        return 0
    fi

    # 2. Check if socket is responsive
    if [[ -S "$SOCK_PATH" ]]; then
        if timeout 0.2 socat -t 0.05 - UNIX-CONNECT:"$SOCK_PATH" <<< "get" >/dev/null 2>&1; then
            return 0
        fi
    fi

    # 3. Attempt starting systemd service
    if systemctl --user start hypr-monitor-dimmer.service 2>/dev/null; then
        return 0
    fi

    # 4. Fallback: launch daemon directly in background
    if ! pgrep -f "hypr-monitor-dimmer.py" >/dev/null 2>&1; then
        local daemon_bin=""
        if [[ -x "${HOME}/.local/bin/hypr-monitor-dimmer.py" ]]; then
            daemon_bin="${HOME}/.local/bin/hypr-monitor-dimmer.py"
        elif [[ -x "/usr/local/bin/hypr-monitor-dimmer.py" ]]; then
            daemon_bin="/usr/local/bin/hypr-monitor-dimmer.py"
        elif [[ -x "$(dirname "$0")/hypr-monitor-dimmer.py" ]]; then
            daemon_bin="$(dirname "$0")/hypr-monitor-dimmer.py"
        fi

        if [[ -n "$daemon_bin" ]]; then
            rm -f "$SOCK_PATH"
            nohup "$daemon_bin" >/dev/null 2>&1 &
            # Brief pause for socket initialization
            local i=0
            while (( i < 5 )); do
                [[ -S "$SOCK_PATH" ]] && break
                sleep 0.05
                (( i++ ))
            done
        fi
    fi
}

# Fast sub-second socket sender
send_socket_cmd() {
    local cmd="$1"
    if [[ -S "$SOCK_PATH" ]]; then
        timeout 0.2 socat -t 0.05 - UNIX-CONNECT:"$SOCK_PATH" <<< "$cmd" 2>/dev/null || true
    fi
}

# Query currently focused monitor name from Hyprland
get_focused_monitor() {
    local focused
    focused=$(hyprctl monitors -j 2>/dev/null | jq -r '.[] | select(.focused == true) | .name' 2>/dev/null)
    echo "${focused:-eDP-1}"
}

# Check if an external monitor is currently attached in Hyprland
has_external_monitor() {
    hyprctl monitors -j 2>/dev/null | jq -e '
        .[] | select(
            ((.name | test("^(eDP|LVDS|dsi|DSI)") | not) and
            (.name | test("^(HDMI|DP|DVI)") or .x > 0 or .y > 0))
        )
    ' >/dev/null 2>&1
}

# Resolve icon path for notifications
get_notification_icon() {
    local val="$1"
    local rounded=$(( ((val + 19) / 20) * 20 ))
    (( rounded > 100 )) && rounded=100
    (( rounded < 20 )) && rounded=20

    if [[ -f "${ICON_DIR}/brightness-${rounded}.png" ]]; then
        echo "${ICON_DIR}/brightness-${rounded}.png"
    else
        echo "display-brightness-symbolic"
    fi
}

# Send desktop notification with progress bar
send_notification() {
    local val="$1"
    local title="$2"
    local icon
    icon=$(get_notification_icon "$val")

    notify-send -e \
        -h "string:x-canonical-private-synchronous:${NOTIFICATION_TAG}" \
        -h "int:value:${val}" \
        -u low \
        -i "$icon" \
        "$title" "Brightness: ${val}%" 2>/dev/null || true
}

# ==============================================================================
# External Monitor Functions
# ==============================================================================

get_external_brightness() {
    local val=""
    if [[ -S "$SOCK_PATH" ]]; then
        val=$(send_socket_cmd "get")
    fi
    if [[ -z "$val" && -f "$CACHE_FILE" ]]; then
        val=$(head -n 1 "$CACHE_FILE" 2>/dev/null | tr -cd '0-9')
    fi
    echo "${val:-100}"
}

ext_inc() {
    local step="${1:-$DEFAULT_STEP}"
    ensure_daemon
    local res
    res=$(send_socket_cmd "inc ${step}")
    local cur="${res:-$(get_external_brightness)}"
    send_notification "$cur" "External Monitor"
    echo "$cur"
}

ext_dec() {
    local step="${1:-$DEFAULT_STEP}"
    ensure_daemon
    local res
    res=$(send_socket_cmd "dec ${step}")
    local cur="${res:-$(get_external_brightness)}"
    send_notification "$cur" "External Monitor"
    echo "$cur"
}

ext_set() {
    local val="$1"
    if [[ -z "$val" ]]; then
        echo "Error: missing brightness value" >&2
        return 1
    fi
    ensure_daemon
    local res
    res=$(send_socket_cmd "set ${val}")
    local cur="${res:-$(get_external_brightness)}"
    send_notification "$cur" "External Monitor"
    echo "$cur"
}

ext_toggle_night() {
    local cur
    cur=$(get_external_brightness)
    if (( cur <= 30 )); then
        ext_set 100
    else
        ext_set 20
    fi
}

ext_waybar_json() {
    if has_external_monitor; then
        local val
        val=$(get_external_brightness)
        echo "{\"text\": \"${val}%\联\", \"tooltip\": \"External Monitor: ${val}%\", \"percentage\": ${val}}" | sed 's/\\联//'
    else
        # Output empty JSON for hide-empty-text in Waybar
        echo "{}"
    fi
}

# ==============================================================================
# Internal (Laptop Screen) Functions
# ==============================================================================

get_internal_brightness() {
    local val
    val=$(brightnessctl -c backlight -m 2>/dev/null | head -n 1 | cut -d, -f4 | tr -d '%')
    if [[ -z "$val" ]]; then
        # Fallback to default classless device
        val=$(brightnessctl -m 2>/dev/null | head -n 1 | cut -d, -f4 | tr -d '%')
    fi
    echo "${val:-100}"
}

int_inc() {
    local step="${1:-$DEFAULT_STEP}"
    brightnessctl -c backlight set "+${step}%" >/dev/null 2>&1 || brightnessctl set "+${step}%" >/dev/null 2>&1
    local cur
    cur=$(get_internal_brightness)
    send_notification "$cur" "Laptop Screen"
    echo "$cur"
}

int_dec() {
    local step="${1:-$DEFAULT_STEP}"
    brightnessctl -c backlight set "${step}%-" >/dev/null 2>&1 || brightnessctl set "${step}%-" >/dev/null 2>&1
    local cur
    cur=$(get_internal_brightness)
    send_notification "$cur" "Laptop Screen"
    echo "$cur"
}

# Smart monitor switching: changes brightness on whichever display currently has focus
smart_change() {
    local action="$1"
    local step="${2:-$DEFAULT_STEP}"
    local focused
    focused=$(get_focused_monitor)

    if [[ "$focused" =~ ^(HDMI|DP|DVI) ]]; then
        if [[ "$action" == "inc" ]]; then
            ext_inc "$step"
        else
            ext_dec "$step"
        fi
    else
        if [[ "$action" == "inc" ]]; then
            int_inc "$step"
        else
            int_dec "$step"
        fi
    fi
}

# ==============================================================================
# CLI Argument Router
# ==============================================================================

case "$1" in
    # Waybar module endpoint
    "--ext-waybar")
        ext_waybar_json
        ;;

    # External monitor controls
    "--ext-inc")
        ext_inc "$2"
        ;;
    "--ext-dec")
        ext_dec "$2"
        ;;
    "--ext-set")
        ext_set "$2"
        ;;
    "--ext-get")
        get_external_brightness
        ;;
    "--toggle-night")
        ext_toggle_night
        ;;

    # Internal laptop controls
    "--int-inc")
        int_inc "$2"
        ;;
    "--int-dec")
        int_dec "$2"
        ;;
    "--int-get")
        get_internal_brightness
        ;;

    # Smart context-aware controls (based on focused monitor)
    "--inc")
        smart_change "inc" "$2"
        ;;
    "--dec")
        smart_change "dec" "$2"
        ;;
    "--get")
        focused=$(get_focused_monitor)
        if [[ "$focused" =~ ^(HDMI|DP|DVI) ]]; then
            get_external_brightness
        else
            get_internal_brightness
        fi
        ;;

    # Status & Help
    "--status")
        send_socket_cmd "status"
        ;;
    "--help"|"-h"|"")
        cat << 'EOF'
Usage: hypr-brightness.sh [OPTION] [ARGUMENT]

Ultra-low-latency brightness control for Hyprland (internal & external monitors).

Waybar Integration:
  --ext-waybar          Outputs JSON payload for Waybar custom module (auto-hides if unplugged)

External Monitor (Artificial Layer-Shell Dimmer):
  --ext-inc [step]      Increment external monitor brightness (default: 2%)
  --ext-dec [step]      Decrement external monitor brightness (default: 2%)
  --ext-set <val>       Set external monitor brightness to <val> (2 - 100)
  --ext-get             Get current external monitor brightness percentage
  --toggle-night        Toggle between night dim mode (20%) and daytime mode (100%)

Internal Monitor (Hardware Backlight via brightnessctl):
  --int-inc [step]      Increment laptop backlight (default: 2%)
  --int-dec [step]      Decrement laptop backlight (default: 2%)
  --int-get             Get current laptop backlight percentage

Context-Aware Controls (Focus-based):
  --inc [step]          Increment brightness of whichever screen has focus
  --dec [step]          Decrement brightness of whichever screen has focus
  --get                 Get brightness of whichever screen has focus
  --status              Print daemon status JSON
EOF
        ;;
    *)
        echo "Unknown option: $1. Run with --help for usage." >&2
        exit 1
        ;;
esac
