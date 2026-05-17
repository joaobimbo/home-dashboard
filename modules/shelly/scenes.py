import json
from pathlib import Path
from uuid import uuid4


class SceneStore:
    def __init__(self, path: str | None = None):
        default_path = Path(__file__).resolve().parent / "scenes.json"
        self._path = Path(path) if path else default_path

    def list_scenes(self):
        return self._load()

    def create_scene(self, name: str, action: str, room: str):
        clean_name = name.strip()
        clean_room = room.strip() or "all"
        if not clean_name:
            return {"ok": False, "error": "Scene name is required"}
        if action not in {"on", "off", "toggle"}:
            return {"ok": False, "error": "Invalid action"}

        scenes = self._load()
        created = {
            "id": str(uuid4())[:8],
            "name": clean_name,
            "action": action,
            "room": clean_room,
        }
        scenes.append(created)
        self._save(scenes)
        return {"ok": True, "scene": created}

    def delete_scene(self, scene_id: str):
        scenes = self._load()
        next_scenes = [scene for scene in scenes if scene.get("id") != scene_id]
        if len(next_scenes) == len(scenes):
            return {"ok": False, "error": "Scene not found"}
        self._save(next_scenes)
        return {"ok": True}

    def get_scene(self, scene_id: str):
        scenes = self._load()
        for scene in scenes:
            if scene.get("id") == scene_id:
                return scene
        return None

    def _load(self):
        if not self._path.exists():
            return []
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, scenes):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(scenes, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
