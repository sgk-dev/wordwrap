#!/usr/bin/env bash
# sgk-wordwrap installer — targets GNOME Wayland (Ubuntu).
# Usage: bash packaging/install.sh
set -euo pipefail

echo "=== sgk-wordwrap installer ==="

# 1. System dependencies
echo "[1/5] Installing system dependencies..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y \
        wl-clipboard xdotool \
        python3-pyqt6 python3-evdev python3-venv \
        2>/dev/null || true
fi

# 2. Python virtual environment (reuses apt-installed PyQt6 / evdev)
VENV_PATH="$HOME/.local/share/sgk-wordwrap/venv"
echo "[2/5] Setting up virtual environment in $VENV_PATH..."
mkdir -p "$(dirname "$VENV_PATH")"
python3 -m venv --system-site-packages "$VENV_PATH"
"$VENV_PATH/bin/pip" install --upgrade pip -q
"$VENV_PATH/bin/pip" install -q .

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/sgk-wordwrap" <<EOF
#!/usr/bin/env bash
exec "$VENV_PATH/bin/python3" -m sgk_wordwrap "\$@"
EOF
chmod +x "$HOME/.local/bin/sgk-wordwrap"

# 3. Input access (evdev hotkey listener + uinput virtual keyboard)
echo "[3/5] Configuring input access..."
if [ -f packaging/99-sgk-uinput.rules ]; then
    sudo cp packaging/99-sgk-uinput.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi
sudo usermod -aG input "$USER"
echo "    NOTE: log out and back in for the 'input' group to take effect."

# 4. systemd user service
echo "[4/5] Installing systemd user service..."
mkdir -p "$HOME/.config/systemd/user/"
sed "s|ExecStart=.*|ExecStart=$HOME/.local/bin/sgk-wordwrap|" \
    packaging/sgk-wordwrap.service > "$HOME/.config/systemd/user/sgk-wordwrap.service"
cp packaging/sgk-wordwrap.desktop "$HOME/.config/autostart/sgk-wordwrap.desktop" 2>/dev/null || \
    { mkdir -p "$HOME/.config/autostart"; cp packaging/sgk-wordwrap.desktop "$HOME/.config/autostart/"; }

# 5. Make the session environment visible to the user unit, then enable it
echo "[5/5] Enabling autostart..."
systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP \
    XDG_SESSION_TYPE DISPLAY DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable sgk-wordwrap

echo ""
echo "=== Installation complete ==="
echo "Start now:     systemctl --user start sgk-wordwrap"
echo "Check status:  systemctl --user status sgk-wordwrap"
echo "View logs:     journalctl --user -u sgk-wordwrap -f"
echo ""
echo "Hotkeys:  Ctrl+F1 convert · Ctrl+Shift+F1 convert (terminal) · Ctrl+Pause on/off"
echo "Config:   ~/.config/sgk-wordwrap/config.json"
echo ""
echo "If you were just added to the 'input' group, log out and back in first."
