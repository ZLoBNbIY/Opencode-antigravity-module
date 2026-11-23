# Клоакинг под нативный Antigravity: исследование и карта патчей

Дата: 23.11.2026. Документ **исследовательский**: при подготовке не делались живые
запросы к Google и не запускался OpenCode. Из репозитория изменён только этот
файл; кэш плагинов (`~/.cache/opencode/...`) только читался.

Источники:

- локальный клон 9router: `%TEMP%\9router`, коммит `5ae63d2` / `v0.5.123 (2026-11-22)`;
- установленные бандлы (только чтение):
  - 3.0.0 — `C:\Users\DevOps\.cache\opencode\npm\@cortexkit\opencode-antigravity-auth@3.0.0\1795447373451\node_modules\@cortexkit\opencode-antigravity-auth\dist\{server,index}.js`;
  - 3.1.13 — `...\opencode-antigravity-auth@3.1.13\1795449545541\...\dist\{server,index}.js`;
- их файлы `.hub-*.bak` (снимки до очередного патча Hub);
- текущий патчер `gui-manager/cloudcode_route_patch.py`;
- ранее написанные `docs/antigravity-request-body-comparison.md` и
  `docs/google-routing-research.md` (там же описан «ложный 429»).

> **Дисклеймер.** Подмена идентичности клиента, Headers/Body и обход проверок
> Google может нарушать Conditions of Service Antigravity / Google Cloud и
> привести к блокировке или ограничению аккаунта, потере квот и валидности OAuth.
> Ничто ниже не является гарантией «безопасности»: это описание того, как
> сторонние проекты маскируются, и перечень наблюдаемых рисков. Используйте только
> на тестовых аккаунтах и на свой страх и риск.

## 1. Что именно является триггером

9router различает **настоящую квоту** и **отказ тела запроса**:

| Случай | Тело ответа | Что делать |
| --- | --- | --- |
| Реальная квота | HTTP 429, `error.status = RESOURCE_EXHAUSTED`, есть `error.details` (`RetryInfo`, `ErrorInfo.reason=QUOTA_EXHAUSTED`, `metadata.quotaResetTimeStamp`) или сообщение вида `Individual quota reached ... Resets in 1h56m` | ждать `retry-after` / дедлайн, переключать аккаунт |
| Ложный отказ («fingerprint rejection») | HTTP 429, `message` ровно `Resource has been exhausted (e.g. check quota).`, **`error.details` отсутствует** | это request-scoped отказ: повтор того же тела бесполезен, квота и аккаунт ни при чём |

Код классификации: `open-sse/executors/antigravity.js:27-55, 193-198, 571-572`
(`isAntigravityPromptRejection()`), тест с точным телом —
`tests/unit/antigravity-prompt-rejection.test.js:1-54`. 9router на такой ответ
не делает backoff и не блокирует аккаунт, а просто возвращает читаемую ошибку;
дополнительно он один раз повторяет запрос, перенеся `systemInstruction` в
первый user turn (`moveSystemInstructionToContents()`, строки 77-85, 170-183).

Известные текстовые триггеры в `systemInstruction`
(`open-sse/config/appConstants.js:185-207`, тесты
`antigravity-hermes-fake-429.test.js` и `antigravity-billing-header-rewrite.test.js`):

- `You are a Claude agent, built on Anthropic's Claude Agent SDK.`;
- строка `x-anthropic-billing-header: cc_version=...` (Claude Code добавляет её в
  system-промпт; в Claude-формате её снимает конвертер, а в OpenAI-формате она доходит
  до Antigravity);
- строки Hermes Agent, найденные бисектом 18.11.2026: `<!-- End Hermes runtime
  environment -->`, `# Google model operational directives`, три длинные строки
  про «deliverable is a working artifact», документацию Hermes и mid-turn
  steering; сама identity-строка `You are Hermes Agent, built by Nous Research.
  Be direct:...`;
- упоминания `opencode` / `OPENCODE` / `OpenCode` (в локальном исследовании Hub
  конкретно доказана подстрока `tools.opencode.session_move` — см.
  `docs/google-routing-research.md:174-193`);
- `You are a personal assistant running inside OpenClaw.`.

Два других источника 429 в 9router **не относятся к Antigravity**: `403
FreeTierError` и гейты `read`/`shell`/`<env>`/`tool_choice=none` — это провайдер
`opencode`/`opencode-zen` (`open-sse/utils/opencodeFingerprint.js:1-33,
411-430`). Ещё одна причина 429 — неизвестные/недоступные имена моделей Gemini 4
(см. локальный `docs/google-routing-research.md:212+`); она лечится маршрутизацией
моделей, а не клоакингом.

## 2. Что у Hub уже есть (не трогать)

| Возможность | 3.0.0 | 3.1.13 |
| --- | --- | --- |
| UA `antigravity/hub/2.33.0`, `cl=1023160026`, `AGY_CLIENT_KIND="hub"` | есть (патч идентичности, `server.js:17196-17198, 17214-17218`) | **нет** (родной `antigravity/cli/1.5.8 ... auth_method=consumer`, `server.js:4013-4018, 4082-4083`) |
| `sessionId`, `labels` (`cascade_id`, `root_cascade_id`, `request_id`, `used_*`), `requestId`, шаги | есть (`server.js:21936-21969`) | есть нативно (`server.js:10777-10811`) |
| Санитайзер systemInstruction + вызов | есть (`server.js:35138-35169`, вызов `35925`) | есть (`server.js:48164-48195`, вызов `48930`) |
| `role: "user"` у systemInstruction и `<USER_REQUEST>`-обёртка, checkpoint-запросы | есть (`server.js:35926-35928, 36209-36245`) | отсутствуют (другая архитектура 3.1) |
| Backfill `thoughtSignature` только на первом `functionCall` | есть (`sanitizeRequestPayloadForAntigravity`, `server.js:35170-35207`) | есть (`server.js:48196+`) |
| Удаление `toolConfig`, разбивка functionDeclarations по одному | есть (`server.js:35103-35105`, патч `split-tool-declarations`) | есть нативно (`server.js:48106-48115`) |
| Заголовки generation без `X-Goog-Api-Client` / `Client-Metadata` | **нет** (`buildAgyCliHeaderPairs`, `server.js:22034-22037`) | есть (`headers.delete(...)`, `server.js:48603-48604`; `buildAgyCliHeaderPairs` больше их не добавляет) |
| Quota-breaker (429/409, дедлайны, 3 страйка → 15 мин) | есть (`QUOTA_BREAKER_MARKER`, `server.js:37703`) | есть (`server.js:51506`) |
| Различение «голого» 429 от квоты | **нет** | **нет** |

Якоря ниже проверены: каждая строка встречается **ровно 1 раз** в `server.js` и
`index.js` обеих версий (кроме явно отмеченных случаев). Оба файла — **LF, без
BOM**, поэтому все замены в Python-патчере должны делать
`text.replace("\n", eol)` как в `_identity_replacements()`. Номера строк
информационные; стабильны только сами строки.

## 3. Матрица трансформаций

| Трансформация | Где в 9router | Якорь в 3.0.0 | Якорь в 3.1.13 | Риск | Решение |
| --- | --- | --- | --- | --- | --- |
| Дополнить таблицу санитайзера: Claude SDK, `x-anthropic-billing-header`, Hermes, OpenClaw | `appConstants.js:187-207`; применение в `executors/antigravity.js:389-396`; тесты `antigravity-hermes-fake-429.test.js`, `antigravity-billing-header-rewrite.test.js` | `var ANTIGRAVITY_BLOCKED_SYSTEM_INSTRUCTION_PATTERNS = [` (L35138); вызов `sanitizeAntigravitySystemInstruction(requestPayload);` (L35925) | та же строка (L48164); вызов (L48930) | Низкий/средний: regex может задеть легитимный текст промпта; правила `^...$` должны оставлять остальные строки netронутыми | **Включить по умолчанию** — только добавить паттерны, существующие замены `opencode → coding agent` не трогать |
| Классификация «голого» RESOURCE_EXHAUSTED: не делать страйк/кулдаун аккаунта | `executors/antigravity.js:27-55, 193-198, 571-572`; `tests/unit/antigravity-prompt-rejection.test.js` | маркер `/* hub-quota-breaker:v1 */` (L37703); внутри `createHubQuotaBreaker()` — `async observe(key, response, now = Date.now()) {` | маркер (L51506); та же функция `observe` | Низкий: меняется только локальное состояние breaker'а; реальная квота по-прежнему считается | **Включить по умолчанию** |
| Один ретрай с переносом systemInstruction в первый user turn | `moveSystemInstructionToContents()` L77-85; `execute()` L170-183 | сразу после `await hubQuotaBreaker.observe(hubQuotaKey, response);` в `createRequestExecutor()` (нужен доступ к `prepared.request`) | после `await hubQuotaBreaker.observe(hubQuotaKey, response, receivedAtMs);` | Средний/высокий: меняется семантика system-промпта и число запросов; в 3.1RequestBody собраны заранее | **Opt-in, по умолчанию выключить** |
| UA `hub/2.33.0` вместо `cli/1.5.8`, снятие `auth_method` | `src/mitm/antigravityIdeVersion.js:15-24, 41-52`; `appConstants.js:143-146` | уже применено: `var AGY_CLI_VERSION = process.env.ANTIGRAVITY_APP_VERSION \|\| "2.33.0";` (L17196) и шаблон с `${AGY_CLIENT_KIND}` (L17218); в `.hub-bundle.bak` — `"1.1.24"` + `auth_method` | `AGY_CLI_VERSION = "1.5.8";` + `AGY_CLI_CHANGE_LIST = "1020628950";` (L4082-4083, внутри `var init_fingerprint = __esm({...})`), шаблон L4017; патчер пропускает 3.1 через `_is_v2_profile()` | Средний: версия должна совпадать с реально установленным приложением, иначе получим несовпадающий клиент | **Opt-in для 3.1**, 3.0 не трогать; версию брать из env |
| Убрать `X-Goog-Api-Client` / `Client-Metadata` из generation-заголовков | `appConstants.js:170-175` (только UA для loadCodeAssist); `executors/antigravity.js:243-253` | блок `const googApiClient = getHeader(headers, "X-Goog-Api-Client") ?? ...` … `pairs.push(["Client-Metadata", clientMetadata]);` (L22034-22037) | уже нативно: в `buildAgyCliHeaderPairs()` (L10949+) этих пар нет; `headers.delete("Client-Metadata")` (L48603-48604) | Низкий | **Включить для 3.0 по умолчанию** |
| Полностью убрать `requestType` на agent-пути | `executors/antigravity.js:434-440`; CHANGELOG L346; `translator/request/openai-to-gemini.js:360-363` | `requestType: isCheckpointRequest ? "checkpoint" : "agent"` (L36245), плюс одиночные `requestType: "agent"` (L27827, L50969) | три вхождения `requestType: "agent"` (L40380 account probe, L49207 main, L70385); `checkpoint` в 3.1 нет | Высокий: плагин/Hub используют это поле в парсерах и маршрутизации; можно сломать кэш/квоту/логи | **НЕ включать по умолчанию**, только отдельный флаг и тесты |
| Подставлять `ANTIGRAVITY_DEFAULT_SYSTEM` («You are Antigravity Agent...») | `appConstants.js:209-210`; вставка в `executors/antigravity.js:398-408` | после `sanitizeAntigravitySystemInstruction(requestPayload);` (L35925) / блока `role` (L35926-35928) | после `sanitizeAntigravitySystemInstruction(requestPayload);` (L48930) | Средний: добавляет текст в каждый system prompt, меняет поведение модели | **Opt-in, выключить**; только если нет строки `You are Antigravity` |
| `cloakTools()` + `_ide`-суффиксы + `AG_DECOY_TOOLS` | `executors/antigravity.js:589-798`, константы `AG_TOOL_SUFFIX` L88, `AG_DEFAULT_TOOLS` L120-141 | — | — | **Высокий**: в самом 9router вызов закомментирован (`translator/index.js:171-178`); нужна симметричная раскладка имён в stream/non-stream; decoy-инструменты «currently unavailable» ломают tool calling | **НЕ брать** |
| `toolConfig: {functionCallingConfig:{mode:"VALIDATED"}}` | `executors/antigravity.js:426` | конфликтует с已有 `delete payload.toolConfig` (L35103-35105) | конфликтует с L48106-48115 | Высокий: меняет валидацию инструментов; локальный comparison документ прямо рекомендует удалять | **НЕ брать** |
| Числовой `CLIENT_METADATA` (`ideType:9`, `platform:5`, `pluginType:2`) и MITM-перезапись `metadata.ideVersion` | `appConstants.js:78-82, 163-181`; `src/mitm/antigravityIdeVersion.js:54-78` | в `generateFingerprint()` строки `clientMetadata: { ideType: "ANTIGRAVITY", ... }` (L17249-17253) | те же (L4048-4052), плюс удаление заголовков | Средний: в теле плагина поля `metadata.ideVersion` нет;发送到 loadCodeAssist уже другой формат; риск сломать onboarding | **НЕ брать** |
| Подстановка длинного `DEFAULT_THINKING_AG_SIGNATURE` | `config/defaultThinkingSignature.js:4` | уже используется sentinel `skip_thought_signature_validator` (`server.js:35186-35205`) | то же (`server.js:48196+`) | Низкий, но бесполезно | **НЕ брать** |
| OpenCode free-tier fingerprint (`<env>`, tools `read`/`shell`, 403 FreeTierError) | `utils/opencodeFingerprint.js:1-33, 411-430` | — | — | Высокий: это другой провайдер; подмена схем инструментов сломает OpenCode | **НЕ брать** |
| Backfill thoughtSignature, `requestId`/`labels`/`sessionId`, checkpoint, деление инструментов | `executors/antigravity.js:152-163, 324-349`; `openai-to-gemini.js:343-397` | уже есть: L21936-21969, L35170-35207, L35103, checkpoint L36209+ | уже есть: L10777-10811, L48196+, L48106-48115 | — | **Уже реализовано, не дублировать** |

## 4. Рекомендуемые вставки (эскиз для реализатора)

### 4.1. Новые паттерны санитайзера (общий блок для 3.0 и 3.1)

Точка вставки — литерал массива `var ANTIGRAVITY_BLOCKED_SYSTEM_INSTRUCTION_PATTERNS = [...]`
(однозначен в обоих бандлах). Добавить **в конец** массива, не меняя существующие
пять правил:

```js
  [/x-anthropic-billing-header:[^\n]*(?:\r?\n)*/gi, ""],
  [/You are a Claude agent, built on Anthropic's Claude Agent SDK\./g, ""],
  [/^[ \t]*You are Hermes Agent, built by Nous Research\. Be direct:[^\n]*/gm, "You are an AI assistant."],
  [/^[ \t]*<!-- End Hermes runtime environment -->[^\n]*(?:\r?\n)?/gm, ""],
  [/^[ \t]*# Google model operational directives[^\n]*(?:\r?\n)?/gm, ""],
  [/^[ \t]*If a tool, install, or network call fails and blocks the real path[^\n]*(?:\r?\n)?/gm, ""],
  [/^[ \t]*When the user asks you to build, run, or verify something[^\n]*(?:\r?\n)?/gm, ""],
  [/^[ \t]*For help with Hermes Agent itself[^\n]*(?:\r?\n)?/gm, ""],
  [/^[ \t]*Mid-turn, the user can steer you: Hermes delivers their message[^\n]*(?:\r?\n)?/gm, ""],
  [/You are Hermes(?: Agent)?(?:,\s*(?:an intelligent AI assistant|an AI assistant|an AI agent))?(?:,?\s*(?:built|created)\s+by\s+Nous Research)?\./gi, "You are an AI assistant."],
  [/You are a personal assistant running inside OpenClaw\./gi, "You are a personal assistant running inside Antigravity."]
```

Важно: не добавлять замену `opencode → antigravity` поверх текущей
`opencode → coding agent`: в локально проверенном случае триггером была
конкретная запись `tools.opencode.session_move`, и существующая замена её уже
устраняет. Двойная замена изменит имена инструментов в промпте.

### 4.2. «Голый 429» не должен блокировать аккаунт

Точка вставки — тело `createHubQuotaBreaker()` сразу после `const rpcType = ...`
(маркер `/* hub-quota-breaker:v1 */`, уникален). Внутри `observe()` до создания
`state`:

```js
  const isBareExhaustion = (bodyText) => {
    try {
      const error = JSON.parse(bodyText)?.error;
      return error?.status === "RESOURCE_EXHAUSTED"
        && /^Resource has been exhausted \(e\.g\. check quota\)\.?$/.test(String(error.message || "").trim())
        && !(Array.isArray(error.details) && error.details.length > 0);
    } catch { return false; }
  };
```

и в `observe()` сразу после проверки `if (!key || response.headers.has(...)) return;`:

```js
      if (response.status === 429) {
        const bodyText = await errorJson(response); // clone(), original body intact
        if (isBareExhaustion(bodyText)) return;      // request-scoped refusal, not quota
      }
```

Далее — как сегодня: для 409/429 с деталями считаем дедлайн и страйки.
Это не мешает реальному quota-breaker'у и убирает ложные 15-минутные
кулдауны после трёх отказов одного и того же промпта.

### 4.3. UA-выравнивание 3.1 (только opt-in)

Точки вставки (в `server.js` и `index.js` идентичны):

```js
// L4017, возврат из buildAntigravityHarnessUserAgent:
  return `antigravity/${AGY_CLIENT_KIND}/${version} (aidev_client; os_type=${osType}; arch=${normalizedArch}${changeList})`;
// L4082-4083, внутри init_fingerprint:
    AGY_CLI_VERSION = "1.5.8";
    AGY_CLI_CHANGE_LIST = "1020628950";
```

Нужно добавить `var AGY_CLIENT_KIND = "hub";` (в 3.0 это L17198), заменить
`AGY_CLI_VERSION`/`AGY_CLI_CHANGE_LIST` на
`process.env.ANTIGRAVITY_APP_VERSION || "2.33.0"` и
`process.env.ANTIGRAVITY_APP_CHANGE_LIST || "1023160026"`, убрать
`; auth_method=${authMethod}` из шаблона. Патчер должен перестать пропускать
3.1 через `_is_v2_profile()` **только для этой правки** (остальные v2-ветки не
трогать). Проверять `node --check` обязательно: в 3.1 константы находятся внутри
`__esm`-closure, а не на верхнем уровне.

### 4.4. Generation-заголовки 3.0

Удалить ровно этот уникальный блок из `buildAgyCliHeaderPairs()`:

```js
  const googApiClient = getHeader(headers, "X-Goog-Api-Client") ?? "google-cloud-sdk vscode_cloudshelleditor/0.1";
  pairs.push(["X-Goog-Api-Client", googApiClient]);
  const clientMetadata = getHeader(headers, "Client-Metadata") ?? `{"ideType":"ANTIGRAVITY","platform":"${process.platform === "win32" ? "WINDOWS" : "MACOS"}","pluginType":"GEMINI"}`;
  pairs.push(["Client-Metadata", clientMetadata]);
```

В 3.1 такого блока нет — это эталон.

## 5. Безопасный opt-out и откат

1. **До применения:** все новые трансформации должны быть отдельными
  -function с маркерами (по образцу `/* hub-quota-breaker:v1 */`) и флагом в
  `config-templates/antigravity.json`, например `"cloaking_v2": false`.
  Патчер не должен трогать бандл, если флаг выключен; текущие маркеры
  `hub-identity-fix:v1`, `hub-prompt`, `hub-route`, `hub-gemini4`,
  `hub-quota-breaker:v1` остаются как есть.
2. **После применения:** остановить OpenCode → восстановить нужный
   `.hub-*.bak` в обратном порядке (quota-breaker → gemini4 → prompt → route →
   bundle/identity) → `node --check <файл>` → обновить состояние
   `plugin-patch-state.json` через штатный self-heal.
3. **Проверка без сети:** юнит-тесты патчера (`tests/test_quota_breaker_patch.py`
   и др.) работают на фикстурах и не делают запросов; живой прогон — только
   вручную на тестовом аккаунте.
4. Не патчить `plugin/dist/cli.js` как «источник истины»: это recovery-бандл Hub;
   рабочие файлы — установленные копии в кэше, и для 3.1 часть правок уже
   нативная.

## 6. Итоговая рекомендация

Минимальный безопасный набор по умолчанию:
**новые паттерны санитайзера (4.1) + корректная классификация «голого» 429
(4.2) + удаление двух заголовков в 3.0 (4.4)**. Всё остальное из 9router —
либо уже есть в Hub, либо конфликтует с рабочим tool calling, либо требует
отдельного решения и тестов. Помнить: даже полная имитация тела и заголовков не
меняет TLS/JA3, порядок заголовков, IP, историю токена и паттерны
использования — гарантии от блокировки не существует.

## 7. Что реализовано в Hub

Патч ставит маркеры `/* hub-cloaking:v1 */ … /* hub-cloaking:end */`
и имеет отдельный статус `cloaking` в `verify_plugin_health()` /
`self_heal_plugin()`. По умолчанию применяются все три пункта
минимального набора из раздела 6.

Расширенные приёмы (выравнивание UA в 3.1, подстановка
`You are Antigravity Agent…`, удаление `requestType: "agent"` и один ретрай
с переносом system-инструкции) **выключены по умолчанию**. Их включает
настройка `"cloaking_v2": true` в `antigravity.json` или переменная
`ANTIGRAVITY_HUB_CLOAKING_OPTIN=1`; `=0` принудительно выключает их.
После смены настройки Hub должен перезапустить self-heal плагина, а OpenCode —
перезапуститься. Патч не сохраняет тела запросов и ответов в логах и на диске;
для ограничения повторов используется только числовой отпечаток тела.
