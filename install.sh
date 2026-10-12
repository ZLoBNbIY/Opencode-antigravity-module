#!/usr/bin/env bash
set -e

echo "========================================================"
echo "  Установка и настройка Opencode-antigravity-module"
echo "========================================================"

CONFIG_DIR="$HOME/.config/opencode"
mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/antigravity.json" ]; then
    echo "[*] Копирование antigravity.json в $CONFIG_DIR"
    cp "$(dirname "$0")/config-templates/antigravity.json" "$CONFIG_DIR/antigravity.json"
else
    echo "[i] Файл antigravity.json уже существует в $CONFIG_DIR."
fi

if [ ! -f "$CONFIG_DIR/opencode.json" ]; then
    echo "[*] Копирование opencode.json в $CONFIG_DIR"
    cp "$(dirname "$0")/config-templates/opencode.json" "$CONFIG_DIR/opencode.json"
else
    echo "[i] Файл opencode.json уже существует в $CONFIG_DIR."
fi

echo ""
echo "[*] Применение патчей совместимости..."
if command -v node >/dev/null 2>&1; then
    node "$(dirname "$0")/scripts/patch_plugin.mjs"
else
    echo "[!] Node.js не найден. Установите Node.js (>=18) для применения патчей."
fi

echo ""
echo "[*] Установка зависимостей GUI (Python)..."
if command -v pip3 >/dev/null 2>&1; then
    pip3 install -r "$(dirname "$0")/gui-manager/requirements.txt" --quiet || true
elif command -v pip >/dev/null 2>&1; then
    pip install -r "$(dirname "$0")/gui-manager/requirements.txt" --quiet || true
fi

echo ""
echo "========================================================"
echo "  Установка завершена!"
echo "========================================================"
echo "Для входа в аккаунт: node plugin/dist/cli.js login"
