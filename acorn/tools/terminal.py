"""Terminal execution with safety controls and streaming output."""
import subprocess
import signal
import os
from pathlib import Path

from acorn.tools.shell import PersistentShell


class CommandRunner:
    """Executes shell commands with safety rails and timeout management.

    In persistent mode commands run in one long-lived shell, so `cd`, `export`,
    and `source venv/bin/activate` carry over to later commands. One-shot mode
    runs each command in its own process and is the safer fallback.
    """

    def __init__(self, working_dir: str = ".", persistent: bool = True):
        self.working_dir = Path(working_dir).resolve()
        self._processes: list[subprocess.Popen] = []
        self.persistent = persistent
        self._shell: PersistentShell | None = None

    @property
    def shell(self) -> PersistentShell:
        """The persistent shell, started lazily on first use."""
        if self._shell is None:
            self._shell = PersistentShell(str(self.working_dir))
            self._shell.start()
        return self._shell

    def execute(self, command: str, timeout: int = 120) -> str:
        """Runs a command, using the persistent shell when enabled."""
        if self.persistent:
            return self.shell.execute(command, timeout=timeout)
        return self.execute_once(command, timeout=timeout)

    def reset_shell(self) -> str:
        """Clears accumulated shell state (cwd, exports, venv)."""
        if self._shell is None:
            return "No shell session to reset."
        return self._shell.reset()

    def current_dir(self) -> str:
        """Where commands will actually run — the shell may have been `cd`'d."""
        if self.persistent and self._shell is not None:
            return self._shell.cwd()
        return str(self.working_dir)

    def execute_once(self, command: str, timeout: int = 120) -> str:
        """Executes a command in its own process. Timeout in seconds."""
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(self.working_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )
            self._processes.append(process)

            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                return f"[Command timed out after {timeout}s]\nPartial stdout:\n{stdout}\nStderr:\n{stderr}"
            finally:
                self._processes.remove(process)

            output_parts = []
            if stdout.strip():
                output_parts.append(stdout.strip())
            if stderr.strip():
                output_parts.append(f"[stderr]:\n{stderr.strip()}")

            exit_info = f"[exit code: {process.returncode}]"
            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long output
            if len(result) > 50_000:
                result = result[:25_000] + "\n\n... [truncated] ...\n\n" + result[-25_000:]

            return f"{result}\n{exit_info}"

        except FileNotFoundError:
            return f"Error: Command not found or invalid shell command: {command}"
        except Exception as e:
            return f"Error executing command: {e}"

    def execute_streaming(self, command: str, callback=None, timeout: int = 120) -> str:
        """Executes a command with real-time output streaming via callback."""
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(self.working_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )
            self._processes.append(process)

            output_lines = []
            try:
                for line in iter(process.stdout.readline, ''):
                    output_lines.append(line)
                    if callback:
                        callback(line)
                    if len(output_lines) > 10_000:
                        output_lines = output_lines[-5_000:]

                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
                output_lines.append(f"\n[Command timed out after {timeout}s]")
            finally:
                self._processes.remove(process)

            result = "".join(output_lines).strip()
            if len(result) > 50_000:
                result = result[:25_000] + "\n\n... [truncated] ...\n\n" + result[-25_000:]

            return f"{result}\n[exit code: {process.returncode}]"

        except Exception as e:
            return f"Error executing command: {e}"

    def set_working_dir(self, path: str) -> str:
        """Changes the working directory for future commands."""
        new_dir = Path(path).resolve()
        if not new_dir.exists():
            return f"Error: Directory not found: {path}"
        if not new_dir.is_dir():
            return f"Error: Not a directory: {path}"
        self.working_dir = new_dir
        # Keep the persistent shell in step, otherwise it would keep running
        # commands in the old directory.
        if self._shell is not None and self._shell.is_alive:
            self._shell.execute(f'cd "{new_dir}"', timeout=10)
        return f"Working directory changed to: {new_dir}"

    def kill_all(self) -> None:
        """Kills all running processes."""
        for proc in self._processes[:]:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

    def close(self) -> None:
        """Shuts down the persistent shell, if one was started."""
        if self._shell is not None:
            self._shell.close()
            self._shell = None
