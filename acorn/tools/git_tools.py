"""Git-aware tools for project understanding and version control."""
import subprocess
from pathlib import Path


class GitTools:
    """Provides git operations for project-aware behavior."""

    def __init__(self, working_dir: str = "."):
        self.working_dir = Path(working_dir).resolve()

    def _run(self, cmd: str) -> str:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=str(self.working_dir), timeout=30
            )
            return result.stdout.strip() or result.stderr.strip()
        except Exception as e:
            return f"Error: {e}"

    @property
    def is_repo(self) -> bool:
        result = self._run("git rev-parse --is-inside-work-tree")
        return result == "true"

    def status(self) -> str:
        """Returns git status summary."""
        return self._run("git status --short --branch")

    def diff(self, staged: bool = False) -> str:
        """Returns diff of changes."""
        cmd = "git diff --staged" if staged else "git diff"
        diff = self._run(cmd)
        if len(diff) > 30_000:
            diff = diff[:15_000] + "\n\n... [diff truncated] ...\n\n" + diff[-15_000:]
        return diff or "(no changes)"

    def log(self, count: int = 10) -> str:
        """Returns recent commit log."""
        return self._run(f"git log --oneline --no-decorate -n {count}")

    def current_branch(self) -> str:
        """Returns current branch name."""
        return self._run("git branch --show-current")

    def project_summary(self) -> str:
        """Generates a project summary from git and file structure."""
        parts = []

        if self.is_repo:
            parts.append(f"Branch: {self.current_branch()}")
            parts.append(f"Recent commits:\n{self.log(5)}")
            status = self.status()
            if status:
                parts.append(f"Status:\n{status}")

        # File structure overview
        tree = self._run("find . -type f -not -path './.git/*' -not -path './node_modules/*' -not -path './__pycache__/*' -not -path './venv/*' -not -path './.venv/*' | head -100")
        if tree:
            parts.append(f"Files:\n{tree}")

        return "\n\n".join(parts) if parts else "Not a git repository."
