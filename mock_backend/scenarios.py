"""Demo scenarios. Each one fixes the clock, the dialed line, the caller's phone
number, and the merchant accounts the mock backend knows about."""

import os
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Adjustment:
    kind: str
    amount: float
    description: str
    dispute_id: str | None = None
    customer_wording: str = ""
    next_step: str = ""
    internal: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Deposit:
    batch_date: date
    gross_sales: float
    fees: float
    status: str
    deposit_date: date
    bank_account_last4: str = "4821"
    adjustments: tuple[Adjustment, ...] = ()
    status_note: str = ""
    batch_count: int = 1


@dataclass(frozen=True)
class Dispute:
    dispute_id: str
    card_brand: str
    amount: float
    reason: str
    transaction_date: date
    received_date: date
    status: str
    response_due: date | None = None
    merchant_guidance: str = ""
    time_sensitive: bool = False


@dataclass(frozen=True)
class Fee:
    name: str
    amount: float
    explanation: str
    recurring: bool = True
    waivable: bool = False


@dataclass(frozen=True)
class Statement:
    period: str
    fees: tuple[Fee, ...]


@dataclass(frozen=True)
class BankChangeRequest:
    new_account_last4: str
    current_account_last4: str
    requested_date: date
    channel: str


@dataclass(frozen=True)
class Merchant:
    merchant_id: str
    name: str
    ani: str
    postal_code: str
    deposit_account_last4: str | None = None
    email_on_file: str | None = None
    collections_hold: bool = False
    fraud_hold_placed: date | None = None
    bank_change: BankChangeRequest | None = None
    deposits: tuple[Deposit, ...] = ()
    disputes: tuple[Dispute, ...] = ()
    statement: Statement | None = None


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

_NORMAL_DEPOSITS = (
    Deposit(batch_date=date(2026, 11, 3), gross_sales=2481.40, fees=62.84, status="posted",
            deposit_date=date(2026, 11, 4)),
    Deposit(batch_date=date(2026, 11, 2), gross_sales=1976.25, fees=50.12, status="posted",
            deposit_date=date(2026, 11, 3)),
)

_STANDARD_FEES = (
    Fee("Processing fees", 214.37, "The per-transaction rate for card sales in October.", recurring=True),
    Fee("Monthly service fee", 9.95, "The standard monthly account fee.", recurring=True),
)

_NORMAL_STATEMENT = Statement(period="October 2026", fees=_STANDARD_FEES)

_blue_fern = dict(
    merchant_id="4472190",
    name="Blue Fern Café",
    ani=BLUE_FERN_ANI,
    postal_code="10013",
    deposit_account_last4="4821",
    email_on_file=os.environ.get("RECAP_EMAIL_TO") or "owner@bluefern.example",
    deposits=_NORMAL_DEPOSITS,
    statement=_NORMAL_STATEMENT,
)

AMEX_PHONE_SPOKEN = "1-800-528-5200"

_SHORT_SUNDAY_DEPOSIT = Deposit(
    batch_date=date(2026, 11, 1),
    batch_count=2,
    gross_sales=2311.75,
    fees=45.10,
    status="posted",
    deposit_date=date(2026, 11, 2),
    adjustments=(
        Adjustment(
            kind="amex_paid_directly",
            amount=200.00,
            description="American Express sales",
            customer_wording="in American Express sales. Those aren't paid by us; American Express pays you directly.",
            next_step=("your American Express setup looks right, so they'll pay you separately. "
                       f"If you don't see it, call them at {AMEX_PHONE_SPOKEN}."),
            internal=(("amex_service_type", "conveyed"), ("amex_se_number", "9417263850")),
        ),
        Adjustment(
            kind="chargeback",
            amount=120.00,
            description="Visa chargeback",
            dispute_id="DP-90417",
            customer_wording="taken back for a chargeback on one Visa transaction.",
        ),
    ),
)

_SHORT_DEPOSIT_DISPUTE = Dispute(
    dispute_id="DP-90417",
    card_brand="Visa",
    amount=120.00,
    reason="the cardholder disputed the sale",
    transaction_date=date(2026, 10, 24),
    received_date=date(2026, 11, 1),
    status="waiting_for_merchant_response",
    merchant_guidance="Send all your evidence together in one package, such as the receipt and proof of delivery.",
    time_sensitive=True,
)

_CHARGEBACK = Dispute(
    dispute_id="DP-88213",
    card_brand="Visa",
    amount=412.30,
    reason="the cardholder says they didn't receive the merchandise",
    transaction_date=date(2026, 10, 9),
    received_date=date(2026, 11, 3),
    response_due=date(2026, 11, 18),
    status="open",
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
            merchants=(Merchant(**_blue_fern, bank_change=BankChangeRequest(
                new_account_last4="9034", current_account_last4="4821",
                requested_date=date(2026, 11, 3), channel="online")),),
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
            id="missing_deposit",
            description="Last night's deposit was sent this morning and hasn't posted yet.",
            now_et="2026-11-04T10:15:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**{**_blue_fern, "deposits": (
                Deposit(batch_date=date(2026, 11, 3), gross_sales=2418.56, fees=61.22, status="sent",
                        deposit_date=date(2026, 11, 4),
                        status_note="Sent to the bank this morning. Most banks post it by the end of the day."),
                _NORMAL_DEPOSITS[1],
            )}),),
            expected_path="3D main menu -> 'my deposit didn't arrive' -> get_recent_deposits -> sent today, posts by end of day",
        ),
        Scenario(
            id="short_deposit_chargeback",
            description="Today's deposit is $412.30 short because of a Visa chargeback.",
            now_et="2026-11-04T11:30:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**{**_blue_fern, "disputes": (_CHARGEBACK,), "deposits": (
                Deposit(batch_date=date(2026, 11, 3), gross_sales=3150.00, fees=78.75, status="posted",
                        deposit_date=date(2026, 11, 4),
                        adjustments=(Adjustment("chargeback", 412.30, "Visa chargeback", "DP-88213"),)),
                _NORMAL_DEPOSITS[1],
            )}),),
            expected_path="3D main menu -> 'my deposit is short' -> deposit breakdown -> get_disputes -> respond by Nov 18 or transfer to disputes",
        ),
        Scenario(
            id="unrecognized_bank_change",
            description="A bank account change the merchant says they didn't request.",
            now_et="2026-11-04T10:45:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**_blue_fern, bank_change=BankChangeRequest(
                new_account_last4="7716", current_account_last4="4821",
                requested_date=date(2026, 11, 3), channel="online")),),
            expected_path="3C bank change -> caller says they didn't request it -> report_unrecognized_bank_change -> transfer to fraud",
        ),
        Scenario(
            id="fee_question",
            description="October statement has a PCI non-compliance fee and a monthly minimum fee.",
            now_et="2026-11-04T13:30:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**{**_blue_fern, "statement": Statement(period="October 2026", fees=_STANDARD_FEES + (
                Fee("PCI non-compliance fee", 19.95,
                    "Charged because this year's PCI security questionnaire hasn't been completed. "
                    "It stops once the questionnaire is done.", recurring=True),
                Fee("Monthly minimum fee", 35.63,
                    "Processing fees were $214.37 in October, below the $250 monthly minimum, "
                    "so the $35.63 difference was charged.", recurring=True),
            ))}),),
            expected_path="3D main menu -> 'what's this fee' -> get_statement_fees -> explain -> offer statements team",
        ),
        Scenario(
            id="deposit_short",
            description="Sunday's deposit is $365.10 short: American Express pays directly, a Visa chargeback, and fees.",
            now_et="2026-11-05T10:00:00",
            dialed_line="US_MAIN",
            ani=BLUE_FERN_ANI,
            merchants=(Merchant(**{**_blue_fern, "disputes": (_SHORT_DEPOSIT_DISPUTE,), "deposits": (
                _SHORT_SUNDAY_DEPOSIT,
                Deposit(batch_date=date(2026, 11, 2), gross_sales=1688.40, fees=32.94, status="posted",
                        deposit_date=date(2026, 11, 3)),
                Deposit(batch_date=date(2026, 11, 3), gross_sales=1912.15, fees=37.29, status="posted",
                        deposit_date=date(2026, 11, 4)),
                Deposit(batch_date=date(2026, 11, 4), gross_sales=2054.80, fees=40.07, status="scheduled",
                        deposit_date=date(2026, 11, 6)),
            )}),),
            expected_path=("verify by last four -> 'Sunday is short' -> get_deposit_reconciliation -> "
                           "get_disputes (no deadline) -> 'yesterday missing' -> get_recent_deposits: not yet due"),
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
    (1, "fraud_hold_recent", "a recent funds hold"),
    (2, "fraud_hold_aged_open", "a funds hold that's been in review for a while"),
    (3, "missing_deposit", "a deposit that hasn't arrived"),
    (4, "fee_question", "a fee they don't recognize"),
    (5, "bank_update_case", "updating their bank account"),
    (6, "unrecognized_bank_change", "a bank account change they didn't make"),
)
