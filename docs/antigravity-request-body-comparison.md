# Тело запроса Antigravity и плагина OpenCode: фактическое сравнение

Дата проверки: 18.11.2026.

Сравнивались:

- установленное приложение Antigravity `2.33.0`
  (`%LOCALAPPDATA%\Programs\antigravity`, language server `2.33.0`);
- плагин `@cortexkit/opencode-antigravity-auth` `3.0.0` и ядро
  `@cortexkit/antigravity-auth-core` `3.0.0` из кэша OpenCode;
- Hub-прокси и health-check из этого репозитория.

Тело оригинального приложения получено живым перехватом HTTPS через локальный
MITM-прокси. Временный CA и ключи после проверки удалены. Ниже не приводятся
токены, полные идентификаторы аккаунта и содержимое промптов.

## Краткий вывод

Плагин правильно повторяет **внешнюю схему** запроса
`v1internal.GenerateContentRequest`: `project`, `requestId`, `request`, `model`,
`userAgent`, `requestType`, а внутри — `contents`, `systemInstruction`, `tools`,
`labels`, `generationConfig`, `sessionId`. Заголовки также почти совпадают:
`Authorization`, `Content-Type`, `Accept-Encoding: gzip`, без
`X-Goog-Api-Client` и `Client-Metadata`, тело стрима передаётся chunked.

Но в реальном теле плагина есть системные расхождения:

1. **Другая модель по умолчанию.** `antigravity-gemini-3.8-flash` уходит в
   `gemini-3.8-flash-medium`, а приложение по умолчанию работает на
   `gemini-3.8-flash-high`.
2. **Другой формат thinking.** Приложение отправляет
   `thinkingConfig.thinkingLevel: "HIGH"`, плагин — числовой
   `thinkingBudget` (`-1` или `4000`). Даже вариант `:high` в плагине не
   превращается в `thinkingLevel: "HIGH"`.
3. **Другой `sessionId`.** Приложение во всех проверенных диалогах отправляет
   `-3750763034362895579` (FNV-1a от пустой строки). Плагин хэширует путь
   workspace, поэтому для текущего каталога получается другое число.
4. **Другие метки.** В приложении есть `cascade_id`, `root_cascade_id`,
   `request_id`, а `last_step_index` считает шаги траектории (`0, 2, 4, ...`).
   Плагин эти три метки не отправляет, а `last_step_index` считает части
   `contents` (на первом запросе `1` вместо `0`).
5. **Сдвинутый `requestId`.** У приложения первый запрос заканчивается на `/1`,
   у плагина — на `/2`. Причина: плагин использует `last_step_index + 1` вместо
   отдельного счётчика запросов.
6. **Лишний `toolConfig`.** Плагин всегда добавляет
   `functionCallingConfig.mode = "VALIDATED"`. Приложение для агентских
   запросов `toolConfig` не отправляет.
7. **Другой User-Agent.** Приложение:
   `antigravity/hub/2.33.0 (...; cl=1023160026)`. Плагин:
   `antigravity/cli/1.3.5 (...; cl=998863838; auth_method=consumer)`.
8. **Служебные запросы.** Приложение для генерации заголовка отправляет
   `requestType: "checkpoint"`, `requestId: "checkpoint/<uuid>"`, модель
   `gemini-3.5-flash-lite`, без `labels` и `tools`. Плагин отправляет такие
   запросы как `requestType: "agent"`.

Пункты 1–3 наиболее вероятно влияют на поведение, кэш и квоты. Пункты 4–5 —
на серверную телеметрию и идентичность запроса. Пункты 6–7 могут влиять на
режим валидации инструментов и на то, как Google классифицирует клиента.

## 1. Как формирует тело оригинальное приложение

### 1.1. Endpoint и транспорт

Активный endpoint:

```text
POST https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse
```

Для `streamGenerateContent` язык server использует
`Transfer-Encoding: chunked`. Ответ — `text/event-stream`.

### 1.2. Внешний конверт

В бинарнике language server есть встроенный proto-дескриптор
`google.internal.cloud.code.v1internal.GenerateContentRequest`. Поля:

| Поле | Тип | Что наблюдалось |
| --- | --- | --- |
| `project` | string | `aicode-consumers` |
| `request_id` | string | `agent/<cascade>/<epoch-ms>/<trajectory>/<seq>` |
| `request` | `google.cloud.aiplatform.master.GenerateContentRequest` | вложенное тело |
| `model` | string | `gemini-3.8-flash-high` |
| `user_prompt_id` | string | в проверенных запросах отсутствует |
| `user_agent` | string | `antigravity` |
| `request_type` | string | `agent` или `checkpoint` |
| `enabled_credit_types` | repeated enum | в проверенных запросах отсутствует |

Фактический порядок ключей в JSON:

```json
{
  "project": "...",
  "requestId": "...",
  "request": { },
  "model": "...",
  "userAgent": "antigravity",
  "requestType": "agent"
}
```

### 1.3. Вложенный `request`

Порядок ключей в реальном запросе:

```json
{
  "contents": [],
  "systemInstruction": {},
  "tools": [],
  "labels": {},
  "generationConfig": {},
  "sessionId": "..."
}
```

Наблюдаемые значения для `gemini-3.8-flash-high`:

- `contents`: один `role: "user"` с текстом в обёртках
  `<USER_REQUEST>...</USER_REQUEST>` и `<ADDITIONAL_METADATA>...</ADDITIONAL_METADATA>`;
- `systemInstruction`: `role: "user"` и один `parts[].text`;
- `tools`: 16 отдельных элементов, каждый вида
  `{ "functionDeclarations": [ { ... } ] }` — по одному объявлению на элемент;
- `toolConfig`: отсутствует;
- `safetySettings`: отсутствует;
- `generationConfig`:
  ```json
  {
    "maxOutputTokens": 65536,
    "thinkingConfig": {
      "includeThoughts": true,
      "thinkingLevel": "HIGH"
    }
  }
  ```
- `sessionId`: `-3750763034362895579`;
- `labels`:
  ```json
  {
    "cascade_id": "<conversation-id>",
    "last_step_index": "0",
    "model_enum": "MODEL_PLACEHOLDER_M318",
    "request_id": "<trajectory-id>-0",
    "root_cascade_id": "<conversation-id>",
    "trajectory_id": "<trajectory-id>",
    "used_claude": "false",
    "used_claude_conservative": "false",
    "used_non_gemini_model": "false"
  }
  ```

`requestId` первого запроса:

```text
agent/607cfe32-5430-4066-b85a-e6830e1c461a/1794980557988/e7a0f91d-001d-44da-88f9-c693f0c7d683/1
```

То есть:

- `cascade_id` = идентификатор диалога;
- `trajectory_id` = идентификатор траектории;
- `last_step_index` = `0` на первом запросе;
- `request_id` в labels = `<trajectory>-0`;
- шаг в `requestId` = `1`.

### 1.4. Заголовки

Реальный запрос содержал только:

```text
host: daily-cloudcode-pa.googleapis.com
user-agent: antigravity/hub/2.33.0 (aidev_client; os_type=windows; arch=amd64; cl=1023160026)
transfer-encoding: chunked
authorization: Bearer ...
content-type: application/json
accept-encoding: gzip
```

Не было:

- `X-Goog-Api-Client`;
- `Client-Metadata`;
- `X-Goog-User-Project`;
- `x-api-key`.

### 1.5. Метки на нескольких ходах

По сохранённым траекториям Antigravity видно закономерность:

| Номер запроса | `last_step_index` | `request_id` в labels |
| --- | --- | --- |
| 1 | `0` | `<trajectory>-0` |
| 2 | `2` | `<trajectory>-1` |
| 3 | `4` | `<trajectory>-2` |
| 4 | `6` | `<trajectory>-3` |
| ... | ... | ... |

`last_step_index` растёт на 2 за каждый запрос модели, а `request_id`
увеличивается на 1. Это разные счётчики.

В длинных диалогах появляется `last_execution_id` и остаётся стабильным
на протяжении одной серии запросов, например `c3456811-...`.

`sessionId` во всех проверенных диалогах и workspace один и тот же:
`-3750763034362895579`. Это FNV-1a 64-bit signed от пустой строки.

### 1.6. Служебный `checkpoint`-запрос

Для генерации заголовка диалога приложение отправляет отдельное тело:

```json
{
  "project": "aicode-consumers",
  "requestId": "checkpoint/<uuid>",
  "request": {
    "contents": [{ "role": "user", "parts": [{ "text": "..." }] }],
    "systemInstruction": {
      "role": "user",
      "parts": [{ "text": "You are a conversation title generator..." }]
    },
    "generationConfig": {
      "thinkingConfig": {
        "includeThoughts": true,
        "thinkingLevel": "LOW"
      }
    },
    "sessionId": "-3750763034362895579"
  },
  "model": "gemini-3.5-flash-lite",
  "userAgent": "antigravity",
  "requestType": "checkpoint"
}
```

Особенности:

- нет `tools`;
- нет `labels`;
- `requestType` = `checkpoint`;
- `requestId` начинается с `checkpoint/`;
- модель `gemini-3.5-flash-lite`;
- thinking level `LOW`.

## 2. Как формирует тело плагин

Основная точка сборки:
`plugin/dist/src/plugin/request.js`, функция `prepareAntigravityRequestIn`.
Метаданные: `@cortexkit/antigravity-auth-core/dist/agy-request-metadata.js`.
Модель и thinking: `transform/model-resolver.js` и `model-registry.js`.

### 2.1. Конверт

Плагин собирает:

```js
{
  project: effectiveProjectId,
  requestId: agyMetadata?.requestId,
  request: requestPayload,
  model: effectiveModel,
  userAgent: 'antigravity',
  requestType: 'agent',
}
```

Порядок ключей совпадает с приложением. В `requestPayload` плагин добавляет
`toolConfig` (см. ниже), поэтому внутри ключей на один больше.

### 2.2. Модель и thinking

Для публичной модели `antigravity-gemini-3.8-flash` без варианта
`resolveModelWithTier` выбирает `gemini-3.8-flash-medium` и
`thinkingBudget: 4000`.

Для `gemini-3.8-flash-high` (native) выбирается
`thinkingBudget: -1` и **не** выбирается `thinkingLevel`.

Даже при явном варианте `:high` плагин отправляет:

```json
{
  "includeThoughts": true,
  "thinkingBudget": -1
}
```

Причина в `model-resolver.js`: у native-модели есть truthy
`thinkingBudget`, поэтому `tierThinkingLevel` не устанавливается, и ветка
Gemini 3 с `thinkingLevel` не срабатывает.

`maxOutputTokens` для Flash-моделей плагин выставляет `65536`, как и
приложение.

### 2.3. Метки

`buildAgyAgentRequestMetadata` формирует:

```json
{
  "last_step_index": "<count>",
  "model_enum": "MODEL_PLACEHOLDER_M318",
  "trajectory_id": "<uuid>",
  "used_claude": "false",
  "used_claude_conservative": "false",
  "used_non_gemini_model": "false"
}
```

`last_execution_id` добавляется только если он уже есть в объекте сессии, но
`completeExecution()` в рабочем коде не вызывается, поэтому на практике его
нет.

Нет `cascade_id`, `root_cascade_id` и `request_id`.

`last_step_index` считается функцией `countAgyRequestSteps(payload)` в режиме
`parts`: количество всех частей во всех `contents`. На первом простом запросе
это `1`, а не `0`.

`requestId`:

```text
agent/<conversationId>/<timestamp>/<trajectoryId>/<lastStepIndex + 1>
```

Поэтому первый запрос заканчивается на `/2`, а не `/1`.

### 2.4. `sessionId`

`AgySessionRegistry` создаёт `AgyRequestSessionStore` с
`workspaceUri = pathToFileURL(resolve(directory)).href`. Далее
`createAgyRequestSessionContext(workspaceUri)` считает FNV-1a от этого URI.

Для текущего workspace:

```text
file:///C:/Users/DevOps/Opencode-antigravity-module
```

получается:

```text
7320627765449649954
```

Приложение же отправляет `-3750763034362895579`.

### 2.5. Инструменты

`applyGeminiTransforms` + `wrapToolsAsFunctionDeclarations` собирают все
объявления в один элемент:

```json
[
  {
    "functionDeclarations": [
      { "name": "a", "description": "", "parameters": { ... } },
      { "name": "b", "description": "", "parameters": { ... } }
    ]
  }
]
```

Приложение отправляет по одному элементу на инструмент.

`configureAntigravityToolCalling` затем всегда добавляет:

```json
{
  "toolConfig": {
    "functionCallingConfig": {
      "mode": "VALIDATED"
    }
  }
}
```

### 2.6. Заголовки

Фактический набор плагина:

```text
accept-encoding: gzip
authorization: Bearer ...
content-type: application/json
user-agent: antigravity/cli/1.3.5 (aidev_client; os_type=windows; arch=amd64; cl=998863838; auth_method=consumer)
```

Остальное совпадает с приложением. Отличается только User-Agent.

### 2.7. Фактический пример

Синтетический запрос через `prepareAntigravityRequest` для
`antigravity-gemini-3.8-flash` дал:

```json
{
  "project": "aicode-consumers",
  "requestId": "agent/<conversation>/<timestamp>/<trajectory>/2",
  "request": {
    "contents": [{ "role": "user", "parts": [{ "text": "..." }] }],
    "systemInstruction": { "parts": [{ "text": "..." }] },
    "tools": [{ "functionDeclarations": [ ... ] }],
    "toolConfig": { "functionCallingConfig": { "mode": "VALIDATED" } },
    "labels": {
      "last_step_index": "1",
      "model_enum": "MODEL_PLACEHOLDER_M319",
      "trajectory_id": "<uuid>",
      "used_claude": "false",
      "used_claude_conservative": "false",
      "used_non_gemini_model": "false"
    },
    "generationConfig": {
      "maxOutputTokens": 65536,
      "thinkingConfig": {
        "includeThoughts": true,
        "thinkingBudget": 4000
      }
    },
    "sessionId": "-3750763034362895579"
  },
  "model": "gemini-3.8-flash-medium",
  "userAgent": "antigravity",
  "requestType": "agent"
}
```

В этом синтетическом вызове `sessionId` был взят из
`DEFAULT_AGY_REQUEST_SESSION` (пустая строка), поэтому совпал с приложением.
В реальном OpenCode используется registry с workspace URI, и значение другое.

## 3. Таблица различий

| Поле / аспект | Antigravity 2.33.0 | Плагин 3.0.0 | Оценка |
| --- | --- | --- | --- |
| Внешние ключи | `project, requestId, request, model, userAgent, requestType` | те же | совпадает |
| `project` | `aicode-consumers` | `aicode-consumers` после `loadCodeAssist`; fallback `rising-fact-p41fc` | в норме, но fallback устарел |
| `model` по умолчанию для 3.8 Flash | `gemini-3.8-flash-high` | `gemini-3.8-flash-medium` | **расхождение** |
| `thinkingConfig` | `thinkingLevel: "HIGH"` | `thinkingBudget: -1` / `4000` | **расхождение** |
| `maxOutputTokens` | `65536` | `65536` | совпадает |
| `tools` | 16 элементов по одному объявлению | один элемент со всеми объявлениями | семантически близко, но не идентично |
| `toolConfig` | отсутствует | `mode: "VALIDATED"` | **лишнее поле** |
| `systemInstruction` | `role: "user"` + `parts` | только `parts` | минорно |
| `labels.cascade_id` | есть | нет | **расхождение** |
| `labels.root_cascade_id` | есть | нет | **расхождение** |
| `labels.request_id` | есть | нет | **расхождение** |
| `labels.last_execution_id` | есть в длинных диалогах, стабилен | практически не появляется | **расхождение** |
| `labels.last_step_index` | `0, 2, 4, ...` | число частей, на первом запросе `1` | **расхождение** |
| `labels.model_enum` | `MODEL_PLACEHOLDER_M318` для high | `M318` для high, `M319` для medium | зависит от модели |
| `requestId`, шаг | `/1` на первом запросе | `/2` | **off-by-one** |
| `sessionId` | `-3750763034362895579` всегда | FNV(workspace URI), например `7320627765449649954` | **расхождение** |
| `requestType` | `agent` / `checkpoint` | только `agent` | расхождение для служебных запросов |
| User-Agent | `antigravity/hub/2.33.0 (...; cl=1023160026)` | `antigravity/cli/1.3.5 (...; cl=998863838; auth_method=consumer)` | **расхождение** |
| `Accept-Encoding` | `gzip` | `gzip` | совпадает |
| `X-Goog-Api-Client` | нет | нет | совпадает |
| `Client-Metadata` | нет | нет | совпадает |
| `X-Goog-User-Project` | нет | удаляется | совпадает |
| Transfer-Encoding | chunked на stream | chunked на stream | совпадает |
| `userPromptId` | нет | нет | совпадает |
| `enabledCreditTypes` | нет | нет | совпадает |
| `safetySettings` | нет | нет | совпадает |

## 4. Почему это важно

### 4.1. Квоты и 429

Google может учитывать `cascade_id`, `trajectory_id`, `last_step_index`,
`request_id` и `sessionId` для серверной сессии, кэша и квот. Если плагин
каждый раз присылает другой `sessionId`, не присылает `cascade_id` и
`request_id`, а `last_step_index` считает иначе, сервер видит не тот же
профиль запросов, что у приложения. Это не доказанная причина 429, но
правдоподобный механизм фрагментации кэша и квоты.

### 4.2. Качество модели

Пользователь OpenCode, выбравший `google/antigravity-gemini-3.8-flash`,
получает `gemini-3.8-flash-medium` с `thinkingBudget: 4000`, тогда как
приложение по умолчанию работает на `gemini-3.8-flash-high` с
`thinkingLevel: "HIGH"`. Это влияет на глубину reasoning и может выглядеть как
«модель стала хуже».

### 4.3. Валидация инструментов

`toolConfig.mode = "VALIDATED"` — это дополнительное ограничение, которого нет
в теле приложения. Оно может менять поведение вызова инструментов и
обработку схем. Если оно не требуется для конкретной модели, его лучше не
отправлять.

### 4.4. Идентичность клиента

User-Agent `antigravity/cli/1.3.5` описывает старый CLI, а не установленное
приложение `antigravity/hub/2.33.0`. Если Google различает клиентов по UA,
плагин и приложение могут попадать в разные политики.

### 4.5. Health-check Hub

`gui-manager/health_checker.py` проверяет генерацию другим телом:

- нет `requestId`;
- нет `sessionId`;
- нет `labels`;
- нет `systemInstruction`;
- нет `tools`;
- `maxOutputTokens: 2048`;
- User-Agent `antigravity/cli/1.1.24`;
- модель для `antigravity-gemini-3.8-flash` — `gemini-3.8-flash-high`.

Такой пробник не эквивалентен ни телу приложения, ни телу плагина. Успешный
ответ Hub не доказывает, что реальный запрос OpenCode пройдёт с теми же
параметрами.

## 5. Рекомендации

Приоритет 1 — поведение модели:

1. Для `antigravity-gemini-3.8-flash` по умолчанию выбирать high, как в
   приложении, либо явно документировать, что без суффикса используется
   medium.
2. Для Gemini 3.5–3.8 Flash отправлять `thinkingLevel` (`"HIGH"`,
   `"MEDIUM"`, `"LOW"`) вместо числового `thinkingBudget`. Использовать
   верхний регистр, как в proto-JSON приложения.
3. Убедиться, что `maxOutputTokens` для high остаётся `65536`.

Приоритет 2 — идентичность сессии:

4. Не хэшировать workspace для `sessionId`. Использовать то же значение, что
   приложение: `-3750763034362895579` (FNV-1a 64-bit signed от пустой строки),
   либо воспроизводить фактический алгоритм приложения.
5. Ввести отдельный счётчик запросов на траекторию:
   - `last_step_index` — шаги траектории (`0, 2, 4, ...`);
   - `request_id` в labels — `<trajectory>-<request_seq>`;
   - шаг в `requestId` — `<request_seq + 1>`.
6. Добавить `cascade_id`, `root_cascade_id` и `request_id` в labels.
7. Реализовать стабильный `last_execution_id` на время выполнения, а не
   генерировать его на каждый запрос.

Приоритет 3 — точное соответствие телу:

8. Для агентских Gemini-запросов не добавлять `toolConfig`, если приложение
   его не отправляет. Оставить `VALIDATED` только там, где это действительно
   нужно (например, Claude).
9. Приводить `systemInstruction` к виду `role: "user"` + `parts`, если
   требуется побайтовое совпадение.
10. Для служебных запросов (заголовок диалога, checkpoint) использовать
    `requestType: "checkpoint"`, `requestId: "checkpoint/<uuid>"`, модель
    `gemini-3.5-flash-lite`, без `labels` и `tools`.
11. Обновить User-Agent до актуального приложения:
    `antigravity/hub/<version> (aidev_client; os_type=windows; arch=amd64; cl=<change-list>)`.
    Версию и `cl` лучше брать из установленного Antigravity, а не хардкодить.
12. Обновить health-check Hub: использовать то же тело и UA, что реальный
    плагин, либо явно помечать пробник как синтетический.

## 6. Как перехват был сделан

1. Локальный MITM-прокси на `127.0.0.1:18080` с временным CA в хранилище
   текущего пользователя.
2. Antigravity запущен с `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY` и
   `AG_LS_PROXY`, указывающими на этот прокси.
3. В приложении отправлен короткий тестовый запрос.
4. Перехвачены `loadCodeAssist`, `fetchAvailableModels`,
   `streamGenerateContent?alt=sse` и `checkpoint`-запрос.
5. После проверки прокси остановлен, CA и сертификаты удалены, приложение
   запущено с обычными настройками.

Перехваченные тела содержат пользовательский текст и системную инструкцию,
поэтому в репозиторий они не добавлялись.

## 7. Итог

Плагин уже очень близок к формату Antigravity: конверт, порядок полей,
заголовки, chunked-стрим и `sessionId`-константа совпадают. Основные
расхождения — модель/thinking по умолчанию, `sessionId`, метки
`cascade_id`/`root_cascade_id`/`request_id`, счётчик `last_step_index`,
`toolConfig` и User-Agent. Именно они делали реальный запрос OpenCode не
эквивалентным запросу оригинального приложения.

## 8. Исправления, применённые после проверки

Правки внесены в bundled-файлы `plugin/dist/index.js` и
`plugin/dist/server.js`, а также в `gui-manager/cloudcode_route_patch.py`,
чтобы фикс переживал обновление плагина. Для установленной копии в кэше
OpenCode они применены тем же патчем.

Что исправлено:

1. **User-Agent.** Теперь `antigravity/hub/2.33.0 (aidev_client;
   os_type=windows; arch=amd64; cl=1023160026)`, как у приложения.
   До исправления установленный бандл отправлял
   `antigravity/cli/1.1.24 (...; cl=974782877; auth_method=consumer)` —
   важная поправка к таблице выше: значение `1.3.5` относилось к
   несобранным исходникам ядра, а не к тому, что реально грузит OpenCode.
2. **`sessionId`.** `AgySessionRegistry` больше не хэширует путь workspace.
   Используется `FNV-1a` от пустой строки → `-3750763034362895579`.
3. **Метки.** Добавлены `cascade_id`, `root_cascade_id`, `request_id`.
   `cascade_id`/`root_cascade_id` берутся из OpenCode session id (или из
   conversation id, если заголовка сессии нет).
4. **Счётчики.** `last_step_index` теперь равен `0, 2, 4, ...`, а шаг в
   `requestId` — `1, 2, 3, ...`. `request_id` в labels =
   `<trajectory>-<request_seq>`. Первый запрос заканчивается на `/1`.
5. **Модель/thinking.** `antigravity-gemini-3.8-flash` по умолчанию
   резолвится в `gemini-3.8-flash-high`, route-map для 3.8 Flash использует
   конкретные модели `low/medium/high`, а `generationConfig` отправляет
   `thinkingLevel: "HIGH"/"MEDIUM"/"LOW"` вместо числового `thinkingBudget`.
6. **`toolConfig`.** Больше не добавляется `VALIDATED`.
7. **`systemInstruction`.** Добавлен `role: "user"`, как в приложении.
8. **Checkpoint-запросы.** Запросы генерации заголовка диалога получают
   `requestType: "checkpoint"`, `requestId: "checkpoint/<uuid>"`, модель
   `gemini-3.5-flash-lite`, `thinkingLevel: "LOW"`, без `labels` и `tools`.
9. **Health-check Hub.** Пробник теперь отправляет конверт и метки в формате
   приложения, UA `antigravity/hub/2.33.0` и `maxOutputTokens: 65536`.
10. **Инструменты.** `functionDeclarations` больше не собираются в один
    элемент: каждое объявление отправляется отдельным
    `{ "functionDeclarations": [ ... ] }`, как у приложения.
11. **Санитайзер системной инструкции.** Заменяются не только
    `tools.opencode.session_move`, а все ссылки `tools.opencode.<name>` →
    `tools["agent"]["<name>"]`, а также слова `OpenCode`/`opencode` →
    `the coding agent`/`coding agent`.
12. **`last_execution_id`.** Появляется один раз при первом
    `functionResponse` в `contents` и дальше остаётся стабильным, как в
    длинных диалогах приложения.
13. **Синхронизация бандла.** Hub больше не перезаписывает установленный
    плагин `3.0.20` локальным снимком `3.0.0`. Если installed-версия новее,
    синхронизация пропускается, а патчи применяются к установленному бандлу
    на месте. Это устраняет откат версии при нажатии «Применить фикс
    плагина». Та же защита добавлена в `scripts/patch_plugin.mjs`.
14. **Обёртка пользовательского запроса.** Последнее пользовательское
    сообщение оборачивается в `<USER_REQUEST>...</USER_REQUEST>` и
    `<ADDITIONAL_METADATA>The current local time is: ...</ADDITIONAL_METADATA>`,
    как у приложения.
15. **Точный checkpoint-запрос.** Для генерации заголовка теперь
    отправляется точный системный промпт Antigravity
    (`You are a conversation title generator...`), содержимое берётся из
    исходного текста запроса, а `generationConfig` содержит только
    `thinkingConfig` с `thinkingLevel: "LOW"`.
16. **Account-access probe.** Проверка доступа к аккаунту больше не
    отправляет `gemini-3.5-flash-low` с `maxOutputTokens: 1`; она использует
    checkpoint-форму: `gemini-3.5-flash-lite`, `requestType: "checkpoint"`,
    `requestId: "checkpoint/<uuid>"`, без labels и tools.
17. **OAuth.** Refresh-token и userinfo запросы теперь отправляют
    User-Agent приложения вместо `GEMINI_CLI_HEADERS`/Node-умолчания.
18. **Санитайзер.** Дополнительно нейтрализуются `Code Mode`/`code mode`,
    а ссылки `tools.opencode.<name>` превращаются в `tools.<name>`.
19. **Subagent-сессии.** Для дочерней сессии `root_cascade_id` берётся из
    `x-opencode-parent-session-id`, как root conversation в приложении.

Проверка после патча (через временный экспорт внутренних функций из установленного
бандла) показала:

```text
UA: antigravity/hub/2.33.0 (aidev_client; os_type=windows; arch=amd64; cl=1023160026)
outer: project=aicode-consumers, requestId=agent/<cascade>/<ts>/<trajectory>/1,
       model=gemini-3.8-flash-high, userAgent=antigravity, requestType=agent
request keys: contents, systemInstruction, tools, labels, generationConfig, sessionId
labels: cascade_id, last_step_index=0, model_enum=MODEL_PLACEHOLDER_M318,
        request_id=<trajectory>-0, root_cascade_id, trajectory_id, used_*
sessionId: -3750763034362895579
generationConfig: maxOutputTokens=65536, thinkingConfig.includeThoughts=true,
                  thinkingLevel=HIGH
toolConfig: absent
systemInstruction.role: user
headers: accept-encoding=gzip, authorization=Bearer ..., content-type=application/json,
         user-agent=antigravity/hub/2.33.0
```

### Что осталось неидентичным

Побайтовая идентичность **всего** запроса недостижима без запуска самого
Antigravity:

- `contents` и `systemInstruction` по-прежнему содержат промпты OpenCode и
  его Code Mode каталог, хотя ссылки `tools.opencode.*` и название продукта
  теперь заменяются санитайзером. Смысл и структура промпта всё равно
  отличаются от agent prompt приложения.
- `tools` теперь разделены по одному объявлению на элемент, но сами имена и
  схемы инструментов — это инструменты OpenCode, а не Antigravity.
- Транспортные признаки: TLS/JA3/JA4, HTTP/2 settings, порядок заголовков,
  тайминги, IP/геолокация, история токена и паттерны использования.

Checkpoint-запрос, обёртки `<USER_REQUEST>`/`<ADDITIONAL_METADATA>`, OAuth UA
и account-access probe теперь совпадают с приложением. Поэтому можно говорить
о совпадении **протокольной части запроса** (schema,
метаданные, заголовки, session identity), но не о полной маскировке клиента.
Google может видеть side-channel признаки, которые этим патчем не меняются.

Сознательно не реализованы три вещи, потому что они ломают OpenCode или
требуют отдельного проекта:

- маппинг имён и схем инструментов OpenCode на инструменты Antigravity
  (`read` → `read_file`, `bash` → `run_command` и т. д.) с обратным
  преобразованием `functionCall`;
- замена `systemInstruction` на полный 35-килобайтный agent prompt
  Antigravity;
- Go-транспорт с TLS/HTTP2-отпечатком language server.

После применения патча нужно перезапустить OpenCode.
