# OpenCode Antigravity Module

Интеграция Google Antigravity с OpenCode: модели Gemini и Claude через Google OAuth, управление несколькими аккаунтами и квотами. Включает графический менеджер **Antigravity Hub**. Ветка `V2` предназначена для OpenCode 2.x.

## Установка

### Windows — установка одной командой

Откройте PowerShell и выполните:

```powershell
(irm https://raw.githubusercontent.com/ZLoBNbIY/Opencode-antigravity-module/V2/install.ps1).Trim([char]65279) | iex
```

Установщик загрузит файлы, проверит Node.js (требуется версия 20 или новее), создаст конфигурацию OpenCode и установит компоненты Antigravity Hub. Для GUI также нужен Python 3.10+; если Python отсутствует, его потребуется установить отдельно.

### Windows — из клонированного репозитория

```powershell
git clone -b V2 https://github.com/ZLoBNbIY/Opencode-antigravity-module.git
cd Opencode-antigravity-module
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### Linux / macOS

```bash
git clone -b V2 https://github.com/ZLoBNbIY/Opencode-antigravity-module.git
cd Opencode-antigravity-module
chmod +x install.sh
./install.sh
```

## Первые шаги

1. Полностью перезапустите OpenCode после установки.
2. Добавьте Google-аккаунт одним из способов:
   - В Hub: запустите `gui-manager/start_manager.bat` (Windows) и выберите добавление Google-аккаунта.
   - В терминале: `node plugin/dist/cli.js login`.
3. В интерфейсе OpenCode (меню выбора моделей / провайдеров):
   - Активируйте ползунок (переключатель) **Google**.
   - Выберите модель с припиской **Antigravity** (например, `google/antigravity-gemini-3.8-flash` или `google/antigravity-claude-sonnet-4-6-thinking`).

> [!NOTE]
> OpenCode запрашивает полный список моделей из API, поэтому в общий перечень могут попадать и уже отключённые со стороны сервиса модели (например, ранние версии Gemini 3.1 / 3.6 / 3.7). Для стабильной работы используйте актуальные флагманские модели с префиксом `antigravity-`.

Чтобы подключить несколько Google-аккаунтов, повторите авторизацию для каждого. Плагин поддерживает ротацию аккаунтов при ограничениях квоты.

## Возможности

- Gemini и Claude через Google Antigravity OAuth.
- Несколько Google-аккаунтов, ротация и отображение квот.
- Antigravity Hub для управления аккаунтами, квотами и настройками.
- Поддержка OAuth-аккаунтов ChatGPT/OpenAI в Hub.
- Бесплатные текстовые модели OpenRouter через ваш API-ключ — отдельный провайдер **OpenRouter Free** в Hub и OpenCode.
- Экспериментальный DeepSeek Web: вход и ограничения описаны в [docs/deepseek.md](docs/deepseek.md).

Чтобы подключить бесплатные модели OpenRouter:

1. Зарегистрируйтесь или войдите на [openrouter.ai](https://openrouter.ai/).
2. Откройте [страницу API-ключей](https://openrouter.ai/settings/keys) и создайте ключ (**Create API Key**). Создание ключа бесплатно; бесплатные модели доступны в пределах квот OpenRouter. Не публикуйте ключ и не отправляйте его в чат.
3. Откройте в Antigravity Hub раздел **OpenRouter Free**, вставьте ключ и нажмите **«Проверить ключ и загрузить модели»**.
4. Отметьте бесплатные модели, которые хотите использовать, и нажмите **«Добавить выбранные в OpenCode»**.

Выбранные модели появятся в отдельном провайдере **OpenRouter Free**. Встроенный провайдер **OpenRouter** отключается, чтобы его общий каталог платных моделей не отображался; при отключении интеграции встроенный провайдер включится снова. Доступность, бесплатные квоты и состав каталога задаёт OpenRouter, и они могут меняться.

## Требования

- OpenCode 2.x.
- Node.js 20 или новее.
- Python 3.10 или новее — для графического Hub.
- Современный браузер для OAuth-входа.

Установщик Windows проверяет версию Node.js и пытается установить или обновить её, если версия ниже требуемой.

## Конфигурация и данные

Основные конфигурационные файлы находятся в `~/.config/opencode/` (в Windows: `%USERPROFILE%\.config\opencode\`). Обычно установщик создаёт их автоматически. Настройки Antigravity хранятся в `antigravity.json`.

Аккаунты и токены не следует публиковать или добавлять в репозиторий. Для переноса аккаунтов между компьютерами используйте экспорт и импорт в Hub.

## Лицензия

MIT. Компоненты сторонних авторов распространяются на условиях их собственных лицензий.
