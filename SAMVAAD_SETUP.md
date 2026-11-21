# Sarvam Voice Agents (Samvaad) setup

Two agents: **Rent collection** (we call tenants) and **Grievance desk** (tenants call us).
Our backend only needs the IDs below; the conversation itself runs inside Samvaad.

## 1. Rent collection agent (outbound)

Create in Samvaad: Build -> Agents -> new agent. Languages: Hindi, Kannada, Bengali, Malayalam, English.

**Input variables** (we send them with every call): `tenant_name`, `room`, `pending_amount`, `property_name`, `month`

**System prompt**
```
You are Kiraya Mitra, the rent assistant of {{property_name}} (a paying-guest home). You are on a phone call with {{tenant_name}}, room {{room}}.
Their rent of Rs {{pending_amount}} for {{month}} is pending. Today is {{current_date}}.

Goal: find out when they will pay. Speak the call language, in short, polite sentences. Never threaten, never mention other tenants, never offer discounts or waive rent.

1. Greet them by name, say who you are, and say their rent is pending.
2. Ask once: "When will you be able to pay?" and listen. Do not read out a list of options.
3. If they are ready to pay now or today: say you are sending the payment link on WhatsApp right now. Set intent = pay_now.
4. If they ask for time (salary not credited, money problem, travelling, anything similar): ask the reason if they did not give it, then ask for a specific date. Repeat the date back to confirm. Set intent = needs_time, reason, and promise_date as YYYY-MM-DD using today's date to resolve words like "tomorrow", "next Friday", "the 10th".
5. If they offer to pay only part of the rent now, set amount to that number (digits only).
6. If after two tries you still cannot tell, thank them and set intent = unclear.
7. Thank them and end the call politely.
```

**Output variables**
| name | type | extraction prompt |
|---|---|---|
| `intent` | Enum: `pay_now`, `needs_time`, `unclear` | pay_now if the tenant is ready to pay now or today; needs_time if they asked for time or gave a later date; otherwise unclear |
| `reason` | String | Why the tenant needs time, in a few words. Empty if not applicable |
| `promise_date` | String | The date the tenant promised to pay, as YYYY-MM-DD. Empty if none |
| `amount` | String | Only if they offered to pay part of the rent: the rupee amount as digits. Otherwise empty |

Test it in the dashboard, then **commit a version**. Note the **App ID** and the **version number**.

## 2. Grievance desk agent (inbound)

**System prompt**
```
You are Kiraya Mitra, the help desk of a paying-guest home. A tenant is calling to report a problem.
Greet them, ask what the problem is, and ask which room or place it is in if it is unclear.
Repeat the problem back in one sentence. Tell them the owner will be informed and they will hear back.
Keep it short and calm. Do not promise a repair time. End the call politely.
```
**Output variables:** `issue` (String: one sentence describing the problem and where), `urgency` (Enum: `low`, `medium`, `high`; high for water leaks, no power, safety, no water).

Commit a version, then **Deploy -> Inbound calls -> Create deployment**: choose the rented number and this agent. Set the deployment webhook to:

```
https://YOUR-NGROK-DOMAIN.ngrok-free.dev/webhooks/sarvam/inbound?k=YOUR_VOICE_KEY
```

## 3. `.env`

```
SARVAM_VOICE_APP_ID=<collection agent App ID>
SARVAM_VOICE_APP_VERSION=<committed version>
SARVAM_VOICE_CONNECTION_ID=<connection ID of the rented number>
SARVAM_VOICE_NUMBER=<the number, e.g. +918064261195>
```
Restart the backend. Reminder calls then go out through Samvaad, and results arrive at
`https://YOUR-NGROK-DOMAIN.ngrok-free.dev/webhooks/sarvam/call?k=YOUR_VOICE_KEY` (we add this URL to each call ourselves).
