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

- **Node.js 18+** — to run the installer and launcher
- **Python 3.11+** — Acorn itself is written in Python
- A **Gemini API key** (free at [aistudio.google.com](https://aistudio.google.com/apikey)) or a **GCP project** for Vertex AI

On first run Acorn asks which one you want to use and saves your choice.

## How this package works

Acorn is a Python program, and npm can't install Python packages. So this
package is a thin launcher: it finds a suitable Python, creates a **private
virtual environment**, installs [`acorn-agent`](https://pypi.org/project/acorn-agent/)
from PyPI into it, and runs that.

The environment is private deliberately — Acorn never installs into your system
or active Python, so an unrelated `pip install` can't break it, and nothing is
left behind when you uninstall.

Setup runs once at install time. If it can't (no Python yet, or you installed
with `--ignore-scripts`), it runs on your first `acorn` instead.

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

**Nothing happened during install**

Some setups disable install scripts (`--ignore-scripts`, or certain pnpm/Bun
configs). That's fine — run `acorn` and it will set itself up, printing progress
as it goes.

## Links

- **Docs:** [acorncli.dev](https://acorncli.dev)
- **PyPI:** [pypi.org/project/acorn-agent](https://pypi.org/project/acorn-agent/)
- **Issues:** [github.com/andamagodwin/acorn/issues](https://github.com/andamagodwin/acorn/issues)

## License

MIT © Andama Godwin
