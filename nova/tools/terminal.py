"""Terminal execution with safety controls and streaming output."""
import subprocess
import signal
import os
from pathlib import Path


class CommandRunner:
    """Executes shell commands with safety rails and timeout management."""

    def __init__(self, working_dir: str = "."):
        self.working_dir = Path(working_dir).resolve()
        self._processes: list[subprocess.Popen] = []

    def execute(self, command: str, timeout: int = 120) -> str:
        """Executes a command and returns combined output. Timeout in seconds."""
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
        return f"Working directory changed to: {new_dir}"

    def kill_all(self) -> None:
        """Kills all running processes."""
        for proc in self._processes[:]:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
