# CLAUDE.md — sgk-wordwrap

## WHAT

Python 3.10+ daemon that fixes text typed in the wrong keyboard layout (Punto
Switcher style). Hotkey → read selected text → convert between layouts → paste
back → switch system layout.

**Target environment (only one supported):** GNOME Shell on **Wayland** (Ubuntu,
Mutter). X11 / KDE / wlroots code exists but is out of scope and untested.

```
sgk_wordwrap/
  app.py              — SgkApp: lifecycle, wiring, thread orchestration
  __main__.py         — CLI entry (--no-gui, --log-level, --install-service)
  core/
    hotkey_manager.py — SgkHotkeyManager: named hotkeys (convert / convert_terminal / toggle)
    text_processor.py — SgkTextProcessor: the conversion flow
    layout_manager.py — SgkLayoutManager: gsettings backend (Wayland); xkb-switch/setxkbmap (X11, unused here)
  input/
    evdev_backend.py  — SgkEvdevHotkeyListener: multi-hotkey listener, most-specific match wins
    uinput_backend.py — SgkUinputInjector: Ctrl+V / Ctrl+Shift+V / Ctrl+Shift+Left / Backspace via evdev.UInput
    clipboard.py      — SgkClipboard: wl-clipboard get/set + paste flow
    x11_backend.py    — XRecord listener (X11, out of scope)
  layouts/
    mapper.py         — SgkLayoutMapper: char conversion from JSON maps (en_ru, en_uk)
    detector.py       — SgkFieldDetector: password/blacklist detection (limited on Wayland)
  gui/tray.py         — SgkTrayIcon: PyQt6 tray, left-click toggle, QTimer state sync
  utils/config.py     — SgkConfig: ~/.config/sgk-wordwrap/config.json, deep-merged defaults
```

## WHY

- **Clipboard-paste, not typing.** `wtype` fails on Mutter ("virtual keyboard
  protocol" unsupported) and keycode typing is layout-dependent. So converted text
  goes: `wl-copy` → uinput `Ctrl+V` (`Ctrl+Shift+V` for terminals) → restore clipboard.
- **evdev listener, not a global grab.** GNOME Wayland has no app-level global
  hotkey API. We read `/dev/input/event*` (needs `input` group) and do NOT consume
  the event — so the hotkey also reaches the focused app. Hence defaults are
  otherwise-inert keys (`Ctrl+F1`, `Ctrl+Shift+F1`, `Ctrl+Pause`).
- **gsettings for layout.** `xkb-switch` crashes on Wayland; `gsettings set
  org.gnome.desktop.input-sources current <idx>` is the only working switch.
- **No active-window API.** `org.gnome.Shell.Introspect.GetWindows` is
  access-denied on GNOME 46; `xdotool` only sees Xwayland windows. So "is this a
  terminal?" and window/title blacklists cannot work generally — the terminal
  case is a separate hotkey (`convert_terminal`), chosen by the user.

## HOW

### Run / test

```bash
python -m sgk_wordwrap --log-level DEBUG    # foreground, with tray
python -m sgk_wordwrap --no-gui             # headless
pytest -q                                   # unit tests
ruff check sgk_wordwrap/
bash packaging/install.sh                   # systemd user service + autostart
```

### Conventions

- Prefix `sgk_` on public methods; classes `Sgk*`. No `print()` — `sgk_get_logger`.
- Never log text content — metadata only (process, layout, char_count).
- No network calls.
- Any exception in the flow is logged; the daemon must not crash.

### Flow (`text_processor.sgk_process(terminal)`)

1. Sensitive-context check → skip.
2. Save clipboard.
3. Acquire text: PRIMARY; else (if fallback) `Ctrl+Shift+Left` then PRIMARY.
4. Safety check (`sgk_is_text_safe`).
5. Direction = current layout → `sgk_get_next_layout()`; need a map.
6. Convert; if unchanged → restore + stop.
7. `clipboard.sgk_type_text(converted, terminal=...)` (copy + paste).
8. `layout_manager.sgk_switch_to(target)`.
9. Restore clipboard.

### Gotchas / known errors

- **`evdev.UInput` with the full `ecodes.KEY` map → `OSError: [Errno 22]`.**
  `uinput_backend._sgk_capabilities()` declares an explicit key subset instead.
- **`gsettings get ... current` returns `uint32 1`** — must strip the `uint32 `
  prefix before `int()` (`_sgk_parse_gsettings_current`).
- **Layout name mismatch:** OS reports `us`, maps/UI use `en`. `_SgkGsettings`
  normalizes on both sides in `switch_to`; `SgkLayoutManager` normalizes on read.
- **`clipboard-indicator` GNOME extension** records transient converted text into
  clipboard history. Not sensitive, but relevant for password fields (FR-14).
- Tray icon state is synced from a `QTimer` poll of `hotkey_manager.sgk_is_paused()`
  because the `toggle` hotkey fires on a non-Qt thread.

### Config keys of note

`hotkeys.convert` / `hotkeys.convert_terminal` / `hotkeys.toggle`,
`behavior.enabled_on_start`, `behavior.clipboard_settle_ms` /
`behavior.paste_settle_ms` / `behavior.hotkey_settle_ms`,
`behavior.fallback_to_word_on_no_selection`, `layouts.active`,
`layouts.custom_maps_dir`, `blacklist.*`.

### Full plan

`_docs/PRD/PRD — sgk-wordwrap MVP (GNOME Wayland).md` — scope, decisions, manual
test matrix, Definition of Done.
