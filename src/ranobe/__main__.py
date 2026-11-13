"""python -m ranobe → the desktop app.  python -m ranobe --web [--port N] → in a browser."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="ranobe")
    parser.add_argument("--web", action="store_true", help="open in a browser instead")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    try:
        from ranobe.ui.app import run
    except ImportError as e:  # Flet is the optional `ui` extra
        raise SystemExit(f"{e}\nInstall the interface: pip install -e .[ui]") from None
    run(web=args.web, port=args.port)


if __name__ == "__main__":
    main()
