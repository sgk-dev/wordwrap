# sgk-wordwrap

Automatic keyboard layout switcher for Linux (X11 & Wayland).

Press `Ctrl+Shift+Z` to convert the selected text (or last word) from the wrong keyboard layout to the correct one.

**Example:** You typed `ghbdtn` with EN layout active instead of RU → press the hotkey → text becomes `привет`, layout switches to RU.

## Features

- Works on X11 (XRecord) and Wayland (evdev)
- GNOME and KDE Plasma support
- EN↔RU and EN↔UK (Ukrainian) built-in mappings
- Custom layout maps (user-defined JSON)
- System tray with pause/resume
- Password field protection (AT-SPI + blacklist)
- 100% local — no telemetry, no network
- Latency < 50ms

## Quick Install (Ubuntu)

```bash
git clone https://github.com/sgk-dev/wordwrap
cd wordwrap
bash packaging/install.sh
```

Or just pip:

```bash
pip install sgk-wordwrap
sgk-wordwrap --install-service
systemctl --user enable --now sgk-wordwrap
```

## Requirements

**System packages:**
```bash
sudo apt install xkb-switch xclip xdotool python3-pyqt6
# Wayland only:
sudo apt install wl-clipboard ydotool
```

**Wayland:** Add yourself to the `input` group (required for evdev):
```bash
sudo usermod -aG input $USER
# Log out and back in
```

## Usage

| Action | Hotkey |
|--------|--------|
| Convert text | `Ctrl+Shift+Z` |

Right-click the tray icon to:
- Pause/resume
- Open Settings (change hotkey, manage blacklist)
- Quit

## Configuration

File: `~/.config/sgk-wordwrap/config.json`

```json
{
  "hotkeys": { "convert": "ctrl+shift+z" },
  "layouts": { "active": ["en", "ru"] },
  "blacklist": {
    "processes": ["keepassxc", "pinentry"]
  }
}
```

## Custom Layouts

Add a JSON file to `~/.config/sgk-wordwrap/layouts/`:

```json
{
  "name": "en-de",
  "from_layout": "en",
  "to_layout": "de",
  "description": "QWERTY → QWERTZ",
  "map": {
    "y": "z", "z": "y",
    "Y": "Z", "Z": "Y"
  }
}
```

## Security

- Text content is **never logged** (only metadata: process name, layout, char count)
- Conversion is **skipped** in password fields (AT-SPI detection + process blacklist)
- No network connections of any kind

## License

MIT © SGK (sidash.seo@gmail.com)
