# Additional-Monitor-Brightness-Control-Widget

> **KDE-style artificial layer-shell monitor dimmer for external displays on Hyprland.**  
> Ultra-low latency, zero DDC/CI hardware delays, 100% click-through, hotplug-resilient, with seamless Waybar and keybinding integration.

---

## 🌟 Overview

Most external desktop monitors lack reliable DDC/CI support under Linux, or suffer from severe 1-2 second hardware lag, I2C bus locks, and sudden crashes when adjusting brightness. KDE Plasma solved this problem elegantly by using an artificial GPU-accelerated layer overlay that dims the display down smoothly without touching hardware registers.

**Additional-Monitor-Brightness-Control-Widget** brings this native KDE-style experience to **Hyprland** using `GtkLayerShell` (Wayland layer-shell protocol).

### Key Features
- **Zero-Latency Response:** Adjust external display brightness instantly with smooth scrolling or key combinations.
- **100% Click-Through & Scroll-Through:** Uses Cairo empty input shapes (`cairo.Region()`) on both `realize` and `draw` cycles, guaranteeing that all mouse clicks, cursor interactions, hovers, and scroll events pass through to windows beneath.
- **Hotplug Resilient:** Subscribes to Hyprland's `socket2` event stream (`monitoradded`, `monitorremoved`, `configreloaded`) and includes a 1-second background health check. Displays re-attach seamlessly on plug/unplug or sleep/wake cycles without crashing.
- **Universal External Monitor Auto-Detection:** Automatically discovers external displays (HDMI, DisplayPort, DVI, or secondary coordinates) and supports explicit selection via `--monitor`.
- **Environment Auto-Discovery:** Seamlessly discovers `WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE` even when launched from systemd or detached subshells.
- **Sub-Second Non-Blocking IPC:** UNIX domain socket server (`/tmp/.ext_dimmer.sock`) with atomic cache fallback (`/tmp/.ext_brightness`), ensuring Waybar never hangs or freezes.
- **Real-Time Waybar Signal Support:** Dispatches `SIGRTMIN+8` (`pkill -RTMIN+8 waybar`) on changes for instantaneous UI updates without busy polling.
- **Unified Client Script:** `hypr-brightness.sh` handles both internal laptop displays (via `brightnessctl`) and external monitors, with smart focus detection and night mode toggle.

---

## 📁 Repository Structure

```
Additional-Monitor-Brithtness-Control-Widget/
├── bin/
│   ├── hypr-monitor-dimmer.py   # Standalone GtkLayerShell daemon
│   └── hypr-brightness.sh       # Zero-lag client for Waybar & Hyprland
├── systemd/
│   └── hypr-monitor-dimmer.service # Systemd user service unit
├── waybar/
│   ├── config.jsonc             # Ready-to-use Waybar custom module configuration
│   ├── style.css                # Polished CSS styles
│   └── README.md                # Waybar setup instructions
├── hyprland/
│   ├── hyprland.conf            # Recommended Hyprland keybindings
│   └── README.md                # Hyprland integration instructions
├── install.sh                   # Interactive / automated installer
├── uninstall.sh                 # Complete cleanup uninstaller
├── LICENSE                      # MIT License
└── README.md                    # Project documentation
```

---

## 📦 Prerequisites

Ensure the following packages are installed on your system:

### Arch Linux / Manjaro
```bash
sudo pacman -S gtk-layer-shell python-gobject python-cairo socat jq brightnessctl
```

### Debian / Ubuntu
```bash
sudo apt install python3-gi gir1.2-gtk-3.0 libgtk-layer-shell0 gir1.2-gtklayershell-0.1 python3-cairo socat jq brightnessctl
```

### Fedora
```bash
sudo dnf install gtk-layer-shell python3-gobject python3-cairo socat jq brightnessctl
```

---

## 🚀 Installation

Clone the repository and run `install.sh`:

```bash
git clone https://github.com/Additional-Monitor-Brightness-Control-Widget.git
cd Additional-Monitor-Brightness-Control-Widget
./install.sh
```

The installer will:
1. Validate all prerequisites and Python GI bindings.
2. Install scripts into `~/.local/bin/`.
3. Install and enable the systemd user service (`hypr-monitor-dimmer.service`).

To install system-wide (to `/usr/local/bin`):
```bash
sudo ./install.sh --global
```

---

## ⌨️ Hyprland Keybindings

Add the keybindings to your `~/.config/hypr/hyprland.conf`:

```ini
# Smart brightness: automatically adjusts whichever display has focus
bindel = , XF86MonBrightnessUp, exec, hypr-brightness.sh --inc 2
bindel = , XF86MonBrightnessDown, exec, hypr-brightness.sh --dec 2

# External monitor dedicated control (Super + Brightness Keys)
bindel = $mainMod, XF86MonBrightnessUp, exec, hypr-brightness.sh --ext-inc 2
bindel = $mainMod, XF86MonBrightnessDown, exec, hypr-brightness.sh --ext-dec 2

# Rapid 10% steps (Super + Shift + Brightness Keys)
bindel = $mainMod SHIFT, XF86MonBrightnessUp, exec, hypr-brightness.sh --ext-inc 10
bindel = $mainMod SHIFT, XF86MonBrightnessDown, exec, hypr-brightness.sh --ext-dec 10

# Toggle Night Mode (Super + Shift + N)
bind = $mainMod SHIFT, N, exec, hypr-brightness.sh --toggle-night

# Laptop display controls (Alt + Brightness Keys)
bindel = ALT, XF86MonBrightnessUp, exec, hypr-brightness.sh --int-inc 2
bindel = ALT, XF86MonBrightnessDown, exec, hypr-brightness.sh --int-dec 2
```

---

## 📊 Waybar Integration

Add the module to your Waybar `config.jsonc`:

```jsonc
"custom/ext-backlight": {
    "format": "󰍹 {}",
    "exec": "hypr-brightness.sh --ext-waybar",
    "return-type": "json",
    "interval": 2,
    "signal": 8,
    "tooltip": true,
    "hide-empty-text": true,
    "on-scroll-up": "hypr-brightness.sh --ext-inc 2",
    "on-scroll-down": "hypr-brightness.sh --ext-dec 2",
    "on-click": "hypr-brightness.sh --toggle-night",
    "on-click-right": "hypr-brightness.sh --ext-set 100",
    "smooth-scrolling-threshold": 1
}
```

Add `"custom/ext-backlight"` to `modules-right` or `modules-left`. The module automatically hides when no external monitor is plugged in.

---

## 🛠️ CLI Reference

### Client Script (`hypr-brightness.sh`)

| Option | Description |
|---|---|
| `--ext-waybar` | Returns JSON for Waybar custom module (auto-hides if unplugged) |
| `--ext-inc [step]` | Increments external brightness (default: 2%) |
| `--ext-dec [step]` | Decrements external brightness (default: 2%) |
| `--ext-set <val>` | Sets external brightness to specific value (2 - 100) |
| `--ext-get` | Returns current external brightness percentage |
| `--toggle-night` | Toggles between night dim mode (20%) and full brightness (100%) |
| `--int-inc [step]` | Increments laptop display backlight via `brightnessctl` |
| `--int-dec [step]` | Decrements laptop display backlight via `brightnessctl` |
| `--int-get` | Returns current laptop backlight percentage |
| `--inc [step]` | Context-aware: increments brightness of currently focused display |
| `--dec [step]` | Context-aware: decrements brightness of currently focused display |
| `--status` | Returns daemon status JSON |

### Daemon (`hypr-monitor-dimmer.py`)

| Flag | Description | Default |
|---|---|---|
| `--monitor`, `-m` | Target monitor name or substring | Auto-detect |
| `--socket`, `-s` | UNIX domain control socket path | `/tmp/.ext_dimmer.sock` |
| `--cache`, `-c` | Brightness cache file path | `/tmp/.ext_brightness` |
| `--step` | Default step percentage | `2` |
| `--default`, `-d` | Default initial brightness | `100` |
| `--min-brightness` | Minimum brightness clamp | `2` |
| `--max-brightness` | Maximum brightness clamp | `100` |
| `--debug` | Output diagnostic logging to stderr | Disabled |

### UNIX Domain Socket Protocol (`/tmp/.ext_dimmer.sock`)

Communicate directly with the daemon via `socat` or netcat:

```bash
# Query current brightness
echo "get" | socat - UNIX-CONNECT:/tmp/.ext_dimmer.sock

# Set brightness to 75%
echo "set 75" | socat - UNIX-CONNECT:/tmp/.ext_dimmer.sock

# Increment / Decrement
echo "inc 5" | socat - UNIX-CONNECT:/tmp/.ext_dimmer.sock
echo "dec 5" | socat - UNIX-CONNECT:/tmp/.ext_dimmer.sock

# Query JSON status
echo "status" | socat - UNIX-CONNECT:/tmp/.ext_dimmer.sock

# Force re-attach overlay to detected monitor
echo "reattach" | socat - UNIX-CONNECT:/tmp/.ext_dimmer.sock

# Cleanly terminate daemon
echo "quit" | socat - UNIX-CONNECT:/tmp/.ext_dimmer.sock
```

---

## 🗑️ Uninstallation

To cleanly stop the service and remove all installed files:

```bash
./uninstall.sh
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
