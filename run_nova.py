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
    # Use the directory where the user invoked nova, not where nova lives
    working_dir = os.getcwd()

    settings = NovaSettings(working_dir=working_dir)

    # Allow CLI overrides
    if "--model" in sys.argv:
        idx = sys.argv.index("--model") + 1
        if idx < len(sys.argv):
            settings.model = sys.argv[idx]

    if "--project" in sys.argv:
        idx = sys.argv.index("--project") + 1
        if idx < len(sys.argv):
            settings.project = sys.argv[idx]

    if "--unsafe" in sys.argv:
        # Elevate all permissions to auto-approve (for advanced users)
        settings.permission_rules = {k: "safe" for k in settings.permission_rules}
        print("⚠️  Running in UNSAFE mode — all actions auto-approved!")

    agent = NovaAgent(settings=settings)
    agent.run()


if __name__ == "__main__":
    main()
