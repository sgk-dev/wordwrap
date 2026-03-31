#!/usr/bin/env bash
# sgk-wordwrap installer
# Usage: bash packaging/install.sh
set -euo pipefail

echo "=== sgk-wordwrap installer ==="

# 1. System dependencies
echo "[1/5] Installing system dependencies..."
if command -v apt-get &>/dev/null; then
    sudo apt-get install -y \
        xkb-switch xclip xdotool \
        python3-pyqt6 python3-pip \
        wl-clipboard ydotool \
        python3-xlib python3-evdev 2>/dev/null || true
fi

# 2. Python package
echo "[2/5] Installing Python package..."
pip install --user .

# 3. udev rules (for Wayland evdev backend)
echo "[3/5] Installing udev rules..."
sudo cp packaging/99-sgk-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG input "$USER"
echo "    NOTE: Log out and back in for 'input' group to take effect"

# 4. systemd user service
echo "[4/5] Installing systemd user service..."
sgk-wordwrap --install-service

# 5. Enable service
echo "[5/5] Enabling autostart..."
systemctl --user daemon-reload
systemctl --user enable sgk-wordwrap

echo ""
echo "=== Installation complete! ==="
echo "Start now:      systemctl --user start sgk-wordwrap"
echo "Check status:   systemctl --user status sgk-wordwrap"
echo "View logs:      journalctl --user -u sgk-wordwrap -f"
echo ""
echo "Default hotkey: Ctrl+Shift+Z"
echo "Config file:    ~/.config/sgk-wordwrap/config.json"
