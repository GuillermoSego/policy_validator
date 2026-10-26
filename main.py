"""Thin wrapper so `python main.py <command>` works as well as `validator <command>`."""

import sys

from policy_validator.cli import main

if __name__ == "__main__":
    sys.exit(main())
