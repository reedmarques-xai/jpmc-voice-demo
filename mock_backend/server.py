"""HTTP server exposing each tool as its own endpoint.

Per-call state (authentication, cases, transfers) is keyed by a call ID taken
from the X-Call-Id header or ?call_id= query param; requests without one share
the "default" call. The scenario comes from ?scenario= or X-Scenario, falling
back to the DEFAULT_SCENARIO env var.
"""

import hmac
import json
import os
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .backend import MockBackend
from .scenarios import DEFAULT_SCENARIO, SCENARIOS
from .session import build_session_update, load_tools

MAX_CALLS = 500

TOOLS = {t["name"]: t for t in load_tools()}


class CallStore:
    def __init__(self, default_scenario: str):
        self.default_scenario = default_scenario
        self._calls: OrderedDict[str, MockBackend] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, call_id: str, scenario: str | None) -> MockBackend:
        with self._lock:
            backend = self._calls.get(call_id)
            if backend is None or (scenario and backend.scenario.id != scenario):
                backend = MockBackend(scenario or self.default_scenario)
                self._calls[call_id] = backend
            self._calls.move_to_end(call_id)
            while len(self._calls) > MAX_CALLS:
                self._calls.popitem(last=False)
            return backend

    def reset(self, call_id: str, scenario: str | None) -> MockBackend:
        with self._lock:
            self._calls.pop(call_id, None)
        return self.get(call_id, scenario)


def _unwrap_args(body: Any) -> dict[str, Any]:
    """Accept either the raw arguments object or a wrapper like {"arguments": {...}}
    or {"arguments": "<json string>"}, which some voice platforms send."""
    if isinstance(body, dict) and "arguments" in body:
        body = body["arguments"]
        if isinstance(body, str):
            body = json.loads(body) if body.strip() else {}
    if not isinstance(body, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return body


def make_handler(store: CallStore, api_key: str | None, public_base_url: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ChaseMockTools/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.address_string()} {fmt % args}", flush=True)

        def _send(self, status: int, body: object) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, X-API-Key, X-Call-Id, X-Scenario")

        def _query(self) -> dict[str, str]:
            return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

        def _call_id(self) -> str:
            return self.headers.get("X-Call-Id") or self._query().get("call_id") or "default"

        def _scenario(self) -> str | None:
            scenario = self._query().get("scenario") or self.headers.get("X-Scenario")
            if scenario and scenario not in SCENARIOS:
                raise ValueError(f"Unknown scenario '{scenario}'. Options: {', '.join(SCENARIOS)}")
            return scenario

        def _authorized(self) -> bool:
            if not api_key:
                return True
            auth = self.headers.get("Authorization", "")
            supplied = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            supplied = supplied or self.headers.get("X-API-Key", "")
            return hmac.compare_digest(supplied, api_key)

        def _base_url(self) -> str:
            if public_base_url:
                return public_base_url.rstrip("/")
            proto = self.headers.get("X-Forwarded-Proto", "http")
            return f"{proto}://{self.headers.get('Host', 'localhost')}"

        def _tool_listing(self, name: str) -> dict[str, Any]:
            tool = TOOLS[name]
            return {
                "name": name,
                "method": "POST",
                "url": f"{self._base_url()}/tools/{name}",
                "description": tool["description"],
                "parameters": tool["parameters"],
            }

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path in {"/", "/health"}:
                return self._send(200, {"status": "ok", "service": "chase-merchant-voice-tools",
                                        "default_scenario": store.default_scenario})
            if path == "/tools":
                return self._send(200, [self._tool_listing(n) for n in TOOLS])
            if path.startswith("/tools/"):
                name = path.removeprefix("/tools/")
                if name not in TOOLS:
                    return self._send(404, {"error": f"Unknown tool '{name}'."})
                return self._send(200, self._tool_listing(name))
            if path == "/scenarios":
                return self._send(200, [{"id": s.id, "description": s.description, "expected": s.expected_path,
                                         "default": s.id == store.default_scenario} for s in SCENARIOS.values()])
            if path == "/session":
                return self._send(200, build_session_update(self._query().get("voice", "Ara")))
            if path == "/state":
                if not self._authorized():
                    return self._send(401, {"error": "Unauthorized"})
                try:
                    b = store.get(self._call_id(), self._scenario())
                except ValueError as exc:
                    return self._send(400, {"error": str(exc)})
                return self._send(200, {"call_id": self._call_id(), "scenario": b.scenario.id,
                                        "authenticated": b.authenticated_merchant_id, "cases": b.cases,
                                        "transfers": b.transfers, "log": b.log})
            self._send(404, {"error": "Not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path.rstrip("/")
            if not self._authorized():
                return self._send(401, {"error": "Unauthorized"})
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                scenario = self._scenario()
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            if path == "/reset":
                b = store.reset(self._call_id(), scenario)
                return self._send(200, {"call_id": self._call_id(), "scenario": b.scenario.id})
            if path.startswith("/tools/"):
                name = path.removeprefix("/tools/")
                if name not in TOOLS:
                    return self._send(404, {"error": f"Unknown tool '{name}'."})
                try:
                    args = _unwrap_args(json.loads(raw) if raw.strip() else {})
                except (json.JSONDecodeError, ValueError) as exc:
                    return self._send(400, {"error": f"Bad request body: {exc}"})
                return self._send(200, store.get(self._call_id(), scenario).call(name, args))
            self._send(404, {"error": "Not found"})

    return Handler


def create_server(host: str, port: int, default_scenario: str) -> ThreadingHTTPServer:
    if default_scenario not in SCENARIOS:
        raise KeyError(f"Unknown scenario '{default_scenario}'. Options: {', '.join(SCENARIOS)}")
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    public_base_url = os.environ.get("PUBLIC_BASE_URL") or (f"https://{railway_domain}" if railway_domain else None)
    handler = make_handler(CallStore(default_scenario), os.environ.get("API_KEY") or None, public_base_url)
    return ThreadingHTTPServer((host, port), handler)


def run(host: str, port: int, default_scenario: str) -> None:
    server = create_server(host, port, default_scenario)
    auth = "on" if os.environ.get("API_KEY") else "off"
    print(f"Mock tools listening on {host}:{port} (default scenario: {default_scenario}, api key: {auth})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
