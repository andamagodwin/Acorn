"""Acorn configuration and settings."""
import os
import json
from dataclasses import dataclass, field
from pathlib import Path


ACORN_HOME = Path.home() / ".acorn"
SESSIONS_DIR = ACORN_HOME / "sessions"

AVAILABLE_MODELS = {
    "gemini-2.5-pro": "Gemini 2.5 Pro — best quality, complex tasks",
    "gemini-2.5-flash": "Gemini 2.5 Flash — fast and efficient",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite — most affordable, high-volume agents",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview — next-gen, complex agentic workloads",
    "gemini-3-flash-preview": "Gemini 3 Flash Preview — enhanced multimodal and coding",
}


@dataclass
class AcornSettings:
    # Vertex AI
    project: str = "your-gcp-project-id"
    location: str = "us-central1"
    model: str = "gemini-2.5-pro"
    flash_model: str = "gemini-2.5-flash"

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
