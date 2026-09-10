# sgk-wordwrap

Fix text typed in the wrong keyboard layout — the Linux answer to Punto Switcher.

Select the mistyped text, press **Ctrl+F1**: `ghbdtn` becomes `привет`, `руддщ`
becomes `hello`, and the system layout switches to match.

> **Supported environment:** GNOME on **Wayland** (Ubuntu, Mutter). Other setups
> (X11, KDE, wlroots) are not targeted by this release.

## How it works

1. Global hotkey caught via evdev (needs the `input` group).
2. Selected text read from the PRIMARY selection (`wl-paste --primary`); if nothing
   is selected, the last word is selected automatically (optional).
3. Text converted character-by-character between layouts (`en ↔ ru` built in).
4. Result pasted back via clipboard + synthetic **Ctrl+V** (`Ctrl+Shift+V` in
   terminals) — `wtype` is not supported by Mutter, so this is the reliable path.
5. System layout switched via `gsettings`.
6. Your clipboard is saved and restored around the operation.

## Hotkeys

| Action | Hotkey |
|--------|--------|
| Convert selection | `Ctrl+F1` |
| Convert selection (terminal — pastes with `Ctrl+Shift+V`) | `Ctrl+Shift+F1` |
| Enable / disable conversion | `Ctrl+Pause` |

All configurable in `~/.config/sgk-wordwrap/config.json`. The listener only
watches the keyboard, so the hotkey also reaches the focused app — that is why the
defaults are otherwise-unused keys.

## Tray

The tray icon (top panel) shows enabled/disabled. Left-click toggles it;
right-click for the menu (enable/disable, layouts, settings, quit).

## Install (GNOME Wayland / Ubuntu)

```bash
bash packaging/install.sh
# log out and back in once (for the 'input' group), then:
systemctl --user start sgk-wordwrap
```

Requires: `wl-clipboard`, `python3-pyqt6`, `python3-evdev`, and membership in the
`input` group (for the evdev listener and the uinput virtual keyboard).

## Run in the foreground

```bash
python -m sgk_wordwrap --log-level DEBUG      # with tray
python -m sgk_wordwrap --no-gui               # headless
```

## Configuration

`~/.config/sgk-wordwrap/config.json` (created on first run):

```json
{
  "hotkeys": {
    "convert": "ctrl+f1",
    "convert_terminal": "ctrl+shift+f1",
    "toggle": "ctrl+pause"
  },
  "layouts": { "active": ["en", "ru"] },
  "behavior": {
    "enabled_on_start": true,
    "fallback_to_word_on_no_selection": true,
    "clipboard_settle_ms": 80,
    "paste_settle_ms": 80
  }
}
```

### Custom layouts

Drop a JSON file into `~/.config/sgk-wordwrap/layouts/`:

```json
{
  "name": "en-de", "from_layout": "en", "to_layout": "de",
  "map": { "y": "z", "z": "y", "Y": "Z", "Z": "Y" }
}
```

## Notes & limitations

- **Direction** is "current layout → the other layout". Correct for the usual case
  (you typed gibberish because the wrong layout was active). Pressed on correct
  text by mistake? Undo with `Ctrl+Z` in the app — the paste is a single edit.
- **Non-text clipboard** (image/files) is lost when restoring; only text is kept.
- **Password fields:** window/process detection is not available on GNOME Wayland,
  so the blacklist is best-effort only. Install `python3-pyatspi` for AT-SPI
  password-field detection.
- Text content is never logged (only metadata); no network access.

## Security

- Converted text is never logged.
- Conversion is skipped for blacklisted processes (best-effort on Wayland).
- No network connections of any kind.

## License

MIT © SGK (sidash.seo@gmail.com)
