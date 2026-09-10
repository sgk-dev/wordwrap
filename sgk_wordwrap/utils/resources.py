"""Generated packaging text (`.desktop` entry, systemd user unit).

Built in code so ``--install-desktop`` / ``--install-service`` work from a pip
or pipx install, where the repo's ``packaging/`` directory is not present.
"""

from __future__ import annotations

_DESKTOP = """\
[Desktop Entry]
Type=Application
Name=WordWrap
GenericName=Keyboard Layout Switcher
Comment=Fix text typed in the wrong keyboard layout
Exec={exec_cmd}
Icon=wordwrap
Categories=Utility;Accessibility;
Keywords=keyboard;layout;switch;punto;
Terminal=false
NoDisplay=false
StartupNotify=false
"""

_AUTOSTART_EXTRA = "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=3\n"

_SYSTEMD_UNIT = """\
[Unit]
Description=WordWrap - keyboard layout switcher
Documentation=https://github.com/sgk-dev/wordwrap
After=graphical-session.target
PartOf=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart={exec_cmd}
Restart=on-failure
RestartSec=3s
Environment=PYTHONUNBUFFERED=1
PassEnvironment=WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE DBUS_SESSION_BUS_ADDRESS
MemoryMax=128M
CPUQuota=10%

[Install]
WantedBy=graphical-session.target
"""


def sgk_desktop_entry(exec_cmd: str, autostart: bool = False) -> str:
    text = _DESKTOP.format(exec_cmd=exec_cmd)
    if autostart:
        text += _AUTOSTART_EXTRA
    return text


def sgk_systemd_unit(exec_cmd: str) -> str:
    return _SYSTEMD_UNIT.format(exec_cmd=exec_cmd)
