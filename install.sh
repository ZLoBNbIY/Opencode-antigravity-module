#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'Installation stopped: %s Earlier steps may have made changes; no automatic rollback was attempted.\n' "$*" >&2
    exit 1
}

skip_patch=0
skip_python=0
for arg in "$@"; do
    case "$arg" in
        --skip-patch) skip_patch=1 ;;
        --skip-python) skip_python=1 ;;
        *) printf 'Usage: %s [--skip-patch] [--skip-python]\n' "$0" >&2; exit 2 ;;
    esac
done

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" ||
    fail 'Could not locate the installer directory.'
for name in opencode.json antigravity.json; do
    [[ -f "$script_dir/config-templates/$name" ]] || fail "Missing config template: $name."
done
patch_script="$script_dir/scripts/patch_plugin.mjs"
requirements="$script_dir/gui-manager/requirements.txt"

if (( ! skip_patch )); then
    [[ -f "$patch_script" ]] || fail 'Missing compatibility patch script.'
    command -v node >/dev/null 2>&1 &&
        node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' ||
        fail 'Node.js >=20 is required (or pass --skip-patch).'
fi
if (( ! skip_python )); then
    [[ -f "$requirements" ]] || fail 'Missing GUI requirements file.'
    command -v python3 >/dev/null 2>&1 &&
        python3 -I -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info < (4,)))' &&
        python3 -I -m pip --version >/dev/null ||
        fail 'Python >=3.10 and its pip module are required (or pass --skip-python).'
fi

config_base="${XDG_CONFIG_HOME:-}"
if [[ "$config_base" != /* ]]; then
    config_base="${HOME:?HOME must be set}/.config"
fi
config_dir="${OPENCODE_CONFIG_DIR:-$config_base/opencode}"
[[ "$config_dir" == /* ]] || fail 'OPENCODE_CONFIG_DIR must be an absolute path to install into it.'
umask 077
mkdir -p -- "$config_dir" || fail "Could not create $config_dir."
stage_dir="$(mktemp -d "$config_dir/.antigravity-install-XXXXXXXX")" ||
    fail 'Could not create a temporary config directory.'
cleanup() {
    rm -f -- "$stage_dir/opencode.json" "$stage_dir/antigravity.json"
    rmdir -- "$stage_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

publish_new_config() {
    local name="$1" existing path
    shift
    for existing in "$@"; do
        path="$config_dir/$existing"
        if [[ -e "$path" || -L "$path" ]]; then
            printf 'Existing config left untouched: %s. Check it against the module template and merge required settings manually.\n' "$path" >&2
            return
        fi
    done

    cp -- "$script_dir/config-templates/$name" "$stage_dir/$name" ||
        fail "Could not stage $name."
    for existing in "$@"; do
        path="$config_dir/$existing"
        if [[ -e "$path" || -L "$path" ]]; then
            fail "Config appeared during installation; it was not modified: $path."
        fi
    done
    # Link into the directory without forcing: this fails if that basename
    # already exists, even if a competing process created it after the check.
    ln -- "$stage_dir/$name" "$config_dir/" || fail "Could not publish $name without overwriting."
    printf 'Created %s/%s\n' "$config_dir" "$name"
}

publish_new_config opencode.json opencode.json opencode.jsonc
publish_new_config antigravity.json antigravity.json

if (( skip_patch )); then
    printf '%s\n' 'Skipped compatibility patch step (--skip-patch).'
else
    node "$patch_script" || fail "Compatibility patch script failed (exit $?)."
    printf '%s\n' 'Compatibility patch script completed. See its output for changes.'
fi
if (( skip_python )); then
    printf '%s\n' 'Skipped GUI dependencies (--skip-python).'
else
    printf '%s\n' 'Installing unlocked GUI requirements (no dependency lock for the shell installer).' >&2
    python3 -I -m pip install -r "$requirements" --quiet ||
        fail "GUI dependency installation failed (exit $?)."
    printf '%s\n' 'GUI dependency installation completed.'
fi

printf '%s\n' 'Installer steps completed. Existing configs, if any, were not updated or validated.'
