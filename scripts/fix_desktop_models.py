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
        cur.execute("SELECT rowid, value FROM state WHERE key='opencode.global.dat' AND name='model'")
        row = cur.fetchone()
        if not row:
            conn.close()
            return

        rowid, val_str = row
        data = json.loads(val_str)

        # 1. Remove discontinued 3.7 models
        user_models = [m for m in data.get("user", []) if "3.7" not in m.get("modelID", "")]

        # 2. Models that should be immediately visible in the quick dropdown
        to_show = [
            "antigravity-claude-opus-4-6",
            "antigravity-claude-opus-4-6-thinking",
            "antigravity-claude-sonnet-4-6",
            "antigravity-claude-sonnet-4-6-thinking",
            "antigravity-gemini-3.8-flash",
            "antigravity-gemini-3.6-flash",
            "antigravity-gemini-3.1-pro"
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

        # 3. Clean recent & ensure Claude Opus/Sonnet and Gemini 3.8 are at top
        if "recent" in data:
            data["recent"] = [m for m in data["recent"] if "3.7" not in m.get("modelID", "")]
            recent_keys = {f"{m.get('providerID')}:{m.get('modelID')}" for m in data["recent"]}
            for m_id in ["antigravity-claude-opus-4-6", "antigravity-claude-sonnet-4-6", "antigravity-gemini-3.8-flash"]:
                k = f"google:{m_id}"
                if k not in recent_keys:
                    data["recent"].insert(0, {"providerID": "google", "modelID": m_id})

        # 4. Clean variant
        if "variant" in data:
            data["variant"] = {k: v for k, v in data["variant"].items() if "3.7" not in k}

        cur.execute("UPDATE state SET value=? WHERE rowid=?", (json.dumps(data), rowid))
        conn.commit()
        conn.close()
        print("[Desktop Fix] OpenCode Desktop models visibility updated: Claude Opus/Sonnet and Gemini active.")
    except Exception as e:
        print(f"[Desktop Fix] Error updating models: {e}")

if __name__ == "__main__":
    fix_models_visibility()
