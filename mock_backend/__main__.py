"""Usage:
    python -m mock_backend repl
    python -m mock_backend serve [--host 127.0.0.1] [--port 8787]
    python -m mock_backend session [--voice Ara]

serve also reads HOST, PORT, API_KEY, and PUBLIC_BASE_URL from the environment.
"""

import argparse
import json
import os

from .backend import MockBackend
from .server import run
from .session import build_session_update


def cmd_repl(_: argparse.Namespace) -> None:
    backend = MockBackend()
    print(f"Scenario: {backend.scenario.description}")
    print('Enter: <tool> [json args], e.g. authenticate_merchant {"merchant_id": "4472190", "bank_account_last4": "4821"}')
    print("Other commands: reset, state, quit")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        name, _, rest = line.partition(" ")
        if name in {"quit", "exit"}:
            return
        if name == "reset":
            backend = MockBackend()
            print("Started a new call")
            continue
        if name == "state":
            print(json.dumps({"authenticated": backend.authenticated_merchant_id, "recaps": backend.recaps,
                              "transfers": backend.transfers}, indent=2, ensure_ascii=False))
            continue
        try:
            tool_args = json.loads(rest) if rest else {}
        except json.JSONDecodeError as exc:
            print(f"Bad JSON: {exc}")
            continue
        print(json.dumps(backend.call(name, tool_args), indent=2, ensure_ascii=False))


def cmd_serve(args: argparse.Namespace) -> None:
    run(args.host, args.port)


def cmd_session(args: argparse.Namespace) -> None:
    print(json.dumps(build_session_update(args.voice), indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m mock_backend")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("repl").set_defaults(func=cmd_repl)
    p = sub.add_parser("serve")
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("session")
    p.add_argument("--voice", default="Ara")
    p.set_defaults(func=cmd_session)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
