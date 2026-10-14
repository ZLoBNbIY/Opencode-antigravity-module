# Antigravity Hub для Linux (экспериментальная версия)

Linux-версия Hub развивается отдельно в ветке `linux` и не меняет Windows-реализацию из ветки `V2`. Она адаптирует графический интерфейс, системный трей, блокировку второго экземпляра, открытие папок и базовое управление OpenCode. Получение аккаунтов и квот, DNS-настройки и встроенный туннель используют общую логику проекта.

> Версия экспериментальная. Работа системного трея зависит от дистрибутива и рабочего стола; перед использованием проверьте запуск и управление OpenCode в своей среде.

## Требования

- OpenCode CLI (`opencode`) в `PATH`
- Python 3.10+, Tkinter и pip
- Node.js для CLI Antigravity
- Графическая сессия с поддержкой системного трея/AppIndicator

Для Debian/Ubuntu установите системные пакеты:

```bash
sudo apt install python3 python3-tk python3-venv python3-pip python3-gi gir1.2-ayatanaappindicator3-0.1
```

## Установка и запуск

Клонируйте именно Linux-ветку:

```bash
git clone -b linux --single-branch https://github.com/ZLoBNbIY/Opencode-antigravity-module.git
cd Opencode-antigravity-module
```

Установите Python-зависимости и запустите Hub:

```bash
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -r gui-manager/requirements-linux.txt
bash gui-manager/start_manager.sh
```

Если системный трей не запустился, Hub не будет сворачиваться в недоступный фон. Управление процессами OpenCode выполняется по именам `opencode`, `opencode-desktop` и `opencode-cli`; проверьте эти действия на своём дистрибутиве, прежде чем полагаться на них.
