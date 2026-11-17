# TokenLavka в Antigravity Hub

TokenLavka — OpenAI-совместимый шлюз, который даёт доступ к моделям Claude, GPT, Gemini, Grok, DeepSeek, Kimi, Qwen и GLM через один API-ключ `sk-…`.

Источник: <https://tokenlavka.com/guides/opencode>, <https://tokenlavka.com/help>.

## Подключение

1. Вставьте ключ на вкладке **🎟️ TokenLavka** и нажмите **«Проверить ключ»**. Проверка выполняется запросом `GET https://tokenlavka.com/v1/models` через текущий маршрут провайдера `tokenlavka`.
2. Отметьте нужные модели и нажмите **«Добавить выбранные в OpenCode»**.
3. В `~/.config/opencode/opencode.json` будет создан отдельный провайдер:

```json
{
  "provider": {
    "tokenlavka": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "TokenLavka",
      "options": {
        "baseURL": "http://127.0.0.1:10880/r/tokenlavka/v1",
        "hubBaseURL": "https://tokenlavka.com/v1"
      },
      "models": { "gpt-6-luna": { "name": "GPT-6 Luna", "limit": { "context": 512000, "output": 65536 } } }
    }
  }
}
```

   `baseURL` указывает на обычный HTTP-эндпоинт маршрутизатора Хаба — так OpenCode не использует локальный CONNECT-прокси (Bun часто сбрасывает такие соединения). Реальный адрес шлюза хранится в `hubBaseURL`, а маршрутизатор сам выбирает транспорт из `provider_routes.tokenlavka`, включая `direct`. Локальный `baseURL` сохраняется при любом выбранном маршруте — менять его вручную не нужно.

4. Ключ импортируется в хранилище учётных данных OpenCode командой `opencode auth import` с `integrationID = tokenlavka`, поэтому его не нужно дублировать в `options.apiKey`.
5. Модели вызываются как `tokenlavka/<id>`, например `tokenlavka/gpt-6-luna`.

## Хранение ключа

- Зашифрованный ключ: `%APPDATA%\AntigravityHub\secure\tokenlavka.json`.
- Ключ **не** попадает в `opencode.json`, логи и интерфейс (в UI видны только последние 4 символа).
- Кнопка «Отключить» делает `opencode auth logout tokenlavka`, очищает список моделей провайдера и удаляет файл ключа.

## Резервная копия

Ключ и выбранные модели включаются в `export_backup` / `import_backup` Hub в разделе `tokenlavka`.

## Маршрутизация и диагностика

- Идентификатор провайдера для маршрутов: `tokenlavka`. Домен `tokenlavka.com` зарегистрирован в `provider_proxy.LOCAL_ROUTES` и `auto_router.DEFAULT_HOSTS`.
- Вкладка диагностики показывает доступность домена через выбранный маршрут, кнопка «Проверить ключ» — реальную авторизацию.

## Коды ошибок

| Код | Причина | Что делать |
|---|---|---|
| 401 | Ключ не распознан | Убедитесь, что ключ скопирован целиком, включая `sk-` |
| 402 | Недостаточно средств / под запрос | Пополните ключ, начните новую сессию или выберите модель дешевле |
| 429 | Слишком частые запросы | Подождите несколько секунд, уменьшите параллельность |
| 404 | Неверный Base URL | Должен быть ровно `https://tokenlavka.com/v1` |
| 502/503 | Модель временно недоступна | Повторите позже или выберите другую модель |

## Доступные модели

Полный список синхронизирован с таблицей `/help`: `claude-opus-5-5`, `claude-opus-4-8`, `claude-opus-5`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-5`, `claude-fable-5`, `claude-fable-5-1`, `gpt-6-astra`, `gpt-6-luna`, `gpt-5-6-sol`, `gpt-5-6-terra`, `gpt-5-6-luna`, `gpt-5-5`, `gpt-5-4`, `gemini-3.1-pro-preview`, `glm-5.3`, `glm-5.3-flash`, `grok-4.7`, `grok-4.6`, `kimi-k3`, `kimi-k2.7-code`, `deepseek-v4-pro`, `deepseek-v4.1-pro`, `deepseek-v4.1-flash`, `qwen-3.8-max`, `qwen-3.8-flash`, `qwen-3.8-omni`, `economy`.
