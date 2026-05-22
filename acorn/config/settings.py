"""Acorn configuration and settings."""
import os
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path


VERSION = "2.2.0"

ACORN_HOME = Path.home() / ".acorn"
SESSIONS_DIR = ACORN_HOME / "sessions"


def check_for_updates(callback=None):
    """Checks PyPI for a newer version (runs in background thread)."""
    def _check():
        try:
            import urllib.request
            url = "https://pypi.org/pypi/acorn-agent/json"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                latest = data["info"]["version"]
                if latest != VERSION:
                    if callback:
                        callback(latest)
        except Exception:
            pass

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()

AVAILABLE_MODELS = {
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro — most powerful agentic model (default pro)",
    "gemini-3.1-pro-preview-customtools": "Gemini 3.1 Pro Custom Tools — optimized for custom tool use",
    "gemini-3-flash-preview": "Gemini 3 Flash — enhanced multimodal and coding (default flash)",
    "gemini-2.5-pro": "Gemini 2.5 Pro — strong coding and world knowledge (GA)",
    "gemini-2.5-flash": "Gemini 2.5 Flash — fast, balanced reasoning (GA)",
}


def _get_api_key() -> str:
    """Reads Gemini API key from env var or config."""
    env_val = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if env_val:
        return env_val

    config_file = ACORN_HOME / "config.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text())
            if "api_key" in data:
                return data["api_key"]
        except (json.JSONDecodeError, KeyError):
            pass

    return ""


def _get_project_id() -> str:
    """Reads GCP project ID from env var, falling back to ~/.acorn/config."""
    env_val = os.environ.get("ACORN_PROJECT") or os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if env_val:
        return env_val

    config_file = ACORN_HOME / "config.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text())
            if "project" in data:
                return data["project"]
        except (json.JSONDecodeError, KeyError):
            pass

    return ""


@dataclass
class AcornSettings:
    # Authentication — API key (simple) or Vertex AI (enterprise)
    api_key: str = field(default_factory=_get_api_key)
    project: str = field(default_factory=_get_project_id)
    location: str = "global"
    use_vertex: bool = False  # set in __post_init__ based on what's available
    model: str = "gemini-3.1-pro-preview"
    flash_model: str = "gemini-3-flash-preview"

    # Smart routing
    use_smart_routing: bool = True
    routing_threshold: int = 200

    # Agent behavior
    max_context_tokens: int = 900_000
    max_output_tokens: int = 65_536
    temperature: float = 0.2
    max_retries: int = 3
    streaming: bool = True

    # Auto-retry
    auto_retry_on_error: bool = True
    max_auto_retries: int = 3

    # Session persistence
    persist_sessions: bool = True

    # Permission tiers: "safe" auto-approves, "ask" prompts, "deny" blocks
    permission_rules: dict = field(default_factory=lambda: {
        "read_file": "safe",
        "list_directory": "safe",
        "search_files": "safe",
        "write_file": "ask",
        "edit_file": "ask",
        "execute_command": "ask",
        "delete_file": "deny",
    })

    # Commands that are always safe to auto-run
    safe_commands: list = field(default_factory=lambda: [
        "ls", "cat", "head", "tail", "find", "grep", "wc",
        "git status", "git log", "git diff", "git branch",
        "python --version", "node --version", "npm --version",
        "pwd", "echo", "which", "type", "file",
    ])

    # Commands that are always blocked
    blocked_commands: list = field(default_factory=lambda: [
        "rm -rf /", "rm -rf ~", "mkfs", "dd if=",
        ":(){:|:&};:", "chmod -R 777 /",
        "curl | sh", "wget | sh",
    ])

    # Working directory
    working_dir: str = field(default_factory=lambda: os.getcwd())

    # Context management
    compaction_threshold: float = 0.75

    def __post_init__(self):
        ACORN_HOME.mkdir(parents=True, exist_ok=True)
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        # Decide auth mode: API key is simpler, Vertex AI for enterprise
        if self.api_key:
            self.use_vertex = False
        elif self.project:
            self.use_vertex = True
        # Load project instructions if available
        self.project_instructions = self._load_project_instructions()

    def is_command_safe(self, command: str) -> bool:
        cmd_lower = command.strip().lower()
        for blocked in self.blocked_commands:
            if blocked in cmd_lower:
                return False
        for safe in self.safe_commands:
            if cmd_lower.startswith(safe):
                return True
        return False

    def is_command_blocked(self, command: str) -> bool:
        cmd_lower = command.strip().lower()
        return any(blocked in cmd_lower for blocked in self.blocked_commands)

    def should_use_flash(self, message: str) -> bool:
        """Determines if a message is simple enough for Flash model."""
        if not self.use_smart_routing:
            return False
        simple_indicators = [
            len(message) < self.routing_threshold,
            message.strip().endswith("?") and len(message) < 100,
            any(message.strip().lower().startswith(w) for w in [
                "hi", "hello", "hey", "thanks", "what is", "explain",
                "how do i", "what does", "why", "when",
            ]),
        ]
        complex_indicators = [
            "refactor" in message.lower(),
            "across all" in message.lower(),
            "multiple files" in message.lower(),
            "implement" in message.lower() and len(message) > 200,
            "build" in message.lower() and len(message) > 200,
            message.count("\n") > 5,
        ]
        if any(complex_indicators):
            return False
        return any(simple_indicators)

    def save_project_id(self, project_id: str):
        """Saves the project ID to ~/.acorn/config.json for future use."""
        config_file = ACORN_HOME / "config.json"
        data = {}
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
            except json.JSONDecodeError:
                pass
        data["project"] = project_id
        config_file.write_text(json.dumps(data, indent=2))

    def save_api_key(self, api_key: str):
        """Saves the API key to ~/.acorn/config.json for future use."""
        config_file = ACORN_HOME / "config.json"
        data = {}
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
            except json.JSONDecodeError:
                pass
        data["api_key"] = api_key
        config_file.write_text(json.dumps(data, indent=2))

    def _load_project_instructions(self) -> str:
        """Loads .acorn.md from the working directory (or parent dirs) for project context."""
        search_dir = Path(self.working_dir)
        for _ in range(10):
            instructions_file = search_dir / ".acorn.md"
            if instructions_file.exists():
                try:
                    content = instructions_file.read_text(encoding="utf-8")
                    if len(content) > 10_000:
                        content = content[:10_000] + "\n\n[...truncated]"
                    return content
                except Exception:
                    return ""
            parent = search_dir.parent
            if parent == search_dir:
                break
            search_dir = parent
        return ""
