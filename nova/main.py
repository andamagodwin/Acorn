#!/usr/bin/env python3
"""Nova Agent — entry point."""
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nova.core.agent import NovaAgent
from nova.config.settings import NovaSettings


def main():
    settings = NovaSettings(
        working_dir=os.getcwd(),
    )
    agent = NovaAgent(settings=settings)
    agent.run()


if __name__ == "__main__":
    main()
