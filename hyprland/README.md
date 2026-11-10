# Hyprland Keybindings & Integration Guide

This guide describes how to configure Hyprland for seamless brightness control across internal and external displays.

---

## 1. Option A: Source Configuration File

Copy `hyprland.conf` to your Hyprland configuration directory:
```bash
cp hyprland/hyprland.conf ~/.config/hypr/brightness.conf
```

Then add this line to your `~/.config/hypr/hyprland.conf`:
```ini
source = ~/.config/hypr/brightness.conf
```

---

## 2. Option B: Paste Keybindings Directly

Add the following keybindings to your `~/.config/hypr/hyprland.conf`:

```ini
# Smart brightness: controls whichever screen is currently focused
bindel = , XF86MonBrightnessUp, exec, hypr-brightness.sh --inc 2
bindel = , XF86MonBrightnessDown, exec, hypr-brightness.sh --dec 2

# External display fine controls
bindel = $mainMod, XF86MonBrightnessUp, exec, hypr-brightness.sh --ext-inc 2
bindel = $mainMod, XF86MonBrightnessDown, exec, hypr-brightness.sh --ext-dec 2

# External display rapid 10% steps
bindel = $mainMod SHIFT, XF86MonBrightnessUp, exec, hypr-brightness.sh --ext-inc 10
bindel = $mainMod SHIFT, XF86MonBrightnessDown, exec, hypr-brightness.sh --ext-dec 10

# Toggle Night Dimming (Super + Shift + N)
bind = $mainMod SHIFT, N, exec, hypr-brightness.sh --toggle-night

# Explicit Laptop Screen controls (Alt + Brightness keys)
bindel = ALT, XF86MonBrightnessUp, exec, hypr-brightness.sh --int-inc 2
bindel = ALT, XF86MonBrightnessDown, exec, hypr-brightness.sh --int-dec 2
```

---

## 3. Autostart Daemon

If you enabled the systemd user service via `./install.sh`, systemd will automatically manage the daemon when graphical sessions start.

Alternatively, to launch it directly from Hyprland, add:
```ini
exec-once = hypr-monitor-dimmer.py
```
