"""Usage:
    python -m mock_backend scenarios
    python -m mock_backend repl [--scenario ID]
    python -m mock_backend serve [--scenario ID] [--host 127.0.0.1] [--port 8787]
    python -m mock_backend session [--voice Ara]

serve also reads HOST, PORT, DEFAULT_SCENARIO, API_KEY, and PUBLIC_BASE_URL from the environment.
"""

import argparse
import json
import os
import shlex

from .backend import MockBackend
from .scenarios import DEFAULT_SCENARIO, SCENARIOS
from .server import run
from .session import build_session_update


def cmd_scenarios(_: argparse.Namespace) -> None:
    for s in SCENARIOS.values():
        print(f"{s.id:<30} {s.description}")
        print(f"{'':<30} expected: {s.expected_path}")


def cmd_repl(args: argparse.Namespace) -> None:
    backend = MockBackend(args.scenario)
    print(f"Scenario: {backend.scenario.id} ({backend.scenario.description})")
    print('Enter: <tool> [json args], e.g. authenticate_merchant {"merchant_id": "4472190", "ani": "+12125550147"}')
    print("Other commands: scenario <id>, state, quit")
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
        if name == "scenario":
            try:
                backend = MockBackend(shlex.split(rest)[0] if rest else DEFAULT_SCENARIO)
                print(f"Switched to {backend.scenario.id}")
            except KeyError as exc:
                print(exc)
            continue
        if name == "state":
            print(json.dumps({"authenticated": backend.authenticated_merchant_id,
                              "cases": backend.cases, "transfers": backend.transfers}, indent=2))
            continue
        try:
            tool_args = json.loads(rest) if rest else {}
        except json.JSONDecodeError as exc:
            print(f"Bad JSON: {exc}")
            continue
        print(json.dumps(backend.call(name, tool_args), indent=2, ensure_ascii=False))


def cmd_serve(args: argparse.Namespace) -> None:
    run(args.host, args.port, args.scenario)


def cmd_session(args: argparse.Namespace) -> None:
    print(json.dumps(build_session_update(args.voice), indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m mock_backend")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scenarios").set_defaults(func=cmd_scenarios)
    p = sub.add_parser("repl")
    p.add_argument("--scenario", default=DEFAULT_SCENARIO, choices=SCENARIOS)
    p.set_defaults(func=cmd_repl)
    p = sub.add_parser("serve")
    p.add_argument("--scenario", default=os.environ.get("DEFAULT_SCENARIO", DEFAULT_SCENARIO), choices=SCENARIOS)
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
