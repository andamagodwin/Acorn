# 🌰 Acorn

**An autonomous coding agent that lives in your terminal.**

Acorn reads your code, writes files, runs commands, and refactors across your entire codebase — powered by Google's Gemini 2.5 Pro via Vertex AI.

```
     █████╗  ██████╗ ██████╗ ██████╗ ███╗   ██╗
    ██╔══██╗██╔════╝██╔═══██╗██╔══██╗████╗  ██║
    ███████║██║     ██║   ██║██████╔╝██╔██╗ ██║
    ██╔══██║██║     ██║   ██║██╔══██╗██║╚██╗██║
    ██║  ██║╚██████╗╚██████╔╝██║  ██║██║ ╚████║
    ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝
```

## Features

- **Streaming responses** — tokens appear in real-time, not after a long wait
- **Smart model routing** — simple questions use Flash (cheap), complex tasks use Pro (powerful)
- **Surgical editing** — modifies specific lines instead of rewriting entire files
- **Multi-file refactoring** — reads and edits across multiple files in one session
- **Auto-retry with error correction** — adapts when commands or edits fail
- **Session persistence** — resume conversations where you left off
- **Undo support** — revert the last file change instantly
- **Permission system** — 3-tier safety (safe/ask/deny) with smart command detection
- **Git-aware** — understands your branch, status, and project structure
- **Markdown rendering** — formatted output with bold, code blocks, and colors

## Installation

```bash
# Clone the repo
git clone <your-repo-url>
cd acorn

# Install as a global CLI command
pip install -e .

# Run from any project directory
acorn
```

### Prerequisites

- Python 3.11+
- Google Cloud project with Vertex AI API enabled
- Authenticated via `gcloud auth application-default login`

## Usage

```bash
# Start Acorn in the current directory
acorn

# Use a different model
acorn --model gemini-2.5-flash

# Disable streaming (wait for full response)
acorn --no-stream

# Disable smart routing (always use Pro)
acorn --no-routing

# Auto-approve all actions (use with caution)
acorn --unsafe

# Override GCP project
acorn --project my-project-id
```

## Slash Commands

| Command | Description |
|---------|-------------|
| `/clear` | Reset conversation context and session |
| `/plan` | Show the current task execution plan |
| `/status` | Display token usage and routing stats |
| `/undo` | Revert the last file modification |
| `/sessions` | List all saved sessions |
| `/model <name>` | Switch the Pro model |
| `/routing on/off` | Toggle smart model routing |
| `/exit` | Quit Acorn |

## Architecture

```
nova/
├── config/settings.py    — Permission tiers, model config, safety rules
├── core/
│   ├── agent.py          — Main brain: streaming agentic loop (25 iterations)
│   ├── context.py        — Context window management with auto-compaction
│   ├── planner.py        — Multi-step task planning and progress tracking
│   ├── router.py         — Smart model routing (Flash vs Pro)
│   └── session.py        — Session persistence to ~/.nova/sessions/
├── tools/
│   ├── filesystem.py     — Read, write, edit (surgical diffs), search, list
│   ├── terminal.py       — Command execution with timeout and streaming
│   └── git_tools.py      — Git-aware project understanding
├── ui/terminal_ui.py     — Rich terminal UI with markdown rendering
└── main.py               — CLI entry point
```

## How It Works

1. You type a request in natural language
2. Acorn routes it to the right model (Flash for simple, Pro for complex)
3. The model reasons about what to do and calls tools (read, edit, run commands)
4. Tool results feed back into the model for up to 25 iterations
5. If something fails, Acorn sees the error and adapts automatically
6. Final response streams to your terminal with proper formatting

## Safety

Acorn has multiple safety layers:

- **Blocked commands** — destructive operations like `rm -rf /` are permanently blocked
- **Safe commands** — read-only commands like `ls`, `git status` auto-execute
- **Permission prompts** — file writes and unknown commands require your approval
- **File backups** — every modification is backed up for `/undo`
- **No secrets** — won't modify `.env` files or expose credentials

## Cost

Running on Vertex AI with your GCP credits:

| Model | Input | Output | Typical session |
|-------|-------|--------|-----------------|
| Gemini 2.5 Pro | $1.25/M tokens | $10/M tokens | $0.50–$2.00 |
| Gemini 2.5 Flash | $0.15/M tokens | $0.60/M tokens | $0.02–$0.10 |

Smart routing saves ~70% on costs by using Flash for simple interactions.

## Configuration

Settings are in `nova/config/settings.py`. Key options:

```python
project = "your-gcp-project-id"
location = "us-central1"
model = "gemini-2.5-pro"
flash_model = "gemini-2.5-flash"
use_smart_routing = True
streaming = True
max_context_tokens = 900_000
```

## License

MIT
