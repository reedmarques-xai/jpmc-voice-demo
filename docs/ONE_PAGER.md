# Chase Merchant Services Voice Agent: Mock Tools Backend

**What it is.** A small Python web service that stands in for Chase's merchant systems during a "My deposit is short" voice agent demo. The xAI voice agent calls it over HTTPS, one endpoint per tool, to verify the caller, explain where a short deposit went, cover the chargeback, email a recap, and transfer calls. Every account, amount, and date is fake and fixed, so the demo plays out the same way every time.

**Live at:** `https://jpmc-voice-demo-production.up.railway.app` (Railway, deployed from `main` of [reedmarques-xai/jpmc-voice-demo](https://github.com/reedmarques-xai/jpmc-voice-demo)). Standard-library Python only, no database; state is kept in memory per call.

## The scenario

One merchant, **Blue Fern Café**: Merchant ID **4472190**, deposit account ending **4821**. The backend's clock is fixed at Thursday, November 5th, 2026, 10 AM Eastern.

The agent ([prompts/deposit_short_prompt.md](../prompts/deposit_short_prompt.md), tools in [tools/deposit_short_tools.json](../tools/deposit_short_tools.json)) runs the call like this:

1. **Greeting.** "Thanks for calling Merchant Services, this is WMM. Can I get your merchant ID, and confirm the last four of the account we deposit to?"
2. **Verification.** It reads both numbers back digit by digit, waits for a yes, then verifies. Two tries; nothing about the account before verification.
3. **"My deposit from Sunday is short."** Sunday's $2,311.75 in card batches (2 batches) became a $1,946.65 deposit. All $365.10 is accounted for, largest first: $200 in American Express sales that American Express pays directly, a $120 Visa chargeback, and $45.10 in fees. Nothing is on hold.
4. **The chargeback.** The cardholder disputed a $120 sale and it's waiting for a response, with guidance to send all evidence together. There's no made-up deadline. The agent offers the disputes team.
5. **Email recap.** It reads the email on file back letter by letter, waits for a yes, and sends one recap per call, only to that address.
6. **"Yesterday's deposit hasn't come in."** It isn't late: Wednesday's sales are scheduled to arrive tomorrow, Friday the 6th.

Internal terms like "conveyed" and the Amex SE number are never said.

The original funds-hold agent ([prompts/system_prompt.md](../prompts/system_prompt.md), [tools/tools.json](../tools/tools.json)) still runs against the same data. Blue Fern Café has no holds and no pending bank change, so it reaches the main menu and can answer deposit, chargeback, and fee questions.

## Endpoints

**Tools** — each is `POST /tools/<name>` with the arguments in a JSON body. The deposit-short agent uses the first six plus `transfer`.

| Tool | Arguments | Purpose |
|---|---|---|
| `authenticate_merchant` | `merchant_id`, plus `bank_account_last4`, `ani`, or `postal_code` | Verifies the caller and starts the call fresh; returns the business name on success |
| `get_deposit_reconciliation` | `merchant_id`, `batch_date` | Explains a day's batches versus what was deposited, every cause listed largest first |
| `get_disputes` | `merchant_id` | Open chargebacks: amount, card brand, reason, guidance, and a deadline only when one exists |
| `get_recent_deposits` | `merchant_id` | Recent batches and whether each is posted, not yet due, or late |
| `get_email_on_file` | `merchant_id` | The email address on file, spelled out for reading back to the caller |
| `send_recap_email` | `merchant_id`, `batch_date` | Emails a recap of that day's charges to the address on file, once per call |
| `transfer` | `queue`, `reason` | Hands off to a team, such as disputes or deposits |
| `get_call_context` | none | Dialed line, caller phone number, current Eastern Time (funds-hold agent) |
| `get_account_status` | `merchant_id` | Collections hold, fraud hold, pending bank change (funds-hold agent) |
| `is_business_hours` | `queue` (`collections`, `fraud`) | Whether specialists are open (funds-hold agent) |
| `get_statement_fees` | `merchant_id` | Last statement's fees with explanations (funds-hold agent) |
| `create_callback_case` | `merchant_id`, `window` | Books a bank change verification callback (funds-hold agent) |
| `report_unrecognized_bank_change` | `merchant_id` | Puts a pending bank change on hold (funds-hold agent) |

**Utility:** `GET /health` (status check) · `GET /tools` and `GET /tools/<name>` (tool definitions with public URLs) · `GET /session` (xAI `session.update` payload for the funds-hold agent) · `GET /state` (sign-in, transfers, recap emails, call log) · `GET /debug/requests` (last 50 raw requests) · `POST /reset` (start the call over).

## Behavior worth knowing

- **Guardrails are enforced server-side, not just in the prompt.** Account tools refuse to run before a successful sign-in. A failed sign-in never says which value didn't match. The recap can't be sent before the email on file is looked up, goes only to that address, and sends once per call.
- **Built to be read aloud.** Dates come back ready to speak ("Sunday, November 1st"), amounts are pre-formatted, and only the last four digits of any account are returned, so the model never does math or reads full numbers.
- **Flexible request formats.** Arguments are accepted as a flat JSON body, wrapped in `arguments`, as a JSON string, nested in a tool-call message, as form fields, or as query parameters. Missing arguments return `tool_ran: false` with a message telling the model not to treat it as a result.
- **Per-call state.** Calls are kept separate by an `X-Call-Id` header, a `call_id` query parameter, or a call or conversation ID in the body; otherwise they share one session. Every `authenticate_merchant` request starts that session over, so each new caller begins signed out with no recap sent.
- **Optional API key.** Set `API_KEY` on Railway to require `Authorization: Bearer <key>` (or `X-API-Key`) on tool calls, `/state`, `/reset`, and `/debug/requests`.
- **Recap emails.** Set `RECAP_EMAIL_TO` to the address on file for Blue Fern Café (otherwise `owner@bluefern.example`). Set `RESEND_API_KEY` to send for real through Resend; without it, the email is built but not sent, and shows up in `/state`. `RECAP_EMAIL_FROM` overrides the sender (default `Merchant Services <onboarding@resend.dev>`).

**Run locally:** `python3 -m mock_backend serve` (port 8787) · `python3 -m mock_backend repl` · `python3 -m unittest` (39 tests).
