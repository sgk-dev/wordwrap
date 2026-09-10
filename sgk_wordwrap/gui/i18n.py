"""Tiny UI translation table for the tray and settings dialog.

Two languages: English (default) and Russian. The active language comes from
config key ``ui.language`` ("en" | "ru"). Missing keys fall back to English,
then to the key itself, so a typo is visible but never crashes the GUI.
"""

from __future__ import annotations

SGK_LANGUAGES: tuple[str, ...] = ("en", "ru")
SGK_LANGUAGE_NAMES: dict[str, str] = {"en": "English", "ru": "Русский"}

_DEFAULT_LANG = "en"

_STRINGS: dict[str, dict[str, str]] = {
    # ---- tray ----
    "tray.enabled": {"en": "Enabled", "ru": "Включено"},
    "tray.paused": {"en": "Paused", "ru": "Выключено"},
    "tray.toggle": {"en": "Enable conversion", "ru": "Включить конверсию"},
    "tray.settings": {"en": "Settings...", "ru": "Настройки..."},
    "tray.about": {"en": "About", "ru": "О программе"},
    "tray.quit": {"en": "Quit", "ru": "Выход"},
    "tray.tooltip": {"en": "WordWrap", "ru": "WordWrap"},
    "tray.tooltip_paused": {"en": "WordWrap - paused", "ru": "WordWrap - выключено"},
    # ---- about dialog ----
    "about.title": {"en": "About WordWrap", "ru": "О программе WordWrap"},
    "about.tagline": {
        "en": "Fix text typed in the wrong keyboard layout.",
        "ru": "Исправляет текст, набранный не в той раскладке.",
    },
    "about.version": {"en": "Version", "ru": "Версия"},
    "about.author": {"en": "Author", "ru": "Автор"},
    "about.license": {"en": "License", "ru": "Лицензия"},
    "about.star": {"en": "★ Star on GitHub", "ru": "★ Звезда на GitHub"},
    "about.donate": {"en": "♥ Support the project", "ru": "♥ Поддержать проект"},
    "about.thanks": {
        "en": "If WordWrap saves you time, a star or a small donation helps a lot.",
        "ru": "Если WordWrap экономит вам время - звезда или небольшой донат очень помогают.",
    },
    # ---- settings dialog ----
    "cfg.title": {"en": "WordWrap - Settings", "ru": "WordWrap - Настройки"},
    "cfg.ok": {"en": "OK", "ru": "ОК"},
    "cfg.cancel": {"en": "Cancel", "ru": "Отмена"},
    "cfg.tab.general": {"en": "General", "ru": "Основное"},
    "cfg.tab.hotkeys": {"en": "Hotkeys", "ru": "Горячие клавиши"},
    "cfg.tab.blacklist": {"en": "Excluded apps", "ru": "Программы-исключения"},
    "cfg.tab.behavior": {"en": "Behavior", "ru": "Поведение"},
    "cfg.language": {"en": "Interface language:", "ru": "Язык интерфейса:"},
    "cfg.autostart": {"en": "Launch on login:", "ru": "Запускать при входе:"},
    "cfg.mono_icon": {"en": "Monochrome tray icon:", "ru": "Чёрно-белая иконка в трее:"},
    "cfg.hotkey.convert": {"en": "Convert selection:", "ru": "Конверсия выделения:"},
    "cfg.hotkey.convert_terminal": {
        "en": "Convert (terminal):",
        "ru": "Конверсия (терминал):",
    },
    "cfg.hotkey.convert_last_word": {
        "en": "Convert last word:",
        "ru": "Конверсия последнего слова:",
    },
    "cfg.hotkey.toggle": {"en": "Enable / disable:", "ru": "Включить / выключить:"},
    "cfg.hotkey.note": {
        "en": "Hotkey changes apply after restart.",
        "ru": "Изменения горячих клавиш применяются после перезапуска.",
    },
    "cfg.bl.explain": {
        "en": "Conversion is disabled in these programs (for example, password managers).",
        "ru": "В этих программах конверсия отключена (например, менеджеры паролей).",
    },
    "cfg.bl.processes": {"en": "Program names", "ru": "Имена программ"},
    "cfg.bl.hint": {
        "en": "One program (process) name per row, e.g. keepassxc.",
        "ru": "По одному имени программы (процесса) в строке, напр. keepassxc.",
    },
    "cfg.bl.add": {"en": "Add", "ru": "Добавить"},
    "cfg.bl.remove": {"en": "Remove", "ru": "Удалить"},
    "cfg.bl.placeholder": {"en": "Program name...", "ru": "Имя программы..."},
    "cfg.beh.fallback": {
        "en": "Select last word when nothing is selected:",
        "ru": "Выделять последнее слово, если ничего не выделено:",
    },
    "cfg.beh.restore": {
        "en": "Restore clipboard after paste:",
        "ru": "Восстанавливать буфер обмена после вставки:",
    },
    "cfg.beh.delay": {"en": "Action delay:", "ru": "Задержка действий:"},
    "cfg.beh.terminal_paste": {
        "en": "Terminal paste shortcut:",
        "ru": "Вставка в терминал:",
    },
    "cfg.saved": {
        "en": "Settings saved.",
        "ru": "Настройки сохранены.",
    },
}


def sgk_normalize_lang(lang: str | None) -> str:
    """Return a supported language code, defaulting to English."""
    if lang and lang.lower() in SGK_LANGUAGES:
        return lang.lower()
    return _DEFAULT_LANG


def sgk_tr(key: str, lang: str | None = None) -> str:
    """Translate ``key`` into ``lang`` (English fallback, then the key itself)."""
    lang = sgk_normalize_lang(lang)
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(lang) or entry.get(_DEFAULT_LANG) or key
