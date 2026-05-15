"""Session persistence — save and resume conversations."""
import json
import hashlib
from datetime import datetime
from pathlib import Path

from nova.config.settings import SESSIONS_DIR


class SessionManager:
    """Saves and loads conversation sessions to disk."""

    def __init__(self, working_dir: str):
        self.working_dir = working_dir
        self.session_id = self._generate_session_id()
        self.session_file = SESSIONS_DIR / f"{self.session_id}.json"

    def _generate_session_id(self) -> str:
        """Creates a stable session ID based on the working directory."""
        dir_hash = hashlib.md5(self.working_dir.encode()).hexdigest()[:8]
        dir_name = Path(self.working_dir).name
        return f"{dir_name}_{dir_hash}"

    def save(self, messages: list[dict], metadata: dict = None) -> None:
        """Saves current conversation to disk."""
        data = {
            "session_id": self.session_id,
            "working_dir": self.working_dir,
            "updated_at": datetime.now().isoformat(),
            "messages": messages,
            "metadata": metadata or {},
        }
        self.session_file.write_text(json.dumps(data, indent=2, default=str))

    def load(self) -> list[dict] | None:
        """Loads a previous session if one exists."""
        if not self.session_file.exists():
            return None
        try:
            data = json.loads(self.session_file.read_text())
            return data.get("messages", [])
        except (json.JSONDecodeError, KeyError):
            return None

    def clear(self) -> None:
        """Deletes the session file."""
        if self.session_file.exists():
            self.session_file.unlink()

    def list_sessions(self) -> list[dict]:
        """Lists all saved sessions."""
        sessions = []
        for f in SESSIONS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                sessions.append({
                    "id": data["session_id"],
                    "dir": data["working_dir"],
                    "updated": data["updated_at"],
                    "messages": len(data.get("messages", [])),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(sessions, key=lambda s: s["updated"], reverse=True)

    @property
    def has_previous_session(self) -> bool:
        return self.session_file.exists()
