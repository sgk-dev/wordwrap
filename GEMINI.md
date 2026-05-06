# GEMINI.md — sgk-wordwrap

Этот файл содержит инструкции для Gemini CLI при работе с проектом sgk-wordwrap.

## Обзор проекта

**sgk-wordwrap** — демон на Python 3.10+, который конвертирует ошибочно набранный текст между раскладками клавиатуры (например, EN→RU, RU→EN) в Linux. Активируется настраиваемой горячей клавишей, захватывает выделенный текст (или последнее слово), перекодирует его, вставляет обратно и переключает активную раскладку.

## Запуск

```bash
# Запуск для разработки
python -m sgk_wordwrap

# С отладочным логированием
python -m sgk_wordwrap --log-level DEBUG

# Установка пользовательского сервиса systemd
python -m sgk_wordwrap --install-service

# Запуск тестов
pytest tests/

# Линтинг
ruff check sgk_wordwrap/
```

## Архитектура

```
sgk_wordwrap/
  app.py              — SgkApp: жизненный цикл (старт/стоп, обработка сигналов)
  core/
    hotkey_manager.py — SgkHotkeyManager: независимый от бэкенда слушатель клавиш
    text_processor.py — SgkTextProcessor: основной процесс конвертации (сценарии A и B)
    layout_manager.py — SgkLayoutManager: xkb-switch / gsettings / D-Bus
  input/
    base.py           — SgkInputBackend ABC
    x11_backend.py    — слушатель глобальных клавиш на базе XRecord (X11)
    evdev_backend.py  — слушатель на базе evdev (Wayland, нужна группа input)
    clipboard.py      — SgkClipboard: чтение/запись/восстановление + симуляция клавиш
  layouts/
    mapper.py         — SgkLayoutMapper: конвертация символов
    detector.py       — SgkFieldDetector: обнаружение полей паролей/только для чтения
    data/             — JSON файлы маппинга (en_ru.json, en_uk.json)
  gui/
    tray.py           — SgkTrayIcon: иконка в трее на PyQt6
    config_dialog.py  — SgkConfigDialog: окно настроек
  utils/
    config.py         — SgkConfig: загрузка/сохранение ~/.config/sgk-wordwrap/config.json
    logger.py         — sgk_get_logger(): структурированное логирование в JSON
    display_server.py — sgk_detect_display_server(): x11 | wayland
```

## Конвенции кода

- **Префикс:** `sgk_` для всех публичных методов, классы именуются `Sgk*`.
- **Никаких `print()`** — используйте `_logger = sgk_get_logger(__name__)`.
- **Никаких сетевых вызовов** — 100% локальная работа.
- **Никогда не логировать содержимое текста** — только метаданные (процесс, раскладка, количество символов).
- **Async:** цикл событий asyncio; слушатель горячих клавиш в отдельном потоке → `loop.call_soon_threadsafe`.
- **Путь конфига:** `~/.config/sgk-wordwrap/config.json`
- **Путь логов:** `~/.local/share/sgk-wordwrap/wordwrap.log`

## Зависимости

Системные пакеты (apt): `xkb-switch`, `xclip`, `xdotool`, `wl-clipboard`, `ydotool`.
Python пакеты: `python-xlib`, `evdev`, `PyQt6`.

## Заметки по Wayland

Бэкенд evdev требует добавления пользователя в группу `input`:
```bash
sudo usermod -aG input $USER  # затем перезайдите в систему
```
Правила udev находятся в `packaging/99-sgk-uinput.rules`.
