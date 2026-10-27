# Промт для установки навыков и Graphify в OpenCode

Скопируйте текст ниже целиком в OpenCode (или другому агенту) на новом ПК.

---

Ты — инженер по настройке OpenCode V2. Установи на этот ПК три набора инструментов и проверь результат. Работай по шагам, не пропуская проверки. OmniRoute в этой задаче не трогай.

## Цель

1. addyosmani/agent-skills — 25 инженерных навыков (спека, план, TDD, ревью, безопасность и т.д.).
2. DietrichGebert/ponytail — навык «ленивого сеньора» + команды review/audit/debt/gain/help.
3. Graphify-Labs/graphify — локальный граф кодовой базы + навык `/graphify`.

Установка по умолчанию — глобальная, чтобы инструменты работали во всех проектах.
Graphify ставится глобально как навык, а граф и плагин — в конкретном проекте.

## Ограничения

- Не изменяй `opencode.json` без предварительной резервной копии.
- Не перезаписывай существующие навыки и настройки: если файл уже есть — сравни и спроси, что делать.
- Не устанавливай ничего, кроме перечисленного. OmniRoute и другие шлюзы не подключай.
- Не выводи и не коммить API-ключи, токены и содержимое `*.json` с секретами.
- Если чего-то не хватает (Node, Python, git) — установи или предложи способ установки, но не пропускай шаг молча.
- После установки не перезапускай OpenCode без необходимости: конфигурация подхватывается горячо, принудительно — командой `/reload`.

## Шаг 0. Определи окружение

Определи:
- ОС и оболочку (Windows PowerShell / bash / zsh);
- путь глобального конфига OpenCode:
  - Linux/macOS: `~/.config/opencode`
  - Windows: `%USERPROFILE%\.config\opencode`
- версию OpenCode (`opencode --version`), если команда доступна;
- наличие `git`, `node` (нужен 20+ для npx), `python` (3.10+), `uv` или `pipx`.

Зафиксируй в отчёте, что найдено и чего не хватает.

## Шаг 1. Подготовь каталоги

Создай:
- `<CONFIG>/skills` — глобальные навыки;
- `<CONFIG>/references` — общие чек-листы для agent-skills;
- `<CONFIG>/agents` — опционально, персоны ревьюеров.

Windows (PowerShell):
```powershell
$cfg = Join-Path $env:USERPROFILE ".config\opencode"
New-Item -ItemType Directory -Force "$cfg\skills","$cfg\references","$cfg\agents" | Out-Null
```

Linux/macOS:
```bash
mkdir -p ~/.config/opencode/{skills,references,agents}
```

## Шаг 2. Установи addyosmani/agent-skills

Предпочтительный способ — whole-repo установка, чтобы не потерять общие `references/`.

```bash
git clone --depth 1 https://github.com/addyosmani/agent-skills.git /tmp/agent-skills
```

Скопируй:
- содержимое `/tmp/agent-skills/skills/*` → `<CONFIG>/skills/` (каждый навык — отдельная папка с `SKILL.md`);
- `/tmp/agent-skills/references/*` → `<CONFIG>/references/`;
- опционально `/tmp/agent-skills/agents/*` → `<CONFIG>/agents/` (personas: code-reviewer, test-engineer, security-auditor, web-performance-auditor).

Windows:
```powershell
git clone --depth 1 https://github.com/addyosmani/agent-skills.git $env:TEMP\agent-skills
Copy-Item "$env:TEMP\agent-skills\skills\*" "$cfg\skills\" -Recurse -Force
Copy-Item "$env:TEMP\agent-skills\references\*" "$cfg\references\" -Recurse -Force
Copy-Item "$env:TEMP\agent-skills\agents\*" "$cfg\agents\" -Recurse -Force
```

Linux/macOS:
```bash
cp -R /tmp/agent-skills/skills/* ~/.config/opencode/skills/
cp -R /tmp/agent-skills/references/* ~/.config/opencode/references/
cp -R /tmp/agent-skills/agents/* ~/.config/opencode/agents/
```

Альтернатива, если есть Node 20+:
```bash
npx skills add addyosmani/agent-skills
```
Если CLI спросит агента — выбери OpenCode. После установки всё равно проверь, что `references/` на месте.

## Шаг 3. Установи ponytail

```bash
git clone --depth 1 https://github.com/DietrichGebert/ponytail.git /tmp/ponytail
```

Скопируй в `<CONFIG>/skills/` папки:
`ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`.

Windows:
```powershell
git clone --depth 1 https://github.com/DietrichGebert/ponytail.git $env:TEMP\ponytail
"ponytail","ponytail-review","ponytail-audit","ponytail-debt","ponytail-gain","ponytail-help" | ForEach-Object {
  Copy-Item "$env:TEMP\ponytail\skills\$_" "$cfg\skills\$_" -Recurse -Force
}
```

Linux/macOS:
```bash
for s in ponytail ponytail-review ponytail-audit ponytail-debt ponytail-gain ponytail-help; do
  cp -R "/tmp/ponytail/skills/$s" ~/.config/opencode/skills/
done
```

Не добавляй `AGENTS.md` из ponytail в глобальный конфиг автоматически. Если пользователь хочет всегда включённый режим — предложи добавить короткий блок в `AGENTS.md` конкретного проекта, а не глобально.

## Шаг 4. Установи Graphify

Graphify — Python-утилита, код парсится локально через tree-sitter, API-ключ для кода не нужен.

Установи CLI (выбери один способ):
```bash
uv tool install graphifyy
# или
pipx install graphifyy
# или
pip install graphifyy
```

Проверь:
```bash
graphify --version
```

Дальше — из корня проекта, где нужен граф:

Вариант A (рекомендуется): глобальный навык + проектный плагин.
```bash
graphify install --platform opencode
```
Что произойдёт:
- навык появится в `<CONFIG>/skills/graphify/`;
- в текущем проекте появится `.opencode/plugins/graphify.js` (подсказка агенту перед чтением файлов).

Вариант B: всё только в проекте.
```bash
graphify install --project --platform opencode
```
Навык и плагин останутся в `<PROJECT>/.opencode/`.

Вариант C: всегда-включённые инструкции в проекте.
```bash
graphify opencode install
```
Добавит секцию в `AGENTS.md` и тот же плагин. Используй, если нужно, чтобы агент всегда шёл в граф, а не в grep.

Построй граф:
```bash
graphify . --code-only
```
`--code-only` индексирует только код и работает полностью офлайн. Без него документация/PDF могут потребовать настроенный LLM-бэкенд. Результат: `graphify-out/graph.json`, `graphify-out/graph.html`, `graphify-out/GRAPH_REPORT.md`.

Проверь запросы:
```bash
graphify query "как устроена точка входа?"
graphify explain "main"
```

## Шаг 5. Проверь установку

1. Убедись, что в `<CONFIG>/skills/` есть папки:
   - 25 навыков agent-skills (включая `using-agent-skills`, `test-driven-development`, `code-review-and-quality`);
   - 6 навыков ponytail;
   - `graphify`.
2. Убедись, что `<CONFIG>/references/` содержит 7 чек-листов.
3. Убедись, что `graphify --version` работает, а в проекте есть `graphify-out/graph.json`.
4. В OpenCode выполни `/reload` и проверь, что навыки видны (список навыков / автодополнение).
5. Если навык не появился — проверь:
   - путь (`<CONFIG>/skills/<name>/SKILL.md`);
   - frontmatter `name` и `description` в `SKILL.md`;
   - логи OpenCode.

## Шаг 6. Отчёт

В конце выведи короткий отчёт:
- ОС и версия OpenCode;
- что установлено и куда (полные пути);
- какие проверки прошли, какие нет;
- что осталось сделать вручную (например, выбрать глобальную или проектную установку, настроить LLM-бэкенд для документов);
- никаких секретов в отчёте.
