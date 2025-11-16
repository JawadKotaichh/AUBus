"""Entry point for the AUBus PyQt client."""
from __future__ import annotations

import argparse
from typing import List, Optional

from gui import run
from server_api import AuthBackendServerAPI, ServerAPI


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AUBus desktop client.")
    parser.add_argument(
        "--auth-backend",
        action="store_true",
        help="Send register/login requests to the live backend instead of the mock API.",
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
        default="bolt_light",
        choices=["bolt_light", "bolt_dark", "light", "dark"],
        help="Initial GUI theme.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)
    if args.auth_backend:
        api: ServerAPI = ServerAPI(
            host=args.server_host, port=args.server_port, timeout=args.timeout
        )
    else:
        api = AuthBackendServerAPI(
            host=args.server_host, port=args.server_port, timeout=args.timeout
        )
    run(api=api, theme=args.theme)


if __name__ == "__main__":
    main()

