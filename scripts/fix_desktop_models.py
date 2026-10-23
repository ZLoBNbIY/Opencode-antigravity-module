import sqlite3
import json
import os
from pathlib import Path

def fix_models_visibility():
    drafts_path = Path(os.path.expandvars(r"%APPDATA%\ai.opencode.desktop\drafts.sqlite"))
    if not drafts_path.exists():
        return

    try:
        conn = sqlite3.connect(str(drafts_path))
        cur = conn.cursor()
        cur.execute("SELECT rowid, value FROM state WHERE name='opencode.global.dat' AND key='model'")
        row = cur.fetchone()
        if not row:
            conn.close()
            return

        rowid, val_str = row
        data = json.loads(val_str)

        # 1. Remove discontinued models (3.7, 3.6, 3.1)
        deprecated_versions = ("3.7", "3.6", "3.1")
        def is_dep(mid):
            return any(v in mid for v in deprecated_versions)

        user_models = [m for m in data.get("user", []) if not is_dep(m.get("modelID", ""))]

        # 2. Models that should be immediately visible in the quick dropdown
        to_show = [
            "antigravity-gemini-4-argon",
            "antigravity-gemini-3.8-flash",
            "antigravity-gemini-3.5-flash",
            "antigravity-claude-opus-5-5",
            "antigravity-claude-opus-5-5-thinking",
            "antigravity-claude-sonnet-5-5",
            "antigravity-claude-sonnet-5-5-thinking",
            "antigravity-claude-opus-4-6",
            "antigravity-claude-opus-4-6-thinking",
            "antigravity-claude-sonnet-4-6",
            "antigravity-claude-sonnet-4-6-thinking",
            "antigravity-gpt-oss-120b-medium"
        ]

        existing_keys = {f"{m.get('providerID')}:{m.get('modelID')}" for m in user_models}

        for m_id in to_show:
            k = f"google:{m_id}"
            if k not in existing_keys:
                user_models.append({"providerID": "google", "modelID": m_id, "visibility": "show"})
                existing_keys.add(k)
            else:
                for m in user_models:
                    if m.get("providerID") == "google" and m.get("modelID") == m_id:
                        m["visibility"] = "show"

        data["user"] = user_models

        # 3. Clean recent & ensure Gemini 4 Argon, Claude Opus/Sonnet 5.5 and Gemini 3.8 are at top
        if "recent" in data:
            data["recent"] = [m for m in data["recent"] if not is_dep(m.get("modelID", ""))]
            recent_keys = {f"{m.get('providerID')}:{m.get('modelID')}" for m in data["recent"]}
            for m_id in [
                "antigravity-gemini-4-argon",
                "antigravity-claude-sonnet-5-5",
                "antigravity-claude-opus-5-5",
                "antigravity-claude-opus-4-6",
                "antigravity-claude-sonnet-4-6",
                "antigravity-gemini-3.8-flash"
            ]:
                k = f"google:{m_id}"
                if k not in recent_keys:
                    data["recent"].insert(0, {"providerID": "google", "modelID": m_id})

        # 4. Clean variant
        if "variant" in data:
            data["variant"] = {k: v for k, v in data["variant"].items() if not is_dep(k)}

        cur.execute("UPDATE state SET value=? WHERE rowid=?", (json.dumps(data), rowid))
        conn.commit()
        conn.close()
        print("[Desktop Fix] OpenCode Desktop models visibility updated: Claude Opus/Sonnet and Gemini active.")
    except Exception as e:
        print(f"[Desktop Fix] Error updating models: {e}")

if __name__ == "__main__":
    fix_models_visibility()
