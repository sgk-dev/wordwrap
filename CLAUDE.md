# CLAUDE.md — sgk-wordwrap

## Project Overview

**sgk-wordwrap** — Python 3.10+ daemon that converts mistyped text between keyboard layouts (e.g., EN→RU, RU→EN) on Linux. Triggered by a configurable hotkey, it grabs selected text (or last word), re-encodes it, pastes back, and switches the active layout.

## Running

```bash
# Development run
python -m sgk_wordwrap

# With debug logging
python -m sgk_wordwrap --log-level DEBUG

# Install systemd user service
python -m sgk_wordwrap --install-service

# Run tests
pytest tests/

# Lint
ruff check sgk_wordwrap/
```

## Architecture

```
sgk_wordwrap/
  app.py              — SgkApp: lifecycle (start/stop, signal handling)
  core/
    hotkey_manager.py — SgkHotkeyManager: backend-agnostic hotkey listener
    text_processor.py — SgkTextProcessor: main conversion flow (scenarios A & B)
    layout_manager.py — SgkLayoutManager: xkb-switch / gsettings / D-Bus
  input/
    base.py           — SgkInputBackend ABC
    x11_backend.py    — XRecord-based global hotkey listener (X11)
    evdev_backend.py  — evdev-based listener (Wayland, needs input group)
    clipboard.py      — SgkClipboard: get/set/restore + key simulation
  layouts/
    mapper.py         — SgkLayoutMapper: character conversion
    detector.py       — SgkFieldDetector: password/readonly field detection
    data/             — JSON mapping files (en_ru.json, en_uk.json)
  gui/
    tray.py           — SgkTrayIcon: PyQt6 system tray
    config_dialog.py  — SgkConfigDialog: settings window
  utils/
    config.py         — SgkConfig: load/save ~/.config/sgk-wordwrap/config.json
    logger.py         — sgk_get_logger(): JSON structured logging
    display_server.py — sgk_detect_display_server(): x11 | wayland
```

## Code Conventions

- **Prefix:** `sgk_` on all public methods, classes named `Sgk*`
- **No print()** — use `_logger = sgk_get_logger(__name__)`
- **No network calls** — 100% local operation
- **Never log text content** — only metadata (process, layout, char_count)
- **Async:** asyncio event loop; hotkey listener in separate thread → `loop.call_soon_threadsafe`
- **Config path:** `~/.config/sgk-wordwrap/config.json`
- **Log path:** `~/.local/share/sgk-wordwrap/wordwrap.log`

## Dependencies

System packages (apt): `xkb-switch`, `xclip`, `xdotool`, `wl-clipboard`, `ydotool`
Python packages: `python-xlib`, `evdev`, `PyQt6`

## Wayland Notes

evdev backend requires user in `input` group:
```bash
sudo usermod -aG input $USER  # then re-login
```
udev rules shipped in `packaging/99-sgk-uinput.rules`.
