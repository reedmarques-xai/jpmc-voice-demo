# Chase Merchant Services Voice Agent: Mock Tools Backend

**What it is.** A small Python web service that stands in for Chase's merchant systems during voice agent demos. The xAI voice agent calls it over HTTPS, one endpoint per tool, to verify the caller, check for funds holds and pending bank account changes, explain deposits and fees, open cases, and transfer calls. Every account, amount, and date is fake and fixed per scenario, so each demo plays out the same way every time.

**Live at:** `https://jpmc-voice-demo-production.up.railway.app` (Railway, deployed from `main` of [reedmarques-xai/jpmc-voice-demo](https://github.com/reedmarques-xai/jpmc-voice-demo)). Standard-library Python only, no database; state is kept in memory per call.

## How a call works

1. **Reason for calling.** The agent opens with "What are you calling about today?" and six options. The caller's answer selects the scenario (`select_demo_scenario`).
2. **Identity.** The caller gives their Merchant ID. The agent verifies it against the caller's phone number, then falls back to zip code. Two tries; no account details before verification.
3. **Account checks, in order.** Collections hold → fraud hold (recent vs. more than 4 days old) → pending bank account change → none.
4. **Resolution.** The agent reads the scripted status, answers deposit and fee questions directly, books a callback, puts an unrecognized bank change on hold, or transfers to a specialist (weekdays 8 AM to 6 PM ET only) or a main menu team.

## Scenarios

The six on the phone menu, all using Merchant ID **4472190** (Blue Fern Café, zip 10013):

| # | Caller hears | What happens |
|---|---|---|
| 1 | A recent funds hold | Hold placed Monday, November 2nd; "allow up to 4 days" message; offers repeat, specialist, or main menu |
| 2 | A funds hold that's been in review for a while | Hold is 7 days old during business hours; transfers to the fraud team |
| 3 | A deposit that hasn't arrived | $2,357.34 sent this morning to the account ending 4821; most banks post by end of day |
| 4 | A fee you don't recognize | Explains a $19.95 PCI non-compliance fee and a $35.63 monthly minimum fee; offers statements team |
| 5 | Updating your bank account | Pending change to the account ending 9034; books a verification callback window |
| 6 | A bank account change you didn't make | Pending change to the account ending 7716; puts it on hold, opens a fraud case, transfers to fraud |

**"My deposit is short" (separate agent).** A second xAI agent runs this flow with its own prompt ([prompts/deposit_short_prompt.md](../prompts/deposit_short_prompt.md)) and tools ([tools/deposit_short_tools.json](../tools/deposit_short_tools.json)), using the same URLs as above. It silently selects the `deposit_short` scenario, opens with "Thanks for calling Merchant Services, this is WMM", and verifies by Merchant ID plus the last four of the deposit account (4821). It then explains that Sunday's $2,311.75 in card batches became a $1,946.65 deposit, with all $365.10 accounted for, largest cause first: $200 in American Express sales paid directly by American Express, a $120 Visa chargeback, and $45.10 in fees. It covers the chargeback with no made-up deadline, and treats yesterday's deposit as not yet due (arriving tomorrow, Friday the 6th) rather than missing. Internal terms like "conveyed" and the SE number are never said. It can also email the caller a recap of the charges: it reads the email on file back letter by letter, waits for a yes, and sends one recap per call, only to the address on file.

Ten more scenarios are available by ID (via `/reset?scenario=<id>` or `?scenario=<id>` on tool URLs): `collections_hold_open`, `collections_hold_after_hours`, `fraud_hold_boundary` (exactly 4 days), `fraud_hold_aged_weekend` (Saturday, specialists closed), `short_deposit_chargeback` ($412.30 Visa chargeback, respond by November 18th), `no_issues`, `auth_postal_fallback` (unrecognized phone, zip works), `auth_fail`, `canada_line` (bilingual, Merchant ID 8830417), and `status_tool_failure` (account system down).

## Endpoints

**Tools** — each is `POST /tools/<name>` with the arguments in a JSON body:

| Tool | Arguments | Purpose |
|---|---|---|
| `select_demo_scenario` | `scenario` (1–6) | Records the caller's reason; starts a fresh call on that scenario |
| `get_call_context` | none | Dialed line (US or Canada), caller phone number, current Eastern Time |
| `authenticate_merchant` | `merchant_id`, plus `ani`, `postal_code`, or `bank_account_last4` | Verifies the caller; returns business name on success |
| `get_account_status` | `merchant_id` | Collections hold, fraud hold (date, age), pending bank change |
| `is_business_hours` | `queue` (`collections`, `fraud`) | Whether specialists are open, and the hours to read aloud |
| `get_recent_deposits` | `merchant_id` | Recent batches: sales, fees, deductions, net deposit, status, and whether it's posted, not yet due, or late |
| `get_deposit_reconciliation` | `merchant_id`, `batch_date` | Explains a day's batches versus what was deposited, every cause listed largest first |
| `get_disputes` | `merchant_id` | Open chargebacks: amount, card brand, reason, guidance, and a deadline only when one exists |
| `get_statement_fees` | `merchant_id` | Last statement's fees with plain-language explanations |
| `create_callback_case` | `merchant_id`, `window` (`morning`, `midday`, `afternoon`) | Books a bank change verification callback |
| `report_unrecognized_bank_change` | `merchant_id` | Puts a pending bank change on hold and opens a fraud case |
| `get_email_on_file` | `merchant_id` | The email address on file, spelled out for reading back to the caller |
| `send_recap_email` | `merchant_id`, `batch_date` | Emails a recap of that day's charges to the address on file, once per call |
| `transfer` | `queue`, `reason` | Hands off to collections, fraud, or one of six main menu teams |

**Utility:** `GET /health` (status check) · `GET /tools` and `GET /tools/<name>` (tool definitions with public URLs) · `GET /scenarios` · `GET /session` (xAI `session.update` payload) · `GET /state` (sign-in, cases, transfers, recap emails, call log) · `GET /debug/requests` (last 50 raw requests) · `POST /reset?scenario=<id>` (start over).

## Behavior worth knowing

- **Guardrails are enforced server-side, not just in the prompt.** Account tools refuse to run before a successful sign-in. A failed sign-in never says which value didn't match. Specialist transfers fail outside business hours.
- **Built to be read aloud.** Dates come back ready to speak ("Monday, November 2nd"), amounts are pre-formatted, and only the last four digits of any account are returned, so the model never does math or reads full numbers.
- **Flexible request formats.** Arguments are accepted as a flat JSON body, wrapped in `arguments`, as a JSON string, nested in a tool-call message, as form fields, or as query parameters. Missing arguments return `tool_ran: false` with a message telling the model not to treat it as a result.
- **Per-call state.** Calls are kept separate by an `X-Call-Id` header, a `call_id` query parameter, or a call or conversation ID in the body; otherwise they share one session, which `select_demo_scenario` resets at the start of each call.
- **Optional API key.** Set `API_KEY` on Railway to require `Authorization: Bearer <key>` (or `X-API-Key`) on tool calls, `/state`, `/reset`, and `/debug/requests`.
- **Recap emails.** Set `RECAP_EMAIL_TO` to the address on file for Blue Fern Café (otherwise `owner@bluefern.example`). Set `RESEND_API_KEY` to send for real through Resend; without it, the email is built but not sent, and shows up in `/state`. `RECAP_EMAIL_FROM` overrides the sender (default `Merchant Services <onboarding@resend.dev>`).

**Run locally:** `python3 -m mock_backend serve` (port 8787) · `python3 -m mock_backend repl` · `python3 -m unittest` (56 tests).
