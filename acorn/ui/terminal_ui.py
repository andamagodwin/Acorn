"""Terminal UI for Acorn — clean, modern output with markdown rendering."""
import re
import sys
import os
import time
import threading


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # Acorn theme colors
    AMBER = "\033[38;2;207;155;54m"
    WARM = "\033[38;2;180;120;60m"
    BROWN = "\033[38;2;139;90;43m"
    DARK_BROWN = "\033[38;2;101;67;33m"

    BG_CODE = "\033[48;5;236m"


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


class MarkdownRenderer:
    """Converts markdown text to ANSI-formatted terminal output."""

    @staticmethod
    def render(text: str) -> str:
        lines = text.split('\n')
        rendered_lines = []
        in_code_block = False
        code_block_lines = []
        code_lang = ""

        for line in lines:
            if line.strip().startswith('```'):
                if in_code_block:
                    width = min(60, _term_width() - 6)
                    rendered_lines.append(f"  {Colors.DIM}{Colors.CYAN}{'─' * width}{Colors.RESET}")
                    for cl in code_block_lines:
                        rendered_lines.append(f"  {Colors.GREEN}{cl}{Colors.RESET}")
                    rendered_lines.append(f"  {Colors.DIM}{Colors.CYAN}{'─' * width}{Colors.RESET}")
                    code_block_lines = []
                    code_lang = ""
                    in_code_block = False
                else:
                    code_lang = line.strip()[3:]
                    in_code_block = True
                continue

            if in_code_block:
                code_block_lines.append(line)
                continue

            if line.startswith('### '):
                rendered_lines.append(f"  {Colors.BOLD}{Colors.AMBER}{line[4:]}{Colors.RESET}")
                continue
            elif line.startswith('## '):
                rendered_lines.append(f"  {Colors.BOLD}{Colors.AMBER}{line[3:]}{Colors.RESET}")
                continue
            elif line.startswith('# '):
                rendered_lines.append(f"  {Colors.BOLD}{Colors.AMBER}{line[2:]}{Colors.RESET}")
                continue

            if line.strip().startswith('* ') or line.strip().startswith('- '):
                indent = len(line) - len(line.lstrip())
                content = line.strip()[2:]
                content = MarkdownRenderer._inline_format(content)
                rendered_lines.append(f"  {' ' * indent}{Colors.AMBER}>{Colors.RESET} {content}")
                continue

            numbered = re.match(r'^(\s*)\d+\.\s+(.*)', line)
            if numbered:
                indent = numbered.group(1)
                content = MarkdownRenderer._inline_format(numbered.group(2))
                rendered_lines.append(f"  {indent}{content}")
                continue

            rendered_lines.append(f"  {MarkdownRenderer._inline_format(line)}")

        if in_code_block and code_block_lines:
            width = min(60, _term_width() - 6)
            rendered_lines.append(f"  {Colors.DIM}{Colors.CYAN}{'─' * width}{Colors.RESET}")
            for cl in code_block_lines:
                rendered_lines.append(f"  {Colors.GREEN}{cl}{Colors.RESET}")
            rendered_lines.append(f"  {Colors.DIM}{Colors.CYAN}{'─' * width}{Colors.RESET}")

        return '\n'.join(rendered_lines)

    @staticmethod
    def _inline_format(text: str) -> str:
        text = re.sub(r'`([^`]+)`', f'{Colors.BG_CODE}{Colors.GREEN} \\1 {Colors.RESET}', text)
        text = re.sub(r'\*\*([^*]+)\*\*', f'{Colors.BOLD}\\1{Colors.RESET}', text)
        text = re.sub(r'__([^_]+)__', f'{Colors.BOLD}\\1{Colors.RESET}', text)
        text = re.sub(r'\*([^*]+)\*', f'{Colors.ITALIC}\\1{Colors.RESET}', text)
        text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', f'{Colors.ITALIC}\\1{Colors.RESET}', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', f'{Colors.UNDERLINE}{Colors.CYAN}\\1{Colors.RESET}', text)
        return text


class Spinner:
    """Animated thinking spinner."""

    FRAMES = ["    ", ".   ", "..  ", "... ", "....", " ...", "  ..", "   ."]

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
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _spin(self):
        i = 0
        while self._running:
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r  {Colors.DIM}{self.message}{frame}{Colors.RESET}")
            sys.stdout.flush()
            time.sleep(0.15)
            i += 1


class TerminalUI:
    """Handles all terminal output formatting."""

    def __init__(self):
        self.md = MarkdownRenderer()

    def banner(self):
        width = min(56, _term_width() - 4)
        C1 = Colors.AMBER
        C2 = Colors.WARM
        C3 = Colors.BROWN
        C4 = Colors.DARK_BROWN
        R = Colors.RESET
        DIM = Colors.DIM

        print()
        print(f"  {C1}{'=' * width}{R}")
        print()
        print(f"  {C2}   █████╗  ██████╗ ██████╗ ██████╗ ███╗   ██╗{R}")
        print(f"  {C2}  ██╔══██╗██╔════╝██╔═══██╗██╔══██╗████╗  ██║{R}")
        print(f"  {C3}  ███████║██║     ██║   ██║██████╔╝██╔██╗ ██║{R}")
        print(f"  {C3}  ██╔══██║██║     ██║   ██║██╔══██╗██║╚██╗██║{R}")
        print(f"  {C4}  ██║  ██║╚██████╗╚██████╔╝██║  ██║██║ ╚████║{R}")
        print(f"  {C4}  ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝{R}")
        print()
        print(f"  {DIM}  Autonomous Coding Agent v2.0{R}")
        print(f"  {DIM}  Powered by Vertex AI | Streaming | Smart Routing{R}")
        print()
        print(f"  {C1}{'=' * width}{R}")
        print()

    def user_prompt(self) -> str:
        try:
            return input(f"  {Colors.AMBER}{Colors.BOLD}>{Colors.RESET} ")
        except (EOFError, KeyboardInterrupt):
            return "exit"

    def acorn_response(self, text: str):
        """Renders Acorn's response with full markdown formatting."""
        rendered = self.md.render(text)
        print(f"\n  {Colors.BROWN}{Colors.BOLD}Acorn{Colors.RESET}")
        print(rendered)

    def stream_start(self):
        print(f"\n  {Colors.BROWN}{Colors.BOLD}Acorn{Colors.RESET}")
        sys.stdout.write("  ")
        sys.stdout.flush()

    def stream_chunk(self, text: str):
        sys.stdout.write(text)
        sys.stdout.flush()

    def stream_end(self):
        print()

    def stream_response_formatted(self, full_text: str):
        """After streaming, show formatted version if markdown is present."""
        if any(c in full_text for c in ['**', '`', '```', '# ', '* ', '- ']):
            rendered = self.md.render(full_text)
            print(f"\n{rendered}")

    def tool_call(self, tool_name: str, args_summary: str):
        print(f"\n  {Colors.CYAN}{tool_name}{Colors.RESET} {Colors.DIM}{args_summary}{Colors.RESET}")

    def tool_result(self, result: str, max_lines: int = 15):
        lines = result.split('\n')
        if len(lines) > max_lines:
            display_lines = lines[:max_lines]
            for line in display_lines:
                print(f"  {Colors.DIM}{line}{Colors.RESET}")
            print(f"  {Colors.DIM}... +{len(lines) - max_lines} lines{Colors.RESET}")
        else:
            for line in lines:
                print(f"  {Colors.DIM}{line}{Colors.RESET}")

    def permission_prompt(self, action: str, details: str) -> bool:
        print(f"\n  {Colors.YELLOW}Permission needed: {action}{Colors.RESET}")
        if len(details) > 120:
            details = details[:120] + "..."
        print(f"  {Colors.DIM}{details}{Colors.RESET}")
        try:
            response = input(f"  {Colors.YELLOW}Allow? [y/N/always]: {Colors.RESET}").strip().lower()
            if response == 'always':
                return True
            return response in ('y', 'yes')
        except (EOFError, KeyboardInterrupt):
            return False

    def error(self, message: str):
        print(f"  {Colors.RED}Error: {message}{Colors.RESET}")

    def success(self, message: str):
        print(f"  {Colors.GREEN}{message}{Colors.RESET}")

    def info(self, message: str):
        print(f"  {Colors.DIM}{message}{Colors.RESET}")

    def plan_display(self, plan_text: str):
        print(f"\n{Colors.CYAN}{plan_text}{Colors.RESET}")

    def divider(self):
        width = min(56, _term_width() - 4)
        print(f"  {Colors.DIM}{'─' * width}{Colors.RESET}")

    def show_help(self):
        C = Colors.AMBER
        R = Colors.RESET
        D = Colors.DIM
        print(f"""
  {C}Commands{R}
  {D}{'─' * 40}{R}
  {C}/model <name>{R}  Change model (or list models)
  {C}/status{R}       Show session stats
  {C}/plan{R}         Show current plan
  {C}/undo{R}         Revert last file change
  {C}/clear{R}        Clear context and session
  {C}/sessions{R}     List saved sessions
  {C}/routing on|off{R}  Toggle smart routing
  {C}/exit{R}         Quit
""")

    def show_status(self, stats: dict):
        C = Colors.AMBER
        R = Colors.RESET
        D = Colors.DIM
        print(f"""
  {C}Status{R}
  {D}{'─' * 40}{R}
  Context:     ~{stats['tokens']:,} tokens ({stats['messages']} messages)
  Compactions: {stats['compactions']}
  Pro model:   {stats['pro_model']}
  Flash model: {stats['flash_model']}
  Routing:     Pro={stats['routing']['pro_calls']} Flash={stats['routing']['flash_calls']}
  Undo stack:  {stats['backups']} backups
""")

    def show_models(self, available: dict, current_pro: str, current_flash: str):
        C = Colors.AMBER
        G = Colors.GREEN
        R = Colors.RESET
        D = Colors.DIM
        print(f"\n  {C}Available Models{R}")
        print(f"  {D}{'─' * 50}{R}")
        for model_id, desc in available.items():
            marker = ""
            if model_id == current_pro:
                marker = f" {G}(active: pro){R}"
            elif model_id == current_flash:
                marker = f" {G}(active: flash){R}"
            print(f"  {Colors.CYAN}{model_id:<32}{R}{D}{desc}{R}{marker}")
        print(f"\n  {D}Use: /model <name> to switch{R}\n")

    def cost_display(self, stats: dict):
        print(f"  {Colors.DIM}Pro: {stats['pro_calls']} | Flash: {stats['flash_calls']} | {stats['estimated_savings']}{Colors.RESET}")
