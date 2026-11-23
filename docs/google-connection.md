# Автоматическое подключение пула Antigravity Hub к OpenCode 2

Документ описывает контракт и точки внедрения на ветке **V2** для нативного
подключения `google` в OpenCode 2. В нём зафиксированы эмпирически проверенные
вызовы, правила идемпотентности и места в коде Hub. Автоматизация реализована
в `gui-manager/google_connection.py` и вызывается из `webview_backend.py`.

## 1. Проблема и цель

Плагин Antigravity (профиль 3.1.x / GA) работает только когда хост OpenCode видит
«свою» connection для интеграции `google`. Если в OpenCode есть только connection
типа `env` (`GOOGLE_GENERATIVE_AI_API_KEY`), запрос уходит напрямую в Google,
минуя плагин, и Google отвечает `API key not valid`.

Цель: при запуске Hub и после добавления Google-аккаунта **гарантированно,
но не более одного раза** создать в OpenCode 2 credential-connection интеграции
`google`, которую плагин создаёт своим методом входа `antigravity-auth-pool-reconnect`
(«Use existing local Antigravity pool»).

Ни в коем случае не удалять и не отключать `env`-connection
`GOOGLE_GENERATIVE_AI_API_KEY` — она является частью штатной конфигурации OpenCode
и не мешает работе credential (наблюдалось сосуществование обеих строк).

## 2. Контракт вызовов OpenCode 2

Вызовы идут через **CLI OpenCode** `opencode-cli.exe`, подкоманду `api`
(проверено: `opencode-cli.exe api --help` → `api <operation | METHOD PATH...>`,
флаги `--data/-d`, `--param`, `--server`). CLI обращается к фоновому сервису
OpenCode (`opencode service status` показывает `http://127.0.0.1:<port>`).

### 2.1 Проверка состояния (read-only)

```
opencode-cli.exe api GET /api/integration
```

Ответ — JSON-конверт `{"location": ..., "data": [ ... ]}`. Нужна только ветка
`data`: элементы с `id == "google"`. У интеграции `google` интересуют только поля:

- `connections[]` — массив объектов `{type, id?, label?, method?, name?}`;
- `methods[]` — справочник, в котором должен присутствовать метод
  `antigravity-auth-pool-reconnect` (это признак того, что плагин 3.1.x загружен).

В observational-примере после успешного подключения:

```json
{"id": "google", "connections": [
  {"type": "credential", "id": "cred_…", "label": "Antigravity Hub pool", "method": "oauth"},
  {"type": "env", "name": "GOOGLE_GENERATIVE_AI_API_KEY"}
]}
```

До подключения массив содержал только `{"type":"env","name":"GOOGLE_GENERATIVE_AI_API_KEY"}`.

### 2.2 Создание attempt

```
opencode-cli.exe api POST /api/integration/google/connect/oauth \
  --data "{\"methodID\":\"antigravity-auth-pool-reconnect\",\"label\":\"Antigravity Hub pool\"}"
```

Тело строго фиксировано:

| Поле       | Значение                              |
|------------|---------------------------------------|
| `methodID` | `antigravity-auth-pool-reconnect`     |
| `label`    | `Antigravity Hub pool`                |

Допустимые наблюдаемые поля ответа attempt: `attemptID`, `mode` (`auto`), `url`
(`""`), `status`. Это «автоматический» вид входа: браузер не открывается,
пользовательские действия не нужны. Плагин внутри (`connectExisting()`) проверяет
наличие непустого локального пула и возвращает placeholder-credential с
`methodID = antigravity-auth-pool-reconnect`; поэтому на пустом пуле attempt
завершится отказом — повторять нужно только после успешного логина.

### 2.3 Завершение attempt

```
opencode-cli.exe api POST /api/integration/google/connect/oauth/{attemptID}/complete \
  --data "{}"
```

`{attemptID}` подставляется из п. 2.2 без дополнительной обработки. Выполняется
**ровно один раз** на attempt. После этого OpenCode создаёт credential с
`integrationID=google`, `method=oauth`, `active=true`.

### 2.4 Верификация

Повторить п. 2.1 и считать успехом наличие в `connections` строки с
`type == "credential"`, `method == "oauth"`, `label == "Antigravity Hub pool"`.
Дополнительно (не обязательно для рабочего кода) состояние `active` можно
прочитать без записи через уже существующий
`openai_manager._read_opencode_credential_rows("google")` — он возвращает строки
БД с полем `active`.

## 3. Надёжный поиск CLI на Windows

Сейчас в репозитории три разных резолвера, и два из них хардкодят версию/папку:

- `gui-manager/antigravity_manager.pyw`: `get_opencode_exe()` (строки 119–137),
  `get_opencode_cli()` (139–151) — уже ищет `resources/opencode-cli.exe` рядом с
  найденным `OpenCode.exe`, затем Roaming-кэш, затем PATH. Это **лучшая база**;
- `gui-manager/openai_manager.py`: `find_opencode_cli()` (56–70) — содержит
  жёстко зашитый путь `…\@opencode-aidesktop\resources\opencode-cli.exe` и
  `…\cli\2.0.27\…`. Замена этого резолвера в текущую реализацию не входила;
  новый код использует общий `antigravity_manager.get_opencode_cli()`;
- `antigravity_manager.get_cli_js()` — не для OpenCode CLI, а для vendored node-CLI
  плагина; в этой фиче не используется.

Рекомендуемый единый резолвер (в `antigravity_manager.pyw`, рядом с
`get_opencode_cli()`, с сохранением текущего имени функции):

1. `shutil.which("opencode-cli")`, затем `shutil.which("opencode")` — если CLI
   в PATH, это самый надёжный вариант.
2. Glob `%LOCALAPPDATA%\Programs\*\resources\opencode-cli.exe` **без имени папки**;
   кандидатов сортировать по `st_mtime` (свежее установленный) и отбирать только
   реально существующие файлы; предпочитать тот, рядом с которым
   (`../OpenCode.exe`) лежит десктопное приложение.
3. `%APPDATA%\ai.opencode.desktop\cli\*\opencode-cli.exe` — уже есть в текущей
   реализации; оставить как fallback, сортировку по убыванию версии сохранить.
4. Не использовать конкретные `@opencode-aidesktop`, `2.0.27` и т.п. в новом коде.
5. Никаких «дефолтных» несуществующих путей как успеха: если ничего не найдено —
   вернуть `None` (текущий `get_opencode_exe()` возвращает строку-кандидат, но
   `get_opencode_cli()` уже возвращает `None` — сохранить именно это поведение).

Все вызовы CLI делать через `antigravity_manager.run_silent_cmd(...)` c
`env=proxy_config.opencode_launch_environment()`: это убирает устаревшие
`HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`, которые иначе могут направить запрос к
локальному сервису через маршрутизатор Hub. Не использовать
`run_google_route_cmd()` (он, наоборот, добавляет proxy-окружение).

## 4. Идемпотентность и обработка состояний

Алгоритм `ensure_google_connection()` (чистая функция + тонкая обёртка с CLI):

1. Если `api._closing.is_set()` или `api._uninstalled` — выход.
2. Проверить версию/профиль (§5). Неподдерживаемый профиль → `skip`, без вызовов.
3. `cli = antigravity_manager.get_opencode_cli()`; `None` → `cli_missing`.
4. `GET /api/integration` (таймаут ~5–8 c). Найти `id == "google"`.
5. Проанализировать `connections`:
   - есть `type == "credential"` и `label == "Antigravity Hub pool"` → **already_connected**, выход, POST не делать;
   - есть любой другой `type == "credential"` (другой label/method) → **foreign_credential**, выход без изменений (не создавать дубликат, не трогать чужую connection);
   - только `type == "env"` → перейти к созданию.
6. Перед POST ещё раз взять per-process лок (см. §7) и повторить шаг 4 — закрыть гонку с другим потоком/логином.
7. POST create → распарсить `attemptID`; если ответ не содержит `attemptID` или `mode != "auto"` → **api_error**, не вызывать complete.
8. POST complete с `{}` один раз.
9. Повторный GET → **connected** / **verify_failed**.

Правила:

- **Не создавать дубликаты** при каждом старте Hub или каждом логине: единственный
  источник истины — presence Hub-labeled credential в GET. Создавать только при
  отсутствии.
- **Connection есть, но не active**: дубликат не создавать. Через
  `_read_opencode_credential_rows("google")` подтвердить `active`; если `false` — вернуть
  диагностику `inactive` и предложить перезапуск сервиса/ручное переключение.
  Вызывать неизвестные `/activate`-эндпоинты или напрямую править БД в v1 **запрещено**.
- **Vault/host**:Hub не должен инициировать или изменять `antigravity-vault`.
  Если в `methods` есть vault-метод — это нормально; если пользователь использует
  vault-конфигурацию, existence Hub-credential не мешает, но Hub не должен
  «переключать» источник учётных данных. Проверка §2.1 не читает и не пишет токены.
- **Env connection** остаётся нетронутой во всех ветвях.

## 5. Совместимость по версиям

Метод `antigravity-auth-pool-reconnect` присутствует **только в бандлах 3.1.x (GA)**.
Проверено по кэшу: он есть в
`~/.cache/opencode/npm/@cortexkit/opencode-antigravity-auth@3.1.13/…/dist/src/ga/server/pool-login.js`
и отсутствует в vendored `plugin/` репозитория (`package.json` → `3.0.0`).
Поэтому:

- для **3.0.x фичу пропускать** (`skip`): там используется sentinel
  `apiKey = "antigravity"` (`gui-manager/opencode_config.py`,
  `GOOGLE_SENTINEL_API_KEY` / `google_api_key_sentinel()`), и нативный connection
  не требуется;
- для **3.1.x** (в V2 это `plugin_pin_version = "3.1.13"` в
  `antigravity_manager.DEFAULT_CONFIG`) — выполнять контракт §2;
- версию брать через `cloudcode_route_patch.get_expected_plugin_version()` —
  он читает pin из `antigravity.json` (`plugin_pin_version`), затем
  `verified_version` из patch-state, затем версию vendored бандла;
  для защиты от конфликтующих pin'ов можно переиспользовать логику
  `HubApi._google_refresh_profile()` (`webview_backend.py`, строки 599–624):
  если Hub pin и pin в `opencode.json` различаются — `skip` (fail closed);
- версию ядра OpenCode получать `opencode-cli.exe --version` (наблюдалось
  `opencode v2.4.1`) только для диагностики; гейт делать по профилю плагина,
  а не по строке версии ядра. Дополнительный признак — наличие метода
  `antigravity-auth-pool-reconnect` в `methods` ответа GET.

## 6. Где вызывать (тайминг)

| Точка в коде | Что делать | Почему |
|---|---|---|
| `webview_backend.py` → `bg_refresher()` (2865–2918), сразу после `self_heal_plugin()` (2867–2872) и до `api._sync_routes(...)` | Запустить **отдельный daemon-поток** `threading.Thread(target=api.ensure_google_connection, daemon=True, name="hub-google-connect").start()` | `bg_refresher` уже daemon-поток, но доп. поток изолирует ожидание CLI/сервиса и не задерживает сетевую инициализацию Hub. Это основной вызов при старте. |
| `webview_backend.py` → `add_google_account()` (1724–1789), после успешной миграции и `service restart` (1764–1783), перед `return` | Запланировать тот же daemon-поток (не ждать результата в UI-потоке) | После логина пул уже не пуст, поэтому reconnect, который при старте мог отказать, теперь выполнится. Сообщение пользователю не меняем: неуспех подключения — только в логах/диагностике. |
| `webview_backend.py` → `restart_opencode()` (1917–1945), после успешного `start_opencode()` | Необязательный **лёгкий** вызов: только `GET /api/integration` с коротким таймаутом | Restart сервиса не удаляет credential; это лишь верификация. Можно не делать, если есть вызов из `bg_refresher`. |
| `HubApi.__init__` (544–592) | **Не вызывать** | Работает в UI-потоке; только подготовить лок/состояние. |
| `get_state()` / WebView-опросы | **Не вызывать** | Вызывается часто; сетевые проверки тут недопустимы. |

Итого рекомендация: **стартовый daemon-поток в `bg_refresher` + повтор после
успешного `add_google_account`**. Повтор после `restart_opencode` — опциональная
верификация.

## 7. Безопасность, таймауты, состояние

- **Локи**: добавить в `HubApi.__init__` `self._google_connect_lock =
  threading.Lock()`; захватывать `acquire(blocking=False)` — если не удалось,
  выход (`connect_in_progress`). Аналог уже используется для логинов
  (`self._login_locks`, строки 589, 1725, 1848, 1861). Hub однокопиечен
  (`acquire_single_instance()`), поэтому внутрипроцессного лока достаточно;
  повторный GET перед POST закрывает остальные гонки.
- **Таймауты** (`run_silent_cmd`): GET 5–8 c; POST create 10 c; POST complete
  10 c; GET verify 5 c. Общий бюджет ~35 c. При `attempt` в состоянии,
  отличном от завершённого, **не вызывать complete повторно** — прервать и
  вернуться в следующий цикл Hub.
- **Логирование**: только `hub_logging.log.info("Google connection: status=%s",
  status)`; при ошибке — `hub_logging.failed("Google connection", exc)`, где
  `exc` приводится к типу/коду. **Never** логировать `stdout`, `stderr`,
  тела POST, `attemptID`, `id` credential, токены и содержимое ответа.
- **Парсинг**: разбирать `json.loads(stdout)`; из dict брать только
  `data` (или сам dict, если конверта нет); из элемента — только
  `id`, `connections`, `methods`; из connection — только `type`, `id`, `label`,
  `method`. Всё остальное игнорировать, в том числе ключи, похожие на токены.
- **Код возврата**: проверять `returncode != 0` до парсинга; не подставлять
  stdout при ошибке в сообщения UI.
- **Окружение**: `env=proxy_config.opencode_launch_environment()` для всех вызовов
  `opencode-cli.exe api …` (§3).
- **Остановка Hub**: проверять `api._closing.is_set()` и `api._uninstalled`
  перед каждым этапом; daemon-поток не должен удерживать выход.
- **Не трогать чужие connection**: никаких `DELETE`, `disconnect`, `PATCH` и
  изменений env-строки. Только два POST из §2.2/§2.3.

## 8. Тесты

Новый модуль `tests/test_google_connection.py` (чистые функции + мок runner),
плюс несколько тестов в `tests/test_webview_backend.py` по уже принятому там
паттерну (faked `antigravity_manager` в `sys.modules`, `Mock(return_value=
SimpleNamespace(returncode=…, stdout=…, stderr=…))`, `patch.object(
threading, "Thread", ImmediateThread)`).

Моки:

- `antigravity_manager.get_opencode_cli()` → путь/ `None`;
- `antigravity_manager.run_silent_cmd` → последовательность `SilentResult`-подобных объектов
  с JSON-строками (`{"data": [...]}`), упорядоченных по вызовам GET/POST/GET;
- `cloudcode_route_patch.get_expected_plugin_version` → `3.1.13` / `3.0.0` / `None`;
- `os.path.exists` для CLI; `hub_logging` → no-op;
- `api._closing` = `threading.Event()`.

Обязательные сценарии:

1. **Уже подключено**: GET возвращает Hub-labeled credential → 0 POST, статус
   `already_connected`, env-строка сохранена.
2. **Absent CLI**: `get_opencode_cli()` → `None` → статус `cli_missing`, 0 вызовов.
3. **Unsupported version**: `3.0.0` → `skip`, 0 вызовов.
4. **Ошибка API**: `returncode != 0`, невалидный JSON или 404 на `/api/integration`
   → `api_error`, без исключения наружу, без повтора POST.
5. **Attempt timeout / pending**: ответ create без `attemptID` или со status не
   complete → `timeout`, complete не вызывается.
6. **Конкурентный логин**: два потока/вызова → лок + повторный GET дают ровно
   один POST create и один complete; второй получает `already_connected` /
   `connect_in_progress`.
7. **Чужая credential**: в `google` есть credential с другим label → `foreign_credential`,
   новых POST нет.
8. **Inactive credential**: GET показывает Hub-connection, а БД-хелпер `active=false`
   → `inactive`, дубликата нет.
9. **Vault/host**: presence `antigravity-vault` в `methods` не меняет поведение;
  UA не делает vault-вызовов.

## 9. Сводка точек в коде

| Файл | Функция / строки | Изменение |
|---|---|---|
| `gui-manager/antigravity_manager.pyw` | `get_opencode_exe()` 119–137, `get_opencode_cli()` 139–151 | Единый резолвер без хардкода `@opencode-aidesktop`; вернуть `None` при отсутствии |
| `gui-manager/antigravity_manager.pyw` | `run_silent_cmd()` 276–297 | Использовать как есть, с `env=opencode_launch_environment()` |
| `gui-manager/proxy_config.py` | `opencode_launch_environment()` 134–139 | Обязательное окружение для вызовов CLI API |
| `gui-manager/openai_manager.py` | `find_opencode_cli()` 56–70 | Убрать захардкоженные пути, delegates в общий резолвер; `_read_opencode_credential_rows()` 115–173 — read-only проверка `active` |
| `gui-manager/cloudcode_route_patch.py` | `get_expected_plugin_version()` 1014–1034 | Версионный гейт (только 3.1.x) |
| `gui-manager/opencode_config.py` | `google_api_key_sentinel()` 104–114, `ensure_google_api_key()` 117–139 | Оставить без изменений: это совместимость с 3.0.x |
| `gui-manager/google_proactive_refresh.py` | `SUPPORTED_PROFILES` 25, `find_cli_3113()` 28–33 | Образец gating только для 3.1.13 |
| `gui-manager/webview_backend.py` | `HubApi.__init__` 544–592 | Добавить `_google_connect_lock`, не делать сетевых вызовов |
| `gui-manager/webview_backend.py` | `add_google_account()` 1724–1789 | Планировать daemon-проверку после успешного логина |
| `gui-manager/webview_backend.py` | `restart_opencode()` 1917–1945 | Опциональная лёгкая верификация |
| `gui-manager/webview_backend.py` | `bg_refresher()` 2865–2918 | **Основной вызов**: daemon-поток после self-heal |
| `tests/test_webview_backend.py` | 181–229, 278–294 | Паттерны моков login/restart |
| `tests/test_google_connection.py` | новый | Сценарии §8 |

## 10. Итог

Минимально надёжная схема для V2:

1. Один раз стартовать `hub-google-connect` из `bg_refresher()`.
2. Повторить после успешного `add_google_account()`.
3. Внутри: проверить профиль ≥3.1 → найти CLI → GET → (только при отсутствии
   Hub-credential) POST create → POST complete → GET verify.
4. Никаких дубликатов, никаких изменений env/vault/host, только безопасные поля
   в логах, жёсткие таймауты и daemon-поток, не блокирующий UI.
5. Отключить автоматизацию можно переменной `AI_HUB_GOOGLE_POOL_CONNECTION=0`
   перед запуском Hub (существующие connection при этом не удаляются).
