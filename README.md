<div align="center">

<img src="https://raw.githubusercontent.com/sgk-dev/wordwrap/master/sgk_wordwrap/gui/icon.png" alt="WordWrap logo" width="128">

# WordWrap

**Fix text typed in the wrong keyboard layout - the Linux answer to Punto Switcher.**

Select the mistyped text, press **Ctrl+F1**:
`ghbdtn` becomes `привет`, `руддщ` becomes `hello`, and the system layout switches to match.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-GNOME%20Wayland-e95420)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-104%20passing-brightgreen)

</div>

---

## Why

You typed a whole sentence before noticing the layout was wrong. Instead of deleting
and retyping, select it and hit one hotkey - WordWrap rewrites the characters through
the correct layout, pastes the result back in place, and flips the system layout so
your next keystroke is already right.

It is **manual on purpose**: it never watches what you type and never guesses. It acts
only when you press the hotkey.

## Features

- **Bidirectional** - works whether EN or RU is currently active; direction is picked
  from the text itself, not from the active layout.
- **Works anywhere text is typed** - editors, browsers, VS Code, Telegram, terminals
  (terminals use a dedicated hotkey that pastes with `Ctrl+Shift+V`).
- **Tray app** - enable / disable with a click, colour or monochrome icon.
- **Bilingual UI** - English by default, Russian selectable in Settings.
- **Launch on login** - one checkbox in Settings.
- **Privacy-first** - text content is never logged, no network access of any kind.

## How it works

1. Global hotkey caught via evdev (needs the `input` group).
2. Selected text is captured with `Ctrl+Insert` and compared against your saved
   clipboard; if nothing is selected, the last word is selected automatically (optional).
3. Text is converted character-by-character between layouts (`en <-> ru` built in).
4. The result is pasted back via clipboard + synthetic **Ctrl+V** (`Ctrl+Shift+V` in
   terminals) - `wtype` is not supported by Mutter, so this is the reliable path.
5. The system layout is switched via `gsettings`.
6. Your clipboard is saved and restored around the operation.

## Hotkeys

| Action | Hotkey |
|--------|--------|
| Convert selection | `Ctrl+F1` |
| Convert selection (terminal - pastes with `Ctrl+Shift+V`) | `Ctrl+Shift+F1` |
| Enable / disable conversion | `Ctrl+Pause` |

All configurable in Settings or `~/.config/sgk-wordwrap/config.json`. The listener only
watches the keyboard and does not consume the event, so the hotkey also reaches the
focused app - that is why the defaults are otherwise-unused keys.

## Tray and settings

The tray icon (top panel) shows enabled / disabled state. Left-click toggles it;
right-click opens the menu:

- **Enabled / Paused** - toggle conversion
- **Settings...** - language, launch-on-login, monochrome icon, hotkeys, blocked
  processes, behavior
- **About** - version, author, links to star or support the project
- **Quit**

Language and icon-style changes apply immediately; hotkey changes need a restart.

## Install (GNOME Wayland / Ubuntu)

```bash
bash packaging/install.sh
# log out and back in once (for the 'input' group), then:
systemctl --user start sgk-wordwrap
```

The installer also adds **WordWrap** to your applications menu, so you can just click
the icon to launch it.

Requires: `wl-clipboard`, `python3-pyqt6`, `python3-evdev`, and membership in the
`input` group (for the evdev listener and the uinput virtual keyboard).

## Launch from the applications menu

If you run from source and just want the clickable icon (no systemd service):

```bash
python -m sgk_wordwrap --install-desktop
```

Then open the GNOME activities overview and search for **WordWrap**.

## Run in the foreground

```bash
python -m sgk_wordwrap --log-level DEBUG      # with tray
python -m sgk_wordwrap --no-gui               # headless
```

## Configuration

`~/.config/sgk-wordwrap/config.json` (created on first run):

```json
{
  "ui": { "language": "en", "tray_icon_style": "color" },
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

## Notes and limitations

- **Direction** is detected from the text. Pressed on correct text by mistake? Undo
  with `Ctrl+Z` in the app - the paste is a single edit.
- **Non-text clipboard** (image / files) is lost when restoring; only text is kept.
- **Password fields:** window / process detection is not available on GNOME Wayland,
  so the process blacklist is best-effort only.
- **Supported environment:** GNOME on Wayland (Ubuntu, Mutter). X11 / KDE / wlroots
  code exists in the tree but is out of scope for this release.

## Support the project

If WordWrap saves you time, a **star on GitHub** or a small donation via
[GitHub Sponsors](https://github.com/sponsors/sgk-dev) helps a lot.

## License

MIT (c) SGK (sidash.seo@gmail.com)

---

<div align="center">

Developed by SGK with ❤️

</div>
