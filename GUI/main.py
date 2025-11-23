"""Entry point for the AUBus PyQt client with modern themes."""

from __future__ import annotations

import argparse
from typing import List, Optional

from gui import run
from server_api import ServerAPI


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the AUBus desktop client with modern UI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Theme Options:
  modern_light    Clean, bright interface with blue accents (default)
  modern_dark     Sleek dark mode with vibrant highlights
  ocean           Professional cyan/teal theme inspired by water
        """,
    )
    parser.add_argument(
        "--server-host",
        default="127.0.0.1",
        help="Backend server hostname or IP (default: %(default)s).",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=5000,
        help="Backend server TCP port (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Socket timeout in seconds when calling the backend (default: %(default)s).",
    )
    parser.add_argument(
        "--theme",
        default="modern_light",
        choices=["modern_light", "modern_dark", "ocean"],
        help="Choose your preferred theme (default: modern_light).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)

    print(f"Starting AUBus with theme: {args.theme}")

    api: ServerAPI = ServerAPI(
        host=args.server_host, port=args.server_port, timeout=args.timeout
    )
    print(f"Connected to backend at {args.server_host}:{args.server_port}")

    run(api=api, theme=args.theme)


if __name__ == "__main__":
    main()
