"""Rich terminal UI for Acorn — colored output, markdown rendering, and spinners."""
import re
import sys
import time
import threading


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    STRIKETHROUGH = "\033[9m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    BG_DARK = "\033[48;5;236m"
    BG_CODE = "\033[48;5;238m"


class MarkdownRenderer:
    """Converts markdown text to ANSI-formatted terminal output."""

    @staticmethod
    def render(text: str) -> str:
        """Converts markdown formatting to ANSI escape codes."""
        lines = text.split('\n')
        rendered_lines = []
        in_code_block = False
        code_block_lines = []

        for line in lines:
            # Code blocks (```)
            if line.strip().startswith('```'):
                if in_code_block:
                    # End code block
                    rendered_lines.append(f"  {Colors.DIM}┌{'─' * 50}")
                    for cl in code_block_lines:
                        rendered_lines.append(f"  │ {Colors.GREEN}{cl}{Colors.RESET}")
                    rendered_lines.append(f"  └{'─' * 50}{Colors.RESET}")
                    code_block_lines = []
                    in_code_block = False
                else:
                    in_code_block = True
                continue

            if in_code_block:
                code_block_lines.append(line)
                continue

            # Headers
            if line.startswith('### '):
                rendered_lines.append(f"{Colors.CYAN}{Colors.BOLD}   {line[4:]}{Colors.RESET}")
                continue
            elif line.startswith('## '):
                rendered_lines.append(f"{Colors.CYAN}{Colors.BOLD}  {line[3:]}{Colors.RESET}")
                continue
            elif line.startswith('# '):
                rendered_lines.append(f"{Colors.CYAN}{Colors.BOLD}{line[2:]}{Colors.RESET}")
                continue

            # Bullet points
            if line.strip().startswith('* ') or line.strip().startswith('- '):
                indent = len(line) - len(line.lstrip())
                content = line.strip()[2:]
                content = MarkdownRenderer._inline_format(content)
                rendered_lines.append(f"{' ' * indent}  • {content}")
                continue

            # Numbered lists
            numbered = re.match(r'^(\s*)\d+\.\s+(.*)', line)
            if numbered:
                indent = numbered.group(1)
                content = MarkdownRenderer._inline_format(numbered.group(2))
                rendered_lines.append(f"{indent}  {content}")
                continue

            # Normal text with inline formatting
            rendered_lines.append(MarkdownRenderer._inline_format(line))

        # Handle unclosed code block
        if in_code_block and code_block_lines:
            rendered_lines.append(f"  {Colors.DIM}┌{'─' * 50}")
            for cl in code_block_lines:
                rendered_lines.append(f"  │ {Colors.GREEN}{cl}{Colors.RESET}")
            rendered_lines.append(f"  └{'─' * 50}{Colors.RESET}")

        return '\n'.join(rendered_lines)

    @staticmethod
    def _inline_format(text: str) -> str:
        """Handles inline markdown: bold, italic, code, links."""
        # Inline code `text`
        text = re.sub(r'`([^`]+)`', f'{Colors.BG_CODE}{Colors.GREEN} \\1 {Colors.RESET}', text)
        # Bold **text**
        text = re.sub(r'\*\*([^*]+)\*\*', f'{Colors.BOLD}\\1{Colors.RESET}', text)
        # Bold __text__
        text = re.sub(r'__([^_]+)__', f'{Colors.BOLD}\\1{Colors.RESET}', text)
        # Italic *text*
        text = re.sub(r'\*([^*]+)\*', f'{Colors.ITALIC}\\1{Colors.RESET}', text)
        # Italic _text_
        text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', f'{Colors.ITALIC}\\1{Colors.RESET}', text)
        # Links [text](url) — show text underlined
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', f'{Colors.UNDERLINE}{Colors.CYAN}\\1{Colors.RESET}', text)
        return text


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
        sys.stdout.write("\r\033[K")
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
    """Handles all terminal output formatting with markdown rendering."""

    def __init__(self):
        self.md = MarkdownRenderer()

    def banner(self):
        # Gradient: pale tan → warm brown → reddish-brown → dark
        TAN = "\033[38;2;210;180;140m"
        BROWN = "\033[38;2;180;120;60m"
        DBROWN = "\033[38;2;139;69;19m"
        RBROWN = "\033[38;2;120;40;20m"
        DARK = "\033[38;2;60;20;10m"
        R = Colors.RESET

        print(f"""
{TAN}     █████╗  {BROWN}██████╗ {DBROWN}██████╗ {RBROWN}██████╗ {DARK}███╗   ██╗
{TAN}    ██╔══██╗{BROWN}██╔════╝{DBROWN}██╔═══██╗{RBROWN}██╔══██╗{DARK}████╗  ██║
{TAN}    ███████║{BROWN}██║     {DBROWN}██║   ██║{RBROWN}██████╔╝{DARK}██╔██╗ ██║
{TAN}    ██╔══██║{BROWN}██║     {DBROWN}██║   ██║{RBROWN}██╔══██╗{DARK}██║╚██╗██║
{TAN}    ██║  ██║{BROWN}╚██████╗{DBROWN}╚██████╔╝{RBROWN}██║  ██║{DARK}██║ ╚████║
{TAN}    ╚═╝  ╚═╝{BROWN} ╚═════╝{DBROWN} ╚═════╝ {RBROWN}╚═╝  ╚═╝{DARK}╚═╝  ╚═══╝{R}
{Colors.DIM}    ─────────────────────────────────────────────
    Autonomous Coding Agent · v2.0
    Powered by Vertex AI · Streaming · Smart Routing
    ─────────────────────────────────────────────{R}
""")

    def user_prompt(self) -> str:
        try:
            return input(f"\n{Colors.GREEN}{Colors.BOLD}You ▶{Colors.RESET} ")
        except (EOFError, KeyboardInterrupt):
            return "exit"

    def nova_response(self, text: str):
        """Renders Nova's response with full markdown formatting."""
        rendered = self.md.render(text)
        print(f"\n{Colors.BLUE}{Colors.BOLD}Acorn:{Colors.RESET} {rendered}")

    def stream_start(self):
        sys.stdout.write(f"\n{Colors.BLUE}{Colors.BOLD}Acorn:{Colors.RESET} ")
        sys.stdout.flush()

    def stream_chunk(self, text: str):
        sys.stdout.write(text)
        sys.stdout.flush()

    def stream_end(self):
        print()

    def stream_response_formatted(self, full_text: str):
        """After streaming completes, re-render with markdown formatting."""
        # Move cursor up and rewrite with formatting
        # For streaming we show raw first, then this is called to show formatted
        rendered = self.md.render(full_text)
        # Only reformat if there's actual markdown syntax present
        if any(c in full_text for c in ['**', '`', '```', '# ', '* ', '- ']):
            print(f"\n{Colors.DIM}{'─' * 50}{Colors.RESET}")
            print(rendered)

    def tool_call(self, tool_name: str, args_summary: str):
        print(f"\n  {Colors.MAGENTA}⚡ {tool_name}{Colors.RESET}{Colors.DIM} → {args_summary}{Colors.RESET}")

    def tool_result(self, result: str, max_lines: int = 20):
        lines = result.split('\n')
        if len(lines) > max_lines:
            display = '\n'.join(lines[:max_lines])
            print(f"  {Colors.DIM}┌{'─' * 50}")
            for line in display.split('\n'):
                print(f"  │ {line}")
            print(f"  │ ... ({len(lines) - max_lines} more lines)")
            print(f"  └{'─' * 50}{Colors.RESET}")
        else:
            print(f"  {Colors.DIM}┌{'─' * 50}")
            for line in lines:
                print(f"  │ {line}")
            print(f"  └{'─' * 50}{Colors.RESET}")

    def permission_prompt(self, action: str, details: str) -> bool:
        print(f"\n  {Colors.YELLOW}⚠️  Permission required:{Colors.RESET}")
        print(f"  {Colors.YELLOW}   Action: {action}{Colors.RESET}")
        if len(details) > 200:
            details = details[:200] + "..."
        print(f"  {Colors.YELLOW}   Details: {details}{Colors.RESET}")
        try:
            response = input(f"  {Colors.YELLOW}   Allow? [y/N/always]: {Colors.RESET}").strip().lower()
            if response == 'always':
                return True
            return response in ('y', 'yes')
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

    def cost_display(self, stats: dict):
        print(f"  {Colors.DIM}💰 Pro: {stats['pro_calls']} | Flash: {stats['flash_calls']} | {stats['estimated_savings']}{Colors.RESET}")
