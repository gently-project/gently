"""Command-line entry point for ``python -m gently.debug``."""

from .analyzer import main


if __name__ == "__main__":
    raise SystemExit(main())
