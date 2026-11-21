# Kiraya Mitra

Voice agent for PG owners: collect rent, chase late payers, pay vendors, settle deposits. Sarvam (Saaras/Sarvam-105B/Bulbul/Mayura) + Cashfree (Payment Links, Payouts, Verification).

## Architecture
- **Owner <-> WhatsApp voice agent**: owner sends voice notes (Kannada/English); Saaras transcribes, Sarvam-105B calls tools, Mayura+Bulbul reply as a voice note + text. Doubts, analytics, vendor payouts, cash entries. Payout PIN is typed (`CONFIRM 1234`), never spoken.
- **Tenants <-> phone calls**: reminders are outbound calls (Twilio) in the tenant's language. Keypad: 1 = link by SMS, 2 = half now + rest Friday, 3 = pay in 3 days. Outcome is reported to the owner on WhatsApp.
- **Dashboard** (`dashboard/`, Next.js + shadcn): overview, tenants, per-tenant detail, month-wise rent ledger, activity/audit log, WhatsApp chat simulator.

## Run
```
# backend (http://localhost:8000)
pip install -r requirements.txt
python -m uvicorn app:app --port 8000
# dashboard (http://localhost:3000, proxies /api to the backend)
cd dashboard && npm install && npm run dev
```
Meta webhook: `PUBLIC_URL/webhooks/whatsapp`. Twilio uses `PUBLIC_URL/calls/*` (set by the app per call). Schedule `POST /cron/reminders` to call late tenants automatically.

## Run (old notes)
```
pip install -r requirements.txt
python -m uvicorn app:app --port 8000      # open http://localhost:8000
python -m pytest tests -q
```
No keys = **mock mode** (rule-based agent, built-in fake pay page, browser TTS). Copy `.env.example` to `.env` and fill keys for live Sarvam + Cashfree sandbox. For Cashfree sandbox webhooks run `ngrok http 8000`, set `PUBLIC_URL`, and register `/webhooks/cashfree/payment` plus `/webhooks/cashfree/payout` in Cashfree. Payment links set their payment `notify_url` automatically.

For business-initiated WhatsApp payment links outside the 24-hour customer-service window, approve a utility template with body variables `{{1}}` tenant name, `{{2}}` amount, and `{{3}}` payment URL, then set `WA_LINK_TEMPLATE` and `WA_TEMPLATE_LANG` in `.env`.

## Demo
Owner chips: "Yaaru innu kottilla?" -> "Ellarigu reminder kalsi" -> tenant (Ankit 204) "Half now, half Friday" -> open link, pay -> owner screen turns green + Kannada announcement -> "Electrician Raju ge 800 kodi" -> enter PIN `1234`, Confirm.

## Safety (enforced in backend)
Payouts only to verified saved payees; LLM can only *prepare* a payout, money moves only via `/payouts/confirm` with PIN; daily limit; tenants can only act on their own id; audit_log table records every tool call.

## Not built
UPI AutoPay (Cashfree Subscriptions), Sarvam Vision ID scan, dashboard login/auth, tenant move-out UI. Voice replies from tenants on calls (keypad only for now).
