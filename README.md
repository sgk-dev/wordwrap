<div align="center">

<img src="https://raw.githubusercontent.com/sgk-dev/wordwrap/master/sgk_wordwrap/gui/icon.png" alt="WordWrap logo" width="128">

# WordWrap

**Fix text typed in the wrong keyboard layout - the Linux answer to Punto Switcher.**

Select the mistyped text, press **Ctrl+F1**:
`ghbdtn` becomes `привет`, `руддщ` becomes `hello`, and the system layout switches to match.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-GNOME%20Wayland-e95420)
![PyPI](https://img.shields.io/pypi/v/sgk-wordwrap?label=pypi)
![License](https://img.shields.io/badge/license-GPLv3-blue)
![Tests](https://img.shields.io/badge/tests-128%20passing-brightgreen)

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
- **Works anywhere text is typed** - editors, browsers, VS Code, Telegram; terminals get
  a dedicated hotkey that clears the input line and pastes with `Ctrl+Shift+V`.
- **Fix the last word** with a single hotkey - no selection needed.
- **Tray app** - enable / disable with a click, colour or monochrome icon.
- **Bilingual UI** - English by default, Russian selectable in Settings.
- **Launch on login** - one checkbox in Settings.
- **Privacy-first** - text content is never logged, no network access of any kind.

## How it works

1. Global hotkey caught via evdev (needs the `input` group).
2. Your clipboard is saved and a private marker is put in it; the selection is copied
   over the marker with `Ctrl+Insert`. Marker still there means nothing is selected, so
   the last word is selected automatically (optional).
3. Text is converted character-by-character between layouts (`en <-> ru` and `en <-> uk`
   built in). The direction comes from the text itself, not from the active layout.
4. The result is pasted back via clipboard + synthetic **Ctrl+V** - `wtype` is not
   supported by Mutter, so this is the reliable path.
5. The system layout is switched via `gsettings`; the real state is read back from
   GNOME's `mru-sources`, and if the switch did not take effect the GNOME `Super+Space`
   shortcut is pressed as a fallback.
6. Your clipboard is restored.

**Terminal mode** (`Ctrl+Shift+F1`) is different: it takes the mouse selection, clears
the whole readline input line (`Ctrl+A`, `Ctrl+K` - `Ctrl+Y` brings it back) and pastes
the fixed text with `Ctrl+Shift+V`. It assumes the mistyped text is the current input
line. For TUI prompts that do not understand `Ctrl+A` / `Ctrl+K` (Claude Code, some
REPLs) switch Settings -> Behavior -> *Terminal: how to erase the old text* to
**Backspace per character** and keep the cursor at the end of the mistyped text.
Full-screen TUIs (vim, tmux, htop) are not supported.

## Hotkeys

| Action | Hotkey |
|--------|--------|
| Convert selection | `Ctrl+F1` |
| Convert in a terminal (clears the input line, pastes with `Ctrl+Shift+V`) | `Ctrl+Shift+F1` |
| Convert the last word (no selection needed) | `Ctrl+F2` |
| Enable / disable conversion | `Ctrl+Pause` |

All configurable in Settings or `~/.config/sgk-wordwrap/config.json`. The listener only
watches the keyboard and does not consume the event, so the hotkey also reaches the
focused app - that is why the defaults are otherwise-unused keys.

## Tray and settings

The tray icon (top panel) shows enabled / disabled state. Left-click toggles it;
right-click opens the menu:

- **Enabled / Paused** - toggle conversion
- **Settings...** - language, launch-on-login, monochrome icon, hotkeys, excluded
  programs, behavior (word fallback, clipboard restore, terminal paste / erase mode)
- **About** - version, author, links to star or support the project
- **Quit**

Language and icon-style changes apply immediately; hotkey changes need a restart.

## Install (GNOME Wayland / Ubuntu)

Requires `wl-clipboard`, `python3-pyqt6`, `python3-evdev` and membership in the `input`
group (for the evdev listener and the uinput virtual keyboard).

**With pipx (from PyPI):**

```bash
sudo apt install wl-clipboard python3-pyqt6 python3-evdev pipx
sudo usermod -aG input "$USER"          # then log out and back in once
pipx install --system-site-packages sgk-wordwrap
sgk-wordwrap --install-desktop          # adds WordWrap to the applications menu
```

The latest development version comes straight from GitHub instead:
`pipx install --system-site-packages git+https://github.com/sgk-dev/wordwrap`.

Then open the GNOME activities overview, search for **WordWrap** and launch it. Turn on
**Launch on login** in Settings if you want it to start with your session.

**From a clone, as a systemd user service:**

```bash
bash packaging/install.sh
# log out and back in once (for the 'input' group), then:
systemctl --user start sgk-wordwrap
```

`install.sh` creates a venv, the menu entry and a `sgk-wordwrap` user service that
starts with the graphical session. Use either the service or the Settings checkbox for
autostart, not both - a second instance simply exits.

## Run in the foreground

```bash
python3 -m sgk_wordwrap --log-level DEBUG      # with tray
python3 -m sgk_wordwrap --no-gui               # headless
```

## Configuration

`~/.config/sgk-wordwrap/config.json` (created on first run):

```json
{
  "ui": { "language": "en", "tray_icon_style": "color" },
  "hotkeys": {
    "convert": "ctrl+f1",
    "convert_terminal": "ctrl+shift+f1",
    "convert_last_word": "ctrl+f2",
    "toggle": "ctrl+pause"
  },
  "layouts": { "custom_maps_dir": null },
  "behavior": {
    "enabled_on_start": true,
    "fallback_to_word_on_no_selection": true,
    "restore_clipboard": true,
    "terminal_paste_combo": "ctrl+shift+v",
    "terminal_erase": "line",
    "copy_settle_ms": 400,
    "clipboard_settle_ms": 150,
    "paste_settle_ms": 100
  }
}
```

### Custom layouts

Point `layouts.custom_maps_dir` at a folder and drop JSON files into it:

```json
{
  "name": "en-de", "from_layout": "en", "to_layout": "de",
  "map": { "y": "z", "z": "y", "Y": "Z", "Z": "Y" }
}
```

## Notes and limitations

- **Direction** is detected from the text. Pressed on correct text by mistake? Undo
  with `Ctrl+Z` in the app - the paste is a single edit.
- **Non-text clipboard** (image / files) cannot be restored; it is cleared after the
  operation. Text is restored as it was.
- **Password fields:** window / process detection is not available on GNOME Wayland,
  so the excluded-programs list is best-effort only. Do not press the hotkey in a
  password field.
- **Active layouts** come from the system (`gsettings`), not from the config.
- **Supported environment:** GNOME on Wayland (Ubuntu, Mutter). X11 / KDE / wlroots
  code exists in the tree but is out of scope for this release.

## Support the project

If WordWrap saves you time, a **star on GitHub** or a small donation via
[GitHub Sponsors](https://github.com/sponsors/sgk-dev) helps a lot.

## License

WordWrap is free software: you can redistribute it and/or modify it under the
terms of the **GNU General Public License v3.0 or later** (see [`LICENSE`](LICENSE)).
It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY.

Copyright (c) 2026 SGK (sidash.seo@gmail.com)

The **WordWrap** name and logo are not covered by the GPL and remain the property
of SGK; forks must use a different name and their own artwork.

---

<div align="center">

Developed by SGK with ❤️

</div>
