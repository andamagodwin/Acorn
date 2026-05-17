# Acorn

**An autonomous coding agent that lives in your terminal.**

Acorn reads your code, writes files, runs commands, and refactors across your entire codebase — powered by Google's Gemini 3.1 Pro via Vertex AI.

```
     █████╗  ██████╗ ██████╗ ██████╗ ███╗   ██╗
    ██╔══██╗██╔════╝██╔═══██╗██╔══██╗████╗  ██║
    ███████║██║     ██║   ██║██████╔╝██╔██╗ ██║
    ██╔══██║██║     ██║   ██║██╔══██╗██║╚██╗██║
    ██║  ██║╚██████╗╚██████╔╝██║  ██║██║ ╚████║
    ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝
```

## Features

- **Streaming responses** — see output as it's generated
- **Smart model routing** — Flash for simple questions, Pro for complex tasks
- **Surgical file editing** — modifies specific lines, not entire files
- **Multi-file refactoring** — reads and edits across your whole codebase
- **Image/screenshot analysis** — attach images for the model to analyze
- **Auto-retry with error recovery** — adapts when things fail
- **Session persistence** — resume conversations where you left off
- **Undo support** — revert the last file change instantly
- **Cost tracking** — see what you're spending per session
- **Project config** — per-repo `.acorn.toml` for custom settings
- **Permission system** — 3-tier safety (safe/ask/deny)
- **Git-aware** — understands your branch, status, and project structure

---

## Quick Start

```bash
# Install from PyPI (easiest)
pip install acorn-agent

# Or install from GitHub
pip install git+https://github.com/andamagodwin/acorn.git

# Run it
acorn
```

On first run it will ask for your GCP project ID. That's it.

---

## Installation (Full Guide)

### Prerequisites

| Requirement | Why |
|-------------|-----|
| Python 3.11+ | Runtime |
| Google Cloud account | Vertex AI access |
| `gcloud` CLI | Authentication |

### Step 1: Clone and Install

```bash
git clone https://github.com/andamagodwin/acorn.git
cd acorn
pip install -e .
```

This installs `acorn` as a global command you can run from anywhere.

### Step 2: Set Up Google Cloud

You need a GCP project with Vertex AI API enabled and authentication configured.

```bash
# Install gcloud CLI if you don't have it
# https://cloud.google.com/sdk/docs/install

# Login to Google Cloud
gcloud auth login
gcloud auth application-default login

# Set your project
gcloud config set project YOUR_PROJECT_ID
```

### Step 3: Enable Vertex AI API

```bash
gcloud services enable aiplatform.googleapis.com
```

Or enable it in the console: https://console.cloud.google.com/apis/library/aiplatform.googleapis.com

### Step 4: Configure Your Project ID

Edit `acorn/config/settings.py` and set your project:

```python
project: str = "your-gcp-project-id"
```

Or use the CLI flag:

```bash
acorn --project your-gcp-project-id
```

Or use a `.acorn.toml` in your repo (see below).

### Step 5: Run

```bash
cd ~/your-project
acorn
```

---

## Usage

```bash
# Start in current directory
acorn

# Use a specific model
acorn --model gemini-2.5-flash

# List available models
acorn --models

# Disable streaming
acorn --no-stream

# Disable smart routing (always use Pro)
acorn --no-routing

# Auto-approve all file writes (careful!)
acorn --unsafe

# Override GCP project
acorn --project my-project-id

# Help
acorn --help
```

### Attach Images

Just include an image path in your message:

```
> what's wrong in screenshot.png
> implement the design in mockup.jpg
```

Gemini will analyze the image and respond accordingly.

---

## Commands

| Command | What it does |
|---------|--------------|
| `/help` | Show all commands |
| `/model <name>` | Switch model (or list available) |
| `/cost` | Show session cost breakdown |
| `/status` | Token usage, routing stats, cost |
| `/plan` | Show current task execution plan |
| `/undo` | Revert the last file change |
| `/clear` | Reset context and session |
| `/sessions` | List saved sessions |
| `/routing on\|off` | Toggle smart routing |
| `/exit` | Quit |

---

## Project Configuration

Drop a `.acorn.toml` in any project root to customize Acorn's behavior for that repo:

```toml
[model]
pro = "gemini-2.5-pro"
flash = "gemini-2.5-flash"
temperature = 0.2
max_output_tokens = 65536

[routing]
enabled = true
threshold = 200

[project]
gcp_project = "your-project-id"
location = "us-central1"

[permissions]
safe_commands = [
    "npm run", "npm test", "cargo build",
    "python -m pytest", "make",
]
```

Acorn auto-detects this file by walking up from your working directory.

---

## For Collaborators

### Joining the Project

1. Get added as a collaborator on the GitHub repo
2. Clone and install:
   ```bash
   git clone https://github.com/andamagodwin/acorn.git
   cd acorn
   pip install -e .
   ```
3. Set up GCP authentication:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
4. Ask the project owner to add you to the GCP project with the **"Vertex AI User"** role in IAM
5. Run `acorn` from any directory

### IAM Setup (For Project Owner)

To add a collaborator to your GCP project:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:their-email@gmail.com" \
  --role="roles/aiplatform.user"
```

Or in the console: IAM & Admin > IAM > Grant Access > Role: "Vertex AI User"

---

## Architecture

```
acorn/
├── config/
│   ├── settings.py        — Models, permissions, safety rules
│   └── project_config.py  — .acorn.toml loader
├── core/
│   ├── agent.py           — Main brain: streaming agentic loop
│   ├── context.py         — Context window with auto-compaction
│   ├── costs.py           — Token usage and cost tracking
│   ├── planner.py         — Multi-step task planning
│   ├── router.py          — Smart model routing (Flash vs Pro)
│   └── session.py         — Session persistence to ~/.acorn/sessions/
├── tools/
│   ├── filesystem.py      — Read, write, edit, search, list
│   ├── terminal.py        — Command execution with timeout
│   └── git_tools.py       — Git-aware project understanding
├── ui/
│   └── terminal_ui.py     — Terminal UI with markdown rendering
└── main.py                — CLI entry point
```

---

## How It Works

1. You type a message
2. Acorn routes it to Flash (simple) or Pro (complex)
3. The model calls tools — reads files, edits code, runs commands
4. Tool results feed back for up to 25 iterations per turn
5. If something fails, it sees the error and adapts
6. Final response renders with markdown formatting

---

## Safety

| Layer | What it does |
|-------|--------------|
| Blocked commands | `rm -rf /`, `mkfs`, fork bombs — permanently blocked |
| Safe commands | `ls`, `git status`, `grep` — auto-execute |
| Permission prompts | File writes, unknown commands — asks you first |
| File backups | Every edit is backed up for `/undo` |
| Context isolation | Won't touch `.env` files or expose secrets |

---

## Cost

| Model | Input | Output | Typical session |
|-------|-------|--------|-----------------|
| Gemini 3.1 Pro | $1.25/M tokens | $10.00/M tokens | $0.50–$2.00 |
| Gemini 2.5 Flash | $0.15/M tokens | $0.60/M tokens | $0.02–$0.10 |

Smart routing saves ~70% by using Flash for greetings, questions, and simple lookups.

Use `/cost` to see your spending mid-session.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'acorn'` | Run `pip install -e .` from the acorn directory |
| `404 NOT_FOUND` model error | Gemini 3.1 requires `location="global"` (already set). If using 2.5 models only, you can use `us-central1` |
| `Permission denied` on gcloud | Run `gcloud auth application-default login` |
| `Vertex AI API not enabled` | Run `gcloud services enable aiplatform.googleapis.com` |
| Session won't resume | Delete `~/.acorn/sessions/` and restart |

---

## License

MIT
