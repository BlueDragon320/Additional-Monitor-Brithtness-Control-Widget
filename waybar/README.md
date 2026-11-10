# Waybar Integration Guide

This guide describes how to integrate the external monitor brightness widget into Waybar.

---

## 1. Add Module Definition to Waybar

In your Waybar config (e.g. `~/.config/waybar/config.jsonc` or `~/.config/waybar/Modules`), include the module definition:

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

### Module Features:
- **`signal: 8`**: Receives instant refresh signals (`pkill -RTMIN+8 waybar`) when brightness changes from keybindings or CLI, avoiding polling lag.
- **`hide-empty-text: true`**: Automatically hides the widget when no external display is plugged in.
- **Scroll**: Scroll up/down to increment/decrement brightness in 2% steps.
- **Left click**: Toggles night mode (20% dim vs. 100% full brightness).
- **Right click**: Immediately resets brightness to 100%.

---

## 2. Add Module to Your Bar Layout

Add `"custom/ext-backlight"` to `modules-right` (or `modules-left` / `modules-center`) in your active Waybar configuration:

```jsonc
"modules-right": [
    "custom/ext-backlight",
    "backlight",
    "pulseaudio",
    "clock",
    "tray"
]
```

---

## 3. Style the Module (Optional)

Include the rules from `style.css` in your Waybar `style.css`:

```css
#custom-ext-backlight {
    color: #89b4fa;
    padding: 2px 10px;
    margin: 3px 4px;
    transition: all 0.2s ease-in-out;
}

#custom-ext-backlight:hover {
    background: rgba(137, 180, 250, 0.2);
}
```

---

## 4. Restart Waybar

Restart or reload Waybar to apply changes:
```bash
killall waybar && waybar &
```
