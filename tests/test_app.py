import base64, hashlib, hmac, json, os, tempfile, time

os.environ.update(DB_PATH=os.path.join(tempfile.mkdtemp(), "t.db"), SARVAM_API_KEY="", CASHFREE_CLIENT_ID="",
                  CASHFREE_CLIENT_SECRET="", CASHFREE_PAYOUT_CLIENT_ID="", CASHFREE_PAYOUT_CLIENT_SECRET="",
                  CASHFREE_VERIFY_CLIENT_ID="", CASHFREE_VERIFY_CLIENT_SECRET="", TWILIO_SID="", TWILIO_TOKEN="",
                  WHATSAPP_TOKEN="", WHATSAPP_APP_SECRET="", OWNER_PHONE="9800000000", PAYOUT_PIN="1234", DAILY_PAYOUT_LIMIT="1000",
                  # blank so tests never place real calls through Sarvam, whatever .env holds
                  SARVAM_VOICE_API_KEY="", SARVAM_ORG_ID="", SARVAM_WORKSPACE_ID="", SARVAM_VOICE_APP_ID="", SARVAM_VOICE_CONNECTION_ID="", SARVAM_VOICE_NUMBER="", SARVAM_ONBOARD_APP_ID="",
                  SARVAM_OWNER_APP_ID="", SARVAM_VOICE_TOOL_SECRET="")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import pytest
from fastapi.testclient import TestClient

import app as A


@pytest.fixture(scope="module")
def c():
    with TestClient(A.app) as c:
        yield c


def voice(c, role, text, tid=None):
    d = {"text": text}
    if tid:
        d["tenant_id"] = tid
    r = c.post(f"/voice/{role}", data=d)
    assert r.status_code == 200, r.text
    return r.json()


def tid(c, name):
    return next(t["id"] for t in c.get("/tenants").json() if t["name"] == name)


def cf_hook(c, path, body, secret, timestamp=None):
    raw = json.dumps(body, separators=(",", ":")).encode()
    ts = str(timestamp or int(time.time()))
    sig = base64.b64encode(hmac.new(secret.encode(), ts.encode() + raw, hashlib.sha256).digest()).decode()
    return c.post(path, content=raw, headers={"content-type": "application/json", "x-webhook-timestamp": ts,
                                              "x-webhook-signature": sig})


def test_who_has_not_paid(c):
    j = voice(c, "owner", "Yaaru innu kottilla?")
    assert j["tool_calls"][0]["tool"] == "get_dues"
    assert {d["name"] for d in j["tool_calls"][0]["result"]["dues"]} == {"Karthikeyan", "Dhananjayadas", "Atrinandan"}


def test_half_now_flow_updates_ledger_and_announces(c):
    t = tid(c, "Karthikeyan")
    rent = next(r["rent"] for r in c.get("/tenants/all").json() if r["name"] == "Karthikeyan")
    j = voice(c, "tenant", "Half now, half Friday", t)
    assert len(j["links"]) == 1
    link = j["links"][0].rsplit("/", 1)[1]
    assert any(x["tool"] == "log_promise" for x in j["tool_calls"])
    before = c.get("/events").json()["last"]
    assert c.post(f"/dev/simulate-payment/{link}").json()["pending"] == rent - rent // 2
    assert c.post(f"/dev/simulate-payment/{link}").json().get("duplicate")  # idempotent
    ev = c.get(f"/events?after={before}").json()["events"]
    assert ev[-1]["type"] == "payment_received" and ev[-1]["announce"]["lang"] == "kn"
    row = next(d for d in c.get("/dues").json()["dues"] if d["name"] == "Karthikeyan")
    assert row["paid"] == rent // 2 and row["status"] == "partial"


def test_cashfree_payment_webhook_security_and_status(c, monkeypatch):
    A.q("insert into tenants(name,phone,room,rent,deposit,language) values('Webhook Test','9000000999','104',500,1000,'en')")
    tenant_id = A.q.last
    A.q("insert into ledger(tenant_id,month,due) values(?,?,500)", (tenant_id, A.month()))
    A.q("insert into payments(tenant_id,link_id,amount,month,url) values(?, 'cf_webhook_test',500,?,'')", (tenant_id, A.month()))
    body = {"type": "PAYMENT_LINK_EVENT", "data": {"link_id": "cf_webhook_test", "link_status": "PAID",
                                                               "link_amount_paid": 500, "link_currency": "INR",
                                                               "cf_payment_id": "cf_test_payment_1"}}
    try:
        assert c.post("/webhooks/cashfree/payment", json=body).status_code == 503
        monkeypatch.setattr(A, "CF_SECRET", "test-secret")
        assert cf_hook(c, "/webhooks/cashfree/payment", body, "wrong-secret").status_code == 401
        assert cf_hook(c, "/webhooks/cashfree/payment", body, "test-secret", int(time.time()) - 301).status_code == 401
        failed = {**body, "data": {**body["data"], "link_status": "FAILED"}}
        assert cf_hook(c, "/webhooks/cashfree/payment", failed, "test-secret").json().get("ignored")
        assert cf_hook(c, "/webhooks/cashfree/payment", body, "test-secret").json()["pending"] == 0
        assert cf_hook(c, "/webhooks/cashfree/payment", body, "test-secret").json().get("duplicate")
    finally:
        A.q("delete from payments where tenant_id=?", (tenant_id,))
        A.q("delete from ledger where tenant_id=?", (tenant_id,))
        A.q("delete from tenants where id=?", (tenant_id,))


def test_cashfree_link_identifies_the_tenant(c, monkeypatch):
    captured = {}

    async def fake_cf(method, path, version, **kwargs):
        captured.update(kwargs["json"])
        return {"link_url": "https://payments-test.cashfree.com/links/test"}

    monkeypatch.setattr(A, "MOCK_CF", False)
    monkeypatch.setattr(A, "cf", fake_cf)
    tenant = A.tenant_row(tid(c, "Atrinandan"))
    import asyncio
    link = asyncio.run(A.make_link(tenant, 1, A.month()))
    try:
        assert captured["customer_details"]["customer_name"] == tenant["name"]
        assert tenant["name"] in captured["link_purpose"]
        assert captured["link_notes"]["tenant_name"] == tenant["name"]
    finally:
        A.q("delete from payments where link_id=?", (link["link_id"],))


def test_cashfree_payout_webhook(c, monkeypatch):
    monkeypatch.setattr(A, "CF_PAYOUT_SECRET", "test-secret")
    payee_id = A.q("select id from payees where verified=1 limit 1")[0]["id"]
    A.q("insert into payouts(payee_id,amount,reason,status,cf_transfer_id,day) values(?,500,'test','processing','payout_hook_test',?)",
        (payee_id, A.dt.date.today().isoformat()))
    payout_id = A.q.last
    body = {"type": "TRANSFER_SUCCESS", "data": {"transfer_id": "payout_hook_test", "status": "SUCCESS",
                                                          "status_code": "COMPLETED"}}
    try:
        assert cf_hook(c, "/webhooks/cashfree/payout", body, "test-secret").json()["status"] == "success"
        assert A.q("select status from payouts where id=?", (payout_id,))[0]["status"] == "success"
    finally:
        A.q("delete from payouts where id=?", (payout_id,))


def test_cashfree_wallet_uses_available_balance(c, monkeypatch):
    class Response:
        status_code = 200
        text = ""

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return Response({"data": {"token": "payout-token"}})

        async def get(self, *args, **kwargs):
            return Response({"data": {"balance": "1250.75", "availableBalance": "1000.25"}})

    monkeypatch.setattr(A, "MOCK_PAYOUT", False)
    monkeypatch.setattr(A.httpx, "AsyncClient", lambda **kwargs: Client())
    A.PAYOUT_TOKEN.update(value=None, expires=0)
    A.WALLET_CACHE.update(value=None, expires=0)
    try:
        wallet = c.get("/wallet").json()
        assert wallet["available_balance"] == 1000.25
        assert wallet["ledger_balance"] == 1250.75
        assert c.get("/summary").json()["wallet_balance"] == 1000.25
    finally:
        A.PAYOUT_TOKEN.update(value=None, expires=0)
        A.WALLET_CACHE.update(value=None, expires=0)


def test_tenant_cannot_act_on_others(c):
    res = A.call_tool  # tenant role forces own id even if the model passes another
    import asyncio
    out = asyncio.run(res("create_ticket", {"tenant_id": 999, "issue": "x"}, "tenant", tid(c, "Dhananjayadas")))
    assert out["ticket_id"]
    assert asyncio.run(res("add_tenant", {}, "tenant", 1))["error"].startswith("tool add_tenant not allowed")


def test_payout_guardrails(c):
    j = voice(c, "owner", "Electrician Raju ge 800 kodi")
    p = j["pending_payout"]
    assert p["readback"].startswith("Raju Kumar") and p["status"] == "pending_confirm"
    assert c.post("/payouts/confirm", json={"payout_id": p["payout_id"], "pin": "0000"}).status_code == 400
    assert c.post("/payouts/confirm", json={"payout_id": p["payout_id"], "pin": "1234"}).json()["status"] == "success"
    assert c.post("/payouts/confirm", json={"payout_id": p["payout_id"], "pin": "1234"}).status_code == 400  # no double pay
    # daily limit 1000: 800 spent, another 800 blocked
    assert "limit" in voice(c, "owner", "pay Raju 800")["tool_calls"][0]["result"]["error"]
    # unverified payee blocked
    assert "not a verified" in voice(c, "owner", "pay Suresh 100")["tool_calls"][0]["result"]["error"]


def test_summary_and_settlement(c):
    s = c.get("/summary").json()
    assert s["repairs_spent"] == 800 and s["beds_vacant"] == 36 - 11
    r = c.post("/tools/settle_deposit", json={"tenant_id": tid(c, "Dhananjayadas"), "deductions": [{"reason": "painting", "amount": 1500}]}).json()
    assert r["refund"] == next(v["rent"] for v in c.get("/tenants/all").json() if v["name"] == "Dhananjayadas") - 1500  # deposit 2x rent, minus deductions and one month due


def test_ledger_history_and_tenant_detail(c):
    L = c.get("/ledger").json()
    assert len(L["months"]) == 4 and len(L["rows"]) == 11
    d = c.get(f"/tenants/{tid(c, 'Karthikeyan')}").json()
    assert len(d["ledger"]) == 4 and d["payments"] and d["promises"]
    assert c.get("/overview").json()["series"]


def test_collection_call_conversation_and_receipts(c):
    r = c.post("/tools/send_reminders").json()
    assert len(r["calls"]) == 3 and all(x["status"] == "simulated" for x in r["calls"])
    calls = {x["name"]: x["call_id"] for x in r["calls"]}
    sim = lambda name, said: c.post(f"/dev/simulate-call/{calls[name]}", params={"said": said}).json()

    # asks for time without a date: the agent asks for the date, then records reason + date
    j = sim("Dhananjayadas", "my salary has not come yet")
    assert j["kind"] == "ask" and "date" in j["reply"]
    assert sim("Dhananjayadas", "I will pay on the 25th")["kind"] == "end"
    row = next(d for d in c.get("/dues").json()["dues"] if d["name"] == "Dhananjayadas")
    assert row["status"] == "promised" and row["promise_date"].endswith("-25")
    call = next(x for x in c.get("/activity").json()["calls"] if x["id"] == calls["Dhananjayadas"])
    assert call["outcome"] == "promised" and "salary" in call["reason"] and call["promise_date"] == row["promise_date"]
    assert "salary" in call["transcript"] and "25th" in call["transcript"]
    pr = c.get(f"/tenants/{tid(c, 'Dhananjayadas')}").json()["promises"][0]
    assert "salary" in pr["reason"] and pr["date"] == row["promise_date"]

    # ready to pay: link goes to the tenant on WhatsApp
    assert sim("Karthikeyan", "yes I can pay now")["kind"] == "end"
    k = c.get(f"/tenants/{tid(c, 'Karthikeyan')}").json()
    assert next(x for x in c.get("/activity").json()["calls"] if x["id"] == calls["Karthikeyan"])["outcome"] == "will_pay_now"
    link = next(x for x in A.q("select * from payments where tenant_id=? and paid=0", (tid(c, "Karthikeyan"),)))
    sent = A.q("select text from messages where role='tenant' and direction='out' and text like ?", ("%" + link["link_id"] + "%",))
    assert sent  # tenant got the link on WhatsApp

    # payment: receipt + transaction details to owner and tenant
    assert c.post(f"/dev/simulate-payment/{link['link_id']}").json()["receipt_no"].startswith("KM-")
    owner = [m["text"] for m in c.get("/messages").json() if m["direction"] == "out"]
    assert any("Transaction ID: TXN" in t and "Receipt: KM-" in t for t in owner)
    ten = [m["text"] for m in A.q("select text from messages where role='tenant' and direction='out'")]
    assert any("Transaction ID: TXN" in t and "Receipt: KM-" in t for t in ten)
    rno = A.q("select receipt_no from payments where link_id=?", (link["link_id"],))[0]["receipt_no"]
    assert "Transaction ID" in c.get(f"/receipt/{rno}").text


def test_whatsapp_owner_chat_and_bad_pin(c):
    c.post("/whatsapp/simulate", data={"text": "Karthikeyan status"})
    c.post("/whatsapp/simulate", data={"text": "Electrician Raju ge 100 kodi"})  # prepares only
    c.post("/whatsapp/simulate", data={"text": "confirm 0000"})
    msgs = c.get("/messages").json()
    assert any("Karthikeyan" in m["text"] for m in msgs if m["direction"] == "out")
    assert any("wrong PIN" in m["text"] for m in msgs if m["direction"] == "out")
    pend = [p for p in c.get("/activity").json()["payouts"] if p["status"] == "pending_confirm"]
    for p in pend:
        c.post("/payouts/cancel", json={"payout_id": p["id"]})


def test_strangers_become_pg_enquiries_and_the_owner_is_told(c):
    c.post("/whatsapp/simulate", data={"text": "What is the rent and deposit for a 3 sharing room?", "tenant_phone": "9123456789"})
    e = A.q("select * from enquiries where phone='9123456789'")
    assert len(e) == 1 and "3 sharing" in e[0]["first_msg"]
    owner = [m["text"] for m in A.q("select text from messages where role='owner' and direction='out'")]
    assert any("asking about the PG" in t or "ಪಿ.ಜಿ" in t or "PG" in t for t in owner)
    assert any(m["role"] == "enquirer" and m["direction"] == "out" for m in c.get("/messages").json()) or A.q("select 1 from messages where role='enquirer' and direction='out'")
    c.post("/whatsapp/simulate", data={"text": "my name is Ravi", "tenant_phone": "9123456789"})
    assert len(A.q("select * from enquiries where phone='9123456789'")) == 1  # same person, one enquiry
    assert not A.q("select 1 from tenants where phone='9123456789'")  # and nothing about tenants is reachable


def test_enquiry_facts_state_rent_deposit_and_vacancies():
    f = A.enquiry_facts()
    assert "11000" in f and "9000" in f and "7000" in f and "22000" in f and "vacant" in f


def test_tenant_whatsapp_agent_sends_created_payment_link(c):
    phone = "9000000002"
    before = A.q("select coalesce(max(id),0) id from messages")[0]["id"]
    assert c.post("/whatsapp/simulate", data={"text": "send my payment link", "tenant_phone": phone}).status_code == 200
    sent = A.q("select text from messages where id>? and role='tenant' and direction='out' order by id desc", (before,))
    assert sent and "/pay/rent_" in sent[0]["text"]


def test_pg_facts_for_the_voice_agent(c):
    f = A.pg_facts()
    occupied = sum(len(r["occupants"]) for r in c.get("/rooms").json())
    assert f["total_rooms"] == "12" and f["total_beds"] == "36" and int(f["vacant_beds"]) == 36 - occupied
    assert "Floor 1, 2-sharing, 11000 rupees" in f["vacancy_details"] and f["property_address"]


def test_rooms_pricing_and_capacity(c):
    rooms = {r["room"]: r for r in c.get("/rooms").json()}
    assert len(rooms) == 12 and rooms["101"]["sharing"] == 2 and rooms["201"]["sharing"] == 3 and rooms["304"]["sharing"] == 4
    r = c.post("/tools/add_tenant", json={"name": "Test", "phone": "9000000001", "room": "301"}).json()
    t = c.get(f"/tenants/{r['tenant_id']}").json()["tenant"]
    assert t["rent"] == 7000 and t["deposit"] == 14000  # 4-sharing rate, deposit = 2 months
    for i in range(rooms["304"]["sharing"] - len(rooms["304"]["occupants"])):  # fill room 304, the next one must be refused
        assert "error" not in c.post("/tools/add_tenant", json={"name": f"F{i}", "phone": f"90000001{i}0", "room": "304"}).json()
    assert "full" in c.post("/tools/add_tenant", json={"name": "X", "phone": "9000000002", "room": "304"}).json()["error"]
    assert "does not exist" in c.post("/tools/add_tenant", json={"name": "X", "phone": "9000000003", "room": "999"}).json()["error"]


def test_inbound_grievance_call(c, monkeypatch):
    k = A.incoming_key()
    stranger = c.post(f"/calls/incoming?k={k}", data={"From": "+919111111111"})
    assert "not registered" in stranger.text and "Hangup" in stranger.text
    assert c.post("/calls/incoming?k=wrong", data={"From": "+919000000002"}).status_code == 403

    r = c.post(f"/calls/incoming?k={k}", data={"From": "+919000000002"})  # Dhananjayadas
    assert "<Record" in r.text
    cid = int(r.text.split("/calls/grievance/")[1].split("?")[0])

    async def fake(url):
        return "the geyser in my room is not working"
    monkeypatch.setattr(A, "fetch_recording", fake)
    done = c.post(f"/calls/grievance/{cid}", data={"RecordingUrl": "x", "RecordingDuration": "6"})
    assert "ticket number" in done.text.lower()
    tickets = c.get("/activity").json()["tickets"]
    assert any(t["name"] == "Dhananjayadas" and "geyser" in t["issue"] for t in tickets)
    assert any("geyser" in m["text"] for m in c.get("/messages").json() if m["direction"] == "out")  # owner told on WhatsApp


def test_sarvam_voice_webhooks(c):
    k = A.voice_key()
    calls = {x["name"]: x["call_id"] for x in c.post("/tools/send_reminders").json()["calls"]}
    hook = lambda cid, **kw: c.post(f"/webhooks/sarvam/call?k={k}", json={"webhook_config": {"metadata": {"call_id": cid}}, **kw})
    assert c.post("/webhooks/sarvam/call?k=bad", json={}).status_code == 403

    # connected call: reason + date understood from the transcript
    cid = calls["Atrinandan"]
    hook(cid, status="connected", interaction_transcript=[
        {"role": "agent", "en_text": "When can you pay?"},
        {"role": "user", "en_text": "My salary is delayed, I will pay on the 25th"}])
    call = next(v for v in c.get("/activity").json()["calls"] if v["id"] == cid)
    assert call["outcome"] == "promised" and "salary" in call["reason"] and call["promise_date"].endswith("-25")
    assert "Agent: When can you pay?" in call["transcript"]
    assert hook(cid, status="connected").json()["ignored"]  # repeated delivery is ignored

    # unanswered
    hook(calls["Dhananjayadas"], status="no_answer")
    assert next(v for v in c.get("/activity").json()["calls"] if v["id"] == calls["Dhananjayadas"])["outcome"] == "no_answer"

    # agent-extracted variables win over the transcript
    cid2 = {x["name"]: x["call_id"] for x in c.post("/tools/send_reminders").json()["calls"]}["Dhananjayadas"]
    hook(cid2, status="connected", interaction_transcript=[{"role": "user", "en_text": "ok send it"}],
         final_agent_variables={"intent": "pay_now"})
    assert next(v for v in c.get("/activity").json()["calls"] if v["id"] == cid2)["outcome"] == "will_pay_now"

    # inbound complaint
    body = {"user_phone_number": "+919000000005", "interaction_id": "i-1", "final_agent_variables": {"issue": "water leak in bathroom"}}
    assert c.post(f"/webhooks/sarvam/inbound?k={k}", json=body).json() == {"ok": True}
    assert c.post(f"/webhooks/sarvam/inbound?k={k}", json=body).json().get("ignored")
    assert any(v["name"] == "Atrinandan" and "water leak" in v["issue"] for v in c.get("/activity").json()["tickets"])


def test_owner_realtime_voice_call_and_tools(c, monkeypatch):
    assert c.post("/voice/owner/call").status_code == 503
    captured = {}

    async def fake_outbound(app_id, app_version, variables, language, phone, hook, metadata):
        captured.update(app_id=app_id, app_version=app_version, variables=variables, language=language,
                        phone=phone, hook=hook, metadata=metadata)
        return "ringing", "owner_attempt_1"

    monkeypatch.setattr(A, "OWNER_VOICE", True)
    monkeypatch.setattr(A, "SV_OWNER_APP", "owner-agent")
    monkeypatch.setattr(A, "SV_OWNER_VER", 3)
    monkeypatch.setattr(A, "samvaad_outbound", fake_outbound)
    r = c.post("/voice/owner/call")
    assert r.json() == {"status": "ringing", "attempt_id": "owner_attempt_1"}
    assert captured["app_id"] == "owner-agent" and captured["hook"] == "/webhooks/sarvam/owner"
    assert captured["phone"] == A.OWNER_PHONE and captured["language"] == "kn"

    monkeypatch.setattr(A, "SV_TOOL_SECRET", "voice-secret")
    assert c.post("/voice-tools/get_dues", json={}).status_code == 403
    tool = c.post("/voice-tools/get_dues", json={}, headers={"X-Voice-Key": "voice-secret"})
    assert tool.status_code == 200 and "dues" in tool.json()
    assert c.post("/webhooks/sarvam/owner?k=bad", json={}).status_code == 403
    hook = c.post(f"/webhooks/sarvam/owner?k={A.voice_key()}", json={"status": "connected", "interaction_id": "owner_attempt_1",
                  "interaction_transcript": [{"role": "agent", "en_text": "How can I help?"}, {"role": "user", "en_text": "Rent summary"}]})
    assert hook.json() == {"ok": True}


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64


def form(**kw):
    base = dict(name="Ravi Kumar", phone="9876500001", whatsapp_same="no", whatsapp="9876500002", email="ravi@example.com", dob="2002-05-01",
                gender="Male", occupation="student", org_name="UVCE", org_role="BE 3rd year", org_location="Bengaluru",
                primary_language="Kannada", secondary_language="English", address="12 MG Road, Mysuru", emergency_name="Suresh",
                emergency_relation="Father", emergency_phone="9876500003", move_in="2026-12-01", food="Vegetarian", consent="on")
    base.update(kw)
    return base


def test_onboarding_flow(c, monkeypatch):
    r = c.post("/onboarding/start", json={"name": "Ravi Kumar", "phone": "9876500001", "room": "302"}).json()
    assert r["status"] == "link_sent"  # no voice agent in tests: the form goes straight to WhatsApp
    ob = A.q("select * from onboarding where id=?", (r["onboarding_id"],))[0]
    assert any(ob["token"] in m["text"] for m in A.q("select text from messages where role='tenant' and direction='out'"))
    assert "already" in c.post("/tools/start_onboarding", json={"name": "Dup", "phone": "9876500001", "room": "302"}).json()["error"]

    pre = c.get(f"/onboard-api/{ob['token']}").json()
    assert (pre["name"], pre["phone"], pre["room"], pre["sharing"], pre["rent"], pre["deposit"]) == ("Ravi Kumar", "9876500001", "302", 4, 7000, 14000)
    assert "<form" in c.get(f"/onboard/{ob['token']}").text and c.get("/onboard-api/nope").status_code == 404

    url = f"/onboard-api/{ob['token']}"
    files = lambda a=PDF, p=PNG: {"aadhaar": ("a.pdf", a, "application/pdf"), "photo": ("p.png", p, "image/png")}
    assert c.post(url, data=form(email="bad"), files=files()).status_code == 400
    assert c.post(url, data=form(consent=""), files=files()).status_code == 400
    assert "must be a" in c.post(url, data=form(), files=files(a=b"just text")).json()["detail"]  # wrong file type
    assert "required" in c.post(url, data=form(), files={"photo": ("p.png", PNG, "image/png")}).json()["detail"]
    assert c.post(url, data={k: v for k, v in form().items() if k != "address"}, files=files()).status_code == 400

    assert c.post(url, data=form(autopay="yes"), files=files()).json() == {"ok": True}
    assert c.post(url, data=form(), files=files()).status_code == 409  # one submission per link
    d = c.get(f"/onboarding/{ob['id']}").json()
    assert d["status"] == "submitted" and d["form"]["primary_language"] == "Kannada" and d["has_aadhaar"] and d["has_photo"]
    assert c.get(f"/onboarding/{ob['id']}/file/photo").content == PNG
    assert any("Ravi Kumar" in m["text"] and "Email: ravi@example.com" in m["text"] for m in c.get("/messages").json() if m["direction"] == "out")

    captured = {}

    async def fake_cf(method, path, version, **kwargs):
        if path == "/pg/links":
            return {"link_url": "https://payments-test.cashfree.com/first-rent"}
        captured.update(kwargs["json"])
        return {"subscription_session_id": "subs_session_test", "subscription_status": "INITIALIZED",
                "cf_subscription_id": "cf_sub_test"}

    monkeypatch.setattr(A, "MOCK_CF", False)
    monkeypatch.setattr(A, "cf", fake_cf)
    approved = c.post(f"/onboarding/{ob['id']}/approve").json()
    tid = approved["tenant_id"]
    assert approved["autopay_status"] == "initialized"
    t = c.get(f"/tenants/{tid}").json()
    assert t["tenant"]["room"] == "302" and t["tenant"]["rent"] == 7000 and t["tenant"]["deposit"] == 14000
    assert t["tenant"]["language"] == "kn" and t["tenant"]["whatsapp"] == "9876500002"  # primary language and WhatsApp number carried over
    assert t["profile"] and "ravi@example.com" in t["profile"]["form_json"]
    auto = A.q("select * from autopay where tenant_id=?", (tid,))[0]
    assert auto["first_charge"].startswith("2027-01-05") and auto["session_id"] == "subs_session_test"
    assert captured["plan_details"]["plan_amount"] == 7000 and captured["authorization_details"]["payment_methods"] == ["upi"]
    assert "subscriptionsCheckout" in c.get(f"/autopay/{auto['token']}").text
    assert any(auto["token"] in m["text"] for m in A.q("select text from messages where role='tenant' and direction='out'"))

    monkeypatch.setattr(A, "CF_SECRET", "test-secret")
    failed_auth = {"type": "SUBSCRIPTION_AUTH_STATUS", "data": {"subscription_id": auto["subscription_id"],
                   "subscription_details": {"subscription_id": auto["subscription_id"], "subscription_status": "ACTIVE"},
                   "authorization_details": {"authorization_status": "FAILED"}, "payment_type": "AUTH", "payment_status": "FAILED"}}
    assert cf_hook(c, "/webhooks/cashfree/subscription", failed_auth, "test-secret").json()["status"] == "failed"
    assert A.q("select status from autopay where id=?", (auto["id"],))[0]["status"] == "failed"
    auth = {"type": "SUBSCRIPTION_AUTH_STATUS", "data": {"subscription_id": auto["subscription_id"],
            "subscription_details": {"subscription_id": auto["subscription_id"], "subscription_status": "ACTIVE"},
            "authorization_details": {"authorization_status": "ACTIVE"}, "payment_type": "AUTH"}}
    assert cf_hook(c, "/webhooks/cashfree/subscription", auth, "test-secret").json()["status"] == "active"
    paid = {"type": "SUBSCRIPTION_PAYMENT_SUCCESS", "data": {"subscription_id": auto["subscription_id"],
            "subscription_details": {"subscription_id": auto["subscription_id"], "subscription_status": "ACTIVE"},
            "payment_type": "CHARGE", "payment_amount": 7000, "payment_currency": "INR",
            "payment_schedule_date": "2027-01-05T10:00:00+05:30", "cf_payment_id": "cf_autopay_1"}}
    assert cf_hook(c, "/webhooks/cashfree/subscription", paid, "test-secret").json()["pending"] == 0
    assert cf_hook(c, "/webhooks/cashfree/subscription", paid, "test-secret").json()["duplicate"]
    assert A.q("select method,status from payments where txn_id='cf_autopay_1'")[0] == {"method": "autopay", "status": "paid"}
    assert c.post(f"/onboarding/{ob['id']}/approve").status_code == 400


def test_onboarding_call_webhook(c):
    k = A.voice_key()
    for phone, expect in (("9876500011", "connected"), ("9876500012", "no_answer")):
        A.q("insert into onboarding(token,name,phone,room,sharing,rent,deposit,call_language,expires) values(?,?,?,?,?,?,?,?,?)",
            (f"tok{phone}", "Meena", phone, "303", 4, 7000, 14000, "hi", "2999-01-01 00:00:00"))
    ids = {r["phone"]: r["id"] for r in A.q("select id, phone from onboarding where phone in ('9876500011','9876500012')")}
    hook = lambda phone, **kw: c.post(f"/webhooks/sarvam/onboarding?k={k}", json={"webhook_config": {"metadata": {"onboarding_id": ids[phone]}}, **kw})
    assert c.post("/webhooks/sarvam/onboarding?k=bad", json={}).status_code == 403
    hook("9876500011", status="connected", final_agent_variables={
        "name_confirmed": "no", "corrected_name": "Meenakshi", "whatsapp_same": "no", "whatsapp_number": "+91 98765 00099", "form_ok": "will_fill"})
    o = A.q("select * from onboarding where id=?", (ids["9876500011"],))[0]
    assert (o["name"], o["whatsapp"], o["status"]) == ("Meenakshi", "9876500099", "link_sent")
    assert any("tok9876500011" in m["text"] for m in A.q("select text from messages where role='tenant' and phone='9876500099'"))
    assert hook("9876500011", status="connected").json()["ignored"]  # repeated delivery

    hook("9876500012", status="no_answer")
    o = A.q("select * from onboarding where id=?", (ids["9876500012"],))[0]
    assert (o["call_outcome"], o["status"]) == ("no_answer", "link_sent")  # no pickup: the form still goes out


def test_onboarding_needs_owner_confirmation(c):
    owner_out = lambda: [m["text"] for m in c.get("/messages").json() if m["direction"] == "out"]
    c.post("/whatsapp/simulate", data={"text": "onboard Asha 9876500077 room 204"})
    ob = A.q("select * from onboarding where phone='9876500077'")[0]
    assert ob["status"] == "pending_confirm"
    assert any("Call Asha on 9 8 7 6 5 0 0 0 7 7 for room 204" in t for t in owner_out())  # read back, digit by digit
    assert not A.q("select 1 from messages where text like ?", (f"%{ob['token']}%",))  # nothing sent yet

    c.post("/whatsapp/simulate", data={"text": "yes"})
    assert A.q("select status from onboarding where id=?", (ob["id"],))[0]["status"] == "link_sent"
    assert A.q("select 1 from messages where text like ?", (f"%{ob['token']}%",))

    c.post("/whatsapp/simulate", data={"text": "onboard Bela 9876500078 room 204"})
    c.post("/whatsapp/simulate", data={"text": "no"})
    assert A.q("select status from onboarding where phone='9876500078'")[0]["status"] == "cancelled"
    c.post("/whatsapp/simulate", data={"text": "yes"})  # nothing pending: handled as a normal message, no call
    assert not A.q("select 1 from onboarding where phone='9876500078' and status='link_sent'")
    assert not A.q("select 1 from onboarding where status='pending_confirm' and phone in ('9876500077','9876500078')")


def test_public_tunnel_only_reaches_public_paths(c):
    web = {"x-forwarded-proto": "https", "host": "example.ngrok-free.dev"}  # how a request looks through ngrok
    for path in ("/tenants/all", "/activity", "/dues", "/messages", "/onboarding", "/onboarding/1/file/aadhaar", "/summary", "/config"):
        assert c.get(path, headers=web).status_code == 404, path
    assert c.post("/tools/send_reminders", headers=web).status_code == 404
    assert c.post("/voice/owner", headers=web, data={"text": "hi"}).status_code == 404
    assert c.post("/payouts/confirm", headers=web, json={"payout_id": 1, "pin": "1234"}).status_code == 404
    assert c.get("/tenants/all").status_code == 200  # the local dashboard still works
    # the paths the outside world needs stay open
    assert c.get("/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=kiraya&hub.challenge=abc", headers=web).text == "abc"
    assert c.get("/onboard-api/nope", headers=web).status_code == 404  # reaches the app: unknown token
    assert c.post("/webhooks/sarvam/call?k=bad", headers=web, json={}).status_code == 403


def test_receipt_link_needs_its_secret_from_outside(c):
    web = {"x-forwarded-proto": "https", "host": "example.ngrok-free.dev"}
    rno = A.q("select receipt_no from payments where receipt_no is not null limit 1")[0]["receipt_no"]
    assert c.get(f"/receipt/{rno}", headers=web).status_code == 404
    assert c.get(f"/receipt/{rno}?k=wrong", headers=web).status_code == 404
    assert "Transaction ID" in c.get(f"/receipt/{rno}?k={A.receipt_key(rno)}", headers=web).text
    assert "Transaction ID" in c.get(f"/receipt/{rno}").text  # local dashboard link has no key


def test_complaints_are_taken_from_registered_numbers_only(c):
    k = A.voice_key()
    before = len(c.get("/activity").json()["tickets"])
    body = {"user_phone_number": "+919111111111", "interaction_id": "i-unknown-1",
            "final_agent_variables": {"issue": "geyser in room 101 gives sparks", "urgency": "high"},
            "interaction_transcript": [{"role": "user", "en_text": "geyser sparks"}]}
    assert c.post(f"/webhooks/sarvam/inbound?k={k}", json=body).json().get("ignored")
    assert A.q("select source from enquiries where phone='9111111111'")[0]["source"] == "call"  # the unknown caller is recorded as an enquiry
    tickets = c.get("/activity").json()
    assert len(tickets["tickets"]) == before  # nothing is logged for a number that is not registered
    assert any(a["action"] == "complaint_rejected_unregistered" for a in tickets["audit"])
    assert any("Contact: +91 9111111111" in m["text"] for m in c.get("/messages").json())  # the owner gets the caller's number as an enquiry
    # a registered number still goes through
    ok = dict(body, user_phone_number="+919000000002", interaction_id="i-known-1")
    assert c.post(f"/webhooks/sarvam/inbound?k={k}", json=ok).json() == {"ok": True}
    assert any("sparks" in t["issue"] for t in c.get("/activity").json()["tickets"])


def test_failed_whatsapp_delivery_is_recorded(c):
    ev = {"entry": [{"changes": [{"value": {"statuses": [{"status": "failed", "recipient_id": "919000000009",
                                                          "errors": [{"code": 131047, "title": "Re-engagement message"}]}]}}]}]}
    assert c.post("/webhooks/whatsapp", json=ev).json() == {"ok": True}
    assert any("131047" in a["payload"] for a in c.get("/activity").json()["audit"] if a["action"] == "delivery_failed")


def _in_days(n):
    import datetime as dt
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def _token(oid):
    return A.q("select token from offboarding where id=?", (oid,))[0]["token"]


def _tenant_msgs():
    return [m["text"] for m in A.q("select text from messages where role='tenant' and direction='out'")]


def test_offboarding_refund_flow(c):
    vid = tid(c, "Vikram")  # 3-sharing, deposit 18000, rent paid
    before = c.get("/summary").json()["deposits_held"]
    oid = c.post("/offboarding/start", json={"tenant_id": vid, "move_out_date": _in_days(10), "reason": "new job"}).json()["offboarding_id"]
    assert "already" in c.post("/offboarding/start", json={"tenant_id": vid, "move_out_date": _in_days(10)}).json()["detail"]
    f = c.post(f"/offboarding/{oid}/deductions", json={"deductions": [{"reason": "painting", "amount": 1500}, {"reason": "cleaning", "amount": 500}]}).json()
    assert (f["deposit"], f["deductions_total"], f["unpaid_dues"], f["refund"]) == (18000, 2000, 0, 16000)
    assert c.post(f"/offboarding/{oid}/deductions", json={"deductions": [{"reason": "", "amount": 5}]}).status_code == 400

    sent = c.post(f"/offboarding/{oid}/propose").json()
    assert sent["refund"] == 16000 and f"/settle/{_token(oid)}" in sent["link"]
    assert any(_token(oid) in t and "Refund to you: ₹16,000" in t for t in _tenant_msgs())
    tok = _token(oid)
    assert c.get(f"/settle-api/{tok}").json()["refund"] == 16000 and c.get(f"/settle-api/{tok}").json()["requires_bank"]

    ans = f"/settle-api/{tok}"
    assert c.post(ans, json={"action": "accept", "account_holder": "Vikram S", "account_number": "123456789012", "ifsc": "BADCODE"}).status_code == 400
    assert c.post(ans, json={"action": "accept", "account_holder": "", "account_number": "123456789012", "ifsc": "HDFC0001234"}).status_code == 400
    assert c.post(ans, json={"action": "accept", "account_holder": "Vikram S", "account_number": "1234 5678 9012", "ifsc": "hdfc0001234"}).json()["status"] == "accepted"
    assert c.post(ans, json={"action": "dispute", "note": "x"}).status_code == 409  # answered once
    d = c.get(f"/offboarding/{oid}").json()
    assert d["status"] == "accepted" and d["bank"] == {"holder": "Vikram S", "last4": "9012", "ifsc": "HDFC0001234"}  # full account number is never shown

    r = c.post(f"/offboarding/{oid}/payout").json()  # 16000 is above the 1000 vendor limit in tests: deposits have their own cap
    assert r["status"] == "pending_confirm" and "16000" in r["readback"]
    assert c.post(f"/offboarding/{oid}/payout/confirm", json={"pin": "0000"}).status_code == 400
    assert c.get(f"/offboarding/{oid}").json()["status"] == "accepted"  # a wrong PIN moves nothing
    assert c.post(f"/offboarding/{oid}/payout/confirm", json={"pin": "1234"}).json()["status"] == "success"

    assert c.get(f"/offboarding/{oid}").json()["status"] == "refunded"
    assert all(t["name"] != "Vikram" for t in c.get("/tenants/all").json())  # the bed is free again
    assert c.get(f"/tenants/{vid}").json()["tenant"]["status"] == "moved_out"  # history stays readable
    assert c.get("/summary").json()["deposits_held"] == before - 18000
    assert any(p["kind"] == "deposit" and p["amount"] == 16000 and p["status"] == "success" for p in c.get("/activity").json()["payouts"])
    assert any("Transaction ID:" in t and "account ending 9012" in t for t in _tenant_msgs())
    assert any("moved out" in m["text"] for m in c.get("/messages").json() if m["direction"] == "out")
    assert c.post(f"/offboarding/{oid}/payout/confirm", json={"pin": "1234"}).status_code == 400  # no double refund


def test_offboarding_dispute_then_revised_settlement(c):
    rid = tid(c, "Rohan")
    oid = c.post("/offboarding/start", json={"tenant_id": rid, "move_out_date": _in_days(5)}).json()["offboarding_id"]
    c.post(f"/offboarding/{oid}/propose")
    tok = _token(oid)
    assert c.post(f"/settle-api/{tok}", json={"action": "dispute", "note": " "}).status_code == 400
    assert c.post(f"/settle-api/{tok}", json={"action": "dispute", "note": "I already paid for cleaning"}).json()["status"] == "disputed"
    assert c.get(f"/offboarding/{oid}").json()["dispute_note"] == "I already paid for cleaning"
    assert any("does not agree" in m["text"] for m in c.get("/messages").json() if m["direction"] == "out")

    # the owner revises through the WhatsApp tool; the tenant must be sent the new figures again
    r = c.post("/tools/add_deduction", json={"tenant_name": "Rohan", "reason": "fan blade", "amount": 300}).json()
    assert r["status"] == "notice" and r["refund"] == 14000 - 300
    assert c.post(f"/settle-api/{tok}", json={"action": "accept"}).status_code == 409  # the old link cannot accept new figures
    c.post(f"/offboarding/{oid}/propose")
    assert c.post(f"/settle-api/{tok}", json={"action": "accept", "account_holder": "Rohan K", "account_number": "998877665544", "ifsc": "SBIN0001234"}).json()["status"] == "accepted"
    assert c.post(f"/offboarding/{oid}/deductions", json={"deductions": []}).status_code == 400  # accepted settlements are locked
    assert c.post(f"/offboarding/{oid}/cancel").json()["status"] == "cancelled"
    assert c.get(f"/tenants/{rid}").json()["tenant"]["status"] == "active"  # cancelling keeps the tenant


def test_offboarding_deductions_larger_than_deposit(c):
    aid = tid(c, "Atrinandan")  # deposit 22000, this month's rent 11000 unpaid
    oid = c.post("/offboarding/start", json={"tenant_id": aid, "move_out_date": _in_days(3)}).json()["offboarding_id"]
    f = c.post(f"/offboarding/{oid}/deductions", json={"deductions": [{"reason": "broken window", "amount": 15000}]}).json()
    assert (f["refund"], f["shortfall"], f["unpaid_dues"]) == (0, 4000, 11000)
    c.post(f"/offboarding/{oid}/propose")
    tok = _token(oid)
    assert c.get(f"/settle-api/{tok}").json()["requires_bank"] is False
    assert c.post(f"/settle-api/{tok}", json={"action": "accept"}).json()["status"] == "accepted"
    assert c.post(f"/offboarding/{oid}/payout").status_code == 400  # nothing to refund
    assert c.post(f"/offboarding/{oid}/complete").json()["status"] == "closed"
    row = next(r for r in c.get("/ledger").json()["rows"] if r["name"] == "Atrinandan")
    assert row["paid"] == 7000 and row["pending"] == 4000  # the 7000 left in the deposit settles rent; 4000 is still owed
    assert any(p["method"] == "deposit" and p["paid"] == 7000 for p in c.get("/activity").json()["payments"])
    assert c.get(f"/tenants/{aid}").json()["tenant"]["status"] == "moved_out"


def test_owner_can_start_a_move_out_on_whatsapp(c):
    date = _in_days(20)
    c.post("/whatsapp/simulate", data={"text": f"Joseph moving out on {date}"})
    ob = A.q("select o.* from offboarding o join tenants t on t.id=o.tenant_id where t.name='Joseph'")[0]
    assert (ob["status"], ob["move_out_date"]) == ("notice", date)
    c.post("/whatsapp/simulate", data={"text": "Joseph deduct 500 for cleaning"})
    assert '"cleaning"' in A.q("select deductions_json from offboarding where id=?", (ob["id"],))[0]["deductions_json"]
    assert not any("settle" in t for t in _tenant_msgs() if "Joseph" in t)  # the tenant hears nothing until the owner sends it


def test_settlement_pages_are_public_but_owner_screens_are_not(c):
    web = {"x-forwarded-proto": "https", "host": "example.ngrok-free.dev"}
    assert c.get("/settle/anything", headers=web).status_code == 200
    assert c.get("/settle-api/nope", headers=web).json()["detail"] == "This link is not valid."
    for path in ("/offboarding", "/offboarding/1"):
        assert c.get(path, headers=web).status_code == 404
    for path in ("/offboarding/1/propose", "/offboarding/1/payout", "/offboarding/1/payout/confirm", "/offboarding/start"):
        assert c.post(path, headers=web, json={}).status_code == 404


def _wa(c, text):
    c.post("/whatsapp/simulate", data={"text": text})


def test_owner_whatsapp_parity_reads_and_staged_actions(c):
    r = c.post("/tools/rooms_status").json()
    assert r["beds_total"] == 36 and 0 < r["beds_vacant"] < 36
    assert c.post("/tools/list_tenants").json()["tenants"]
    assert c.post("/tools/month_ledger", json={"month_": "1999-01"}).json()["error"]

    # a call is only staged until the owner says yes
    before = A.q("select count(*) n from calls")[0]["n"]
    room = next(x["room"] for x in r["rooms"] if x["free"])
    c.post("/tools/add_tenant", json={"name": "Latecomer", "phone": "9800011122", "room": room, "language": "en"})  # owes this month's rent
    late = "latecomer"
    _wa(c, f"call {late}")
    assert A.q("select count(*) n from calls")[0]["n"] == before
    assert A.q("select kind from pending_actions where status='pending'")[0]["kind"] == "call_tenant"
    _wa(c, "no")
    assert A.q("select count(*) n from pending_actions where status='pending'")[0]["n"] == 0
    assert A.q("select count(*) n from calls")[0]["n"] == before
    _wa(c, f"call {late}")
    _wa(c, "yes")
    assert A.q("select count(*) n from calls")[0]["n"] == before + 1


def test_owner_runs_a_whole_move_out_on_whatsapp(c):
    name = "Meera" if A.q("select 1 from tenants where name='Meera' and status='active'") else A.q("select name from tenants where status='active' and name not in ('Karthikeyan','Atrinandan','Dhananjayadas') limit 1")[0]["name"]
    t = A.q("select id from tenants where name=?", (name,))[0]["id"]
    c.post("/tools/start_offboarding", json={"tenant_name": name, "move_out_date": _in_days(4)})
    assert c.post("/tools/move_out_action", json={"tenant_name": name, "action": "complete"}).json()["error"]  # nothing accepted yet
    n = len(_tenant_msgs())
    s = c.post("/tools/move_out_action", json={"tenant_name": name, "action": "send_settlement"}).json()
    assert s["status"] == "needs_confirm" and len(_tenant_msgs()) == n  # staged, tenant not messaged
    _wa(c, "yes")
    assert len(_tenant_msgs()) == n + 1
    oid = A.q("select id,token from offboarding where tenant_id=?", (t,))[0]
    c.post(f"/settle-api/{oid['token']}", json={"action": "accept", "account_holder": "Some One", "account_number": "123456789012", "ifsc": "HDFC0001234"})
    st = c.post("/tools/offboarding_status", json={"tenant_name": name}).json()
    assert st["status"] == "accepted" and st["bank_last4"] == "9012"
    r = c.post("/tools/move_out_action", json={"tenant_name": name, "action": "prepare_refund"}).json()
    assert r["status"] == "pending_confirm"  # still needs CONFIRM + PIN
    c.post("/tools/move_out_action", json={"tenant_name": name, "action": "cancel"})
    _wa(c, "yes")
    assert A.q("select status from offboarding where id=?", (oid["id"],))[0]["status"] == "cancelled"


def test_owner_onboarding_review_and_tickets_on_whatsapp(c):
    tk = c.post("/tools/create_ticket", json={"tenant_id": c.get("/tenants/all").json()[0]["id"], "issue": "tap leaking"}).json()["ticket_id"]
    assert any(x["id"] == tk for x in c.post("/tools/list_tickets").json()["tickets"])
    assert c.post("/tools/close_ticket", json={"ticket_id": tk}).json()["status"] == "closed"
    assert c.post("/tools/close_ticket", json={"ticket_id": tk}).json()["error"]
    assert c.post("/tools/onboarding_decide", json={"name": "Nobody Here", "action": "approve"}).json()["error"]


def test_staged_calls_add_up_instead_of_replacing(c):
    room = next(x["room"] for x in c.post("/tools/rooms_status").json()["rooms"] if x["free"] > 1)
    for n, p in (("Late One", "9800011133"), ("Late Two", "9800011144")):
        c.post("/tools/add_tenant", json={"name": n, "phone": p, "room": room, "language": "en"})
    c.post("/tools/call_tenant", json={"tenant_name": "Late One"})
    c.post("/tools/call_tenant", json={"tenant_name": "Late Two"})
    row = A.q("select arg from pending_actions where status='pending'")
    assert len(row) == 1 and len(json.loads(row[0]["arg"])["tenant_ids"]) == 2
    before = A.q("select count(*) n from calls")[0]["n"]
    _wa(c, "yes")
    assert A.q("select count(*) n from calls")[0]["n"] == before + 2  # both get called


def test_spoken_names_still_find_the_tenant(c):
    for spoken in ("Dhananjay", "dhananjaya das", "Dhanajayadas"):
        assert A.find_tenant(name=spoken)["name"] == "Dhananjayadas"
    assert "not found" in c.post("/tools/tenant_info", json={"tenant_name": "Zzzz"}).json()["error"]


def test_spoken_yes_and_no_variants():
    for ok in ("Yes, indeed.", "yes please", "Okay go ahead", "No.", "no, cancel it", "ಹೌದು"):
        assert A.is_yes_no(ok), ok
    for bad in ("Who hasn't paid?", "yesterday Atri paid", "Call both of them and collect the rent"):
        assert not A.is_yes_no(bad), bad


def test_enquiry_quick_answers_and_name_capture(c):
    phone = "9345678901"
    c.post("/whatsapp/simulate", data={"text": "How much is the deposit and do you have vacancies?", "tenant_phone": phone})
    out = [m["text"] for m in A.q("select text from messages where phone=? and role='enquirer' and direction='out'", (phone,))]
    assert "22000" in out[0] and "vacant" in out[0] and "your name" in out[0]
    c.post("/whatsapp/simulate", data={"text": "Suresh Kumar", "tenant_phone": phone})
    e = A.q("select * from enquiries where phone=?", (phone,))[0]
    assert e["name"] == "Suresh Kumar" and "deposit" in e["first_msg"]
    assert any("Contact: +91 9345678901" in m["text"] and "Suresh Kumar" in m["text"] for m in c.get("/messages").json())  # owner has name and number


def test_payment_check_for_the_voice_agent(c):
    k = A.voice_key()
    room = A.q("select room from tenants where name='Dhananjayadas'")[0]["room"]
    r = c.get("/webhooks/sarvam/payment-check", params={"k": k, "tenant_name": "Dhananjayadas", "room": room}).json()
    assert r["status"] in ("partial", "unpaid", "paid") and "records" in r["message"]
    assert c.get("/webhooks/sarvam/payment-check", params={"k": "bad", "tenant_name": "x", "room": "1"}).status_code == 403
    assert c.get("/webhooks/sarvam/payment-check", params={"k": k, "tenant_name": "Nobody", "room": "999"}).json()["status"] == "unknown"


def _accepted_move_out(c, name, days=5, amount_rupees=None):
    tid_ = tid(c, name)
    oid = c.post("/offboarding/start", json={"tenant_id": tid_, "move_out_date": _in_days(days)}).json()["offboarding_id"]
    c.post(f"/offboarding/{oid}/propose")
    tok = _token(oid)
    r = c.post(f"/settle-api/{tok}", json={"action": "accept", "account_holder": "Refund Person", "account_number": "123456789012", "ifsc": "HDFC0001234"})
    assert r.json()["status"] == "accepted", r.text
    return tid_, oid


def test_real_payout_path_rejection_success_and_no_double_refund(c, monkeypatch):
    monkeypatch.setattr(A, "MOCK_PAYOUT", False)
    monkeypatch.setattr(A, "DEPOSIT_PAYOUT_LIMIT", 10**7, raising=False)
    monkeypatch.setattr(A, "payout_limit", lambda kind: 10**7)

    async def wallet(*a, **k):
        return {"available_balance": 100000.0}
    monkeypatch.setattr(A, "cashfree_wallet", wallet)
    t_id, oid = _accepted_move_out(c, "Arjun")
    refund = A.ob_figures(A.ob_row(oid))["refund"]

    # wallet too low: refused before any PIN is asked
    async def poor(*a, **k):
        return {"available_balance": 10.0}
    monkeypatch.setattr(A, "cashfree_wallet", poor)
    assert "wallet" in c.post(f"/offboarding/{oid}/payout").json()["detail"].lower()
    monkeypatch.setattr(A, "cashfree_wallet", wallet)

    # Cashfree refuses the transfer (4xx): nothing sent, owner can retry, move-out stays open
    async def refuse(method, path, ver, **kw):
        if path == "/payout/beneficiary":
            return {"beneficiary_id": "x"}
        raise A.ToolError("Cashfree 403: ip not whitelisted")
    monkeypatch.setattr(A, "cf", refuse)
    c.post(f"/offboarding/{oid}/payout")
    bad = c.post(f"/offboarding/{oid}/payout/confirm", json={"pin": "1234"})
    assert bad.status_code == 400 and "Nothing was sent" in bad.json()["detail"]
    assert A.q("select status from offboarding where id=?", (oid,))[0]["status"] == "accepted"
    assert A.q("select status from payouts where id=?", (A.ob_row(oid)["payout_id"],))[0]["status"] == "pending_confirm"

    # Cashfree accepts but is still processing: the move-out waits, a second refund is blocked
    sent = {}

    async def processing(method, path, ver, **kw):
        if path == "/payout/beneficiary":
            if method == "GET":
                raise A.ToolError("Cashfree 404: beneficiary_not_found")  # first refund: the account gets registered
            sent["beneficiary"] = kw["json"]
            return {"beneficiary_id": kw["json"]["beneficiary_id"]}
        sent.update(kw["json"])
        return {"status": "RECEIVED", "status_code": "PENDING"}
    monkeypatch.setattr(A, "cf", processing)
    assert c.post(f"/offboarding/{oid}/payout/confirm", json={"pin": "1234"}).json()["status"] == "processing"
    assert sent["transfer_amount"] == refund and sent["beneficiary_details"]["beneficiary_id"] == sent["beneficiary"]["beneficiary_id"]
    assert sent["beneficiary"]["beneficiary_instrument_details"] == {"bank_account_number": "123456789012", "bank_ifsc": "HDFC0001234"}
    assert A.q("select status from offboarding where id=?", (oid,))[0]["status"] == "accepted"
    assert "already processing" in c.post(f"/offboarding/{oid}/payout").json()["detail"]

    # Cashfree's payout webhook says it landed: the move-out closes and the tenant gets the transaction id
    monkeypatch.setattr(A, "CF_PAYOUT_SECRET", "test-secret")
    transfer_id = A.q("select cf_transfer_id from payouts where id=?", (A.ob_row(oid)["payout_id"],))[0]["cf_transfer_id"]
    body = {"type": "TRANSFER_SUCCESS", "data": {"transfer_id": transfer_id, "status": "SUCCESS", "status_code": "COMPLETED"}}
    assert cf_hook(c, "/webhooks/cashfree/payout", body, "test-secret").json()["status"] == "success"
    assert A.q("select status from offboarding where id=?", (oid,))[0]["status"] == "refunded"
    assert A.q("select status from tenants where id=?", (t_id,))[0]["status"] == "moved_out"
    assert any(transfer_id in m["text"] and "account ending 9012" in m["text"] for m in A.q("select text from messages where role='tenant' and direction='out'"))


def test_names_are_kept_in_english_letters(monkeypatch):
    import asyncio

    async def fake(path, **kw):
        assert path == "/transliterate"
        return {"transliterated_text": "keshav karthik"}
    monkeypatch.setattr(A, "SK", "key")
    monkeypatch.setattr(A, "sarvam", fake)
    assert asyncio.run(A.english_name("केशव कार्तिक")) == "Keshav Karthik"
    assert asyncio.run(A.english_name("Keshava Karthik")) == "Keshava Karthik"  # already English: untouched
