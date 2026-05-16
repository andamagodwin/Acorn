#!/usr/bin/env python3
"""Quick launcher — run this from anywhere."""
import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from acorn.main import main

if __name__ == "__main__":
    main()
