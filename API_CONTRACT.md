# Kiraya Mitra — Starter API Contract

> **Implementation note:** tools are served by generic `POST /tools/{name}` (same JSON args as below); events are polled via `GET /events?after=N` (not SSE); payout confirm is UI-only `POST /payouts/confirm`, not an LLM tool. See `app.py`.

Boundary: **P1 voice brain** (Saaras → Sarvam-105B tools → Bulbul) calls **P2 backend** (FastAPI/Node + SQLite + Cashfree sandbox) over plain JSON/HTTP.
Every tool the LLM can call = one endpoint. Base URL: `http://localhost:8000`. All money in **paise-free rupees as integers** (₹8500 → `8500`). Dates ISO `YYYY-MM-DD`. Languages: `kn|hi|bn|ml|en`.

Common error shape (any non-2xx): `{"error": "code", "message": "human text"}`.
Every call may carry header `X-Owner-Id` (hardcode `1` for the demo; no auth).

## Voice brain → backend (tools)

| Tool | Endpoint | Request | Response |
|---|---|---|---|
| add_tenant | `POST /tenants` | `{name, phone, room, rent, deposit, language, due_day}` | `{tenant_id, ...}` |
| get_dues | `GET /dues?tenant_id=` (omit = all) | — | `{dues:[{tenant_id, name, room, language, rent, paid, pending, promise_date}]}` |
| create_rent_link | `POST /payments/link` | `{tenant_id, amount, month:"2026-11"}` | `{link_id, url, amount, status:"created"}` |
| log_promise | `POST /promises` | `{tenant_id, amount, date}` | `{promise_id}` |
| create_ticket | `POST /tickets` | `{tenant_id, issue}` | `{ticket_id, status:"open"}` |
| verify_payee | `POST /payees/verify` | `{name, account_no?, ifsc?, upi?}` | `{payee_id, verified:true, bank_name_match:"Raju Kumar"}` |
| pay_vendor — step 1 | `POST /payouts/prepare` | `{payee_id, amount, reason}` | `{payout_id, readback:"Raju Kumar, ₹800", requires_pin:true}` |
| pay_vendor — step 2 | `POST /payouts/confirm` | `{payout_id, pin}` | `{status:"processing"\|"success"\|"failed", cashfree_transfer_id}` |
| settle_deposit (stretch) | `POST /deposits/settle` | `{tenant_id, deductions:[{reason, amount}]}` | `{deposit, deductions_total, dues, refund, payout_id}` |
| offboard tenant | agent tools `start_offboarding` → `finish_offboarding` | tenant + deductions | Refund requiring payout PIN; affordability uses the live Cashfree Payouts available balance |
| monthly_summary | `GET /summary?month=2026-11` | — | `{collected, pending, repairs_spent, beds_vacant, deposits_held, wallet_balance, wallet_status}` |

Rules enforced **in backend, not the LLM**:
- `payouts/prepare` rejects unless payee `verified=true` and saved. LLM never sees raw account numbers.
- `payouts/confirm` requires correct PIN (demo: `1234`) and daily owner limit (₹5,000) not exceeded.
- `pay_vendor` tool must be called as prepare → read back aloud → owner says yes + PIN → confirm. Never skip.
- Every call above writes a row to `audit_log(ts, actor, action, payload)`.

## Cashfree → backend (webhooks)

| Endpoint | Purpose |
|---|---|
| `POST /webhooks/cashfree/payment` | Payment-link paid/partial. Verify signature (`x-webhook-signature` + `x-webhook-timestamp`), update `ledger`, then emit event below. Idempotent on `link_id`/`cf_payment_id`. |
| `POST /webhooks/cashfree/payout` | Transfer status → update `payouts`. |
| `POST /webhooks/cashfree/subscription` | AutoPay mandate and recurring-charge status. A successful `CHARGE` updates `payments` and `ledger`; authorization ₹1 events are ignored. |

Expose via ngrok; register URL in Cashfree sandbox dashboard.

## Backend → frontends (events)

`GET /events` (SSE) pushes JSON events; owner screen subscribes.

```json
{"type":"payment_received","tenant_id":4,"room":"204","name":"Ankit","amount":4250,"pending":4250,
 "announce":{"lang":"kn","text":"Room 204, payment received"}}
{"type":"payout_done","payee":"Raju Kumar","amount":800}
{"type":"promise_logged","tenant_id":4,"date":"2026-11-21","amount":4250}
```

Backend returns `announce.text` already translated; P1 exposes `POST /tts` for the frontend to speak it.

## Voice brain's own endpoints (P3/P4 frontends call these)

| Endpoint | Request | Response |
|---|---|---|
| `POST /voice/owner` | multipart `audio` (or JSON `{text}` fallback) | `{transcript, reply_text, reply_audio_url, tool_calls:[...]}` — reply in Kannada |
| `POST /voice/owner/call` | — | Places a realtime call from the dedicated Sarvam owner agent; `{status, attempt_id}` |
| `POST /voice-tools/{name}` | tool JSON + `X-Voice-Key` | Protected owner tool endpoint used during the realtime call; payout confirmation is deliberately unavailable |
| `POST /voice/tenant` | multipart `audio`/`{text}` + `tenant_id` | `{transcript, reply_text, reply_audio_url}` — reply in tenant's language; handles "pay now / half now / salary on 10th" by calling `create_rent_link` / `log_promise` |
| `POST /remind` | `{tenant_ids:[...]}` or `{all_late:true}` | `{sent:[{tenant_id, lang, voice_note_url, link_url}]}` — Mayura translation + Bulbul voice note + payment link |
| `POST /tts` | `{text, lang}` | `{audio_url}` |

Always send a `{text}` fallback path so the demo survives mic/Saaras failure.

## Tables (SQLite)

`owners(id,name,phone)` · `properties(id,owner_id,name,beds,due_day)` · `tenants(id,property_id,name,phone,room,rent,deposit,language,status)` ·
`ledger(id,tenant_id,month,due,paid,status[due|partial|paid|promised],promise_date)` · `payments(id,tenant_id,link_id,cf_payment_id,amount,status)` ·
`payees(id,name,account_ref,verified)` · `payouts(id,payee_id,amount,reason,status,cf_transfer_id,confirmed_at)` ·
`autopay(id,tenant_id,subscription_id,status,first_charge,last_payment_status)` · `tickets(id,tenant_id,issue,status)` · `audit_log(...)`

## Seed (P5)

1 property "Sai Residency", 8 tenants (mix hi/bn/ml), 3 late (rooms 204, 207, 301), 1 verified payee "Raju Kumar" (electrician).

## Freeze rule

Change a field → tell P1 and P2 in chat first. Contract frozen at 12:30.
