"""The Nova Agent brain — orchestrates tools, context, and planning."""
import json
from google import genai
from google.genai import types

from nova.config.settings import NovaSettings
from nova.core.context import ContextManager
from nova.core.planner import Planner
from nova.tools.filesystem import read_file, write_file, edit_file, list_directory, search_files
from nova.tools.terminal import CommandRunner
from nova.tools.git_tools import GitTools
from nova.ui.terminal_ui import TerminalUI, Spinner


SYSTEM_PROMPT = """You are Nova, an elite autonomous coding agent operating on the user's local machine.

## Core Capabilities
- Read, write, and edit files with surgical precision
- Execute terminal commands (with user permission for unsafe ones)
- Search across codebases
- Understand git state and project structure
- Plan and execute multi-step tasks

## Operating Principles
1. ALWAYS read a file before editing it — never guess at contents
2. Use edit_file for surgical changes; write_file only for new files or complete rewrites
3. Explain your reasoning BRIEFLY before each tool call (1 sentence max)
4. If a command fails, analyze the error and adapt — don't retry blindly
5. For complex tasks, break them into numbered steps and execute sequentially
6. After modifying code, verify it works (run tests, lint, or build)
7. Respect the user's codebase style — match existing patterns

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
    """The main agent class that ties everything together."""

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
        }

    # --- Tool Executors ---

    def _exec_read_file(self, args: dict) -> str:
        return read_file(
            args["filepath"],
            offset=args.get("offset", 0),
            limit=args.get("limit", 0),
        )

    def _exec_write_file(self, args: dict) -> str:
        if not self._check_permission("write_file", args["filepath"]):
            return "Permission denied by user."
        return write_file(args["filepath"], args["content"])

    def _exec_edit_file(self, args: dict) -> str:
        if not self._check_permission("edit_file", args["filepath"]):
            return "Permission denied by user."
        return edit_file(args["filepath"], args["old_string"], args["new_string"])

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

    # --- Permission System ---

    def _check_permission(self, tool_name: str, details: str) -> bool:
        rule = self.settings.permission_rules.get(tool_name, "ask")
        if rule == "safe":
            return True
        if rule == "deny":
            self.ui.error(f"Tool '{tool_name}' is blocked by permission rules.")
            return False
        return self.ui.permission_prompt(tool_name, details)

    # --- Main Chat Loop ---

    def _handle_tool_calls(self, response) -> list[types.Part]:
        """Processes tool calls from the model response and returns results."""
        tool_results = []

        for part in response.candidates[0].content.parts:
            if part.function_call:
                fc = part.function_call
                tool_name = fc.name
                args = dict(fc.args) if fc.args else {}

                # Display tool call
                args_display = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
                self.ui.tool_call(tool_name, args_display)

                # Execute
                executor = self._tool_map.get(tool_name)
                if executor:
                    result = executor(args)
                else:
                    result = f"Unknown tool: {tool_name}"

                self.ui.tool_result(result)

                tool_results.append(types.Part.from_function_response(
                    name=tool_name,
                    response={"result": result},
                ))

        return tool_results

    def chat(self, user_message: str) -> str:
        """Sends a message to Nova and handles the full tool-calling loop."""
        self.context.add("user", user_message)

        # Build the message history for the API
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

        # Agentic loop: keep going until the model stops calling tools
        max_iterations = 20
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            spinner = Spinner("Thinking")
            spinner.start()

            try:
                response = self.client.models.generate_content(
                    model=self.settings.model,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                spinner.stop()
                error_msg = f"API Error: {e}"
                self.ui.error(error_msg)
                return error_msg
            finally:
                spinner.stop()

            # Check if the response has tool calls
            has_tool_calls = any(
                part.function_call
                for part in response.candidates[0].content.parts
            )

            if has_tool_calls:
                # Add model's response (with tool calls) to history
                contents.append(response.candidates[0].content)

                # Execute tools and get results
                tool_results = self._handle_tool_calls(response)

                # Add tool results to history
                contents.append(types.Content(
                    role="user",
                    parts=tool_results,
                ))
            else:
                # No tool calls — we have the final text response
                final_text = response.text or "(No response)"
                self.context.add("model", final_text)

                # Handle context compaction if needed
                if self.context.needs_compaction:
                    self.ui.info("[Compacting context to stay within limits...]")
                    self.context.compact(self._summarize)

                return final_text

        return "Error: Reached maximum tool-calling iterations. Task may be too complex for a single turn."

    def _summarize(self, text: str) -> str:
        """Uses the model to summarize conversation history for compaction."""
        try:
            response = self.client.models.generate_content(
                model=self.settings.model,
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

    def run(self):
        """Main interactive loop."""
        self.ui.banner()

        # Show project context on startup
        if self.git.is_repo:
            self.ui.info(f"📁 Project: {self.settings.working_dir}")
            self.ui.info(f"🌿 Branch: {self.git.current_branch()}")
        else:
            self.ui.info(f"📁 Working directory: {self.settings.working_dir}")

        self.ui.info("Type 'exit' to quit, '/plan' to see current plan, '/clear' to reset context.\n")

        while True:
            user_input = self.ui.user_prompt()

            if not user_input.strip():
                continue

            cmd = user_input.strip().lower()
            if cmd in ('exit', 'quit', '/exit', '/quit'):
                self.ui.success("Nova signing off. ✦")
                break
            elif cmd == '/clear':
                self.context.clear()
                self.ui.success("Context cleared.")
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
                continue

            response = self.chat(user_input)
            self.ui.nova_response(response)
