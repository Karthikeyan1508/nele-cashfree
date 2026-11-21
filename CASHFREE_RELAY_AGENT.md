# Cashfree Relay Agent for Tenant AutoPay & Dunning

This document defines how **Cashfree Relay** (Cashfree's AI-powered operations Super Agent) is configured and connected for automated rent AutoPay and failed-payment recovery in **Kiraya Mitra**.

---

## 1. Architecture Overview

```
 [Prospective Tenant]
         │ (Fills onboarding form: Aadhaar, Photo, Room)
         ▼
 [Owner Dashboard: Onboarding Approval]
         │
         ├──> t_add_tenant() ──> Welcome note + Deposit link sent
         │
         └──> t_setup_autopay()
                     │
                     ▼
           [Cashfree Subscriptions API]
           Creates Monthly Rent Plan & Mandate
                     │
                     ▼
           [UPI AutoPay Mandate Link]
           Sent to Tenant via WhatsApp
                     │
                     ▼
         Tenant Authorizes in GPay / PhonePe / Paytm
                     │
                     ▼
      [Cashfree Webhook: SUBSCRIPTION_ACTIVE]
         Tenant status updated to AutoPay: ACTIVE
```

### Recurring Rent Debit & Relay Autonomous Recovery:
```
      On Rent Day (5th of each month):
                     │
            [Cashfree AutoPay Engine]
                     │
            ┌────────┴────────┐
            ▼                 ▼
        [SUCCESS]          [FAILED / DECLINED]
            │                 (e.g., low balance, bank downtime)
            │                 │
    Ledger Marked Paid        ▼
    Receipt Issued      [CASHFREE RELAY SUPER AGENT]
                        Autonomous Dunning & Recovery:
                        1. Analyzes failure code
                        2. Dispatches WhatsApp recovery note with retry link
                        3. Intelligently schedules retry debit
                        4. Alerts PG owner via Kannada voice alert
```

---

## 2. Cashfree Relay Super Agent Prompt & Configuration

Deploy this agent in your **Cashfree Merchant Dashboard -> Relay Canvas** or via the **Cashfree Relay MCP Server** (`.mcp.json`).

### Agent Metadata:
- **Agent Name:** `Kiraya Mitra PG Rent AutoPay & Dunning Agent`
- **Role:** Autonomous Recurring Payment Monitor & Recovery Specialist
- **Connected Channels:** WhatsApp Business API, Cashfree Subscriptions v2, Kiraya Mitra Webhook

### Agent System Prompt:
```markdown
You are the Cashfree Relay Autonomous Operations Agent for Kiraya Mitra PG Management.
Your responsibility is to oversee tenant UPI AutoPay recurring rent collection and execute conversational dunning whenever an auto-debit fails.

Core Directives:
1. Monitor recurring subscription transactions for incoming rent debits under the property plans ("rent_plan_*").
2. When a mandate is initialized for a newly onboarded tenant, ensure the UPI authorization link is dispatched over WhatsApp.
3. When an auto-debit fails (due to insufficient funds, bank downtime, or mandate limits):
   - Do NOT immediately cancel the tenant's mandate or lease.
   - Analyze the failure reason code.
   - Immediately send a polite, localized WhatsApp notification to the tenant stating that their rent auto-debit could not be completed, and provide an instant 1-click payment link.
   - Schedule an automated retry debit according to bank best-time windows (typically within 48 to 72 hours).
   - If 2 consecutive retries fail, post an escalation alert to the Kiraya Mitra webhook (/webhooks/cashfree/subscription) so the owner is notified.
4. Always maintain a professional, empathetic, and respectful tone.
```

---

## 3. Webhook Integration

Kiraya Mitra backend listens on:
```
POST PUBLIC_URL/webhooks/cashfree/subscription
```

### Supported Cashfree Events:

| Event Type | Action Taken |
|---|---|
| `SUBSCRIPTION_ACTIVE` | Mandate approved by tenant. Updates `subscriptions.status = 'active'`. Sends confirmation to tenant & owner. |
| `SUBSCRIPTION_CHARGED` | Monthly auto-debit successful. Updates ledger for current month, issues receipt, notifies owner. |
| `SUBSCRIPTION_PAYMENT_DECLINED` / `SUBSCRIPTION_FAILED` | Debit failed. Triggers **Cashfree Relay Agent Recovery**, sends tenant retry link and alerts owner. |
| `RELAY_RECOVERY_UPDATE` | Logs audit trail of Relay Agent actions. |

---

## 4. Connecting via Model Context Protocol (MCP)

This repository includes `.mcp.json` with the official Cashfree MCP server:
```json
{
  "mcpServers": {
    "cashfree": {
      "url": "https://mcp.cashfree.com/mcp"
    }
  }
}
```

### To interact with Cashfree Relay via MCP:
1. Log in to your Cashfree Merchant Dashboard with Owner credentials.
2. Connect your AI client (e.g. Claude Desktop or Antigravity) to `https://mcp.cashfree.com/mcp`.
3. Use plain-language prompts to view or manage your agent:
   > *"Show me all tenants with pending AutoPay mandates for this month."*
   > *"What is the recovery status of failed AutoPay debits handled by Cashfree Relay?"*

---

## 5. Testing & Simulation in Offline / Demo Mode

When `MOCK_CF` is active (no Cashfree credentials in `.env`):
- Newly approved tenants receive a simulated mandate link: `http://localhost:8000/autopay/{sub_id}`.
- Opening that page allows you to:
  - **Authorize UPI AutoPay (Demo)**: Simulates UPI approval and transitions the mandate to `ACTIVE`.
  - **Simulate Debit Failure (Test Relay Recovery)**: Triggers the complete Cashfree Relay recovery cycle, generates a retry link, and dispatches WhatsApp messages to tenant and owner.
- You can also test directly from the **Dashboard -> Tenants -> [Tenant Detail] -> AutoPay (Relay) tab**.
