"""Usage:
    python -m mock_backend scenarios
    python -m mock_backend repl [--scenario ID]
    python -m mock_backend serve [--scenario ID] [--port 8787]
    python -m mock_backend session [--voice Ara]
"""

import argparse
import json
import shlex
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .backend import MockBackend
from .scenarios import DEFAULT_SCENARIO, SCENARIOS
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
    state = {"backend": MockBackend(args.scenario)}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: object) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            b = state["backend"]
            if path == "/scenarios":
                self._send(200, [{"id": s.id, "description": s.description, "expected": s.expected_path,
                                  "active": s.id == b.scenario.id} for s in SCENARIOS.values()])
            elif path == "/state":
                self._send(200, {"scenario": b.scenario.id, "authenticated": b.authenticated_merchant_id,
                                 "cases": b.cases, "transfers": b.transfers, "log": b.log})
            elif path == "/session":
                self._send(200, build_session_update())
            else:
                self._send(404, {"error": "Not found"})

        def do_POST(self) -> None:
            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if url.path == "/reset":
                scenario = parse_qs(url.query).get("scenario", [state["backend"].scenario.id])[0]
                try:
                    state["backend"] = MockBackend(scenario)
                except KeyError as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(200, {"scenario": scenario})
            if url.path.startswith("/tools/"):
                try:
                    tool_args = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    return self._send(400, {"error": "Body must be JSON"})
                return self._send(200, state["backend"].call(url.path.removeprefix("/tools/"), tool_args))
            self._send(404, {"error": "Not found"})

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Mock tools on http://127.0.0.1:{args.port} (scenario: {args.scenario})")
    print("POST /tools/<name> with JSON args | POST /reset?scenario=<id> | GET /scenarios /state /session")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


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
    p.add_argument("--scenario", default=DEFAULT_SCENARIO, choices=SCENARIOS)
    p.add_argument("--port", type=int, default=8787)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("session")
    p.add_argument("--voice", default="Ara")
    p.set_defaults(func=cmd_session)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
