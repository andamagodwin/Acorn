#!/usr/bin/env python3
"""Acorn Agent — entry point for the `acorn` CLI command."""
import sys
import os


def main():
    working_dir = os.getcwd()

    from acorn.config.settings import AcornSettings, AVAILABLE_MODELS
    from acorn.core.agent import AcornAgent

    settings = AcornSettings(working_dir=working_dir)

    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print("""
\033[38;2;139;90;43m Acorn v2.0\033[0m — Autonomous Coding Agent

\033[1mUsage:\033[0m acorn [options]

\033[1mOptions:\033[0m
  --model <name>     Set the Pro model (default: gemini-3.1-pro-preview)
  --flash <name>     Set the Flash model (default: gemini-3.1-flash-lite)
  --no-stream        Disable streaming (wait for full response)
  --no-routing       Disable smart routing (always use Pro)
  --no-session       Disable session persistence
  --unsafe           Auto-approve all actions (dangerous!)
  --project <id>     Override GCP project ID
  --models           List available models
  -h, --help         Show this help
        """)
        return

    if "--models" in args:
        print("\n\033[1mAvailable Models:\033[0m\n")
        for model_id, description in AVAILABLE_MODELS.items():
            print(f"  \033[36m{model_id:<30}\033[0m {description}")
        print()
        return

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

    agent = AcornAgent(settings=settings)
    agent.run()


if __name__ == "__main__":
    main()
