"""Nova configuration and settings."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NovaSettings:
    # Vertex AI
    project: str = "your-gcp-project-id"
    location: str = "us-central1"
    model: str = "gemini-2.5-pro"

    # Agent behavior
    max_context_tokens: int = 900_000
    max_output_tokens: int = 65_536
    temperature: float = 0.2
    max_retries: int = 3
    streaming: bool = True

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
    compaction_threshold: float = 0.75  # compact at 75% of max tokens

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
