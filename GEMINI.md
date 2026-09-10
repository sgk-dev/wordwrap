# GEMINI.md - sgk-wordwrap

Инструкции для Gemini CLI при работе с проектом sgk-wordwrap.

## Что это

Демон на Python 3.10+ - «исправитель раскладки» для Linux (аналог Punto Switcher).
Горячая клавиша → читает выделенный текст → перекодирует между раскладками →
вставляет обратно → переключает системную раскладку.

**Поддерживаемая среда - только одна:** GNOME Shell на **Wayland** (Ubuntu, Mutter).
Код для X11 / KDE / wlroots в репозитории есть, но вне области и не тестируется.

## Ключевые решения (почему так)

- **Вставка через буфер обмена, не печать.** `wtype` не работает на Mutter
  («virtual keyboard protocol» не поддержан), а посимвольный ввод через uinput
  раскладко-зависим. Поэтому: `wl-copy` → uinput `Ctrl+V` (`Ctrl+Shift+V` для
  терминалов) → восстановление буфера.
- **evdev-слушатель, без глобального перехвата.** На GNOME Wayland нет API
  глобальных хоткеев для приложений. Читаем `/dev/input/event*` (нужна группа
  `input`), событие НЕ поглощаем - хоткей уходит и в активное приложение. Поэтому
  дефолтные клавиши безвредные: `Ctrl+F1`, `Ctrl+Shift+F1`, `Ctrl+Pause`.
- **Раскладка через gsettings.** `xkb-switch` на Wayland падает;
  `gsettings set org.gnome.desktop.input-sources current <idx>` - единственный
  рабочий способ.
- **Нет API активного окна.** `org.gnome.Shell.Introspect.GetWindows` на GNOME 46
  запрещён; `xdotool` видит только Xwayland-окна. Поэтому детект «это терминал?»
  и blacklist по окну невозможны - терминал вынесен в отдельный хоткей
  (`convert_terminal`), выбор за пользователем.

## Запуск и тесты

```bash
python -m sgk_wordwrap --log-level DEBUG    # передний план, с треем
python -m sgk_wordwrap --no-gui             # headless
pytest -q
ruff check sgk_wordwrap/
bash packaging/install.sh                   # systemd user service + автозапуск
```

## Хоткеи (по умолчанию, настраиваются в config.json)

| Действие | Клавиша |
|----------|---------|
| Конверсия выделения | `Ctrl+F1` |
| Конверсия (терминал, вставка `Ctrl+Shift+V`) | `Ctrl+Shift+F1` |
| Вкл / выкл конверсии | `Ctrl+Pause` |

## Поток (`text_processor.sgk_process(terminal)`)

1. Проверка «чувствительного» контекста → пропуск.
2. Сохранить буфер обмена.
3. Взять текст: PRIMARY; иначе (если fallback) `Ctrl+Shift+Left` → PRIMARY.
4. Проверка безопасности текста.
5. Направление = текущая раскладка → `sgk_get_next_layout()`; нужна карта.
6. Конверсия; если без изменений - восстановить буфер и выйти.
7. `clipboard.sgk_type_text(converted, terminal=...)` - копирование + вставка.
8. `layout_manager.sgk_switch_to(target)`.
9. Восстановить буфер обмена.

## Конвенции

- Префикс `sgk_` на публичных методах, классы `Sgk*`. Никаких `print()` -
  `sgk_get_logger`.
- Никогда не логировать содержимое текста - только метаданные.
- Никаких сетевых вызовов.
- Любое исключение в потоке логируется, демон не падает.

## Ловушки / известные ошибки

- **`evdev.UInput` с полной картой `ecodes.KEY` → `OSError: [Errno 22]`.** В
  `uinput_backend._sgk_capabilities()` объявляется явный подсписок клавиш.
- **`gsettings get ... current` возвращает `uint32 1`** - префикс `uint32 ` надо
  снять до `int()` (`_sgk_parse_gsettings_current`).
- **Несовпадение имён раскладок:** ОС отдаёт `us`, карты/UI используют `en`.
  `_SgkGsettings.switch_to` нормализует обе стороны; `SgkLayoutManager` - при чтении.
- **Расширение `clipboard-indicator`** сохраняет транзитный текст в историю буфера.
  Не секрет, но важно для полей пароля.
- Иконка в трее синхронизируется через `QTimer`-опрос
  `hotkey_manager.sgk_is_paused()` (хоткей `toggle` срабатывает не в Qt-потоке).
- **Весь текст UI - только через дефис `-`** (не длинное/среднее тире). Строки
  трея и настроек лежат в `gui/i18n.py` (EN/RU), тест `test_i18n` это стережёт.
- Язык (`ui.language`) и стиль иконки (`ui.tray_icon_style`: `color`/`mono`)
  применяются на лету через `tray.sgk_apply_ui()`; хоткеи - только после рестарта.
- Автозапуск = наличие файла `~/.config/autostart/wordwrap.desktop`
  (`utils/autostart.py`), а не ключ конфига.

## Полный план

`_docs/PRD/PRD - sgk-wordwrap MVP (GNOME Wayland).md` - область, решения, ручная
матрица тестов, критерии готовности.
