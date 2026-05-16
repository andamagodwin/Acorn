#!/usr/bin/env python3
"""Acorn Agent — entry point for the `acorn` CLI command."""
import sys
import os
import signal


def _handle_sigint(sig, frame):
    """Clean exit on Ctrl+C — resets terminal and exits gracefully."""
    sys.stdout.write("\033[0m\r\033[K")
    sys.stdout.flush()
    print("\n  Interrupted. Bye!")
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_sigint)


def main():
    working_dir = os.getcwd()

    from acorn.config.settings import AcornSettings, AVAILABLE_MODELS, VERSION

    args = sys.argv[1:]

    if "--version" in args or "-v" in args:
        print(f"acorn {VERSION}")
        return

    if "--help" in args or "-h" in args:
        print(f"""
\033[38;2;139;90;43m Acorn v{VERSION}\033[0m — Autonomous Coding Agent

\033[1mUsage:\033[0m acorn [options]

\033[1mOptions:\033[0m
  --model <name>     Set the Pro model (default: gemini-3.1-pro-preview)
  --flash <name>     Set the Flash model (default: gemini-3-flash-preview)
  --no-stream        Disable streaming (wait for full response)
  --no-routing       Disable smart routing (always use Pro)
  --no-session       Disable session persistence
  --unsafe           Auto-approve all actions (dangerous!)
  --project <id>     Override GCP project ID
  --models           List available models
  -v, --version      Show version
  -h, --help         Show this help

\033[1mEnvironment:\033[0m
  ACORN_PROJECT      GCP project ID (or GCP_PROJECT, GOOGLE_CLOUD_PROJECT)
        """)
        return

    if "--models" in args:
        print("\n\033[1mAvailable Models:\033[0m\n")
        for model_id, description in AVAILABLE_MODELS.items():
            print(f"  \033[36m{model_id:<30}\033[0m {description}")
        print()
        return

    settings = AcornSettings(working_dir=working_dir)

    # First-run: prompt for project ID if not configured
    if not settings.project:
        print("\033[38;2;207;155;54m  First-time setup: GCP project ID needed.\033[0m")
        print("  \033[2mYou can also set ACORN_PROJECT env var to skip this.\033[0m\n")
        try:
            project_id = input("  Enter your GCP project ID: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  No project set. Exiting.")
            return
        if not project_id:
            print("  No project set. Exiting.")
            return
        settings.project = project_id
        settings.save_project_id(project_id)
        print(f"  \033[32mSaved to ~/.acorn/config.json\033[0m\n")

    if "--model" in args:
        idx = args.index("--model") + 1
        if idx < len(args):
            settings.model = args[idx]

    if "--flash" in args:
        idx = args.index("--flash") + 1
        if idx < len(args):
            settings.flash_model = args[idx]

    if "--project" in args:
        idx = args.index("--project") + 1
        if idx < len(args):
            settings.project = args[idx]

    if "--no-stream" in args:
        settings.streaming = False

    if "--no-routing" in args:
        settings.use_smart_routing = False

    if "--no-session" in args:
        settings.persist_sessions = False

    if "--unsafe" in args:
        settings.permission_rules = {k: "safe" for k in settings.permission_rules}
        print("\033[33m  Warning: Running in UNSAFE mode — all actions auto-approved!\033[0m")

    from acorn.core.agent import AcornAgent
    agent = AcornAgent(settings=settings)
    agent.run()


if __name__ == "__main__":
    main()
