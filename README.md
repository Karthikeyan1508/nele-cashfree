# Nele

Voice agent for PG owners: collect rent, chase late payers, pay vendors, settle deposits. Sarvam (Saaras/Sarvam-105B/Bulbul/Mayura) + Cashfree (Payment Links, Payouts, Verification).

## Architecture
- **Owner <-> WhatsApp voice agent**: owner sends voice notes (Kannada/English); Saaras transcribes, Sarvam-105B calls tools, Mayura+Bulbul reply as a voice note + text. Doubts, analytics, vendor payouts, cash entries. Payout PIN is typed (`CONFIRM 1234`), never spoken.
- **Owner <-> realtime voice agent**: the dashboard's **Call my agent** action asks a dedicated Sarvam Voice Agent to call the owner. The live agent uses protected HTTP tools, while payout confirmation and PIN entry remain in the dashboard.
- **Move-out refunds**: the owner asks to offboard a tenant, gives deposit deductions, then confirms the refund with the payout PIN; affordability uses the live Cashfree Payouts balance.
- **Cashfree wallet**: the owner dashboard reads Cashfree's live available Payouts balance and refreshes it after payment and payout webhooks.
- **UPI AutoPay**: tenants can opt in on the move-in form. After owner approval, Cashfree sends a mandate flow for monthly rent; signed charge webhooks reconcile the rent ledger.
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
No keys = **mock mode** (rule-based agent, built-in fake pay page, browser TTS). Copy `.env.example` to `.env` and fill keys for live Sarvam + Cashfree sandbox. For Cashfree sandbox webhooks run `ngrok http 8000`, set `PUBLIC_URL`, and register `/webhooks/cashfree/payment`, `/webhooks/cashfree/payout`, and `/webhooks/cashfree/subscription` in Cashfree. Payment links set their payment `notify_url` automatically.

For business-initiated WhatsApp payment links outside the 24-hour customer-service window, approve a utility template with body variables `{{1}}` tenant name, `{{2}}` amount, and `{{3}}` payment URL, then set `WA_LINK_TEMPLATE` and `WA_TEMPLATE_LANG` in `.env`.

### Realtime owner agent

Create a separate Sarvam Voice Agent for the owner, commit a version, and put its ID/version in `SARVAM_OWNER_APP_ID` and `SARVAM_OWNER_APP_VERSION`. Add only the required backend actions as Sarvam HTTP tools: `POST {PUBLIC_URL}/voice-tools/{tool_name}` with JSON arguments and header `X-Voice-Key: {SARVAM_VOICE_TOOL_SECRET}`. Use the names and schemas in `TOOLS` in `app.py`; the usual set is `get_dues`, `tenant_info`, `monthly_summary`, `send_reminders`, `record_payment`, `start_onboarding`, `start_offboarding`, `finish_offboarding`, and `prepare_payout`. Never expose `/payouts/confirm` to the voice agent.

The agent should speak Kannada/English, identify itself as Nele for the configured property, use a tool for every factual or mutating answer, read back prepared payouts, and tell the owner to confirm them in the dashboard. The completion webhook is supplied automatically when the dashboard places the call.

## Demo
Owner chips: "Yaaru innu kottilla?" -> "Ellarigu reminder kalsi" -> tenant (Ankit 204) "Half now, half Friday" -> open link, pay -> owner screen turns green + Kannada announcement -> "Electrician Raju ge 800 kodi" -> enter PIN `1234`, Confirm.

## Safety (enforced in backend)
Payouts only to verified saved payees; LLM can only *prepare* a payout, money moves only via `/payouts/confirm` with PIN; daily limit; tenants can only act on their own id; audit_log table records every tool call.

## Not built
Sarvam Vision ID scan, dashboard login/auth, tenant move-out UI. Voice replies from tenants on calls (keypad only for now).

## Where the Cashfree work plugs in
Everything money-related goes through five functions in `app.py`; each runs in mock mode until `CASHFREE_CLIENT_ID` and `CASHFREE_CLIENT_SECRET` are set.
| Function | Used for | Cashfree product |
|---|---|---|
| `make_link` | rent, deposit and part-payment links | Payment Links |
| `apply_payment` (called by `/webhooks/cashfree/payment`) | marks rent paid, sends receipts | Payment webhooks |
| `t_verify_payee` | checks a bank account before any payout, including the tenant's deposit refund account | Verification (bank account) |
| `t_prepare_payout` + `confirm_payout` | vendor payments and deposit refunds; money moves only after the owner's PIN | Payouts |
Move-outs (`/offboarding`) call `t_verify_payee` when the tenant submits bank details and `t_prepare_payout` / `confirm_payout` (kind `deposit`) for the refund, so nothing in the move-out flow needs to change when these go live. Deposit refunds have their own daily cap, `DEPOSIT_PAYOUT_LIMIT` (default 100000).
