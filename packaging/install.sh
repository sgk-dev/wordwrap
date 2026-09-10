#!/usr/bin/env bash
# WordWrap installer - targets GNOME Wayland (Ubuntu).
# Usage: bash packaging/install.sh
set -euo pipefail

echo "=== WordWrap installer ==="

# 1. System dependencies
echo "[1/6] Installing system dependencies..."
if command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y \
        wl-clipboard xdotool \
        python3-pyqt6 python3-evdev python3-venv \
        2>/dev/null || true
fi

# 2. Python virtual environment (reuses apt-installed PyQt6 / evdev)
VENV_PATH="$HOME/.local/share/sgk-wordwrap/venv"
echo "[2/6] Setting up virtual environment in $VENV_PATH..."
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
echo "[3/6] Configuring input access..."
if [ -f packaging/99-sgk-uinput.rules ]; then
    sudo cp packaging/99-sgk-uinput.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi
sudo usermod -aG input "$USER"
echo "    NOTE: log out and back in for the 'input' group to take effect."

# 4. App icon + application menu entry (click-to-launch)
echo "[4/6] Installing icon and application menu entry..."
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$ICON_DIR" "$APP_DIR"
cp sgk_wordwrap/gui/icon.png "$ICON_DIR/wordwrap.png"
cp packaging/wordwrap.desktop "$APP_DIR/wordwrap.desktop"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database "$APP_DIR" 2>/dev/null || true

# 5. Autostart entry
echo "[5/6] Installing autostart entry..."
mkdir -p "$HOME/.config/autostart"
cp packaging/wordwrap.desktop "$HOME/.config/autostart/wordwrap.desktop"

# 6. systemd user service
echo "[6/6] Installing systemd user service..."
mkdir -p "$HOME/.config/systemd/user/"
sed "s|ExecStart=.*|ExecStart=$HOME/.local/bin/sgk-wordwrap|" \
    packaging/sgk-wordwrap.service > "$HOME/.config/systemd/user/sgk-wordwrap.service"
systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP \
    XDG_SESSION_TYPE DISPLAY DBUS_SESSION_BUS_ADDRESS 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable sgk-wordwrap

echo ""
echo "=== Installation complete ==="
echo "Start now:     systemctl --user start sgk-wordwrap"
echo "Or launch it from the applications menu: WordWrap"
echo "Check status:  systemctl --user status sgk-wordwrap"
echo "View logs:     journalctl --user -u sgk-wordwrap -f"
echo ""
echo "Hotkeys:  Ctrl+F1 convert - Ctrl+Shift+F1 convert (terminal) - Ctrl+Pause on/off"
echo "Config:   ~/.config/sgk-wordwrap/config.json"
echo ""
echo "If you were just added to the 'input' group, log out and back in first."
