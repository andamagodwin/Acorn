"""A persistent shell session so state carries across commands.

One-shot `subprocess.run` per command throws away everything the command did to
its environment: `cd`, `export`, `source venv/bin/activate`, and `nvm use` all
evaporate the moment the process exits. That forces the agent into brittle
one-liners like `cd foo && source venv/bin/activate && pytest` repeated on every
call.

This keeps a single long-lived shell open and feeds commands to its stdin. To
know when a command has finished, we write a unique sentinel after it and read
until that sentinel comes back, which also carries the exit code.
"""
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path


IS_WINDOWS = os.name == "nt"

# Commands that would strand the shell waiting on input it will never get.
# The sentinel would never come back and we'd burn the whole timeout.
INTERACTIVE_HINTS = (
    "vim", "vi ", "nano", "emacs", "less", "more ", "man ",
    "top", "htop", "watch ", "tail -f", "ssh ", "ftp",
    "python\n", "python3\n", "node\n", "irb", "psql", "mysql",
)

# Prelude that makes output deterministic and stops the shell from decorating it.
SHELL_PRELUDE = r"""
export TERM=dumb
export NO_COLOR=1
export CLICOLOR=0
export PS1=
export PS2=
export PAGER=cat
export GIT_PAGER=cat
export DEBIAN_FRONTEND=noninteractive
set +m
unset HISTFILE
# Survive the SIGINT we send to interrupt a timed-out command. A trap bound to a
# command (rather than '') is reset to default in child processes, so the child
# still dies while this shell keeps its state and its place in the input stream.
trap ':' INT
"""


class ShellDied(RuntimeError):
    """Raised when the underlying shell process is gone and can't be used."""


class PersistentShell:
    """A single long-lived shell whose state persists between commands."""

    def __init__(self, working_dir: str = ".", shell_path: str | None = None):
        self.working_dir = str(Path(working_dir).resolve())
        self.shell_path = shell_path or self._detect_shell()
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._sentinel = f"__ACORN_{uuid.uuid4().hex[:12]}__"
        self._lock = threading.Lock()
        self.restart_count = 0

    @staticmethod
    def _detect_shell() -> str:
        if IS_WINDOWS:
            return os.environ.get("COMSPEC", "cmd.exe")
        for candidate in (os.environ.get("SHELL"), "/bin/bash", "/bin/zsh", "/bin/sh"):
            if candidate and Path(candidate).exists():
                return candidate
        return "/bin/sh"

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Boots the shell. Safe to call when already running."""
        if self.is_alive:
            return

        self._queue = queue.Queue()
        self._proc = subprocess.Popen(
            [self.shell_path],
            cwd=self.working_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
            # Own process group, so a timeout can interrupt the running command
            # without taking down the shell itself.
            preexec_fn=os.setsid if not IS_WINDOWS else None,
        )

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        if not IS_WINDOWS:
            self._write(SHELL_PRELUDE)
            # Drain the prelude's output so it can't leak into the first command.
            self._run_raw("true", timeout=10)

    def _read_loop(self) -> None:
        """Pumps shell stdout onto a queue so reads can honour a deadline."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in iter(proc.stdout.readline, ""):
                self._queue.put(line)
        except (ValueError, OSError):
            pass
        finally:
            self._queue.put(None)  # EOF marker

    def _write(self, text: str) -> None:
        if not self.is_alive or self._proc.stdin is None:
            raise ShellDied("Shell is not running")
        try:
            self._proc.stdin.write(text if text.endswith("\n") else text + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise ShellDied(f"Shell stdin closed: {e}") from e

    def execute(self, command: str, timeout: int = 120) -> str:
        """Runs a command in the persistent shell and returns its output."""
        with self._lock:
            hint = self._interactive_hint(command)
            if hint:
                return (
                    f"Error: '{hint.strip()}' looks like an interactive program, which would "
                    f"hang this shell. Run it with flags that make it non-interactive, or use "
                    f"a non-interactive equivalent."
                )

            if not self.is_alive:
                self.start()

            try:
                return self._run_raw(command, timeout)
            except ShellDied:
                # Shell fell over; bring up a fresh one so the next call works.
                self.restart_count += 1
                self._teardown()
                self.start()
                return (
                    "Error: The persistent shell died and was restarted. "
                    "Shell state (cd, exports, activated venvs) was lost."
                )

    def _run_raw(self, command: str, timeout: int) -> str:
        """Writes a command plus sentinel, then reads back to the sentinel."""
        self._drain()

        self._write(command)
        # Leading \n terminates any partial line the command left behind, so the
        # sentinel always lands at the start of a line we can match.
        self._write(f'printf "\\n%s %s\\n" "{self._sentinel}" "$?"')

        lines, exit_code, timed_out = self._read_until_sentinel(timeout)

        if timed_out:
            recovered = self._interrupt_and_resync(lines)
            partial = "".join(lines).strip()
            note = ""
            if not recovered:
                # Wedged beyond rescue — rebuild so the next command isn't
                # reading leftovers from this one.
                self.restart_count += 1
                self._teardown()
                self.start()
                note = "\n[Shell did not recover and was restarted — shell state was lost]"
            return (
                f"[Command timed out after {timeout}s and was interrupted]\n"
                f"{self._truncate(partial) if partial else '(no output)'}{note}"
            )

        output = "".join(lines).strip() or "(no output)"
        return f"{self._truncate(output)}\n[exit code: {exit_code}]"

    def _read_until_sentinel(self, timeout: float, lines: list | None = None):
        """Reads output until the sentinel line. Returns (lines, exit_code, timed_out)."""
        lines = lines if lines is not None else []
        exit_code = "?"
        start = time.monotonic()

        while True:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                return lines, exit_code, True
            try:
                line = self._queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue

            if line is None:
                raise ShellDied("Shell closed its output stream")

            if self._sentinel in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    exit_code = parts[-1]
                return lines, exit_code, False

            lines.append(line)
            if len(lines) > 20_000:
                del lines[:10_000]

    def _interrupt_and_resync(self, lines: list) -> bool:
        """Kills the running command, then waits for the sentinel to come back.

        The sentinel `printf` was already written to the shell's stdin, so once
        the interrupted command exits the shell reads and runs it. Waiting for
        it is what keeps our reads aligned with the shell's output for the next
        command; giving up here would leave stale output in the queue.
        """
        if IS_WINDOWS or not self.is_alive:
            return False
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGINT)
        except (ProcessLookupError, OSError):
            return False

        try:
            _, _, still_stuck = self._read_until_sentinel(5.0, lines)
        except ShellDied:
            return False
        return not still_stuck

    def _drain(self) -> None:
        """Throws away anything buffered from a previous command."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if item is None:
                raise ShellDied("Shell closed its output stream")

    @staticmethod
    def _interactive_hint(command: str) -> str | None:
        stripped = command.strip()
        probe = stripped + "\n"
        for hint in INTERACTIVE_HINTS:
            if probe.startswith(hint) or f"| {hint}" in probe:
                return hint
        return None

    @staticmethod
    def _truncate(text: str, limit: int = 50_000) -> str:
        if len(text) <= limit:
            return text
        half = limit // 2
        return f"{text[:half]}\n\n... [truncated {len(text) - limit} chars] ...\n\n{text[-half:]}"

    def cwd(self) -> str:
        """Asks the shell where it actually is — it may have been `cd`'d."""
        if not self.is_alive:
            return self.working_dir
        try:
            with self._lock:
                result = self._run_raw("pwd", timeout=5)
            return result.split("\n[exit code:")[0].strip() or self.working_dir
        except (ShellDied, Exception):
            return self.working_dir

    def reset(self) -> str:
        """Tears down and restarts, clearing all accumulated shell state."""
        with self._lock:
            self._teardown()
            self.start()
        return "Shell session reset — cwd, exports, and venv activation cleared."

    def _teardown(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            if not IS_WINDOWS:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass

    def close(self) -> None:
        with self._lock:
            self._teardown()
