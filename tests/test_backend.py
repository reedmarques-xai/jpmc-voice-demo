import json
import os
import unittest
from unittest import mock
from urllib.error import URLError

from mock_backend import SCENARIOS, MockBackend, build_session_update, mailer
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


class DepositShortTests(unittest.TestCase):
    def setUp(self):
        self.b = MockBackend("deposit_short")
        r = self.b.call("authenticate_merchant", {"merchant_id": BLUE_FERN, "bank_account_last4": "4821"})
        self.assertTrue(r["authenticated"], r)

    def test_last_four_verification(self):
        b = MockBackend("deposit_short")
        self.assertEqual(b.call("authenticate_merchant", {"merchant_id": BLUE_FERN, "bank_account_last4": "1234"}),
                         {"authenticated": False})
        self.assertIn("error", b.call("get_deposit_reconciliation", {"merchant_id": BLUE_FERN, "batch_date": "Sunday"}))
        self.assertTrue(b.call("authenticate_merchant", {"merchant_id": BLUE_FERN,
                                                         "bank_account_last4": "4 8 2 1"})["authenticated"])

    def test_reconciliation_line(self):
        r = self.b.call("get_deposit_reconciliation", {"merchant_id": BLUE_FERN, "batch_date": "Sunday"})
        self.assertEqual((r["batch_day_spoken"], r["batches_total"], r["deposited"], r["difference"]),
                         ("Sunday", "$2,311.75", "$1,946.65", "$365.10"))
        self.assertEqual((r["unexplained"], r["fully_explained"], r["holds"], r["batch_count"]),
                         ("$0.00", True, "none", 2))

    def test_causes_largest_first_with_customer_wording(self):
        causes = self.b.call("get_deposit_reconciliation",
                             {"merchant_id": BLUE_FERN, "batch_date": "Sunday"})["causes"]
        self.assertEqual([c["amount"] for c in causes], ["$200", "$120", "$45.10"])
        self.assertEqual([c["type"] for c in causes], ["amex_paid_directly", "chargeback", "processing_fees"])
        self.assertEqual(causes[0]["next_step"],
                         "For the $200, your American Express setup looks right, so they'll pay you separately. "
                         "If you don't see it, call them at 1-800-528-5200.")

    def test_internal_terms_kept_out_of_spoken_fields(self):
        r = self.b.call("get_deposit_reconciliation", {"merchant_id": BLUE_FERN, "batch_date": "Sunday"})
        self.assertEqual(r["internal_do_not_say"]["amex_service_type"], "conveyed")
        spoken = json.dumps({k: v for k, v in r.items() if k != "internal_do_not_say"}).lower()
        for term in ("conveyed", "service type", "9417263850", " se "):
            self.assertNotIn(term, spoken)

    def test_batch_date_formats(self):
        for value in ("Sunday", "sunday", "last Sunday", "2026-11-01"):
            r = self.b.call("get_deposit_reconciliation", {"merchant_id": BLUE_FERN, "batch_date": value})
            self.assertEqual(r["batches_total"], "$2,311.75", value)
        y = self.b.call("get_deposit_reconciliation", {"merchant_id": BLUE_FERN, "batch_date": "yesterday"})
        self.assertEqual(y["batch_date_spoken"], "Wednesday, November 4th")
        self.assertIn("error", self.b.call("get_deposit_reconciliation",
                                           {"merchant_id": BLUE_FERN, "batch_date": "next fortnight"}))

    def test_chargeback_has_no_deadline(self):
        d = self.b.call("get_disputes", {"merchant_id": BLUE_FERN})["disputes"][0]
        self.assertEqual((d["amount"], d["status"], d["response_due_known"], d["time_sensitive"]),
                         ("$120", "waiting_for_merchant_response", False, True))
        self.assertNotIn("response_due_spoken", d)
        self.assertNotIn("days_to_respond", d)
        self.assertTrue(d["merchant_guidance"].startswith("Send all your evidence together in one package"))

    def test_yesterday_is_not_yet_due(self):
        latest = self.b.call("get_recent_deposits", {"merchant_id": BLUE_FERN})["deposits"][0]
        self.assertEqual((latest["batch_date_relative_spoken"], latest["timing"], latest["deposit_date_relative_spoken"]),
                         ("yesterday, Wednesday the 4th", "not_yet_due", "tomorrow, Friday the 6th"))

    def test_existing_deadline_scenario_unchanged(self):
        b = authed("short_deposit_chargeback")
        d = b.call("get_disputes", {"merchant_id": BLUE_FERN})["disputes"][0]
        self.assertTrue(d["response_due_known"])
        self.assertEqual(d["response_due_spoken"], "Wednesday, November 18th")


class EmailRecapTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ)
        self.env.start()
        os.environ.pop("RESEND_API_KEY", None)
        self.addCleanup(self.env.stop)
        self.b = authed("deposit_short", bank_account_last4="4821")
        self.email = self.b.scenario.merchants[0].email_on_file

    def _send(self, b=None):
        return (b or self.b).call("send_recap_email", {"merchant_id": BLUE_FERN, "batch_date": "Sunday"})

    def test_requires_authentication(self):
        b = MockBackend("deposit_short")
        self.assertIn("error", b.call("get_email_on_file", {"merchant_id": BLUE_FERN}))
        self.assertIn("error", self._send(b))

    def test_email_on_file_is_spelled_out(self):
        r = self.b.call("get_email_on_file", {"merchant_id": BLUE_FERN})
        self.assertEqual((r["email_on_file"], r["email"]), (True, self.email))
        self.assertEqual(r["email_spoken"], mailer.spoken_email(self.email))
        self.assertEqual(mailer.spoken_email("R.Marques@x.ai"), "r dot m-a-r-q-u-e-s at x dot a-i")
        self.assertEqual(mailer.spoken_email("owner_1+demo@blue-fern.com"),
                         "o-w-n-e-r underscore 1 plus d-e-m-o at b-l-u-e dash f-e-r-n dot com")

    def test_must_look_up_email_before_sending(self):
        self.assertIn("get_email_on_file", self._send()["error"])
        self.assertEqual(self.b.recaps, [])

    def test_recap_contents(self):
        self.b.call("get_email_on_file", {"merchant_id": BLUE_FERN})
        r = self._send()
        self.assertEqual((r["sent"], r["delivery"], r["to_spoken"]), (True, "preview", mailer.spoken_email(self.email)))
        recap = self.b.recaps[0]
        self.assertEqual((recap["to"], recap["subject"]), (self.email, "Your deposit recap for Sunday, November 1st"))
        for expected in ("$2,311.75", "$1,946.65", "$365.10", "$200 in American Express sales",
                         "$120 taken back for a chargeback", "$45.10 in processing fees", "1-800-528-5200",
                         "Send all your evidence together in one package", "Friday, November 6th"):
            self.assertIn(expected, recap["text"])
        for internal in ("conveyed", "9417263850", "service type", "respond by"):
            self.assertNotIn(internal, recap["text"].lower())

    def test_sends_once_per_call(self):
        self.b.call("get_email_on_file", {"merchant_id": BLUE_FERN})
        self._send()
        self.assertTrue(self._send()["already_sent"])
        self.assertEqual(len(self.b.recaps), 1)

    def test_sends_through_resend_when_key_is_set(self):
        os.environ.update(RESEND_API_KEY="re_test", RECAP_EMAIL_FROM="Merchant Services <recap@example.com>")
        self.b.call("get_email_on_file", {"merchant_id": BLUE_FERN})
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id": "email_123"}'
        with mock.patch("mock_backend.mailer.urllib.request.urlopen", return_value=response) as urlopen:
            r = self._send()
        self.assertEqual((r["sent"], r["delivery"]), (True, "resend"))
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, mailer.RESEND_URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test")
        self.assertEqual((payload["from"], payload["to"]), ("Merchant Services <recap@example.com>", [self.email]))
        self.assertIn("$365.10", payload["text"])
        self.assertIn("<li>", payload["html"])
        self.assertEqual(self.b.recaps[0]["id"], "email_123")

    def test_send_failure_is_reported_and_can_retry(self):
        os.environ["RESEND_API_KEY"] = "re_test"
        self.b.call("get_email_on_file", {"merchant_id": BLUE_FERN})
        with mock.patch("mock_backend.mailer.urllib.request.urlopen", side_effect=URLError("down")):
            self.assertEqual(self._send(), {"error": "Couldn't send the recap email right now."})
        self.assertEqual(self.b.recaps[0]["status"], "failed")
        os.environ.pop("RESEND_API_KEY")
        self.assertTrue(self._send()["sent"])


class DepositShortToolFileTests(unittest.TestCase):
    def test_uses_shared_urls_and_known_params(self):
        import pathlib
        shared = {t["name"]: t for t in load_tools()}
        path = pathlib.Path(__file__).resolve().parent.parent / "tools" / "deposit_short_tools.json"
        for tool in json.loads(path.read_text()):
            self.assertNotIn("?", tool["url"])
            self.assertTrue(tool["url"].endswith(f"/tools/{tool['name']}"))
            self.assertLessEqual(set(tool["parameters"]["properties"]),
                                 set(shared[tool["name"]]["parameters"]["properties"]), tool["name"])


if __name__ == "__main__":
    unittest.main()
