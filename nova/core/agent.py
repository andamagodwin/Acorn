"""The Nova Agent brain — orchestrates tools, context, planning, and streaming."""
import json
import traceback
from google import genai
from google.genai import types

from nova.config.settings import NovaSettings
from nova.core.context import ContextManager
from nova.core.planner import Planner
from nova.core.session import SessionManager
from nova.core.router import ModelRouter
from nova.tools.filesystem import read_file, write_file, edit_file, list_directory, search_files
from nova.tools.terminal import CommandRunner
from nova.tools.git_tools import GitTools
from nova.ui.terminal_ui import TerminalUI, Spinner


SYSTEM_PROMPT = """You are Acorn, an elite autonomous coding agent operating on the user's local machine.

## Core Capabilities
- Read, write, and edit files with surgical precision
- Execute terminal commands (with user permission for unsafe ones)
- Search across codebases
- Understand git state and project structure
- Plan and execute multi-step tasks
- Refactor across multiple files in a single session

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


class NovaAgent:
    """The main agent class — streaming, smart routing, auto-retry, session persistence."""

    def __init__(self, settings: NovaSettings | None = None):
        self.settings = settings or NovaSettings()
        self.ui = TerminalUI()
        self.context = ContextManager(
            max_tokens=self.settings.max_context_tokens,
            compaction_ratio=self.settings.compaction_threshold,
        )
        self.planner = Planner()
        self.runner = CommandRunner(self.settings.working_dir)
        self.git = GitTools(self.settings.working_dir)
        self.session = SessionManager(self.settings.working_dir)
        self.router = ModelRouter(
            pro_model=self.settings.model,
            flash_model=self.settings.flash_model,
        )

        # Track file changes for undo
        self._file_backups: list[dict] = []

        # Initialize Vertex AI client
        self.client = genai.Client(
            vertexai=True,
            project=self.settings.project,
            location=self.settings.location,
        )

        # Build tool declarations
        self._tools = self._build_tools()
        self._tool_map = self._build_tool_map()

    def _build_tools(self) -> list:
        """Declares all tools available to the model."""
        return [
            types.Tool(function_declarations=[
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
                    description="Runs a terminal command. Safe commands auto-execute; others require user permission.",
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
                    description="Reads multiple files at once for understanding before making changes. Use this when you need to understand relationships between files.",
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
            ])
        ]

    def _build_tool_map(self) -> dict:
        """Maps tool names to their execution functions."""
        return {
            "read_file": self._exec_read_file,
            "write_file": self._exec_write_file,
            "edit_file": self._exec_edit_file,
            "list_directory": self._exec_list_directory,
            "search_files": self._exec_search_files,
            "execute_command": self._exec_execute_command,
            "git_status": self._exec_git_status,
            "multi_edit": self._exec_multi_read,
        }

    # --- Tool Executors ---

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
        # Backup for undo
        self._backup_file(filepath)
        return write_file(filepath, args["content"])

    def _exec_edit_file(self, args: dict) -> str:
        filepath = args["filepath"]
        if not self._check_permission("edit_file", filepath):
            return "Permission denied by user."
        # Backup for undo
        self._backup_file(filepath)
        return edit_file(filepath, args["old_string"], args["new_string"])

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
        """Reads multiple files and returns their contents together."""
        filepaths = args.get("filepaths", [])
        results = []
        for fp in filepaths[:10]:  # cap at 10 files
            content = read_file(fp)
            results.append(f"{'='*60}\n📄 {fp}\n{'='*60}\n{content}")
        return "\n\n".join(results)

    # --- File Backup for Undo ---

    def _backup_file(self, filepath: str) -> None:
        """Stores file content before modification for undo support."""
        from pathlib import Path
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
        # Keep only last 20 backups
        if len(self._file_backups) > 20:
            self._file_backups = self._file_backups[-20:]

    def undo_last(self) -> str:
        """Reverts the last file change."""
        from pathlib import Path
        if not self._file_backups:
            return "Nothing to undo."
        backup = self._file_backups.pop()
        filepath = backup["filepath"]
        if not backup["existed"]:
            # File didn't exist before — delete it
            path = Path(filepath)
            if path.exists():
                path.unlink()
                return f"Undo: Deleted {filepath} (was newly created)"
            return f"Undo: {filepath} already gone."
        else:
            # Restore previous content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(backup["content"])
            return f"Undo: Restored {filepath} to previous state."

    # --- Permission System ---

    def _check_permission(self, tool_name: str, details: str) -> bool:
        rule = self.settings.permission_rules.get(tool_name, "ask")
        if rule == "safe":
            return True
        if rule == "deny":
            self.ui.error(f"Tool '{tool_name}' is blocked by permission rules.")
            return False
        return self.ui.permission_prompt(tool_name, details)

    # --- Streaming Response ---

    def _stream_response(self, model: str, contents: list, config) -> tuple[str, list]:
        """Streams a response, handling both text and tool calls."""
        try:
            response_stream = self.client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            )

            full_text = ""
            all_parts = []
            streaming_text = False

            for chunk in response_stream:
                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts:
                    if part.text:
                        if not streaming_text:
                            self.ui.stream_start()
                            streaming_text = True
                        self.ui.stream_chunk(part.text)
                        full_text += part.text
                    if part.function_call:
                        all_parts.append(part)

            if streaming_text:
                self.ui.stream_end()

            return full_text, all_parts

        except Exception as e:
            raise e

    # --- Auto-Retry Logic ---

    def _handle_tool_calls_with_retry(self, parts: list, contents: list, config, model: str) -> tuple[list, bool]:
        """Executes tool calls with auto-retry on failure."""
        tool_results = []
        had_errors = False

        for part in parts:
            if not part.function_call:
                continue

            fc = part.function_call
            tool_name = fc.name
            args = dict(fc.args) if fc.args else {}

            # Display tool call
            args_display = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
            self.ui.tool_call(tool_name, args_display)

            # Execute with retry
            executor = self._tool_map.get(tool_name)
            if executor:
                result = executor(args)
                # Check if it failed
                if result.startswith("Error"):
                    had_errors = True
                    self.ui.tool_result(f"[FAILED] {result}")
                else:
                    self.ui.tool_result(result)
            else:
                result = f"Unknown tool: {tool_name}"
                self.ui.tool_result(result)

            tool_results.append(types.Part.from_function_response(
                name=tool_name,
                response={"result": result},
            ))

        return tool_results, had_errors

    # --- Main Chat Method ---

    def chat(self, user_message: str) -> str:
        """Sends a message and handles streaming + tool loop + auto-retry."""
        self.context.add("user", user_message)

        # Smart routing: pick the right model
        model = self.router.route(user_message)
        if model == self.settings.flash_model:
            self.ui.info(f"[⚡ Flash mode — simple query]")
        else:
            self.ui.info(f"[🧠 Pro mode — complex task]")

        # Build message history
        contents = []
        for msg in self.context.messages:
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

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=self._tools,
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens,
        )

        # Agentic loop with streaming
        max_iterations = 25
        iteration = 0
        retry_count = 0

        while iteration < max_iterations:
            iteration += 1

            try:
                if self.settings.streaming:
                    full_text, tool_parts = self._stream_response(model, contents, config)
                else:
                    spinner = Spinner("Thinking")
                    spinner.start()
                    response = self.client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config,
                    )
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

            if tool_parts:
                # Build the model's response content for history
                model_content_parts = []
                if full_text:
                    model_content_parts.append(types.Part.from_text(text=full_text))
                model_content_parts.extend(tool_parts)

                contents.append(types.Content(
                    role="model",
                    parts=model_content_parts,
                ))

                # Execute tools with auto-retry awareness
                tool_results, had_errors = self._handle_tool_calls_with_retry(
                    tool_parts, contents, config, model
                )

                # Add tool results
                contents.append(types.Content(
                    role="user",
                    parts=tool_results,
                ))

                # If there were errors and auto-retry is on, the model will
                # naturally see the error and adapt on the next iteration
                if had_errors and self.settings.auto_retry_on_error:
                    self.ui.info("[Auto-retry: letting Nova adapt to the error...]")

            else:
                # Final text response (no tool calls)
                final_text = full_text or "(No response)"
                self.context.add("model", final_text)

                # If streamed, re-render with markdown formatting
                if self.settings.streaming:
                    self.ui.stream_response_formatted(final_text)

                # Persist session
                if self.settings.persist_sessions:
                    self._save_session()

                # Handle context compaction
                if self.context.needs_compaction:
                    self.ui.info("[Compacting context to stay within limits...]")
                    self.context.compact(self._summarize)

                return final_text

        return "Error: Reached maximum iterations. Task may be too complex for a single turn."

    def _summarize(self, text: str) -> str:
        """Uses Flash model to summarize (cheaper than Pro for meta-tasks)."""
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
        """Persists the current conversation."""
        messages = [
            {"role": m.role, "content": m.content}
            for m in self.context.messages
        ]
        self.session.save(messages, metadata={
            "router_stats": self.router.stats,
            "compactions": self.context.compaction_count,
        })

    def _load_session(self) -> bool:
        """Loads a previous session if available."""
        messages = self.session.load()
        if not messages:
            return False
        for msg in messages[-20:]:  # load last 20 messages max
            self.context.add(msg["role"], msg["content"])
        return True

    # --- Main Interactive Loop ---

    def run(self):
        """Main interactive loop with all features."""
        self.ui.banner()

        # Show project context
        if self.git.is_repo:
            self.ui.info(f"📁 Project: {self.settings.working_dir}")
            self.ui.info(f"🌿 Branch: {self.git.current_branch()}")
        else:
            self.ui.info(f"📁 Working directory: {self.settings.working_dir}")

        # Offer to resume previous session
        if self.settings.persist_sessions and self.session.has_previous_session:
            self.ui.info("💾 Previous session found for this directory.")
            try:
                resume = input(f"  Resume? [y/N]: ").strip().lower()
                if resume in ('y', 'yes'):
                    if self._load_session():
                        self.ui.success(f"Resumed session ({len(self.context.messages)} messages loaded)")
                    else:
                        self.ui.info("Could not load session, starting fresh.")
            except (EOFError, KeyboardInterrupt):
                pass

        self.ui.info("Commands: /clear /plan /status /undo /sessions /model /exit")
        self.ui.info(f"Smart routing: {'ON' if self.settings.use_smart_routing else 'OFF'} | Streaming: {'ON' if self.settings.streaming else 'OFF'}\n")

        while True:
            user_input = self.ui.user_prompt()

            if not user_input.strip():
                continue

            cmd = user_input.strip().lower()

            # Slash commands
            if cmd in ('exit', 'quit', '/exit', '/quit'):
                self.ui.success("Acorn signing off. 🌰")
                break
            elif cmd == '/clear':
                self.context.clear()
                self.session.clear()
                self.ui.success("Context and session cleared.")
                continue
            elif cmd == '/plan':
                plan = self.planner.progress_display
                if plan:
                    self.ui.plan_display(plan)
                else:
                    self.ui.info("No active plan.")
                continue
            elif cmd == '/status':
                self.ui.info(f"Context: ~{self.context.total_tokens} tokens")
                self.ui.info(f"Messages: {len(self.context.messages)}")
                self.ui.info(f"Compactions: {self.context.compaction_count}")
                self.ui.info(f"Model routing: {self.router.stats}")
                self.ui.info(f"File backups (undo): {len(self._file_backups)}")
                continue
            elif cmd == '/undo':
                result = self.undo_last()
                self.ui.success(result)
                continue
            elif cmd == '/sessions':
                sessions = self.session.list_sessions()
                if sessions:
                    for s in sessions[:10]:
                        self.ui.info(f"  {s['id']} — {s['dir']} ({s['messages']} msgs, {s['updated']})")
                else:
                    self.ui.info("No saved sessions.")
                continue
            elif cmd.startswith('/model'):
                parts = user_input.strip().split(maxsplit=1)
                if len(parts) > 1:
                    new_model = parts[1]
                    self.settings.model = new_model
                    self.router.pro_model = new_model
                    self.ui.success(f"Pro model changed to: {new_model}")
                else:
                    self.ui.info(f"Current: Pro={self.router.pro_model}, Flash={self.router.flash_model}")
                continue
            elif cmd == '/routing off':
                self.settings.use_smart_routing = False
                self.ui.success("Smart routing disabled — always using Pro.")
                continue
            elif cmd == '/routing on':
                self.settings.use_smart_routing = True
                self.ui.success("Smart routing enabled.")
                continue

            # Normal message — send to agent
            response = self.chat(user_input)
            if not self.settings.streaming:
                self.ui.nova_response(response)
            # When streaming is on, output is already printed by stream methods
