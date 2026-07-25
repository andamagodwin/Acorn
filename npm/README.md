# acorn-agent

**An autonomous coding agent that lives in your terminal.**

Acorn reads your code, writes files, runs commands, and refactors across your
entire codebase — powered by Google's Gemini.

**Website:** [acorncli.dev](https://acorncli.dev) · **Source:** [github.com/andamagodwin/acorn](https://github.com/andamagodwin/acorn)

```bash
npm install -g acorn-agent
acorn
```

---

## Requirements

- **Node.js 18+**
- A **Gemini API key** (free at [aistudio.google.com](https://aistudio.google.com/apikey)) or a **GCP project** for Vertex AI

**No Python needed** on the platforms below — the binary is self-contained.

On first run Acorn asks which auth you want to use and saves your choice.

## Supported platforms

| Platform | Prebuilt binary |
|---|---|
| macOS (Apple Silicon) | yes |
| macOS (Intel) | yes |
| Linux (x86_64) | yes |
| Linux (arm64) | yes |
| Windows (x86_64) | yes |

Anything else falls back to Python (see below), which needs **Python 3.11+**.

## How this package works

Acorn is written in Python, so npm can't install it directly. This package
handles that in two ways, preferring the first:

**1. Prebuilt binary.** `acorn-agent` declares one `acorn-agent-<platform>-<arch>`
package per platform as an optional dependency. Each carries `os` and `cpu`
fields, so npm downloads only the one matching your machine — a single
self-contained binary with Python and every dependency baked in. Nothing else is
required.

**2. Python fallback.** On a platform with no prebuilt binary, or if optional
dependencies were skipped, the launcher finds a Python 3.11+, creates a
**private virtual environment**, and installs
[`acorn-agent`](https://pypi.org/project/acorn-agent/) from PyPI into it.

The venv is private deliberately — Acorn never installs into your system or
active Python, so an unrelated `pip install` can't break it, and nothing is left
behind when you uninstall.

### Already have Python tooling?

Installing from PyPI directly is equally supported and skips the Node layer:

```bash
pip install acorn-agent
```

Both routes give you the same `acorn` command.

## Configuration

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini API key (simplest setup) |
| `ACORN_PROJECT` | GCP project ID for Vertex AI |
| `ACORN_PYTHON` | Path to a specific Python, if auto-detection picks the wrong one |
| `ACORN_SKIP_POSTINSTALL` | Skip install-time setup; it will run on first use |

## Troubleshooting

**"Python 3.11+ was not found on your PATH"**

Install Python from [python.org/downloads](https://python.org/downloads) and open
a new terminal. If you have it somewhere unusual, point Acorn at it:

```bash
ACORN_PYTHON=/usr/local/bin/python3.12 acorn
```

**Environment got into a bad state**

Rebuild it from scratch:

```bash
npm rebuild acorn-agent
```

**It's using Python when I expected the binary**

Optional dependencies were probably skipped. Reinstall without `--no-optional`,
and check your package manager isn't configured to omit them:

```bash
npm install -g acorn-agent
```

**Nothing happened during install**

Some setups disable install scripts (`--ignore-scripts`, or certain pnpm/Bun
configs). That's fine — the binary path needs no install step at all, and the
Python fallback sets itself up on first `acorn`.

## Links

- **Docs:** [acorncli.dev](https://acorncli.dev)
- **PyPI:** [pypi.org/project/acorn-agent](https://pypi.org/project/acorn-agent/)
- **Issues:** [github.com/andamagodwin/acorn/issues](https://github.com/andamagodwin/acorn/issues)

## License

MIT © Andama Godwin
