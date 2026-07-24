"""Acorn Agent — orchestrates tools, context, planning, and streaming."""
import json
import signal
import base64
import traceback
from pathlib import Path
from google import genai
from google.genai import types

from acorn.config.settings import AcornSettings, check_for_updates
from acorn.config.project_config import load_project_config, apply_project_config
from acorn.core.context import ContextManager
from acorn.core.costs import CostTracker
from acorn.core.planner import Planner
from acorn.core.session import SessionManager
from acorn.core.router import ModelRouter
from acorn.tools.filesystem import read_file, write_file, edit_file, list_directory, search_files
from acorn.tools.terminal import CommandRunner
from acorn.tools.git_tools import GitTools
from acorn.tools.web import web_search, fetch_url
from acorn.tools.mcp import MCPManager, json_schema_to_gemini, parse_qualified_name
from acorn.ui.terminal_ui import TerminalUI, Spinner


SYSTEM_PROMPT = """You are Acorn, an elite autonomous coding agent operating on the user's local machine.

## Core Capabilities
- Read, write, and edit files with surgical precision
- Execute terminal commands (with user permission for unsafe ones)
- Search across codebases
- Understand git state and project structure
- Plan and execute multi-step tasks
- Refactor across multiple files in a single session
- Analyze images and screenshots provided by the user
- Search the web and read pages for current information

## Shell Behavior
Commands run in ONE persistent shell session, so state carries between calls:
- `cd` persists — don't re-`cd` on every command
- `export VAR=x`, `source venv/bin/activate`, and `nvm use` all stay in effect
- Prefer separate calls over chaining with `&&`; earlier setup still applies
- Never run interactive programs (vim, less, top, a bare `python`) — they hang
  the session. Use non-interactive flags instead.

## Using the Web
- Use web_search for current information: library versions, recent releases,
  error messages you don't recognize, API changes since your training data
- Use fetch_url to read a specific page, including search results worth opening
- Prefer official documentation over blog posts when both are available

## Operating Principles
1. ALWAYS read a file before editing it — never guess at contents
2. Use edit_file for surgical changes; write_file only for new files or complete rewrites
3. Explain your reasoning BRIEFLY before each tool call (1 sentence max)
4. If a command fails, analyze the error and try a different approach — adapt intelligently
5. For complex tasks, break them into numbered steps and execute sequentially
6. After modifying code, verify it works (run tests, lint, or build)
7. Respect the user's codebase style — match existing patterns
8. When refactoring across multiple files, read ALL affected files first, then edit them

## Error Recovery
- If a tool call fails, read the error carefully and adapt your approach
- If an edit fails because old_string wasn't found, re-read the file to get current contents
- If a command fails, check error output and try to fix the issue
- Never repeat the exact same failing action — always change something

## Safety Rules
- Never delete files without explicit user request
- Never run destructive commands (rm -rf, format disk, etc.)
- Never modify .env files or expose secrets
- If uncertain, ask the user before proceeding

## Response Style
- Be concise but precise
- Show diffs or relevant output, not walls of text
- If you make a plan, show it, then execute step by step
- Admit when you're unsure — don't hallucinate file contents
"""

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}


class AcornAgent:
    """The main agent class — streaming, smart routing, auto-retry, session persistence."""

    def __init__(self, settings: AcornSettings | None = None):
        self.settings = settings or AcornSettings()

        # Load project-level config (.acorn.toml)
        project_config = load_project_config(self.settings.working_dir)
        if project_config:
            apply_project_config(self.settings, project_config)
            self._has_project_config = True
        else:
            self._has_project_config = False

        self.ui = TerminalUI()
        self.context = ContextManager(
            max_tokens=self.settings.max_context_tokens,
            compaction_ratio=self.settings.compaction_threshold,
        )
        self.costs = CostTracker()
        self.planner = Planner()
        self.runner = CommandRunner(
            self.settings.working_dir,
            persistent=self.settings.persistent_shell,
        )
        self.git = GitTools(self.settings.working_dir)
        self.session = SessionManager(self.settings.working_dir)

        self._file_backups: list[dict] = []

        if self.settings.use_vertex:
            self.client = genai.Client(
                vertexai=True,
                project=self.settings.project,
                location=self.settings.location,
            )
        else:
            self.client = genai.Client(
                api_key=self.settings.api_key,
            )

        # The router needs a live client to break ties, so it's built after it.
        self.router = ModelRouter(
            pro_model=self.settings.model,
            flash_model=self.settings.flash_model,
            enabled=self.settings.use_smart_routing,
            classifier=self._classify_complexity if self.settings.routing_classifier else None,
        )

        self.mcp = MCPManager(self.settings.working_dir)
        self._mcp_started = 0
        self._mcp_failed = 0
        if self.settings.mcp_enabled:
            self._mcp_started, self._mcp_failed = self.mcp.start_all()

        self._tools = self._build_tools()
        self._tool_map = self._build_tool_map()

    def _classify_complexity(self, prompt: str) -> str:
        """Asks Flash whether a request is SIMPLE or COMPLEX. Used to break
        routing ties only, so it's capped tight on output tokens."""
        response = self.client.models.generate_content(
            model=self.settings.flash_model,
            contents=[types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            )],
            config=types.GenerateContentConfig(
                max_output_tokens=8,
                temperature=0.0,
            ),
        )
        return response.text or ""

    def _build_tools(self) -> list:
        """Declares all tools available to the model."""
        declarations = self._builtin_declarations()
        if self.settings.web_enabled:
            declarations.extend(self._web_declarations())
        declarations.extend(self._mcp_declarations())
        return [types.Tool(function_declarations=declarations)]

    def _web_declarations(self) -> list:
        return [
            types.FunctionDeclaration(
                name="web_search",
                description=(
                    "Searches the web. Use for current information, library versions, "
                    "unfamiliar errors, or anything newer than your training data."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "query": types.Schema(type="STRING", description="Search query"),
                        "max_results": types.Schema(type="INTEGER", description="Results to return (default 6, max 15)"),
                    },
                    required=["query"],
                ),
            ),
            types.FunctionDeclaration(
                name="fetch_url",
                description="Fetches a web page and returns its readable text content.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "url": types.Schema(type="STRING", description="The http(s) URL to fetch"),
                        "max_chars": types.Schema(type="INTEGER", description="Max characters to return (default 15000)"),
                    },
                    required=["url"],
                ),
            ),
        ]

    def _mcp_declarations(self) -> list:
        """Exposes every running MCP server's tools to the model."""
        declarations = []
        for tool in self.mcp.all_tools():
            try:
                schema = json_schema_to_gemini(tool["schema"], types)
                description = tool["description"] or f"{tool['name']} (via {tool['server']} MCP server)"
                declarations.append(types.FunctionDeclaration(
                    name=tool["qualified_name"],
                    description=description[:1000],
                    parameters=schema,
                ))
            except Exception as e:
                # One malformed schema shouldn't cost us every other tool.
                self.ui.info(f"[Skipped MCP tool {tool['qualified_name']}: {e}]")
        return declarations

    def _builtin_declarations(self) -> list:
        return [
                types.FunctionDeclaration(
                    name="read_file",
                    description="Reads a file's contents. Use offset/limit for large files.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "filepath": types.Schema(type="STRING", description="Path to the file to read"),
                            "offset": types.Schema(type="INTEGER", description="Starting line number (1-indexed, optional)"),
                            "limit": types.Schema(type="INTEGER", description="Number of lines to read (optional)"),
                        },
                        required=["filepath"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="write_file",
                    description="Creates or overwrites a file. Use edit_file for modifications to existing files.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "filepath": types.Schema(type="STRING", description="Path for the file"),
                            "content": types.Schema(type="STRING", description="Complete file content to write"),
                        },
                        required=["filepath", "content"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="edit_file",
                    description="Surgically edits a file by replacing old_string with new_string. old_string must be unique in the file.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "filepath": types.Schema(type="STRING", description="Path to the file to edit"),
                            "old_string": types.Schema(type="STRING", description="Exact text to find and replace (must be unique)"),
                            "new_string": types.Schema(type="STRING", description="Replacement text"),
                        },
                        required=["filepath", "old_string", "new_string"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="list_directory",
                    description="Lists files and folders in a directory. Use pattern for glob filtering.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "path": types.Schema(type="STRING", description="Directory path (default: current directory)"),
                            "pattern": types.Schema(type="STRING", description="Glob pattern filter, e.g. '*.py' (optional)"),
                        },
                        required=[],
                    ),
                ),
                types.FunctionDeclaration(
                    name="search_files",
                    description="Searches file contents for a query string across a directory.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "directory": types.Schema(type="STRING", description="Directory to search in"),
                            "query": types.Schema(type="STRING", description="Text to search for"),
                            "file_pattern": types.Schema(type="STRING", description="Glob pattern for files to search, e.g. '*.py' (default: *.py)"),
                        },
                        required=["directory", "query"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="execute_command",
                    description=(
                        "Runs a terminal command in a persistent shell session. cd, exports, "
                        "and venv activation persist across calls. Safe commands auto-execute; "
                        "others require user permission. Never run interactive programs."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "command": types.Schema(type="STRING", description="The shell command to execute"),
                            "timeout": types.Schema(type="INTEGER", description="Timeout in seconds (default: 120)"),
                        },
                        required=["command"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="git_status",
                    description="Returns current git status, branch, and recent commits.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={},
                        required=[],
                    ),
                ),
                types.FunctionDeclaration(
                    name="multi_edit",
                    description="Reads multiple files at once for understanding before making changes.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "filepaths": types.Schema(
                                type="ARRAY",
                                items=types.Schema(type="STRING"),
                                description="List of file paths to read simultaneously",
                            ),
                        },
                        required=["filepaths"],
                    ),
                ),
        ]

    def _build_tool_map(self) -> dict:
        return {
            "read_file": self._exec_read_file,
            "write_file": self._exec_write_file,
            "edit_file": self._exec_edit_file,
            "list_directory": self._exec_list_directory,
            "search_files": self._exec_search_files,
            "execute_command": self._exec_execute_command,
            "git_status": self._exec_git_status,
            "multi_edit": self._exec_multi_read,
            "web_search": self._exec_web_search,
            "fetch_url": self._exec_fetch_url,
        }

    def _exec_read_file(self, args: dict) -> str:
        return read_file(
            args["filepath"],
            offset=args.get("offset", 0),
            limit=args.get("limit", 0),
        )

    def _exec_write_file(self, args: dict) -> str:
        filepath = args["filepath"]
        if not self._check_permission("write_file", filepath):
            return "Permission denied by user."
        self._backup_file(filepath)
        change = write_file(filepath, args["content"])
        self._render_change(change)
        return change.message

    def _exec_edit_file(self, args: dict) -> str:
        filepath = args["filepath"]
        if not self._check_permission("edit_file", filepath):
            return "Permission denied by user."
        self._backup_file(filepath)
        change = edit_file(filepath, args["old_string"], args["new_string"])
        self._render_change(change)
        return change.message

    def _render_change(self, change) -> None:
        """Shows the user a colored diff. The model only gets change.message,
        so a large diff never lands in the context window."""
        if not change.ok:
            return
        if change.created:
            self.ui.file_created(change.filepath, change.added)
        elif change.diff:
            self.ui.show_diff(change.filepath, change.diff, change.added, change.removed)

    def _exec_web_search(self, args: dict) -> str:
        if not self._check_permission("web_search", args.get("query", "")):
            return "Permission denied by user."
        return web_search(args["query"], max_results=args.get("max_results", 6))

    def _exec_fetch_url(self, args: dict) -> str:
        url = args["url"]
        if not self._check_permission("fetch_url", url):
            return "Permission denied by user."
        return fetch_url(url, max_chars=args.get("max_chars", 15_000))

    def _exec_mcp_tool(self, tool_name: str, args: dict) -> str:
        parsed = parse_qualified_name(tool_name)
        label = f"{parsed[0]}.{parsed[1]}" if parsed else tool_name
        if not self._check_permission("mcp_tool", f"{label} {args}"):
            return "Permission denied by user."
        return self.mcp.call(tool_name, args)

    def _exec_list_directory(self, args: dict) -> str:
        return list_directory(args.get("path", "."), args.get("pattern", ""))

    def _exec_search_files(self, args: dict) -> str:
        return search_files(
            args["directory"],
            args["query"],
            args.get("file_pattern", "*.py"),
        )

    def _exec_execute_command(self, args: dict) -> str:
        command = args["command"]
        timeout = args.get("timeout", 120)

        if self.settings.is_command_blocked(command):
            return f"BLOCKED: This command is not allowed for safety reasons: {command}"

        if not self.settings.is_command_safe(command):
            if not self._check_permission("execute_command", command):
                return "Permission denied by user."

        return self.runner.execute(command, timeout=timeout)

    def _exec_git_status(self, args: dict) -> str:
        return self.git.project_summary()

    def _exec_multi_read(self, args: dict) -> str:
        filepaths = args.get("filepaths", [])
        results = []
        for fp in filepaths[:10]:
            content = read_file(fp)
            results.append(f"{'='*60}\n {fp}\n{'='*60}\n{content}")
        return "\n\n".join(results)

    def _backup_file(self, filepath: str) -> None:
        path = Path(filepath)
        content = None
        if path.exists():
            try:
                content = path.read_text(encoding='utf-8')
            except Exception:
                pass
        self._file_backups.append({
            "filepath": filepath,
            "content": content,
            "existed": path.exists(),
        })
        if len(self._file_backups) > 20:
            self._file_backups = self._file_backups[-20:]

    def undo_last(self) -> str:
        if not self._file_backups:
            return "Nothing to undo."
        backup = self._file_backups.pop()
        filepath = backup["filepath"]
        if not backup["existed"]:
            path = Path(filepath)
            if path.exists():
                path.unlink()
                return f"Undo: Deleted {filepath} (was newly created)"
            return f"Undo: {filepath} already gone."
        else:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(backup["content"])
            return f"Undo: Restored {filepath} to previous state."

    def _check_permission(self, tool_name: str, details: str) -> bool:
        rule = self.settings.permission_rules.get(tool_name, "ask")
        if rule == "safe":
            return True
        if rule == "deny":
            self.ui.error(f"Tool '{tool_name}' is blocked by permission rules.")
            return False
        return self.ui.permission_prompt(tool_name, details)

    # --- Multimodal support ---

    def _parse_image_from_message(self, message: str) -> tuple[str, list]:
        """Checks if the message references an image file and loads it."""
        parts = []
        text_parts = []

        words = message.split()
        for word in words:
            # Check if word looks like a file path to an image
            path = Path(word)
            if not path.is_absolute():
                path = Path(self.settings.working_dir) / word
            if path.exists() and path.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    image_data = path.read_bytes()
                    mime_type = self._get_mime_type(path.suffix.lower())
                    parts.append(types.Part.from_bytes(data=image_data, mime_type=mime_type))
                    self.ui.info(f"Attached image: {path.name}")
                except Exception:
                    text_parts.append(word)
            else:
                text_parts.append(word)

        clean_text = " ".join(text_parts)
        return clean_text, parts

    def _get_mime_type(self, ext: str) -> str:
        mime_map = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
        }
        return mime_map.get(ext, 'image/png')

    # --- Streaming ---

    def _stream_response(self, model: str, contents: list, config,
                         context: str = "thinking") -> tuple[str, list]:
        """Streams a response with real-time text output."""
        # Declared before the try: a Ctrl-C raised while the request is still
        # being set up would otherwise hit the handler below with these unbound,
        # turning a clean interrupt into an UnboundLocalError.
        full_text = ""
        all_parts = []
        started_text = False

        # Something has to fill the gap between the request going out and the
        # first token coming back, which can be several seconds on Pro.
        spinner = Spinner(context=context)
        spinner.start()

        try:
            response_stream = self.client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            )

            for chunk in response_stream:
                # The wait is over as soon as anything arrives; stop() is
                # idempotent so the later calls are no-ops.
                spinner.stop()
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts:
                    if part.text:
                        if not started_text:
                            self.ui.stream_start_live()
                            started_text = True
                        full_text += part.text
                        self.ui.stream_chunk_live(part.text)
                    if part.function_call:
                        all_parts.append(part)

            if started_text:
                self.ui.stream_end_live()

            return full_text, all_parts

        except KeyboardInterrupt:
            if started_text:
                # Flush whatever was mid-line so the prompt isn't left ragged.
                self.ui.stream_end_live()
            raise
        finally:
            # Covers the error paths too — a spinner thread left running would
            # keep overwriting whatever gets printed next.
            spinner.stop()

    def _handle_tool_calls_with_retry(self, parts: list, contents: list, config, model: str) -> tuple[list, bool]:
        tool_results = []
        had_errors = False

        for part in parts:
            if not part.function_call:
                continue

            fc = part.function_call
            tool_name = fc.name
            args = dict(fc.args) if fc.args else {}

            args_display = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
            self.ui.tool_call(tool_name, args_display)

            executor = self._tool_map.get(tool_name)
            if executor:
                result = executor(args)
            elif parse_qualified_name(tool_name):
                result = self._exec_mcp_tool(tool_name, args)
            else:
                result = f"Unknown tool: {tool_name}"

            if result.startswith("Error"):
                had_errors = True
                self.ui.tool_result(f"[FAILED] {result}")
            elif tool_name in ("edit_file", "write_file"):
                # The diff was already rendered; repeating the message is noise.
                pass
            else:
                self.ui.tool_result(result)

            tool_results.append(types.Part.from_function_response(
                name=tool_name,
                response={"result": result},
            ))

        return tool_results, had_errors

    def chat(self, user_message: str) -> str:
        """Sends a message and handles streaming + tool loop + auto-retry."""
        # Check for image attachments
        clean_text, image_parts = self._parse_image_from_message(user_message)
        display_text = clean_text if clean_text else user_message

        self.context.add("user", display_text)

        # Force Pro model if image is attached (vision requires Pro)
        if image_parts:
            model = self.settings.model
            self.ui.info(f"[Pro mode - vision]")
        else:
            model = self.router.route(display_text)
            if model == self.settings.flash_model:
                self.ui.info(f"[Flash mode]")
            else:
                self.ui.info(f"[Pro mode]")

        # Build message history
        contents = []
        for msg in self.context.messages[:-1]:  # all but the current one
            if msg.role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg.content)],
                ))
            elif msg.role == "model":
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=msg.content)],
                ))

        # Current message with potential image parts
        current_parts = []
        if clean_text:
            current_parts.append(types.Part.from_text(text=clean_text))
        elif user_message:
            current_parts.append(types.Part.from_text(text=user_message))
        current_parts.extend(image_parts)
        contents.append(types.Content(role="user", parts=current_parts))

        system_instruction = SYSTEM_PROMPT
        if self.settings.project_instructions:
            system_instruction += f"\n\n## Project Instructions (from .acorn.md)\n{self.settings.project_instructions}"

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=self._tools,
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens,
        )

        max_iterations = 25
        iteration = 0
        retry_count = 0
        # Picks which pool the status messages come from. Starts as planning
        # (nothing has been looked at yet) and shifts as the turn unfolds.
        think_context = "fast" if model == self.settings.flash_model else "planning"

        while iteration < max_iterations:
            iteration += 1

            try:
                if self.settings.streaming:
                    full_text, tool_parts = self._stream_response(
                        model, contents, config, context=think_context
                    )
                else:
                    spinner = Spinner(context=think_context)
                    spinner.start()
                    try:
                        response = self.client.models.generate_content(
                            model=model,
                            contents=contents,
                            config=config,
                        )
                    finally:
                        spinner.stop()
                    full_text = response.text or ""
                    tool_parts = [
                        p for p in response.candidates[0].content.parts
                        if p.function_call
                    ]
            except Exception as e:
                error_msg = f"API Error: {e}"
                self.ui.error(error_msg)
                if retry_count < self.settings.max_auto_retries:
                    retry_count += 1
                    self.ui.info(f"[Retrying... attempt {retry_count}/{self.settings.max_auto_retries}]")
                    continue
                return error_msg

            # Track costs
            input_size = sum(len(m.content) for m in self.context.messages)
            self.costs.estimate_from_text(model, "x" * input_size, full_text)

            if tool_parts:
                model_content_parts = []
                if full_text:
                    model_content_parts.append(types.Part.from_text(text=full_text))
                model_content_parts.extend(tool_parts)

                contents.append(types.Content(
                    role="model",
                    parts=model_content_parts,
                ))

                tool_results, had_errors = self._handle_tool_calls_with_retry(
                    tool_parts, contents, config, model
                )

                contents.append(types.Content(
                    role="user",
                    parts=tool_results,
                ))

                # A failed tool means the next turn is recovery work; otherwise
                # it's reasoning over whatever the tools just returned.
                think_context = "solving" if had_errors else "thinking"

                if had_errors and self.settings.auto_retry_on_error:
                    self.ui.info("[Adapting to error...]")

            else:
                final_text = full_text or "(No response)"
                self.context.add("model", final_text)

                if not self.settings.streaming:
                    self.ui.stream_response_formatted(final_text)

                # Show cost after response
                self.ui.cost_inline(self.costs.format_cost())

                if self.settings.persist_sessions:
                    self._save_session()

                if self.context.needs_compaction:
                    # Compaction is a blocking model call; don't leave the
                    # terminal silent while it runs.
                    spinner = Spinner(context="recalling")
                    spinner.start()
                    try:
                        self.context.compact(self._summarize)
                    finally:
                        spinner.stop()
                    self.ui.info("[Context compacted]")

                return final_text

        return "Error: Reached maximum iterations. Task may be too complex for a single turn."

    def _summarize(self, text: str) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.settings.flash_model,
                contents=[types.Content(
                    role="user",
                    parts=[types.Part.from_text(
                        text=f"Summarize this conversation concisely, preserving key decisions, file paths, and context:\n\n{text[:10000]}"
                    )],
                )],
                config=types.GenerateContentConfig(
                    max_output_tokens=2000,
                    temperature=0.1,
                ),
            )
            return response.text
        except Exception:
            return text[:2000]

    def _save_session(self) -> None:
        messages = [
            {"role": m.role, "content": m.content}
            for m in self.context.messages
        ]
        self.session.save(messages, metadata={
            "router_stats": self.router.stats,
            "compactions": self.context.compaction_count,
            "costs": self.costs.session_summary,
        })

    def _load_session(self) -> bool:
        messages = self.session.load()
        if not messages:
            return False
        for msg in messages[-20:]:
            self.context.add(msg["role"], msg["content"])
        return True

    # --- Main Interactive Loop ---

    def run(self):
        self.ui.banner()

        self._update_available = None
        check_for_updates(callback=lambda v: setattr(self, '_update_available', v))

        if self.git.is_repo:
            self.ui.info(f"Project: {self.settings.working_dir}")
            self.ui.info(f"Branch:  {self.git.current_branch()}")
        else:
            self.ui.info(f"Directory: {self.settings.working_dir}")

        auth_mode = "Vertex AI" if self.settings.use_vertex else "API Key"
        self.ui.info(f"Auth:    {auth_mode}")
        self.ui.info(f"Model:   {self.settings.model} | Flash: {self.settings.flash_model}")

        if self._mcp_started:
            tool_count = len(self.mcp.all_tools())
            self.ui.success(
                f"MCP: {self._mcp_started} server(s), {tool_count} tools available"
            )
        if self._mcp_failed:
            self.ui.info(f"MCP: {self._mcp_failed} server(s) failed to start — see /mcp")

        if self._has_project_config:
            self.ui.success("Loaded .acorn.toml config")

        if self.settings.project_instructions:
            self.ui.success("Loaded .acorn.md project instructions")

        if self.settings.persist_sessions and self.session.has_previous_session:
            self.ui.info("Previous session found.")
            try:
                resume = input(f"  Resume? [y/N]: ").strip().lower()
                if resume in ('y', 'yes'):
                    if self._load_session():
                        self.ui.success(f"Resumed ({len(self.context.messages)} messages)")
                    else:
                        self.ui.info("Could not load session, starting fresh.")
            except (EOFError, KeyboardInterrupt):
                pass

        self.ui.divider()

        if self._update_available:
            from acorn.config.settings import VERSION
            self.ui.info(f"Update available: v{self._update_available} (current: v{VERSION})")
            self.ui.info("Run: pip install --upgrade acorn-agent")

        self.ui.info("Type /help for commands, /exit to quit\n")

        try:
            self._interactive_loop()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Reaps the persistent shell and any MCP servers we started."""
        try:
            self.runner.close()
        except Exception:
            pass
        try:
            self.mcp.stop_all()
        except Exception:
            pass

    def _interactive_loop(self):
        while True:
            try:
                user_input = self.ui.user_prompt()
            except (EOFError, KeyboardInterrupt):
                print()
                if self.costs.total_cost > 0:
                    self.ui.info(f"Session cost: {self.costs.format_cost()}")
                self.ui.success("See you later.")
                break

            if not user_input.strip():
                continue

            cmd = user_input.strip().lower()

            if cmd in ('exit', 'quit', '/exit', '/quit'):
                if self.costs.total_cost > 0:
                    self.ui.info(f"Session cost: {self.costs.format_cost()}")
                self.ui.success("See you later.")
                break
            elif cmd == '/clear':
                self.context.clear()
                self.session.clear()
                self.costs = CostTracker()
                self.ui.success("Context cleared.")
                continue
            elif cmd == '/help':
                self.ui.show_help()
                continue
            elif cmd == '/plan':
                plan = self.planner.progress_display
                if plan:
                    self.ui.plan_display(plan)
                else:
                    self.ui.info("No active plan.")
                continue
            elif cmd == '/cost':
                summary = self.costs.session_summary
                self.ui.show_cost(summary)
                continue
            elif cmd == '/status':
                self.ui.show_status({
                    "tokens": self.context.total_tokens,
                    "messages": len(self.context.messages),
                    "compactions": self.context.compaction_count,
                    "pro_model": self.router.pro_model,
                    "flash_model": self.router.flash_model,
                    "routing": self.router.stats,
                    "backups": len(self._file_backups),
                    "cost": self.costs.format_cost(),
                    "shell_mode": "persistent" if self.settings.persistent_shell else "one-shot",
                    "shell_cwd": self.runner.current_dir(),
                    "mcp_servers": len(self.mcp.servers),
                    "mcp_tools": len(self.mcp.all_tools()),
                })
                continue
            elif cmd == '/undo':
                result = self.undo_last()
                self.ui.success(result)
                continue
            elif cmd == '/sessions':
                sessions = self.session.list_sessions()
                if sessions:
                    for s in sessions[:10]:
                        self.ui.info(f"  {s['id']} — {s['dir']} ({s['messages']} msgs)")
                else:
                    self.ui.info("No saved sessions.")
                continue
            elif cmd.startswith('/model'):
                parts = user_input.strip().split(maxsplit=1)
                if len(parts) > 1:
                    new_model = parts[1]
                    self.settings.model = new_model
                    self.router.pro_model = new_model
                    self.ui.success(f"Model: {new_model}")
                else:
                    from acorn.config.settings import AVAILABLE_MODELS
                    self.ui.show_models(AVAILABLE_MODELS, self.router.pro_model, self.router.flash_model)
                continue
            elif cmd == '/routing off':
                self.settings.use_smart_routing = False
                self.router.enabled = False
                self.ui.success("Smart routing disabled — always using Pro.")
                continue
            elif cmd == '/routing on':
                self.settings.use_smart_routing = True
                self.router.enabled = True
                self.ui.success("Smart routing enabled.")
                continue
            elif cmd == '/routing':
                self.ui.show_routing(self.router.enabled, self.router.last_decision)
                continue
            elif cmd == '/shell reset':
                self.ui.success(self.runner.reset_shell())
                continue
            elif cmd == '/shell':
                self.ui.show_shell(
                    persistent=self.settings.persistent_shell,
                    cwd=self.runner.current_dir(),
                )
                continue
            elif cmd == '/mcp':
                self.ui.show_mcp(self.mcp.status(), self.mcp.all_tools())
                continue
            elif cmd in ('/web on', '/web off'):
                self.settings.web_enabled = cmd.endswith('on')
                self._tools = self._build_tools()
                state = "enabled" if self.settings.web_enabled else "disabled"
                self.ui.success(f"Web tools {state}.")
                continue
            elif cmd == '/config':
                from acorn.config.settings import VERSION, ACORN_HOME
                self.ui.info(f"Version:     {VERSION}")
                self.ui.info(f"Config dir:  {ACORN_HOME}")
                self.ui.info(f"Auth mode:   {'Vertex AI' if self.settings.use_vertex else 'API Key'}")
                self.ui.info(f"Working dir: {self.settings.working_dir}")
                if self.settings.project_instructions:
                    self.ui.info(f"Project instructions: .acorn.md loaded")
                continue

            try:
                response = self.chat(user_input)
                if not self.settings.streaming:
                    self.ui.acorn_response(response)
            except KeyboardInterrupt:
                print(f"\033[0m")
                self.ui.info("Cancelled.")
                continue
