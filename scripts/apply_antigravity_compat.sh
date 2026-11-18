#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

PYTHON=${ANTIGRAVITY_PYTHON:-}
if [ -z "$PYTHON" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON=python
  else
    echo "Python 3 not found. Install Python 3 and retry." >&2
    exit 1
  fi
fi
export ANTIGRAVITY_PYTHON="$PYTHON"

NODE=${ANTIGRAVITY_NODE:-}
if [ -z "$NODE" ]; then
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js not found. Install Node.js 20+ and retry." >&2
    exit 1
  fi
  NODE=node
fi

echo "=== Antigravity compatibility patch ==="
echo "Repo: $ROOT"
echo "Python: $PYTHON"

echo
echo "[1/3] Node patches"
"$NODE" "$SCRIPT_DIR/patch_plugin.mjs" || echo "patch_plugin.mjs failed; continuing with Python patches."

echo
echo "[2/3] Hub route patch"
"$PYTHON" "$ROOT/gui-manager/cloudcode_route_patch.py"

echo
echo "[3/3] Identity / Antigravity body patch"
"$PYTHON" "$ROOT/gui-manager/cloudcode_route_patch.py" identity

echo
echo "=== Status ==="
"$PYTHON" "$ROOT/gui-manager/cloudcode_route_patch.py" status

echo
echo "Done. Restart OpenCode so it loads the patched bundle."
echo "For a different Antigravity build, export ANTIGRAVITY_APP_VERSION and ANTIGRAVITY_APP_CHANGE_LIST."
