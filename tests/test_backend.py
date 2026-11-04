import json
import unittest

from mock_backend import SCENARIOS, MockBackend, build_session_update
from mock_backend.backend import SERVICE_QUEUES, SPECIALIST_QUEUES
from mock_backend.session import load_tools

BLUE_FERN = "4472190"


def authed(scenario_id: str, **second_factor) -> MockBackend:
    b = MockBackend(scenario_id)
    ani = b.call("get_call_context")["ani"]
    result = b.call("authenticate_merchant", {"merchant_id": BLUE_FERN, **(second_factor or {"ani": ani})})
    assert result["authenticated"], result
    return b


class ToolSchemaTests(unittest.TestCase):
    def test_schemas_match_backend(self):
        tools = {t["name"]: t for t in load_tools()}
        self.assertEqual(set(tools) - {"select_demo_scenario"}, set(MockBackend()._tools))
        queues = set(tools["transfer"]["parameters"]["properties"]["queue"]["enum"])
        self.assertEqual(queues, SPECIALIST_QUEUES | SERVICE_QUEUES)

    def test_session_update_is_serializable(self):
        payload = build_session_update()
        self.assertEqual(payload["type"], "session.update")
        self.assertIn("Chase Merchant Services", payload["session"]["instructions"])
        json.dumps(payload)


class AuthTests(unittest.TestCase):
    def test_status_requires_auth(self):
        b = MockBackend("fraud_hold_recent")
        self.assertIn("error", b.call("get_account_status", {"merchant_id": BLUE_FERN}))

    def test_ani_success(self):
        b = authed("no_issues")
        self.assertEqual(b.authenticated_merchant_id, BLUE_FERN)

    def test_postal_fallback(self):
        b = MockBackend("auth_postal_fallback")
        ani = b.call("get_call_context")["ani"]
        self.assertFalse(b.call("authenticate_merchant", {"merchant_id": BLUE_FERN, "ani": ani})["authenticated"])
        r = b.call("authenticate_merchant", {"merchant_id": "447 2190", "postal_code": "10013"})
        self.assertEqual(r["merchant_name"], "Blue Fern Café")

    def test_failure_does_not_leak_details(self):
        b = MockBackend("auth_fail")
        r = b.call("authenticate_merchant", {"merchant_id": BLUE_FERN, "postal_code": "10013"})
        self.assertEqual(r, {"authenticated": False})
        r = b.call("authenticate_merchant", {"merchant_id": "0000000", "postal_code": "10013"})
        self.assertEqual(r, {"authenticated": False})

    def test_canadian_postal_normalized(self):
        b = MockBackend("canada_line")
        r = b.call("authenticate_merchant", {"merchant_id": "8830417", "postal_code": "h2x1y4"})
        self.assertTrue(r["authenticated"])


class FlowTests(unittest.TestCase):
    def test_collections_open_transfers(self):
        b = authed("collections_hold_open")
        self.assertTrue(b.call("get_account_status", {"merchant_id": BLUE_FERN})["collections_hold"]["active"])
        self.assertTrue(b.call("is_business_hours", {"queue": "collections"})["open"])
        self.assertTrue(b.call("transfer", {"queue": "collections", "reason": "x"})["transferred"])

    def test_collections_after_hours_falls_to_aged_fraud(self):
        b = authed("collections_hold_after_hours")
        s = b.call("get_account_status", {"merchant_id": BLUE_FERN})
        self.assertFalse(b.call("is_business_hours", {"queue": "collections"})["open"])
        self.assertGreater(s["fraud_hold"]["days_since_placed"], 4)
        self.assertIn("error", b.call("transfer", {"queue": "fraud", "reason": "x"}))

    def test_recent_fraud_hold_date(self):
        s = authed("fraud_hold_recent").call("get_account_status", {"merchant_id": BLUE_FERN})["fraud_hold"]
        self.assertEqual(s["days_since_placed"], 2)
        self.assertEqual(s["placed_date_spoken"], "Monday, November 2nd")

    def test_boundary_is_four_days(self):
        s = authed("fraud_hold_boundary").call("get_account_status", {"merchant_id": BLUE_FERN})["fraud_hold"]
        self.assertEqual(s["days_since_placed"], 4)

    def test_aged_weekend_closed(self):
        b = authed("fraud_hold_aged_weekend")
        self.assertFalse(b.call("is_business_hours", {"queue": "fraud"})["open"])

    def test_bank_update_callback(self):
        b = authed("bank_update_case")
        s = b.call("get_account_status", {"merchant_id": BLUE_FERN})
        self.assertFalse(s["fraud_hold"]["active"])
        bank = s["bank_account_update_case"]
        self.assertEqual((bank["open"], bank["bank_account_last4"], bank["current_account_last4"]),
                         (True, "9034", "4821"))
        self.assertEqual(bank["requested_date_spoken"], "Tuesday, November 3rd")
        case = b.call("create_callback_case", {"merchant_id": BLUE_FERN, "window": "midday"})
        self.assertEqual((case["category"], case["type"], case["origin"]),
                         ("ECC-Advanced Merchant Support", "DDA Research", "IVR"))
        self.assertEqual(case["window_spoken"], "10 AM and 2 PM")

    def test_service_transfer_after_hours_allowed(self):
        b = authed("fraud_hold_aged_weekend")
        self.assertTrue(b.call("transfer", {"queue": "terminal_support", "reason": "x"})["transferred"])

    def test_tool_failure(self):
        b = authed("status_tool_failure")
        self.assertIn("error", b.call("get_account_status", {"merchant_id": BLUE_FERN}))

    def test_canada_line(self):
        self.assertEqual(MockBackend("canada_line").call("get_call_context")["dialed_line"], "CA_MAIN")

    def test_missing_deposit(self):
        d = authed("missing_deposit").call("get_recent_deposits", {"merchant_id": BLUE_FERN})["deposits"][0]
        self.assertEqual((d["status"], d["net_deposit"], d["deposit_date_spoken"]),
                         ("sent", "$2,357.34", "Wednesday, November 4th"))
        self.assertIn("end of the day", d["status_note"])

    def test_short_deposit_chargeback(self):
        b = authed("short_deposit_chargeback")
        d = b.call("get_recent_deposits", {"merchant_id": BLUE_FERN})["deposits"][0]
        self.assertEqual((d["gross_sales"], d["fees"], d["net_deposit"]), ("$3,150.00", "$78.75", "$2,658.95"))
        self.assertEqual(d["adjustments"][0]["dispute_id"], "DP-88213")
        dispute = b.call("get_disputes", {"merchant_id": BLUE_FERN})["disputes"][0]
        self.assertEqual((dispute["amount"], dispute["response_due_spoken"], dispute["days_to_respond"]),
                         ("$412.30", "Wednesday, November 18th", 14))

    def test_unrecognized_bank_change(self):
        b = authed("unrecognized_bank_change")
        r = b.call("report_unrecognized_bank_change", {"merchant_id": BLUE_FERN})
        self.assertEqual((r["blocked_account_last4"], r["deposits_continue_to_last4"]), ("7716", "4821"))
        again = b.call("report_unrecognized_bank_change", {"merchant_id": BLUE_FERN})
        self.assertEqual(again["case_id"], r["case_id"])
        self.assertEqual(len(b.cases), 1)
        status = b.call("get_account_status", {"merchant_id": BLUE_FERN})["bank_account_update_case"]
        self.assertEqual(status["status"], "on_hold_fraud_review")
        self.assertTrue(b.call("transfer", {"queue": "fraud", "reason": "x"})["transferred"])

    def test_report_bank_change_without_pending_change_errors(self):
        self.assertIn("error", authed("no_issues").call("report_unrecognized_bank_change", {"merchant_id": BLUE_FERN}))

    def test_fee_question(self):
        fees = authed("fee_question").call("get_statement_fees", {"merchant_id": BLUE_FERN})
        names = {f["name"]: f["amount"] for f in fees["fees"]}
        self.assertEqual(names["PCI non-compliance fee"], "$19.95")
        self.assertEqual(names["Monthly minimum fee"], "$35.63")
        self.assertEqual(fees["total_fees"], "$279.90")

    def test_new_tools_require_auth(self):
        b = MockBackend("short_deposit_chargeback")
        for tool in ("get_recent_deposits", "get_disputes", "get_statement_fees", "report_unrecognized_bank_change"):
            self.assertIn("error", b.call(tool, {"merchant_id": BLUE_FERN}), tool)

    def test_every_scenario_loads(self):
        for sid in SCENARIOS:
            MockBackend(sid).call("get_call_context")


if __name__ == "__main__":
    unittest.main()
