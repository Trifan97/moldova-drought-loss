"""Command line: python -m drought_loss.

Only --version exists so far. The download, run and report stages arrive with the steps
that implement them, so the help text never advertises something that does not work.
"""

import argparse

from drought_loss import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m drought_loss")
    parser.add_argument("--version", action="version", version=f"drought_loss {__version__}")
    parser.parse_args(argv)
    parser.print_help()


if __name__ == "__main__":
    main()
