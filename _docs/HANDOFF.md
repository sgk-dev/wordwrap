# HANDOFF — sgk-wordwrap

Свёрнутый контекст рабочей сессии от 2026-09-10. Читать вместе с
`_docs/PRD/PRD — sgk-wordwrap MVP (GNOME Wayland).md` (полный план) и `CLAUDE.md`.

---

## 1. Что это

`sgk-wordwrap` — «исправитель раскладки» для Linux, аналог Punto Switcher.
Выделяешь текст, набранный не в той раскладке (`ghbdtn` / `руддщ`), жмёшь хоткей —
текст переписывается в правильную раскладку, системная раскладка переключается.

**Инструмент ручной:** не следит за набором, срабатывает только по хоткею.

## 2. Целевая среда (единственная поддерживаемая)

- **Wayland**, **GNOME Shell 46**, Ubuntu, композитор **Mutter**.
- Пользователь в группе `input`; `/dev/uinput` и `/dev/input/event*` доступны.
- Раскладки в системе: `us`, `ru` (gsettings `org.gnome.desktop.input-sources`).
- Клавиатуры: Keychron K8 + 2× SINOWEALTH.
- Трей: расширение `ubuntu-appindicators` включено, `QSystemTrayIcon` работает.

X11 / KDE / wlroots — код в репозитории есть, но вне поддержки и не тестируется.

## 3. Ключевые архитектурные решения (и почему)

| Узел | Решение | Почему |
|------|---------|--------|
| Вставка текста | буфер обмена + синтетический **Ctrl+V** (`Ctrl+Shift+V` для терминалов) через `evdev.UInput` | `wtype` не поддержан Mutter («virtual keyboard protocol»); посимвольный ввод раскладко-зависим |
| Захват выделения | **Ctrl+Insert** → читаем CLIPBOARD, сравниваем с сохранённым | PRIMARY на Linux хранит устаревшее выделение вечно и не говорит «выделено ли сейчас». **Ctrl+C нельзя — в терминале это SIGINT, убивает программу.** |
| Нет выделения | сами выделяем последнее слово `Ctrl+Shift+Left`, потом Ctrl+Insert | fallback; в терминалах ненадёжен |
| Направление конверсии | **по содержимому текста** (`mapper.sgk_detect_likely_layout`), не по активной раскладке | «не та» раскладка обычно и активна; для уже набранного текста активная раскладка ничего не говорит |
| Переключение раскладки | `gsettings set org.gnome.desktop.input-sources current <idx>` | `xkb-switch` на Wayland падает |
| Хоткей | evdev-слушатель `/dev/input/event*`, событие **не поглощаем** | на GNOME Wayland нет API глобальных хоткеев; поэтому дефолты — безвредные клавиши |
| Определение активного окна | **нет** | `org.gnome.Shell.Introspect.GetWindows` = Access denied на GNOME 46; `xdotool` видит только Xwayland. → детект терминала/паролей по окну невозможен |

## 4. Хоткеи (дефолт, настраиваются в `~/.config/sgk-wordwrap/config.json`)

| Действие | Клавиша |
|----------|---------|
| Конверсия выделения | `Ctrl+F1` |
| Конверсия для терминала (вставка `Ctrl+Shift+V`) | `Ctrl+Shift+F1` |
| Вкл / выкл конверсии | `Ctrl+Pause` |

## 5. Поток конверсии (`core/text_processor.py::sgk_process`)

1. Пауза (`hotkey_settle_ms`, 150) — дать отпустить физические клавиши.
2. Проверка «чувствительного» контекста (blacklist процессов) → пропуск.
3. Сохранить CLIPBOARD.
4. **Захват текста:** Ctrl+Insert → CLIPBOARD; если ≠ сохранённого → это выделение.
   Иначе (fallback вкл) → `Ctrl+Shift+Left` → Ctrl+Insert снова.
5. Проверка безопасности (не пусто, не длиннее `max_text_length`).
6. **Направление:** `sgk_detect_likely_layout(text, active)`; если не определилось —
   `current → other`.
7. Конверсия по JSON-карте; если строка не изменилась → откат, стоп.
8. `sgk_type_text(converted, terminal)` — `wl-copy` + пауза + uinput Ctrl+V.
9. `layout_manager.sgk_switch_to(target)`.
10. Восстановить CLIPBOARD.

Любое исключение логируется, демон не падает. Содержимое текста не логируется.

## 6. Что сделано в этой сессии

Ветка **`sgk-dev`** (будет переименована — см. §9). Начато от коммита `e3c4b40`.

Крупные коммиты (после переименования префикс `[wordwrap]` убран, история переписана):

- `add PRD for GNOME Wayland MVP`
- `fix gsettings layout backend: uint32 parse and us/en name mismatch`
- `uinput injector: explicit key caps, add sgk_paste, drop dead type_text`
- `clipboard: wayland paste via clipboard swap plus uinput, drop wtype/ydotool`
- `rewire core: named multi-hotkey dispatch, new conversion flow, tray toggle`
- `packaging: fix installer venv creation and import wayland session env`
- `bump version to 0.2.0, docs for gnome wayland, lint cleanup`
- `fix crash: 'name'/'process' collide with LogRecord and kill the evdev listener`
- `fix text acquisition: force selection via Ctrl+C instead of trusting stale PRIMARY`
- `fix conversion direction: detect source layout from text, not from active layout`
- `add browser test page for manual conversion checks`
- `use Ctrl+Insert not Ctrl+C for copy (terminal-safe), add logo tray icon, log layout switch`

### Баги, найденные и исправленные

1. **`evdev.UInput` с полной картой `ecodes.KEY` → `OSError [Errno 22]`.**
   → `uinput_backend._sgk_capabilities()` объявляет явный подсписок клавиш.
2. **`gsettings get current` отдаёт `uint32 N`** — не парсилось (`.isdigit()` на
   `"uint32 1"` = False) → всегда индекс 0. → `_sgk_parse_gsettings_current`.
3. **Рассинхрон имён раскладок:** ОС отдаёт `us`, карты/UI — `en`;
   `_SgkGsettings.switch_to('en')` ничего не делал. → нормализация обеих сторон.
4. **`extra={"name": …}` / `{"process": …}` в логах** конфликтует с полями
   `LogRecord` → `KeyError` → первое нажатие хоткея роняло поток-слушатель.
   → переименованы в `hotkey` / `proc`; + `_sgk_handle_key_event` обёрнут в try.
5. **Доверие устаревшему PRIMARY** — брало старое выделение (`len: 70`) вместо
   набранного. → захват через Ctrl+Insert + сравнение с сохранённым буфером.
6. **Направление от активной раскладки, а не от текста** — `ghbdtn` при активной
   `ru` пытались `ru→en`, латиница не ключи карты → `sgk_no_change_after_convert`.
   → `_sgk_pick_direction` определяет исходную раскладку по символам.
7. **`Ctrl+C` для захвата = SIGINT в терминале** — убивало Claude Code и любую
   программу на переднем плане. → заменено на `Ctrl+Insert`.
8. **`mapper.sgk_detect_likely_layout`** для кириллицы возвращал None (карты `uk`
   затирали `ru`). → фильтр по `from_layout in candidates`.

### Проверено

- `pytest -q` → **82 зелёных**; `ruff check sgk_wordwrap/` → чисто.
- **E2E против настоящих GTK4-полей** (тот же тулкит, что GNOME Text Editor):
  `ghbdtn` (при активной RU, выделено) → `привет`; `руддщ` выделено → `hello`;
  без выделения → последнее слово → `привет`. Все три — **замена**, не вставка рядом.
- Демон стартует headless и с треем, чистое завершение по SIGTERM.
- Переключение раскладки `sgk_switch_to('ru'/'en')` — в изоляции работает в обе
  стороны (проверено live через `gsettings`).

### НЕ проверено / открытые вопросы

- Живое нажатие `Ctrl+F1` в реальных приложениях (VS Code / Firefox / Chrome /
  Telegram / терминал) — это делает пользователь, матрица в PRD §10.
  Я нажать хоткей не могу: демон читает железную клавиатуру, события из
  автоматизации туда не доходят.
- **Жалоба «раскладка не переключается»** — в изоляции переключается. Добавлен
  debug-лог `sgk_switch_to want=… now=…` — по нему в следующем прогоне видно, что
  реально происходит. Гипотеза: она и переключалась (плашка GNOME «EN/RU» — это
  штатный OSD, не баг), просто попадала туда, где пользователь уже был.
- **Fallback «последнее слово»** ненадёжен в Electron (VS Code) и терминалах —
  надёжный путь: выделить текст руками, потом хоткей.
- **Детект полей пароля** на Wayland фактически не работает (нет данных об окне).
  `python3-pyatspi` не ставился (решение B2 в PRD). Пароли пока не защищены.
- **VS Code «copy-line без выделения»**: если ничего не выделено, Ctrl+Insert в
  VS Code копирует всю строку → может вставить рядом. Митигация: выделять руками.
- Настройки в трее (окно `config_dialog.py`) — заглушка, доводить позже (B5).
- Тайминги вставки (`clipboard_settle_ms` / `paste_settle_ms` / `copy_settle_ms`,
  сейчас 80/80/120) — подбираются под ощущения, крутятся в конфиге.

## 7. Как запускать и тестировать

```bash
cd ~/wordwrap
git fetch origin && git reset --hard origin/staging   # ветка после переименования

python3 -m sgk_wordwrap --log-level DEBUG              # с треем (нужен для иконки!)
python3 -m sgk_wordwrap --no-gui --log-level DEBUG     # headless

pytest -q
ruff check sgk_wordwrap/
bash packaging/install.sh                              # systemd user service + автозапуск
```

**Тест-страница для браузера:** `_docs/test-page.html`. Поднять локально и открыть:
```bash
cd ~/wordwrap/_docs && python3 -m http.server 8777 --bind 127.0.0.1
# http://127.0.0.1:8777/test-page.html
```
Пишешь в поле, выделяешь (Ctrl+A), жмёшь Ctrl+F1 — страница логирует каждое
изменение с код-пойнтами (видно: замена / вставка рядом / лишние символы).

## 8. Структура репозитория (всё нужное, мусора нет)

```
sgk_wordwrap/        пакет (app, core/, input/, layouts/, gui/, utils/)
  gui/icon.png       иконка трея из логотипа пользователя (256×256, прозрачный фон)
tests/               82 юнит-теста — НЕ удалять, это контроль качества
packaging/           systemd unit, .desktop, debian/, install.sh
_docs/               PRD (RU), HANDOFF (этот файл), test-page.html
CLAUDE.md GEMINI.md README.md LICENSE pyproject.toml .gitignore
```

Локальный мусор (в `.gitignore`, не в репозитории): `.pytest_cache/`,
`.ruff_cache/`, `*.egg-info/`, `__pycache__/` — регенерируются, можно удалять с диска.

## 9. Ветки

Приведено к: **`master`** (стабильная) + **`staging`** (рабочая, сюда весь код
сессии). Ветки `main` и `sgk-dev` удалены (локально и на `origin`), default на
GitHub переведён на `master`. Работаем в `staging`.

## 10. Что делать дальше

1. Прогнать матрицу приложений (PRD §10) вживую, зафиксировать где не работает.
2. По логу `sgk_switch_to` разобраться с жалобой на непереключение раскладки.
3. Решить по `python3-pyatspi` (защита полей пароля).
4. Подобрать тайминги вставки под реальные ощущения.
5. При стабильности — merge `staging` → `master`, `bash packaging/install.sh`.
