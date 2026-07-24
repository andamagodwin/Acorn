"""Model Context Protocol client — lets Acorn use tools from external servers.

MCP over stdio is newline-delimited JSON-RPC 2.0, which is small enough to
implement directly. Doing so keeps Acorn's install at a single dependency and
avoids pulling an async stack into what is otherwise a synchronous CLI.

Servers are declared in ~/.acorn/mcp.json (or .mcp.json in the project root),
using the same shape other MCP clients use so existing configs work unchanged:

    {
      "mcpServers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
      }
    }
"""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30
STARTUP_TIMEOUT = 20

# Tools are exposed to the model as mcp__<server>__<tool> so two servers can
# both offer a "search" without colliding.
TOOL_PREFIX = "mcp"
NAME_SEPARATOR = "__"

# Gemini's function-declaration schema vocabulary.
JSON_TO_GEMINI_TYPE = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
    "null": "STRING",
}


class MCPError(RuntimeError):
    """Raised when an MCP server misbehaves or can't be reached."""


def qualified_name(server: str, tool: str) -> str:
    return f"{TOOL_PREFIX}{NAME_SEPARATOR}{server}{NAME_SEPARATOR}{tool}"


def parse_qualified_name(name: str) -> tuple[str, str] | None:
    """Splits mcp__server__tool back into (server, tool)."""
    if not name.startswith(TOOL_PREFIX + NAME_SEPARATOR):
        return None
    remainder = name[len(TOOL_PREFIX) + len(NAME_SEPARATOR):]
    if NAME_SEPARATOR not in remainder:
        return None
    server, tool = remainder.split(NAME_SEPARATOR, 1)
    return server, tool


class MCPServer:
    """One MCP server subprocess, spoken to over stdio JSON-RPC."""

    def __init__(self, name: str, command: str, args: list[str] | None = None,
                 env: dict | None = None, cwd: str | None = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.tools: list[dict] = []
        self.error: str | None = None

        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._id_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._stderr_tail: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """Launches the server and performs the MCP handshake."""
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self.cwd,
                env={**os.environ, **self.env},
            )
        except FileNotFoundError:
            self.error = f"Command not found: {self.command}"
            return False
        except Exception as e:
            self.error = f"Failed to launch: {e}"
            return False

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        try:
            self._handshake()
            self.tools = self._list_tools()
        except (MCPError, Exception) as e:
            self.error = str(e)
            self.stop()
            return False

        return True

    def _handshake(self) -> None:
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"roots": {"listChanged": False}},
            "clientInfo": {"name": "acorn", "version": _acorn_version()},
        }, timeout=STARTUP_TIMEOUT)
        # Per spec the server isn't usable until it sees this notification.
        self._notify("notifications/initialized", {})

    def _list_tools(self) -> list[dict]:
        result = self._request("tools/list", {}, timeout=STARTUP_TIMEOUT)
        tools = result.get("tools", [])
        return [t for t in tools if isinstance(t, dict) and t.get("name")]

    def call_tool(self, tool: str, arguments: dict, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Invokes a tool and flattens the response into text."""
        if not self.is_running:
            return f"Error: MCP server '{self.name}' is not running."
        try:
            result = self._request(
                "tools/call",
                {"name": tool, "arguments": arguments or {}},
                timeout=timeout,
            )
        except MCPError as e:
            return f"Error calling {self.name}.{tool}: {e}"

        text = _flatten_content(result.get("content", []))
        if result.get("isError"):
            return f"Error from {self.name}.{tool}: {text or '(no detail)'}"
        return text or "(no output)"

    # --- JSON-RPC plumbing ---

    def _read_loop(self) -> None:
        """Routes each response to whoever is waiting on its id."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    # Servers sometimes log plain text to stdout; ignore it.
                    continue
                msg_id = message.get("id")
                if msg_id is None:
                    continue  # a notification from the server
                with self._pending_lock:
                    waiter = self._pending.pop(msg_id, None)
                if waiter is not None:
                    waiter.put(message)
        except (ValueError, OSError):
            pass
        finally:
            # Unblock anyone still waiting — the pipe is gone.
            with self._pending_lock:
                waiters = list(self._pending.values())
                self._pending.clear()
            for waiter in waiters:
                waiter.put(None)

    def _drain_stderr(self) -> None:
        """Keeps the last few stderr lines for error messages."""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in iter(proc.stderr.readline, ""):
                self._stderr_tail.append(line.rstrip())
                if len(self._stderr_tail) > 20:
                    del self._stderr_tail[:10]
        except (ValueError, OSError):
            pass

    def _send(self, payload: dict) -> None:
        if not self.is_running or self._proc.stdin is None:
            raise MCPError(f"server '{self.name}' is not running")
        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise MCPError(f"lost connection to '{self.name}': {e}") from e

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
        with self._id_lock:
            request_id = self._next_id
            self._next_id += 1

        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = waiter

        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        })

        try:
            message = waiter.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise MCPError(f"'{method}' timed out after {timeout}s") from None

        if message is None:
            detail = "; ".join(self._stderr_tail[-3:]) or "process exited"
            raise MCPError(f"server closed the connection ({detail})")

        if "error" in message:
            error = message["error"] or {}
            raise MCPError(error.get("message", "unknown error"))

        return message.get("result", {}) or {}

    def stop(self) -> None:
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
            proc.terminate()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            try:
                proc.kill()
            except OSError:
                pass


class MCPManager:
    """Loads MCP server config, starts servers, and dispatches tool calls."""

    def __init__(self, working_dir: str = "."):
        self.working_dir = working_dir
        self.servers: dict[str, MCPServer] = {}
        self.failures: dict[str, str] = {}

    @staticmethod
    def config_paths(working_dir: str) -> list[Path]:
        """Project config first so a repo can override the user's servers."""
        from acorn.config.settings import ACORN_HOME
        return [
            Path(working_dir) / ".mcp.json",
            Path(working_dir) / ".acorn" / "mcp.json",
            ACORN_HOME / "mcp.json",
        ]

    def load_config(self) -> dict:
        """Merges every config file that exists, nearest first."""
        merged: dict[str, dict] = {}
        for path in reversed(self.config_paths(self.working_dir)):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                self.failures[str(path)] = f"Invalid config: {e}"
                continue
            servers = data.get("mcpServers") or data.get("servers") or {}
            if isinstance(servers, dict):
                merged.update(servers)
        return merged

    def start_all(self) -> tuple[int, int]:
        """Starts every configured server. Returns (started, failed).

        Servers boot in parallel — several of them shelling out to `npx` would
        otherwise add up to a long wait before the first prompt appears.
        """
        config = self.load_config()
        failed = 0
        candidates: list[MCPServer] = []

        for name, spec in config.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("disabled") or spec.get("enabled") is False:
                continue

            command = spec.get("command")
            if not command:
                self.failures[name] = "No 'command' specified"
                failed += 1
                continue

            candidates.append(MCPServer(
                name=name,
                command=command,
                args=spec.get("args", []),
                env=spec.get("env", {}),
                cwd=spec.get("cwd") or self.working_dir,
            ))

        if not candidates:
            return 0, failed

        results: dict[str, bool] = {}

        def boot(server: MCPServer) -> None:
            results[server.name] = server.start()

        threads = [threading.Thread(target=boot, args=(s,), daemon=True) for s in candidates]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=STARTUP_TIMEOUT + 10)

        started = 0
        for server in candidates:
            if results.get(server.name):
                self.servers[server.name] = server
                started += 1
            else:
                self.failures[server.name] = server.error or "Startup timed out"
                failed += 1
                server.stop()

        return started, failed

    @property
    def has_servers(self) -> bool:
        return bool(self.servers)

    def all_tools(self) -> list[dict]:
        """Every tool across every running server, with qualified names."""
        tools = []
        for server_name, server in self.servers.items():
            for tool in server.tools:
                tools.append({
                    "qualified_name": qualified_name(server_name, tool["name"]),
                    "server": server_name,
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "schema": tool.get("inputSchema", {}),
                })
        return tools

    def call(self, qualified: str, arguments: dict, timeout: int = DEFAULT_TIMEOUT) -> str:
        parsed = parse_qualified_name(qualified)
        if parsed is None:
            return f"Error: '{qualified}' is not a valid MCP tool name."
        server_name, tool_name = parsed
        server = self.servers.get(server_name)
        if server is None:
            return f"Error: No MCP server named '{server_name}' is running."
        return server.call_tool(tool_name, arguments, timeout=timeout)

    def status(self) -> list[dict]:
        rows = [
            {
                "name": name,
                "running": server.is_running,
                "tools": len(server.tools),
                "error": None,
            }
            for name, server in self.servers.items()
        ]
        rows.extend(
            {"name": name, "running": False, "tools": 0, "error": error}
            for name, error in self.failures.items()
        )
        return rows

    def stop_all(self) -> None:
        for server in self.servers.values():
            server.stop()
        self.servers.clear()


def _flatten_content(content) -> str:
    """MCP returns a list of typed content blocks; render them as text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content else ""

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind == "resource":
            resource = block.get("resource", {})
            uri = resource.get("uri", "")
            text = resource.get("text", "")
            parts.append(f"[resource {uri}]\n{text}" if text else f"[resource {uri}]")
        elif kind == "image":
            parts.append(f"[image: {block.get('mimeType', 'unknown type')}]")
        else:
            parts.append(json.dumps(block))
    return "\n".join(p for p in parts if p).strip()


def json_schema_to_gemini(schema: dict, types_module):
    """Converts a JSON Schema into a Gemini types.Schema.

    MCP servers write ordinary JSON Schema, which is a much bigger vocabulary
    than Gemini accepts. Unsupported keywords are dropped rather than passed
    through, since sending them makes the API reject the whole tool.
    """
    if not isinstance(schema, dict):
        return types_module.Schema(type="OBJECT", properties={})

    # Collapse unions to their first concrete branch — Gemini has no anyOf.
    for union_key in ("anyOf", "oneOf", "allOf"):
        if union_key in schema and isinstance(schema[union_key], list):
            for branch in schema[union_key]:
                if isinstance(branch, dict) and branch.get("type") != "null":
                    merged = {k: v for k, v in schema.items() if k != union_key}
                    merged.update(branch)
                    return json_schema_to_gemini(merged, types_module)

    raw_type = schema.get("type", "object")
    if isinstance(raw_type, list):
        # e.g. ["string", "null"] — take the first non-null option.
        raw_type = next((t for t in raw_type if t != "null"), "string")
    gemini_type = JSON_TO_GEMINI_TYPE.get(str(raw_type).lower(), "STRING")

    kwargs: dict = {"type": gemini_type}

    description = schema.get("description")
    if description:
        kwargs["description"] = str(description)[:1000]

    enum_values = schema.get("enum")
    if enum_values and gemini_type == "STRING":
        kwargs["enum"] = [str(v) for v in enum_values]

    if gemini_type == "OBJECT":
        properties = schema.get("properties") or {}
        converted = {
            key: json_schema_to_gemini(value, types_module)
            for key, value in properties.items()
            if isinstance(value, dict)
        }
        kwargs["properties"] = converted
        required = [r for r in schema.get("required", []) if r in converted]
        if required:
            kwargs["required"] = required
        # Gemini rejects an OBJECT with no properties, so give it a placeholder.
        if not converted:
            kwargs["properties"] = {
                "_": types_module.Schema(type="STRING", description="unused")
            }

    if gemini_type == "ARRAY":
        items = schema.get("items")
        kwargs["items"] = (
            json_schema_to_gemini(items, types_module)
            if isinstance(items, dict)
            else types_module.Schema(type="STRING")
        )

    return types_module.Schema(**kwargs)


def _acorn_version() -> str:
    try:
        from acorn.config.settings import VERSION
        return VERSION
    except Exception:
        return "0"
