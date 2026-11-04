"""Demo scenarios. Each one fixes the clock, the dialed line, the caller's phone
number, and the merchant accounts the mock backend knows about."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Merchant:
    merchant_id: str
    name: str
    ani: str
    postal_code: str
    collections_hold: bool = False
    fraud_hold_placed: date | None = None
    bank_update_case_last4: str | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    now_et: str
    dialed_line: str
    ani: str
    merchants: tuple[Merchant, ...] = field(default_factory=tuple)
    failing_tools: frozenset[str] = frozenset()
    expected_path: str = ""


BLUE_FERN_ANI = "+12125550147"

_blue_fern = dict(
    merchant_id="4472190",
    name="Blue Fern Café",
    ani=BLUE_FERN_ANI,
    postal_code="10013",
)

SCENARIOS: dict[str, Scenario] = {
    s.id: s
    for s in [
        Scenario(
            id="collections_hold_open",
            description="Collections hold, weekday business hours.",
            now_et="2026-11-04T10:30:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern, collections_hold=True),),
            expected_path="3A: transfer to collections",
        ),
        Scenario(
            id="collections_hold_after_hours",
            description="Collections hold plus a 7-day-old fraud hold, weekday evening.",
            now_et="2026-11-04T19:15:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(
                Merchant(**_blue_fern, collections_hold=True, fraud_hold_placed=date(2026, 10, 28)),
            ),
            expected_path="3A skipped -> 3B aged after hours: email message -> step 4 without specialist option",
        ),
        Scenario(
            id="fraud_hold_recent",
            description="Fraud hold placed 2 days ago, business hours.",
            now_et="2026-11-04T11:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern, fraud_hold_placed=date(2026, 11, 2)),),
            expected_path="3B recent: 'placed on Monday, November 2nd' -> step 4 with specialist option",
        ),
        Scenario(
            id="fraud_hold_boundary",
            description="Fraud hold placed exactly 4 days ago, business hours.",
            now_et="2026-11-04T09:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern, fraud_hold_placed=date(2026, 10, 31)),),
            expected_path="3B recent (4 days counts as recent) -> step 4",
        ),
        Scenario(
            id="fraud_hold_aged_open",
            description="Fraud hold placed 7 days ago, business hours.",
            now_et="2026-11-04T14:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern, fraud_hold_placed=date(2026, 10, 28)),),
            expected_path="3B aged in hours: transfer to fraud",
        ),
        Scenario(
            id="fraud_hold_aged_weekend",
            description="Fraud hold placed 10 days ago, Saturday morning.",
            now_et="2026-11-07T10:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern, fraud_hold_placed=date(2026, 10, 28)),),
            expected_path="3B aged after hours: email message -> step 4 without specialist option",
        ),
        Scenario(
            id="bank_update_case",
            description="Open bank account update case, no holds.",
            now_et="2026-11-04T13:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern, bank_update_case_last4="4821"),),
            expected_path="3C -> step 5 callback window -> create_callback_case -> main menu",
        ),
        Scenario(
            id="no_issues",
            description="Clean account.",
            now_et="2026-11-04T12:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern),),
            expected_path="3D -> main menu",
        ),
        Scenario(
            id="auth_postal_fallback",
            description="Calling from an unregistered phone; postal code 10013 succeeds.",
            now_et="2026-11-04T11:00:00",
            dialed_line="US_MAIN",
            ani="+16465550199",
            merchants=(Merchant(**_blue_fern, fraud_hold_placed=date(2026, 11, 2)),),
            expected_path="auth by phone fails -> ask postal code -> success -> 3B recent",
        ),
        Scenario(
            id="auth_fail",
            description="Unregistered phone and no postal code will match.",
            now_et="2026-11-04T11:00:00",
            dialed_line="US_MAIN",
            ani="+16465550199",
            merchants=(Merchant(**{**_blue_fern, "postal_code": "99999"}),),
            expected_path="two failed tries -> 'I wasn't able to identify you' -> main menu",
        ),
        Scenario(
            id="canada_line",
            description="Canada main line, Montréal merchant with a recent fraud hold.",
            now_et="2026-11-04T10:00:00",
            dialed_line="CA_MAIN",
            ani="+15145550123",
            merchants=(
                Merchant(
                    merchant_id="8830417",
                    name="Boulangerie Saint-Laurent",
                    ani="+15145550123",
                    postal_code="H2X 1Y4",
                    fraud_hold_placed=date(2026, 11, 3),
                ),
            ),
            expected_path="bilingual greeting -> French or English -> 3B recent",
        ),
        Scenario(
            id="status_tool_failure",
            description="get_account_status is down.",
            now_et="2026-11-04T11:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern),),
            failing_tools=frozenset({"get_account_status"}),
            expected_path="brief apology -> offer main menu or transfer",
        ),
    ]
}

DEFAULT_SCENARIO = "fraud_hold_recent"

DEMO_MENU: tuple[tuple[int, str, str], ...] = (
    (1, "fraud_hold_recent", "a recent fraud hold"),
    (2, "fraud_hold_aged_open", "an older fraud hold that goes to a specialist"),
    (3, "fraud_hold_aged_weekend", "an older fraud hold after hours"),
    (4, "collections_hold_open", "a collections hold"),
    (5, "bank_update_case", "a bank account update with a callback"),
    (6, "no_issues", "an account with no issues"),
    (7, "auth_postal_fallback", "a caller verified by zip code"),
    (8, "auth_fail", "a caller who can't be verified"),
    (9, "canada_line", "a call on the Canada line, in French or English"),
    (10, "status_tool_failure", "a system outage"),
)
