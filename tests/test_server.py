import json
import os
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mock_backend.server import create_server

AUTH_ARGS = {"merchant_id": "4472190", "ani": "+12125550147"}


class ServerTestCase(unittest.TestCase):
    env: dict[str, str] = {}

    def setUp(self):
        with mock.patch.dict(os.environ, self.env, clear=False):
            for key in ("API_KEY", "PUBLIC_BASE_URL", "RAILWAY_PUBLIC_DOMAIN"):
                if key not in self.env:
                    os.environ.pop(key, None)
            self.server = create_server("127.0.0.1", 0, "fraud_hold_recent")
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except HTTPError as err:
            return err.code, json.loads(err.read())


class OpenServerTests(ServerTestCase):
    def test_health(self):
        self.assertEqual(self.request("GET", "/health"), (200, {
            "status": "ok", "service": "chase-merchant-voice-tools", "default_scenario": "fraud_hold_recent"}))

    def test_tool_listing_has_one_url_per_tool(self):
        status, tools = self.request("GET", "/tools")
        self.assertEqual(status, 200)
        self.assertEqual(len(tools), 6)
        for t in tools:
            self.assertEqual(t["url"], f"{self.base}/tools/{t['name']}")
            self.assertEqual(t["method"], "POST")
        self.assertEqual(self.request("GET", "/tools/transfer")[1]["name"], "transfer")
        self.assertEqual(self.request("GET", "/tools/nope")[0], 404)

    def test_calls_are_isolated(self):
        a, b = {"X-Call-Id": "a"}, {"X-Call-Id": "b"}
        self.assertTrue(self.request("POST", "/tools/authenticate_merchant", AUTH_ARGS, a)[1]["authenticated"])
        self.assertIn("fraud_hold", self.request("POST", "/tools/get_account_status", {"merchant_id": "4472190"}, a)[1])
        self.assertIn("error", self.request("POST", "/tools/get_account_status", {"merchant_id": "4472190"}, b)[1])

    def test_scenario_from_query(self):
        q = "?scenario=bank_update_case&call_id=c"
        self.request("POST", f"/tools/authenticate_merchant{q}", AUTH_ARGS)
        status = self.request("POST", f"/tools/get_account_status{q}", {"merchant_id": "4472190"})[1]
        self.assertTrue(status["bank_account_update_case"]["open"])
        self.assertEqual(self.request("POST", "/tools/get_call_context?scenario=bogus")[0], 400)

    def test_wrapped_arguments(self):
        self.assertTrue(self.request("POST", "/tools/authenticate_merchant",
                                     {"arguments": json.dumps(AUTH_ARGS)})[1]["authenticated"])
        self.assertTrue(self.request("POST", "/tools/authenticate_merchant",
                                     {"arguments": AUTH_ARGS}, {"X-Call-Id": "w"})[1]["authenticated"])

    def test_reset_clears_auth(self):
        h = {"X-Call-Id": "r"}
        self.request("POST", "/tools/authenticate_merchant", AUTH_ARGS, h)
        self.request("POST", "/reset", None, h)
        self.assertIn("error", self.request("POST", "/tools/get_account_status", {"merchant_id": "4472190"}, h)[1])


class ApiKeyTests(ServerTestCase):
    env = {"API_KEY": "s3cret", "PUBLIC_BASE_URL": "https://tools.example.com"}

    def test_tool_calls_require_key(self):
        self.assertEqual(self.request("POST", "/tools/get_call_context")[0], 401)
        self.assertEqual(self.request("POST", "/tools/get_call_context", None,
                                      {"Authorization": "Bearer s3cret"})[0], 200)
        self.assertEqual(self.request("POST", "/tools/get_call_context", None, {"X-API-Key": "s3cret"})[0], 200)
        self.assertEqual(self.request("GET", "/state")[0], 401)

    def test_listing_uses_public_url_and_stays_open(self):
        status, tools = self.request("GET", "/tools")
        self.assertEqual(status, 200)
        self.assertEqual(tools[0]["url"], "https://tools.example.com/tools/get_call_context")
        self.assertEqual(self.request("GET", "/health")[0], 200)


if __name__ == "__main__":
    unittest.main()
