"""Terminal UI for Acorn — clean, modern output with markdown rendering."""
import re
import sys
import os
import time
import random
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

    # Diff rendering — tinted backgrounds so changed lines read as blocks
    # rather than as punctuation you have to hunt for.
    DIFF_ADD = "\033[38;5;114m"
    DIFF_DEL = "\033[38;5;174m"
    DIFF_ADD_BG = "\033[48;5;22m\033[38;5;157m"
    DIFF_DEL_BG = "\033[48;5;52m\033[38;5;217m"
    DIFF_HUNK = "\033[38;5;110m"
    DIFF_GUTTER = "\033[38;5;240m"


TOOL_VERBS = {
    "read_file": [
        "Peeking at", "Snooping through", "Eyeballing", "Absorbing",
        "Devouring", "Scanning", "Inspecting", "Squinting at",
        "Perusing", "Nosing into", "Leafing through", "Deciphering",
    ],
    "write_file": [
        "Scribbling", "Conjuring", "Manifesting", "Birthing",
        "Crafting", "Forging", "Summoning", "Materializing",
        "Cooking up", "Whipping up", "Spinning up",
    ],
    "edit_file": [
        "Performing surgery on", "Tweaking", "Massaging",
        "Sprinkling magic on", "Rearranging the atoms of",
        "Giving a facelift to", "Polishing", "Tinkering with",
        "Nudging", "Reshuffling", "Fine-tuning",
    ],
    "list_directory": [
        "Rummaging through", "Exploring", "Poking around",
        "Cataloguing", "Taking inventory of", "Scouting",
        "Surveying the land of", "Mapping out",
    ],
    "search_files": [
        "Hunting for clues in", "Spelunking through",
        "Playing detective in", "Digging through",
        "Sifting the sands of", "Excavating",
        "Going on a treasure hunt in", "Combing through",
    ],
    "execute_command": [
        "Unleashing", "Firing off", "Launching",
        "Sending to the shadow realm:", "Whispering to the shell:",
        "Consulting the oracle:", "Dispatching",
        "Pulling the lever on", "Running",
    ],
    "git_status": [
        "Consulting the git gods", "Reading the commit tea leaves",
        "Checking the vibe of the repo", "Peering into git history",
        "Asking git what's up", "Interrogating the repository",
    ],
    "multi_edit": [
        "Juggling multiple files", "Multi-tasking like a champ",
        "Reading the whole bookshelf", "Gathering intel from",
        "Assembling the puzzle pieces", "Speed-reading",
    ],
    "web_search": [
        "Googling", "Scouring the web for", "Asking the internet about",
        "Casting a net for", "Trawling the web for", "Searching for",
        "Consulting the hive mind about",
    ],
    "fetch_url": [
        "Fetching", "Reeling in", "Pulling down", "Grabbing",
        "Downloading", "Reading up on", "Opening",
    ],
}

THINKING_MESSAGES = [
    "Pondering", "Cooking up something", "Brainstorming",
    "Churning the gears", "Consulting the neural pathways",
    "Assembling thoughts", "Marinating on that",
    "Doing some mental gymnastics", "Scheming",
    "Loading brain.exe", "Crunching the vibes",
    "Summoning wisdom", "Connecting the dots",
]


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _get_tool_verb(tool_name: str) -> str:
    # MCP tools arrive as mcp__<server>__<tool>; name the server so it's clear
    # the work is happening outside Acorn.
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            return f"Calling {parts[1]}:{parts[2]}"
    verbs = TOOL_VERBS.get(tool_name, ["Working on", "Processing", "Handling"])
    return random.choice(verbs)


def _inline_format(text: str) -> str:
    """Applies inline markdown (bold, italic, code, links) to a single line."""
    text = re.sub(r'`([^`]+)`', f'{Colors.BG_CODE}{Colors.GREEN} \\1 {Colors.RESET}', text)
    text = re.sub(r'\*\*([^*]+)\*\*', f'{Colors.BOLD}\\1{Colors.RESET}', text)
    text = re.sub(r'__([^_]+)__', f'{Colors.BOLD}\\1{Colors.RESET}', text)
    text = re.sub(r'\*([^*]+)\*', f'{Colors.ITALIC}\\1{Colors.RESET}', text)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', f'{Colors.ITALIC}\\1{Colors.RESET}', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', f'{Colors.UNDERLINE}{Colors.CYAN}\\1{Colors.RESET}', text)
    return text


class StreamingMarkdownRenderer:
    """Renders markdown one complete line at a time.

    Formatting a line needs the whole line — you can't tell `**bold**` from a
    literal asterisk until the closing marker arrives. So output is buffered to
    the newline and rendered then, which is what lets streamed responses come
    out formatted instead of as raw markdown.

    Code fences are emitted as they arrive rather than held until the block
    closes, so a long code block still streams.
    """

    def __init__(self, indent: str = "  "):
        self.indent = indent
        self.reset()

    def reset(self) -> None:
        self._in_code_block = False

    @property
    def in_code_block(self) -> bool:
        return self._in_code_block

    def _border(self) -> str:
        width = min(60, _term_width() - 6)
        return f"{self.indent}{Colors.DIM}{Colors.CYAN}{'─' * width}{Colors.RESET}"

    def feed_line(self, line: str) -> str:
        """Renders one complete line, without a trailing newline."""
        line = line.rstrip('\r')

        if line.strip().startswith('```'):
            self._in_code_block = not self._in_code_block
            return self._border()

        if self._in_code_block:
            return f"{self.indent}{Colors.GREEN}{line}{Colors.RESET}"

        if line.startswith('### '):
            return f"{self.indent}{Colors.BOLD}{Colors.AMBER}{line[4:]}{Colors.RESET}"
        if line.startswith('## '):
            return f"{self.indent}{Colors.BOLD}{Colors.AMBER}{line[3:]}{Colors.RESET}"
        if line.startswith('# '):
            return f"{self.indent}{Colors.BOLD}{Colors.AMBER}{line[2:]}{Colors.RESET}"

        stripped = line.strip()
        if stripped.startswith('* ') or stripped.startswith('- '):
            depth = len(line) - len(line.lstrip())
            content = _inline_format(stripped[2:].lstrip())
            return f"{self.indent}{' ' * depth}{Colors.AMBER}>{Colors.RESET} {content}"

        numbered = re.match(r'^(\s*)(\d+\.)\s+(.*)', line)
        if numbered:
            depth, marker, content = numbered.groups()
            return (
                f"{self.indent}{depth}{Colors.BOLD}{Colors.AMBER}{marker}{Colors.RESET} "
                f"{_inline_format(content)}"
            )

        return f"{self.indent}{_inline_format(line)}"

    def flush(self) -> str:
        """Closes an unterminated code block so the border isn't left dangling."""
        if self._in_code_block:
            self._in_code_block = False
            return self._border()
        return ""


class MarkdownRenderer:
    """Converts markdown text to ANSI-formatted terminal output."""

    @staticmethod
    def render(text: str) -> str:
        # Shares the streaming renderer so both paths format identically.
        renderer = StreamingMarkdownRenderer()
        rendered = [renderer.feed_line(line) for line in text.split('\n')]
        tail = renderer.flush()
        if tail:
            rendered.append(tail)
        return '\n'.join(rendered)

    @staticmethod
    def _inline_format(text: str) -> str:
        return _inline_format(text)


class Spinner:
    """Animated thinking spinner with fun messages."""

    FRAMES = ["    ", ".   ", "..  ", "... ", "....", " ...", "  ..", "   ."]

    def __init__(self, message: str = None):
        self.message = message or random.choice(THINKING_MESSAGES)
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


class ToolSpinner:
    """Brief animated indicator for tool execution."""

    FRAMES = ["|", "/", "-", "\\"]

    def __init__(self, message: str):
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
            sys.stdout.write(f"\r  {Colors.CYAN}{frame}{Colors.RESET} {Colors.DIM}{self.message}{Colors.RESET}")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1


class TerminalUI:
    """Handles all terminal output formatting."""

    def __init__(self):
        self.md = MarkdownRenderer()
        self._stream_renderer = StreamingMarkdownRenderer()
        self._stream_buffer = ""

    def banner(self):
        from acorn.config.settings import VERSION
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
        print(f"  {DIM}  Autonomous Coding Agent v{VERSION}{R}")
        print(f"  {DIM}  Powered by Gemini | Live Streaming | Smart Routing{R}")
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

    def stream_start_live(self):
        """Called when live streaming begins — print the Acorn header."""
        print(f"\n  {Colors.BROWN}{Colors.BOLD}Acorn{Colors.RESET}")
        sys.stdout.flush()
        self._stream_buffer = ""
        self._stream_renderer.reset()

    def stream_chunk_live(self, text: str):
        """Streams text to the terminal, formatting each line as it completes.

        Buffers to the newline because markdown can't be resolved mid-line:
        `**bold**` is indistinguishable from a literal asterisk until its
        closing marker arrives.
        """
        self._stream_buffer += text
        if '\n' not in self._stream_buffer:
            return

        *complete, self._stream_buffer = self._stream_buffer.split('\n')
        for line in complete:
            sys.stdout.write(self._stream_renderer.feed_line(line) + "\n")
        sys.stdout.flush()

    def stream_end_live(self):
        """Finalizes live streaming output."""
        if self._stream_buffer:
            sys.stdout.write(self._stream_renderer.feed_line(self._stream_buffer) + "\n")
            self._stream_buffer = ""
        tail = self._stream_renderer.flush()
        if tail:
            sys.stdout.write(tail + "\n")
        sys.stdout.flush()

    def stream_response_formatted(self, full_text: str):
        """Render the complete response with markdown formatting (used for non-streaming mode)."""
        rendered = self.md.render(full_text)
        print(f"\n  {Colors.BROWN}{Colors.BOLD}Acorn{Colors.RESET}")
        print(rendered)

    def tool_call(self, tool_name: str, args_summary: str):
        """Shows a fun loading message for tool calls."""
        verb = _get_tool_verb(tool_name)
        # Extract the most relevant arg for display
        short_arg = self._extract_short_arg(tool_name, args_summary)
        if short_arg:
            print(f"  {Colors.CYAN}~{Colors.RESET} {Colors.DIM}{verb} {short_arg}{Colors.RESET}")
        else:
            print(f"  {Colors.CYAN}~{Colors.RESET} {Colors.DIM}{verb}...{Colors.RESET}")

    def _extract_short_arg(self, tool_name: str, args_summary: str) -> str:
        """Pulls out the most interesting part of tool args for display."""
        if not args_summary:
            return ""
        # Try to get filepath or command
        if "filepath=" in args_summary:
            match = re.search(r"filepath='([^']*)'", args_summary)
            if match:
                path = match.group(1)
                # Show just filename for brevity
                if '/' in path:
                    return path.split('/')[-1]
                return path
        if "command=" in args_summary:
            match = re.search(r"command='([^']*)'", args_summary)
            if match:
                cmd = match.group(1)
                if len(cmd) > 40:
                    cmd = cmd[:40] + "..."
                return cmd
        if "query=" in args_summary:
            match = re.search(r"query='([^']*)'", args_summary)
            if match:
                return f"'{match.group(1)}'"
        if "path=" in args_summary:
            match = re.search(r"path='([^']*)'", args_summary)
            if match:
                return match.group(1)
        # Fallback: just trim it
        if len(args_summary) > 50:
            return args_summary[:50] + "..."
        return args_summary

    def tool_result(self, result: str, max_lines: int = 10):
        lines = result.split('\n')
        if len(lines) > max_lines:
            display_lines = lines[:max_lines]
            for line in display_lines:
                print(f"    {Colors.DIM}{line}{Colors.RESET}")
            print(f"    {Colors.DIM}... +{len(lines) - max_lines} lines{Colors.RESET}")
        else:
            for line in lines:
                print(f"    {Colors.DIM}{line}{Colors.RESET}")

    def show_diff(self, filepath: str, diff: str, added: int, removed: int,
                  max_lines: int = 40):
        """Renders a unified diff with colors and real line numbers."""
        name = os.path.basename(filepath) or filepath
        stat = f"{Colors.DIFF_ADD}+{added}{Colors.RESET} {Colors.DIFF_DEL}-{removed}{Colors.RESET}"
        print(f"  {Colors.BOLD}{Colors.AMBER}{name}{Colors.RESET}  {stat}")

        if not diff.strip():
            return

        width = min(72, _term_width() - 6)
        print(f"  {Colors.DIM}{'─' * width}{Colors.RESET}")

        old_no = new_no = 0
        shown = 0
        skipped = 0

        for line in diff.splitlines():
            # File headers restate what we already printed above.
            if line.startswith(("--- ", "+++ ")):
                continue

            if line.startswith("@@"):
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
                if match:
                    old_no = int(match.group(1))
                    new_no = int(match.group(2))
                    tail = match.group(3).strip()
                    label = f" {tail}" if tail else ""
                    if shown:
                        print(f"  {Colors.DIM}{'┈' * width}{Colors.RESET}")
                    print(f"  {Colors.DIFF_HUNK}@@{label}{Colors.RESET}")
                continue

            if shown >= max_lines:
                skipped += 1
                continue

            body = line[1:] if line else ""
            body = body.rstrip("\n")

            if line.startswith("+"):
                gutter = f"{new_no:>4}"
                print(f"  {Colors.DIFF_GUTTER}{gutter}{Colors.RESET} {Colors.DIFF_ADD_BG}+ {body}{Colors.RESET}")
                new_no += 1
            elif line.startswith("-"):
                gutter = f"{old_no:>4}"
                print(f"  {Colors.DIFF_GUTTER}{gutter}{Colors.RESET} {Colors.DIFF_DEL_BG}- {body}{Colors.RESET}")
                old_no += 1
            else:
                gutter = f"{new_no:>4}"
                print(f"  {Colors.DIFF_GUTTER}{gutter}{Colors.RESET} {Colors.DIM}  {body}{Colors.RESET}")
                old_no += 1
                new_no += 1
            shown += 1

        if skipped:
            print(f"  {Colors.DIM}... {skipped} more diff lines{Colors.RESET}")
        print(f"  {Colors.DIM}{'─' * width}{Colors.RESET}")

    def file_created(self, filepath: str, line_count: int):
        """Shown when a brand new file is written — there's no diff to display."""
        name = os.path.basename(filepath) or filepath
        print(
            f"  {Colors.BOLD}{Colors.AMBER}{name}{Colors.RESET}  "
            f"{Colors.DIFF_ADD}+{line_count} lines{Colors.RESET} {Colors.DIM}(new file){Colors.RESET}"
        )

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
  {C}/cost{R}         Show session cost breakdown
  {C}/status{R}       Show session stats
  {C}/plan{R}         Show current plan
  {C}/undo{R}         Revert last file change
  {C}/clear{R}        Clear context and session
  {C}/sessions{R}     List saved sessions
  {C}/config{R}       Show configuration details
  {C}/exit{R}         Quit

  {C}Tools{R}
  {D}{'─' * 40}{R}
  {C}/routing{R}         Explain the last routing decision
  {C}/routing on|off{R}  Toggle smart routing
  {C}/shell{R}           Show shell mode and working directory
  {C}/shell reset{R}     Clear shell state (cd, exports, venv)
  {C}/mcp{R}             List MCP servers and their tools
  {C}/web on|off{R}      Toggle web search and page fetching

  {C}Tips{R}
  {D}{'─' * 40}{R}
  Attach images: just include the path in your message
  e.g. "what's in screenshot.png"
  Commands share one shell — cd and venv activation persist
  MCP servers: configure in ~/.acorn/mcp.json
  Project config: drop a .acorn.toml in your repo root
  Project instructions: drop a .acorn.md for custom context
  Docs: https://acorncli.dev
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
  Routing:     Pro={stats['routing']['pro_calls']} Flash={stats['routing']['flash_calls']} \
(tie-breaks: {stats['routing'].get('classifier_calls', 0)})
  Shell:       {stats.get('shell_mode', 'one-shot')} — {stats.get('shell_cwd', '')}
  MCP:         {stats.get('mcp_servers', 0)} servers, {stats.get('mcp_tools', 0)} tools
  Undo stack:  {stats['backups']} backups
  Session cost: {stats.get('cost', '$0.00')}
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

    def show_routing(self, enabled: bool, decision):
        """Explains the most recent routing decision."""
        C, R, D = Colors.AMBER, Colors.RESET, Colors.DIM
        state = f"{Colors.GREEN}on{R}" if enabled else f"{Colors.YELLOW}off{R}"
        print(f"\n  {C}Smart Routing{R}  {state}")
        print(f"  {D}{'─' * 46}{R}")
        if decision is None:
            print(f"  {D}No requests routed yet.{R}\n")
            return
        print(f"  Last request -> {Colors.CYAN}{decision.model}{R}")
        print(f"  Score:  {decision.score:+.1f}   {D}(via {decision.source}){R}")
        if decision.reasons:
            print(f"  {D}Signals:{R}")
            for reason in decision.reasons:
                print(f"    {D}{reason}{R}")
        print()

    def show_shell(self, persistent: bool, cwd: str):
        C, R, D = Colors.AMBER, Colors.RESET, Colors.DIM
        mode = f"{Colors.GREEN}persistent{R}" if persistent else f"{Colors.YELLOW}one-shot{R}"
        print(f"\n  {C}Shell{R}  {mode}")
        print(f"  {D}{'─' * 46}{R}")
        print(f"  Working dir: {cwd}")
        if persistent:
            print(f"  {D}cd, exports, and venv activation persist between commands.{R}")
            print(f"  {D}Use /shell reset to clear that state.{R}")
        print()

    def show_mcp(self, rows: list, tools: list):
        """Lists MCP servers and the tools they expose."""
        C, R, D = Colors.AMBER, Colors.RESET, Colors.DIM
        print(f"\n  {C}MCP Servers{R}")
        print(f"  {D}{'─' * 46}{R}")

        if not rows:
            print(f"  {D}No MCP servers configured.{R}")
            print(f"  {D}Add them in ~/.acorn/mcp.json or .mcp.json:{R}")
            print(f'  {D}  {{"mcpServers": {{"name": {{"command": "npx", "args": [...]}}}}}}{R}\n')
            return

        for row in rows:
            if row["running"]:
                badge = f"{Colors.GREEN}running{R}"
                detail = f"{row['tools']} tools"
            else:
                badge = f"{Colors.RED}failed{R}"
                detail = row.get("error") or "not running"
            print(f"  {Colors.CYAN}{row['name']:<18}{R} {badge}  {D}{detail}{R}")

        if tools:
            print(f"\n  {C}Available tools{R}")
            print(f"  {D}{'─' * 46}{R}")
            for tool in tools:
                description = (tool["description"] or "").split("\n")[0][:52]
                print(f"  {D}{tool['qualified_name']:<34}{R} {D}{description}{R}")
        print()

    def cost_inline(self, cost_str: str):
        """Shows cost after each response, subtle."""
        print(f"  {Colors.DIM}[{cost_str}]{Colors.RESET}")

    def show_cost(self, summary: dict):
        """Detailed cost breakdown."""
        C = Colors.AMBER
        R = Colors.RESET
        D = Colors.DIM
        total = summary['total_cost']
        print(f"""
  {C}Session Cost{R}
  {D}{'─' * 40}{R}
  API calls:     {summary['total_calls']}
  Pro calls:     {summary['pro_calls']}
  Flash calls:   {summary['flash_calls']}
  Input tokens:  ~{summary['input_tokens']:,}
  Output tokens: ~{summary['output_tokens']:,}
  {D}{'─' * 40}{R}
  {C}Total: ~${total:.4f}{R}
""")
