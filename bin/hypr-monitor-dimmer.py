#!/usr/bin/env python3
"""
hypr-monitor-dimmer.py - Hotplug-Resilient Artificial Monitor Dimmer for Hyprland.
Uses GtkLayerShell (GTK 3.0, GtkLayerShell 0.1, Cairo) to display an artificial
fullscreen dark overlay on external monitors, replicating KDE Plasma's external
display brightness control with zero DDC/CI latency and 100% click-through.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

# --- Phase 1: Auto-discover Display & Hyprland Environment ---
xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

def discover_wayland_display():
    """Discover active WAYLAND_DISPLAY if missing from environment."""
    if "WAYLAND_DISPLAY" in os.environ and os.environ["WAYLAND_DISPLAY"]:
        return os.environ["WAYLAND_DISPLAY"]
    
    # Check runtime directory for wayland-* sockets
    if os.path.exists(xdg_runtime):
        candidates = []
        for item in sorted(os.listdir(xdg_runtime)):
            if item.startswith("wayland-") and not item.endswith((".lock", ".sock")):
                sock_file = os.path.join(xdg_runtime, item)
                if os.path.exists(sock_file):
                    candidates.append(item)
        if candidates:
            os.environ["WAYLAND_DISPLAY"] = candidates[0]
            return candidates[0]
    
    # Fallback default
    os.environ["WAYLAND_DISPLAY"] = "wayland-1"
    return "wayland-1"

def discover_hypr_signature():
    """Discover active HYPRLAND_INSTANCE_SIGNATURE if missing from environment."""
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        return sig
    
    hypr_dir = os.path.join(xdg_runtime, "hypr")
    if os.path.exists(hypr_dir):
        subdirs = [
            d for d in os.listdir(hypr_dir)
            if os.path.isdir(os.path.join(hypr_dir, d)) and not d.startswith(".")
        ]
        if subdirs:
            # Sort by mtime of .socket2.sock if available to pick the freshest
            def get_sock_mtime(d):
                p = os.path.join(hypr_dir, d, ".socket2.sock")
                try:
                    return os.path.getmtime(p)
                except OSError:
                    return 0
            subdirs.sort(key=get_sock_mtime, reverse=True)
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = subdirs[0]
            return subdirs[0]
    
    # Attempt via hyprctl instances
    try:
        out = subprocess.check_output(["hyprctl", "instances"], text=True, timeout=0.5)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("instance "):
                found = line.split()[1].rstrip(":")
                os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = found
                return found
    except Exception:
        pass
    
    return None

# Ensure environment is prepared BEFORE importing Gtk
discover_wayland_display()
discover_hypr_signature()

# Enforce Wayland backend for GTK
os.environ["GDK_BACKEND"] = "wayland"

# --- Phase 2: Import GTK, GtkLayerShell, and Cairo ---
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, Gdk, GtkLayerShell, GLib
import cairo

try:
    from gi.repository import GLibUnix
except ImportError:
    GLibUnix = None


class HyprMonitorDimmer:
    def __init__(self, target_monitor=None, socket_path="/tmp/.ext_dimmer.sock",
                 cache_file="/tmp/.ext_brightness", default_brightness=100,
                 step=2, min_brightness=2, max_brightness=100, debug=False):
        self.target_monitor_name = target_monitor
        self.socket_path = socket_path
        self.cache_file = cache_file
        self.default_brightness = default_brightness
        self.step = step
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.debug = debug

        self.win = None
        self.current_gdk_mon = None
        self.current_hypr_mon_name = None
        self.server_sock = None
        self.socket_watch_id = None
        self.listener_running = True

        # Load brightness from cache or fallback to default
        self.brightness = self._load_cached_brightness()

        # Listen to GDK monitor addition/removal signals
        disp = Gdk.Display.get_default()
        if disp:
            try:
                disp.connect("monitor-added", self._on_gdk_monitors_changed)
                disp.connect("monitor-removed", self._on_gdk_monitors_changed)
            except Exception as e:
                self.log(f"Warning: could not connect GdkDisplay signals: {e}")

        # Setup initial overlay window
        self.setup_window()

        # Start UNIX domain socket server
        self.setup_socket()

        # Start Hyprland socket2 event listener thread for instant hotplug handling
        self.start_hypr_listener()

        # Start 1-second health check timer
        GLib.timeout_add_seconds(1, self.health_check)

        # Setup signal handlers for graceful termination
        if GLibUnix and hasattr(GLibUnix, "signal_add"):
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.quit)
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        elif hasattr(GLib, "unix_signal_add"):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.quit)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)

    def log(self, msg):
        if self.debug:
            sys.stderr.write(f"[hypr-monitor-dimmer] {msg}\n")
            sys.stderr.flush()

    def _load_cached_brightness(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    val = int(f.read().strip())
                    return max(self.min_brightness, min(self.max_brightness, val))
            except Exception:
                pass
        return max(self.min_brightness, min(self.max_brightness, self.default_brightness))

    def _save_cached_brightness(self):
        try:
            tmp_cache = f"{self.cache_file}.tmp.{os.getpid()}"
            with open(tmp_cache, "w") as f:
                f.write(f"{self.brightness}\n")
            os.replace(tmp_cache, self.cache_file)
        except Exception as e:
            self.log(f"Failed to update cache file: {e}")

    def query_hyprland_monitors(self):
        """Query active monitors from Hyprland via hyprctl monitors -j."""
        discover_hypr_signature()
        try:
            res = subprocess.run(
                ["hyprctl", "monitors", "-j"],
                capture_output=True,
                text=True,
                timeout=0.5,
                env=os.environ
            )
            if res.returncode == 0:
                return json.loads(res.stdout)
        except Exception as e:
            self.log(f"hyprctl query error: {e}")
        return []

    def detect_target_monitor(self):
        """
        Detects target external monitor based on CLI target_monitor_name
        or auto-detecting any external monitor (non-eDP/LVDS, HDMI/DP, or x > 0).
        Returns tuple (Gdk.Monitor, hypr_monitor_dict).
        """
        disp = Gdk.Display.get_default()
        if not disp:
            return None, None

        hypr_mons = self.query_hyprland_monitors()
        target_hypr = None

        if self.target_monitor_name:
            # Look for exact match or substring match in hyprland monitors
            for m in hypr_mons:
                m_name = m.get("name", "")
                m_desc = m.get("description", "")
                m_model = m.get("model", "")
                if (self.target_monitor_name.lower() in m_name.lower() or
                    self.target_monitor_name.lower() in m_desc.lower() or
                    self.target_monitor_name.lower() in m_model.lower()):
                    target_hypr = m
                    break
        else:
            # Universal auto-detection: find external monitor
            # Filter out internal displays (eDP, LVDS, DSI)
            internal_prefixes = ("edp", "lvds", "dsi")
            for m in hypr_mons:
                name = m.get("name", "").lower()
                if any(name.startswith(p) for p in internal_prefixes):
                    continue
                # If it's HDMI, DP, DVI, or positioned at x > 0 / y > 0
                if ("hdmi" in name or "dp" in name or "dvi" in name or
                    m.get("x", 0) > 0 or m.get("y", 0) > 0):
                    target_hypr = m
                    break
            
            # If not found yet, take any non-internal monitor
            if not target_hypr:
                for m in hypr_mons:
                    name = m.get("name", "").lower()
                    if not any(name.startswith(p) for p in internal_prefixes):
                        target_hypr = m
                        break

        if not target_hypr:
            # If hyprctl returned nothing or no external monitor was identified,
            # inspect GDK monitors directly as fallback
            n_gdk = disp.get_n_monitors()
            for i in range(n_gdk):
                gmon = disp.get_monitor(i)
                geom = gmon.get_geometry()
                model = gmon.get_model() or ""
                mfg = gmon.get_manufacturer() or ""
                # Check if user specified a name matching model
                if self.target_monitor_name:
                    if (self.target_monitor_name.lower() in model.lower() or
                        self.target_monitor_name.lower() in mfg.lower()):
                        return gmon, {"name": model or f"Monitor-{i}", "x": geom.x, "y": geom.y}
                elif geom.x > 0 or geom.y > 0:
                    return gmon, {"name": model or f"External-{i}", "x": geom.x, "y": geom.y}
            return None, None

        # Match target_hypr to Gdk.Monitor by geometry and/or model
        target_x = target_hypr.get("x", 0)
        target_y = target_hypr.get("y", 0)
        target_w = target_hypr.get("width", 0)
        target_h = target_hypr.get("height", 0)

        n_gdk = disp.get_n_monitors()
        best_gmon = None

        for i in range(n_gdk):
            gmon = disp.get_monitor(i)
            geom = gmon.get_geometry()
            # Match geometry directly
            if geom.x == target_x and geom.y == target_y:
                best_gmon = gmon
                break
            if geom.width == target_w and geom.height == target_h and geom.x == target_x:
                best_gmon = gmon
                break

        # Fallback to index if geometry matching had slight rounding or scale discrepancy
        if not best_gmon and n_gdk > 1:
            # If target_hypr has x > 0, pick a gdk monitor with x > 0
            for i in range(n_gdk):
                gmon = disp.get_monitor(i)
                if gmon.get_geometry().x > 0:
                    best_gmon = gmon
                    break

        return best_gmon, target_hypr

    def setup_window(self):
        """Constructs or re-attaches the fullscreen GtkLayerShell overlay."""
        gdk_mon, hypr_mon = self.detect_target_monitor()

        if not gdk_mon or not hypr_mon:
            self.log("No active target external monitor detected. Remaining dormant.")
            self.destroy_window()
            return False

        mon_name = hypr_mon.get("name", "Unknown")

        # If window is already attached to this monitor, ensure it's mapped and return
        if self.win and self.current_gdk_mon == gdk_mon and self.win.get_mapped():
            self.log(f"Window already mapped on {mon_name}.")
            return False

        # Destroy old window cleanly if monitor changed
        self.destroy_window()

        self.current_gdk_mon = gdk_mon
        self.current_hypr_mon_name = mon_name
        self.log(f"Setting up layer-shell overlay on {mon_name}...")

        try:
            self.win = Gtk.Window()
            self.win.set_app_paintable(True)
            self.win.set_decorated(False)
            self.win.set_skip_taskbar_hint(True)
            self.win.set_skip_pager_hint(True)

            # Enable RGBA visual for transparency
            screen = Gdk.Screen.get_default()
            if screen:
                visual = screen.get_rgba_visual()
                if visual:
                    self.win.set_visual(visual)

            # Initialize GtkLayerShell
            GtkLayerShell.init_for_window(self.win)
            GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.NONE)
            GtkLayerShell.set_exclusive_zone(self.win, -1)

            # Anchor to all four edges for fullscreen coverage
            for edge in (
                GtkLayerShell.Edge.TOP,
                GtkLayerShell.Edge.BOTTOM,
                GtkLayerShell.Edge.LEFT,
                GtkLayerShell.Edge.RIGHT
            ):
                GtkLayerShell.set_anchor(self.win, edge, True)

            GtkLayerShell.set_monitor(self.win, self.current_gdk_mon)

            # Connect event handlers
            self.win.connect("draw", self.on_draw)
            self.win.connect("realize", self.on_realize)
            self.win.connect("destroy", self.on_window_destroy)

            self.win.show_all()
            self.log(f"Overlay successfully displayed on {mon_name}.")
        except Exception as e:
            self.log(f"Error creating overlay window: {e}")
            self.destroy_window()

        return False

    def destroy_window(self):
        """Safely tears down the overlay window without crashing."""
        if self.win:
            try:
                self.win.hide()
                self.win.destroy()
            except Exception as e:
                self.log(f"Error destroying window: {e}")
            self.win = None
            self.current_gdk_mon = None
            self.current_hypr_mon_name = None

    def on_window_destroy(self, widget):
        self.win = None
        self.current_gdk_mon = None
        self.current_hypr_mon_name = None

    def on_realize(self, widget):
        """Sets an empty Cairo region on realize to guarantee 100% click/scroll-through."""
        self._apply_empty_input_shape(widget)

    def on_draw(self, widget, cr):
        """Draws the dark dimming veil and reinforces click-through input shape."""
        self._apply_empty_input_shape(widget)

        # Alpha calculation:
        # Brightness 100% -> Alpha 0.0 (completely transparent)
        # Brightness 50%  -> Alpha 0.50
        # Brightness 2%   -> Alpha 0.98 (dark night mode)
        # We cap at 0.98 to avoid total blackout while allowing ultra-low dimming
        alpha = max(0.0, min(0.98, (100.0 - self.brightness) / 100.0))

        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0.0, 0.0, 0.0, alpha)
        cr.paint()
        return False

    def _apply_empty_input_shape(self, widget):
        """Forces an empty input region so all pointer and scroll events pass through."""
        try:
            empty_region = cairo.Region()
            widget.input_shape_combine_region(empty_region)
            gdk_win = widget.get_window()
            if gdk_win:
                gdk_win.input_shape_combine_region(empty_region, 0, 0)
        except Exception:
            pass

    def set_brightness(self, val):
        """Sets external brightness, updates cache, repaints window, and notifies Waybar."""
        clamped = max(self.min_brightness, min(self.max_brightness, val))
        self.brightness = clamped
        self._save_cached_brightness()

        # If window is not active but monitor is present, try setup
        if not self.win or not self.win.get_mapped():
            self.setup_window()

        if self.win:
            self.win.queue_draw()

        # Signal Waybar to refresh custom/ext-backlight module immediately
        self.signal_waybar()
        self.log(f"Brightness set to {self.brightness}%")

    def signal_waybar(self):
        """Sends SIGRTMIN+8 to Waybar for zero-latency module refresh."""
        try:
            subprocess.run(["pkill", "-RTMIN+8", "waybar"], capture_output=True)
        except Exception:
            pass

    def health_check(self):
        """1-second periodic fail-safe health check."""
        try:
            gdk_mon, hypr_mon = self.detect_target_monitor()
            if gdk_mon and hypr_mon:
                if not self.win or not self.win.get_mapped():
                    self.log("Health check: target monitor found but window unmapped. Setting up window.")
                    self.setup_window()
            else:
                if self.win:
                    self.log("Health check: target monitor no longer present. Destroying window.")
                    self.destroy_window()
        except Exception as e:
            self.log(f"Health check error: {e}")
        return True

    def _on_gdk_monitors_changed(self, *args):
        """GDK monitor addition/removal handler."""
        self.log("GDK display monitors changed signal received.")
        GLib.timeout_add(300, self.setup_window)

    def on_hypr_monitor_event(self, event_type, data):
        """Handles monitoradded / monitorremoved from Hyprland socket2."""
        self.log(f"Hyprland event: {event_type}>>{data}")
        if event_type == "monitorremoved":
            # If data matches current monitor name or general external keywords
            if (self.current_hypr_mon_name and self.current_hypr_mon_name in data) or \
               any(k in data for k in ("HDMI", "DP", "DVI")):
                self.log(f"Target monitor disconnected ({data}). Tearing down overlay.")
                self.destroy_window()
        elif event_type in ("monitoradded", "monitoraddedv2", "configreloaded"):
            # Allow 350ms for Hyprland display modesetting to stabilize
            GLib.timeout_add(350, self.setup_window)

    def start_hypr_listener(self):
        """Launches Hyprland socket2 listener thread."""
        t = threading.Thread(target=self._hypr_listener_thread, daemon=True)
        t.start()

    def _hypr_listener_thread(self):
        """Reads event stream from Hyprland socket2."""
        while self.listener_running:
            his = discover_hypr_signature()
            if not his:
                time.sleep(2)
                continue

            sock_path = os.path.join(xdg_runtime, "hypr", his, ".socket2.sock")
            if not os.path.exists(sock_path):
                time.sleep(2)
                continue

            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(sock_path)
                f = s.makefile("r", encoding="utf-8", errors="ignore")
                for line in f:
                    if not self.listener_running:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    if ">>" in line:
                        parts = line.split(">>", 1)
                        evt = parts[0]
                        data = parts[1] if len(parts) > 1 else ""
                        if evt in ("monitoradded", "monitoraddedv2", "monitorremoved", "configreloaded"):
                            GLib.idle_add(self.on_hypr_monitor_event, evt, data)
                s.close()
            except Exception as e:
                self.log(f"Hyprland socket2 connection interrupted: {e}")
                time.sleep(1)

    def setup_socket(self):
        """Creates the UNIX domain socket server for client control."""
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        try:
            self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server_sock.bind(self.socket_path)
            self.server_sock.listen(5)
            self.server_sock.setblocking(False)

            self.socket_watch_id = GLib.io_add_watch(
                self.server_sock.fileno(),
                GLib.IO_IN,
                self.handle_socket_client
            )
            self.log(f"Listening on control socket: {self.socket_path}")
        except Exception as e:
            sys.stderr.write(f"Failed to bind socket {self.socket_path}: {e}\n")

    def handle_socket_client(self, fd, cond):
        """Processes client connections and requests."""
        if not self.server_sock:
            return False

        try:
            conn, _ = self.server_sock.accept()
            conn.settimeout(0.5)
            raw_data = conn.recv(1024)
            if not raw_data:
                conn.close()
                return True

            req = raw_data.decode("utf-8", errors="ignore").strip()
            parts = req.split()
            cmd = parts[0].lower() if parts else ""

            response = ""

            if cmd == "get":
                response = f"{self.brightness}\n"
            elif cmd == "set":
                if len(parts) > 1 and parts[1].isdigit():
                    self.set_brightness(int(parts[1]))
                response = f"{self.brightness}\n"
            elif cmd == "inc":
                step_val = int(parts[1]) if (len(parts) > 1 and parts[1].isdigit()) else self.step
                self.set_brightness(self.brightness + step_val)
                response = f"{self.brightness}\n"
            elif cmd == "dec":
                step_val = int(parts[1]) if (len(parts) > 1 and parts[1].isdigit()) else self.step
                self.set_brightness(self.brightness - step_val)
                response = f"{self.brightness}\n"
            elif cmd == "status":
                st = {
                    "brightness": self.brightness,
                    "monitor": self.current_hypr_mon_name,
                    "connected": self.current_gdk_mon is not None,
                    "mapped": self.win.get_mapped() if self.win else False,
                    "socket": self.socket_path
                }
                response = f"{json.dumps(st)}\n"
            elif cmd == "reattach":
                self.setup_window()
                response = "ok\n"
            elif cmd == "quit":
                response = "bye\n"
                conn.sendall(response.encode())
                try:
                    conn.shutdown(socket.SHUT_WR)
                except Exception:
                    pass
                conn.close()
                self.quit()
                return False
            else:
                response = f"ERR unknown command: {cmd}\n"

            conn.sendall(response.encode())
            try:
                # Crucial: send shutdown so clients reading EOF don't hang
                conn.shutdown(socket.SHUT_WR)
            except Exception:
                pass
            conn.close()
        except Exception as e:
            self.log(f"Socket connection handling error: {e}")

        return True

    def quit(self, *args):
        """Clean shutdown handler."""
        self.log("Shutting down daemon...")
        self.listener_running = False
        self.destroy_window()

        if self.socket_watch_id:
            GLib.source_remove(self.socket_watch_id)
            self.socket_watch_id = None

        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None

        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        Gtk.main_quit()
        return False


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Hyprland Artificial Monitor Dimmer Daemon using GtkLayerShell"
    )
    parser.add_argument(
        "--monitor", "-m",
        type=str,
        default=None,
        help="Target monitor name or pattern (default: auto-detect external monitor)"
    )
    parser.add_argument(
        "--socket", "-s",
        type=str,
        default="/tmp/.ext_dimmer.sock",
        help="UNIX domain control socket path (default: /tmp/.ext_dimmer.sock)"
    )
    parser.add_argument(
        "--cache", "-c",
        type=str,
        default="/tmp/.ext_brightness",
        help="Brightness cache file path (default: /tmp/.ext_brightness)"
    )
    parser.add_argument(
        "--default", "-d",
        type=int,
        default=100,
        help="Default brightness percentage if no cache exists (default: 100)"
    )
    parser.add_argument(
        "--step",
        type=int,
        default=2,
        help="Default brightness adjustment step (default: 2)"
    )
    parser.add_argument(
        "--min-brightness",
        type=int,
        default=2,
        help="Minimum brightness percentage limit (default: 2)"
    )
    parser.add_argument(
        "--max-brightness",
        type=int,
        default=100,
        help="Maximum brightness percentage limit (default: 100)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to stderr"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    dimmer = HyprMonitorDimmer(
        target_monitor=args.monitor,
        socket_path=args.socket,
        cache_file=args.cache,
        default_brightness=args.default,
        step=args.step,
        min_brightness=args.min_brightness,
        max_brightness=args.max_brightness,
        debug=args.debug
    )
    Gtk.main()


if __name__ == "__main__":
    main()
