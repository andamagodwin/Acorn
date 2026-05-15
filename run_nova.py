#!/usr/bin/env python3
"""Quick launcher — run this from anywhere."""
import sys
import os

# Ensure the project root is in the path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from nova.core.agent import NovaAgent
from nova.config.settings import NovaSettings


def main():
    working_dir = os.getcwd()
    settings = NovaSettings(working_dir=working_dir)

    # CLI argument overrides
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print("""
Nova v2.0 — Autonomous Coding Agent

Usage: nova [options]

Options:
  --model <name>     Set the Pro model (default: gemini-2.5-pro)
  --flash <name>     Set the Flash model (default: gemini-2.5-flash)
  --no-stream        Disable streaming (wait for full response)
  --no-routing       Disable smart routing (always use Pro)
  --no-session       Disable session persistence
  --unsafe           Auto-approve all actions (dangerous!)
  --project <id>     Override GCP project ID
  -h, --help         Show this help
        """)
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
        print("⚠️  Running in UNSAFE mode — all actions auto-approved!")

    agent = NovaAgent(settings=settings)
    agent.run()


if __name__ == "__main__":
    main()
