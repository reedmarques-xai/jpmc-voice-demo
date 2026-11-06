"""The "My deposit is short" scenario: a fixed clock, the dialed line, the caller's
phone number, and the merchant account the mock backend knows about."""

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


BLUE_FERN_ANI = "+12125550147"

_STANDARD_FEES = (
    Fee("Processing fees", 214.37, "The per-transaction rate for card sales in October.", recurring=True),
    Fee("Monthly service fee", 9.95, "The standard monthly account fee.", recurring=True),
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

BLUE_FERN = Merchant(
    merchant_id="4472190",
    name="Blue Fern Café",
    ani=BLUE_FERN_ANI,
    postal_code="10013",
    deposit_account_last4="4821",
    email_on_file=os.environ.get("RECAP_EMAIL_TO") or "owner@bluefern.example",
    deposits=(
        _SHORT_SUNDAY_DEPOSIT,
        Deposit(batch_date=date(2026, 11, 2), gross_sales=1688.40, fees=32.94, status="posted",
                deposit_date=date(2026, 11, 3)),
        Deposit(batch_date=date(2026, 11, 3), gross_sales=1912.15, fees=37.29, status="posted",
                deposit_date=date(2026, 11, 4)),
        Deposit(batch_date=date(2026, 11, 4), gross_sales=2054.80, fees=40.07, status="scheduled",
                deposit_date=date(2026, 11, 6)),
    ),
    disputes=(_SHORT_DEPOSIT_DISPUTE,),
    statement=Statement(period="October 2026", fees=_STANDARD_FEES),
)

SCENARIO = Scenario(
    id="deposit_short",
    description="Sunday's deposit is $365.10 short: American Express pays directly, a Visa chargeback, and fees.",
    now_et="2026-11-05T10:00:00",
    dialed_line="US_MAIN",
    ani=BLUE_FERN_ANI,
    merchants=(BLUE_FERN,),
)
