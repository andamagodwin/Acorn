"""Rich terminal UI for Nova — colored output, spinners, and formatted displays."""
import sys
import time
import threading


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    BG_DARK = "\033[48;5;236m"


class Spinner:
    """Animated thinking spinner."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "Thinking"):
        self.message = message
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join()
        sys.stdout.write("\r\033[K")  # Clear the line
        sys.stdout.flush()

    def _spin(self):
        i = 0
        while self._running:
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r{Colors.CYAN}{frame} {self.message}...{Colors.RESET}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1


class TerminalUI:
    """Handles all terminal output formatting."""

    def banner(self):
        print(f"""
{Colors.CYAN}{Colors.BOLD}╔══════════════════════════════════════════════════╗
║              ✦  N O V A  v1.0  ✦                ║
║        Autonomous Coding Agent                   ║
║        Powered by Vertex AI (Gemini 2.5 Pro)     ║
╚══════════════════════════════════════════════════╝{Colors.RESET}
""")

    def user_prompt(self) -> str:
        try:
            return input(f"\n{Colors.GREEN}{Colors.BOLD}You ▶{Colors.RESET} ")
        except (EOFError, KeyboardInterrupt):
            return "exit"

    def nova_response(self, text: str):
        print(f"\n{Colors.BLUE}{Colors.BOLD}Nova:{Colors.RESET} {text}")

    def stream_start(self):
        sys.stdout.write(f"\n{Colors.BLUE}{Colors.BOLD}Nova:{Colors.RESET} ")
        sys.stdout.flush()

    def stream_chunk(self, text: str):
        sys.stdout.write(text)
        sys.stdout.flush()

    def stream_end(self):
        print()

    def tool_call(self, tool_name: str, args_summary: str):
        print(f"\n  {Colors.MAGENTA}⚡ {tool_name}{Colors.RESET}{Colors.DIM} → {args_summary}{Colors.RESET}")

    def tool_result(self, result: str, max_lines: int = 20):
        lines = result.split('\n')
        if len(lines) > max_lines:
            display = '\n'.join(lines[:max_lines])
            print(f"  {Colors.DIM}┌─────────────────────────────────")
            for line in display.split('\n'):
                print(f"  │ {line}")
            print(f"  │ ... ({len(lines) - max_lines} more lines)")
            print(f"  └─────────────────────────────────{Colors.RESET}")
        else:
            print(f"  {Colors.DIM}┌─────────────────────────────────")
            for line in lines:
                print(f"  │ {line}")
            print(f"  └─────────────────────────────────{Colors.RESET}")

    def permission_prompt(self, action: str, details: str) -> bool:
        print(f"\n  {Colors.YELLOW}⚠️  Permission required:{Colors.RESET}")
        print(f"  {Colors.YELLOW}   Action: {action}{Colors.RESET}")
        print(f"  {Colors.YELLOW}   Details: {details}{Colors.RESET}")
        try:
            response = input(f"  {Colors.YELLOW}   Allow? [y/N/always]: {Colors.RESET}").strip().lower()
            return response in ('y', 'yes', 'always')
        except (EOFError, KeyboardInterrupt):
            return False

    def error(self, message: str):
        print(f"\n  {Colors.RED}✗ Error: {message}{Colors.RESET}")

    def success(self, message: str):
        print(f"\n  {Colors.GREEN}✓ {message}{Colors.RESET}")

    def info(self, message: str):
        print(f"  {Colors.DIM}{message}{Colors.RESET}")

    def plan_display(self, plan_text: str):
        print(f"\n{Colors.CYAN}{plan_text}{Colors.RESET}")

    def divider(self):
        print(f"  {Colors.DIM}{'─' * 50}{Colors.RESET}")
