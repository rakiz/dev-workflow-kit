#!/usr/bin/env python3
"""List a notes directory (default: notes/ next to this script), one file name per line."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def list_notes(directory):
    return sorted(os.listdir(directory))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    directory = argv[-1] if argv else os.path.join(HERE, "notes")
    for name in list_notes(directory):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
