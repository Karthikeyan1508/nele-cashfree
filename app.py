"""Kiraya Mitra backend: voice agent for PG owners. Sarvam (voice/LLM) + Cashfree (money).
Runs fully in MOCK mode with no keys (fake payment page, canned translations) so the demo never dies."""
import asyncio, random, base64, datetime as dt, hashlib, hmac, html, json, os, re, sqlite3, uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent
if (ROOT / ".env").exists():  # tiny .env loader, no dependency
    for ln in (ROOT / ".env").read_text().splitlines():
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.split(" #")[0].strip())  # drop inline comments

SK = os.getenv("SARVAM_API_KEY", "")
CF_ID, CF_SECRET = os.getenv("CASHFREE_CLIENT_ID", ""), os.getenv("CASHFREE_CLIENT_SECRET", "")
CF_PAYOUT_ID = os.getenv("CASHFREE_PAYOUT_CLIENT_ID") or CF_ID
CF_PAYOUT_SECRET = os.getenv("CASHFREE_PAYOUT_CLIENT_SECRET") or CF_SECRET
CF_VERIFY_ID = os.getenv("CASHFREE_VERIFY_CLIENT_ID") or CF_ID
CF_VERIFY_SECRET = os.getenv("CASHFREE_VERIFY_CLIENT_SECRET") or CF_SECRET
CF_BASE = os.getenv("CASHFREE_BASE", "https://sandbox.cashfree.com")
CF_PAYOUT_BASE = os.getenv("CASHFREE_PAYOUT_BASE", "https://payout-gamma.cashfree.com" if "sandbox" in CF_BASE else "https://payout-api.cashfree.com")
MOCK_CF = not (CF_ID and CF_SECRET)
MOCK_PAYOUT = not (CF_PAYOUT_ID and CF_PAYOUT_SECRET)
MOCK_VERIFY = not (CF_VERIFY_ID and CF_VERIFY_SECRET)
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000")
PIN = os.getenv("PAYOUT_PIN", "1234")
DAILY_LIMIT = int(os.getenv("DAILY_PAYOUT_LIMIT", "5000"))
LLM = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b")
STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SPEAKER = os.getenv("SARVAM_SPEAKER", "shubh")
OWNER_PHONE = os.getenv("OWNER_PHONE", "9800000000")
WA_TOKEN, WA_PHONE_ID = os.getenv("WHATSAPP_TOKEN", ""), os.getenv("WHATSAPP_PHONE_ID", "")
WA_VERIFY, WA_APP_SECRET = os.getenv("WHATSAPP_VERIFY_TOKEN", "kiraya"), os.getenv("WHATSAPP_APP_SECRET", "")
WA_CODEC = os.getenv("WA_AUDIO_CODEC", "mp3")  # WhatsApp rejects wav; mp3/aac/ogg-opus are accepted
TW_SID, TW_TOKEN, TW_FROM = os.getenv("TWILIO_SID", ""), os.getenv("TWILIO_TOKEN", ""), os.getenv("TWILIO_FROM", "")
WA_LINK_TEMPLATE, WA_TEMPLATE_LANG = os.getenv("WA_LINK_TEMPLATE", ""), os.getenv("WA_TEMPLATE_LANG", "en")
WA_RECEIPT_TEMPLATE = os.getenv("WA_RECEIPT_TEMPLATE", "")  # body vars: name, amount, receipt no, transaction id
SV_KEY, SV_ORG, SV_WS = os.getenv("SARVAM_VOICE_API_KEY", ""), os.getenv("SARVAM_ORG_ID", ""), os.getenv("SARVAM_WORKSPACE_ID", "")
SV_APP, SV_VER = os.getenv("SARVAM_VOICE_APP_ID", ""), int(os.getenv("SARVAM_VOICE_APP_VERSION", "1") or 1)
SV_CONN, SV_NUM = os.getenv("SARVAM_VOICE_CONNECTION_ID", ""), os.getenv("SARVAM_VOICE_NUMBER", "")
VOICE = all([SV_KEY, SV_ORG, SV_WS, SV_APP, SV_CONN, SV_NUM])  # Sarvam Voice Agents (Samvaad) places the calls when fully configured
LANG_NAMES = {"kn": "Kannada", "hi": "Hindi", "bn": "Bengali", "ml": "Malayalam", "en": "English"}
SV_ONB_APP, SV_ONB_VER = os.getenv("SARVAM_ONBOARD_APP_ID", ""), int(os.getenv("SARVAM_ONBOARD_APP_VERSION", "1") or 1)
WA_ONBOARD_TEMPLATE = os.getenv("WA_ONBOARD_TEMPLATE", "")  # body vars: name, form link
UPLOADS = ROOT / "uploads"  # Aadhaar and photo files; never served publicly
UPLOADS.mkdir(exist_ok=True)
GRAPH = "https://graph.facebook.com/v21.0"
MIME = {"mp3": "audio/mpeg", "aac": "audio/aac", "opus": "audio/ogg", "wav": "audio/wav"}
DB = Path(os.getenv("DB_PATH", ROOT / "kiraya.db"))
AUDIO = ROOT / "static" / "audio"
AUDIO.mkdir(parents=True, exist_ok=True)
RATES = {2: 11000, 3: 9000, 4: 7000}  # rent per bed per month, by sharing type
# floor 1 = 2-sharing, floor 2 = 3-sharing, floor 3 = 4-sharing; rooms 101-104, 201-204, 301-304
ROOMS = {f"{f}0{n}": {"floor": f, "sharing": f + 1, "rent": RATES[f + 1]} for f in (1, 2, 3) for n in (1, 2, 3, 4)}
PROPERTY = {"name": "Sai Residency", "beds": sum(r["sharing"] for r in ROOMS.values()), "due_day": 5}
LC = {"kn": "kn-IN", "hi": "hi-IN", "bn": "bn-IN", "ml": "ml-IN", "en": "en-IN"}
LANGS = {"kannada": "kn", "hindi": "hi", "bengali": "bn", "malayalam": "ml", "english": "en"}

SCHEMA = """
create table if not exists tenants(id integer primary key, name text, phone text, room text, rent int, deposit int, language text, status text default 'active', whatsapp text);
create table if not exists onboarding(id integer primary key, token text unique, name text, phone text, room text, sharing int, rent int, deposit int, call_language text default 'hi', status text default 'invited', call_outcome text, whatsapp text, form_json text, aadhaar_file text, photo_file text, tenant_id int, created text default current_timestamp, submitted_at text, expires text);
create table if not exists ledger(id integer primary key, tenant_id int, month text, due int, paid int default 0, status text default 'due', promise_date text, unique(tenant_id, month));
create table if not exists payments(id integer primary key, tenant_id int, link_id text unique, amount int, paid int default 0, month text, url text, status text default 'created', method text default 'link', ts text default current_timestamp, paid_ts text, txn_id text, receipt_no text);
create table if not exists calls(id integer primary key, tenant_id int, month text, status text, outcome text, digit text, call_sid text, text text, audio_url text, ts text default current_timestamp, turn int default 1, transcript text default '', reason text, promise_date text);
create table if not exists messages(id integer primary key, ts text default current_timestamp, phone text, role text, direction text, kind text, text text, audio_url text, channel text default 'whatsapp', wa_id text unique);
create table if not exists promises(id integer primary key, tenant_id int, amount int, date text, reason text, ts text default current_timestamp);
create table if not exists payees(id integer primary key, name text, account_no text, ifsc text, verified int default 0, bank_name text);
create table if not exists payouts(id integer primary key, payee_id int, amount int, reason text, kind text default 'vendor', status text, cf_transfer_id text, day text, offboard_id int);
create table if not exists offboards(id integer primary key, tenant_id int, deductions_json text default '[]', refund int, status text default 'awaiting_deductions', created text default current_timestamp);
create table if not exists autopay(id integer primary key, tenant_id int unique, subscription_id text unique, cf_subscription_id text, token text unique, session_id text, status text default 'requested', first_charge text, last_payment_status text, created text default current_timestamp);
create table if not exists tickets(id integer primary key, tenant_id int, issue text, status text default 'open', ts text default current_timestamp);
create table if not exists audit_log(id integer primary key, ts text, actor text, action text, payload text);
create unique index if not exists payments_txn_id_uq on payments(txn_id) where txn_id is not null;
create unique index if not exists payouts_transfer_id_uq on payouts(cf_transfer_id) where cf_transfer_id is not null;
"""


# ---------- db ----------
def q(sql, a=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(sql, a)
        rows = [dict(r) for r in cur.fetchall()]
        c.commit()
        q.last = cur.lastrowid
        return rows
    finally:
        c.close()


def month():
    return dt.date.today().strftime("%Y-%m")


def shift_month(n):
    d = dt.date.today().replace(day=1)
    for _ in range(n):
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return d.strftime("%Y-%m")


def ensure_month():  # roll the ledger over: every active tenant owes rent each month
    q("insert or ignore into ledger(tenant_id,month,due) select id,?,rent from tenants where status='active'", (month(),))


def last10(p):
    return re.sub(r"\D", "", p or "")[-10:]


def e164(p):
    return "+91" + last10(p)


def audit(actor, action, payload):
    q("insert into audit_log(ts,actor,action,payload) values(?,?,?,?)",
      (dt.datetime.now().isoformat(), actor, action, json.dumps(payload, ensure_ascii=False, default=str)))


def seed():
    if q("select 1 from tenants"):
        return
    # (name, phone, language, late payer). Only Karthikeyan, Dhananjayadas and Keshava Karthik are unpaid this month; the rest are paid demo tenants.
    # Tenants are spread randomly over the rooms, never beyond a room's bed count (fixed seed, so the layout is stable).
    # Karthikeyan (the owner's own number) is a temporary extra late payer for testing; remove before the hackathon demo.
    rows = [("Karthikeyan", "9000000001", "en", 1), ("Dhananjayadas", "9000000002", "en", 1),
            ("Rahul", "9800000102", "hi", 0), ("Sneha", "9800000103", "bn", 0),
            ("Arjun", "9800000104", "ml", 0), ("Meera", "9800000105", "ml", 0),
            ("Rohan", "9800000201", "hi", 0), ("Priya", "9800000202", "bn", 0),
            ("Vikram", "9800000203", "hi", 0), ("Joseph", "9800000204", "ml", 0),
            ("Keshava Karthik", "9000000003", "en", 1)]
    rng = random.Random(7)
    free = {room: v["sharing"] for room, v in ROOMS.items()}
    for n, p, lang, late in rows:
        r = rng.choice([room for room, beds in free.items() if beds > 0])
        free[r] -= 1
        rent = ROOMS[r]["rent"]
        q("insert into tenants(name,phone,room,rent,deposit,language) values(?,?,?,?,?,?)", (n, p, r, rent, 2 * rent, lang))
        tid = q.last
        q("insert into ledger(tenant_id,month,due,paid,status) values(?,?,?,?,?)",
          (tid, month(), rent, 0 if late else rent, "due" if late else "paid"))
        if not late:
            q("insert into payments(tenant_id,link_id,amount,paid,month,url,status,method,paid_ts) values(?,?,?,?,?,'','paid','upi',?)",
              (tid, f"seed_{tid}_{month()}", rent, rent, month(), f"{month()}-04 10:15:00"))
        for back in (3, 2, 1):  # rent history; the late payers pay on the 14th
            m = shift_month(back)
            q("insert into ledger(tenant_id,month,due,paid,status) values(?,?,?,?,'paid')", (tid, m, rent, rent))
            q("insert into payments(tenant_id,link_id,amount,paid,month,url,status,method,paid_ts) values(?,?,?,?,?,'','paid',?,?)",
              (tid, f"seed_{tid}_{m}", rent, rent, m, "cash" if n == "Meera" else "upi", f"{m}-{14 if late else 5:02d} 11:00:00"))
    # sandbox test bank account from Cashfree docs; mock mode never calls the bank
    q("insert into payees(name,account_no,ifsc,verified,bank_name) values('Raju Kumar','026291800001191','YESB0000262',1,'Raju Kumar')")
    q("insert into payees(name,account_no,ifsc,verified) values('Suresh Plumber','111122223333','HDFC0000001',0)")


# ---------- sarvam ----------
async def sarvam(path, **kw):
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.sarvam.ai" + path, headers={"api-subscription-key": SK}, **kw)
        r.raise_for_status()
        return r.json()


async def tr(text, lang, fallback=None, src="en-IN"):
    if lang == "en" and src == "en-IN":
        return text
    if not SK:
        return fallback or text
    try:
        j = await sarvam("/translate", json={"input": text, "source_language_code": src,
                                              "target_language_code": LC[lang], "model": "mayura:v1"})
        return j["translated_text"]
    except Exception as e:
        print("translate failed:", e)
        return fallback or text


async def tts(text, lang, codec="wav"):
    if not SK:
        return None  # browser speechSynthesis takes over
    try:
        body = {"text": text[:2400], "target_language_code": LC[lang], "model": TTS_MODEL, "speaker": SPEAKER}
        if codec != "wav":
            body["output_audio_codec"] = codec
        j = await sarvam("/text-to-speech", json=body)
        name = f"{uuid.uuid4().hex}.{codec}"
        (AUDIO / name).write_bytes(base64.b64decode(j["audios"][0]))
        return f"/static/audio/{name}"
    except Exception as e:
        print("tts failed:", e)
        return None


async def stt(data: bytes, name="a.webm", ctype="audio/webm"):
    j = await sarvam("/speech-to-text", files={"file": (name, data, ctype)},
                     data={"model": STT_MODEL, "mode": "translate"})  # translate => English text for the agent
    return j["transcript"]


# ---------- cashfree ----------
async def cf(method, path, ver, idempotency_key=None, credentials=None, **kw):
    client_id, client_secret = credentials or (CF_ID, CF_SECRET)
    headers = {"x-client-id": client_id, "x-client-secret": client_secret, "x-api-version": ver}
    if idempotency_key:
        headers["x-idempotency-key"] = idempotency_key
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(method, CF_BASE + path, headers=headers, **kw)
        if r.status_code >= 400:
            raise ToolError(f"Cashfree {r.status_code}: {r.text[:200]}")
        return r.json()


PAYOUT_TOKEN = {"value": None, "expires": 0.0}
WALLET_CACHE = {"value": None, "expires": 0.0}


async def cashfree_wallet(force=False):
    """Cashfree Payouts available balance; never falls back to a local estimate."""
    now = asyncio.get_running_loop().time()
    if not force and WALLET_CACHE["value"] and WALLET_CACHE["expires"] > now:
        return WALLET_CACHE["value"]
    if MOCK_PAYOUT:
        raise ToolError("Cashfree Payouts credentials are not configured")
    if not PAYOUT_TOKEN["value"] or PAYOUT_TOKEN["expires"] <= now:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(CF_PAYOUT_BASE + "/payout/v1/authorize", headers={
                "x-client-id": CF_PAYOUT_ID, "x-client-secret": CF_PAYOUT_SECRET})
        if r.status_code >= 400:
            raise ToolError(f"Cashfree Payouts auth failed ({r.status_code})")
        body = r.json()
        token = (body.get("data") or {}).get("token") or body.get("token")
        if not token:
            raise ToolError("Cashfree Payouts auth returned no token")
        PAYOUT_TOKEN.update(value=token, expires=now + 300)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(CF_PAYOUT_BASE + "/payout/v1.2/getBalance", headers={
            "authorization": f"Bearer {PAYOUT_TOKEN['value']}", "content-type": "application/json"})
    if r.status_code >= 400:
        PAYOUT_TOKEN["expires"] = 0
        raise ToolError(f"Cashfree balance fetch failed ({r.status_code})")
    data = (r.json().get("data") or {})
    try:
        value = {"available_balance": float(data["availableBalance"]), "ledger_balance": float(data["balance"]),
                 "source": "cashfree", "updated_at": dt.datetime.now().isoformat(timespec="seconds")}
    except (KeyError, TypeError, ValueError):
        raise ToolError("Cashfree balance response was invalid")
    WALLET_CACHE.update(value=value, expires=now + 10)
    return value


def refresh_wallet():
    WALLET_CACHE["expires"] = 0


# ---------- events ----------
EVENTS = []


async def publish(type_, announce_en=None, kn_fallback=None, **data):
    ev = {"id": len(EVENTS) + 1, "type": type_, **data}
    if announce_en:
        ev["announce"] = {"lang": "kn", "text": await tr(announce_en, "kn", fallback=kn_fallback)}
    EVENTS.append(ev)


# ---------- tools ----------
class ToolError(Exception):
    pass


def tenant_row(tid):
    r = q("select * from tenants where id=? and status='active'", (tid,))
    if not r:
        raise ToolError(f"tenant {tid} not found")
    return r[0]


def find_tenant(tid=None, name=None):
    if tid:
        return tenant_row(int(tid))
    r = q("select * from tenants where status='active' and (lower(name)=lower(?) or room=?)", (name or "", name or ""))
    if not r:
        raise ToolError(f"tenant '{name}' not found")
    return r[0]


async def make_link(t, amount, mon, purpose=None):
    link_id = f"rent_{t['id']}_{uuid.uuid4().hex[:8]}"
    purpose = purpose or f"Rent {mon} Room {t['room']}"
    purpose = purpose if t["name"].lower() in purpose.lower() else f"{t['name']} - {purpose}"
    if MOCK_CF:
        url = f"{PUBLIC_URL}/pay/{link_id}"
    else:
        j = await cf("POST", "/pg/links", "2025-01-01", idempotency_key=link_id, json={
            "link_id": link_id, "link_amount": amount, "link_currency": "INR",
            "link_purpose": purpose,
            "customer_details": {"customer_name": t["name"], "customer_phone": t["phone"]},
            "link_notes": {"tenant_name": t["name"], "room": t["room"]},
            "link_partial_payments": False, "link_notify": {"send_sms": False, "send_email": False},
            "link_meta": {"notify_url": PUBLIC_URL + "/webhooks/cashfree/payment"}})
        url = j["link_url"]
    q("insert into payments(tenant_id,link_id,amount,month,url) values(?,?,?,?,?)", (t["id"], link_id, amount, mon, url))
    return {"link_id": link_id, "url": url, "amount": amount, "status": "created"}


async def t_add_tenant(name, phone, room, rent=None, deposit=None, language="hi", due_day=5):
    language = LANGS.get(str(language).lower(), language)
    if language not in LC:
        raise ToolError("language must be one of kn hi bn ml en")
    room = str(room)
    if room not in ROOMS:
        raise ToolError(f"room {room} does not exist; rooms are {', '.join(ROOMS)}")
    if q("select count(*) n from tenants where status='active' and room=?", (room,))[0]["n"] >= ROOMS[room]["sharing"]:
        raise ToolError(f"room {room} is full ({ROOMS[room]['sharing']}-sharing)")
    rent = int(rent or ROOMS[room]["rent"])
    deposit = int(deposit if deposit is not None else 2 * rent)  # deposit = 2 months' rent
    q("insert into tenants(name,phone,room,rent,deposit,language) values(?,?,?,?,?,?)",
      (name, phone, room, rent, deposit, language))
    t = tenant_row(q.last)
    q("insert or ignore into ledger(tenant_id,month,due) values(?,?,?)", (t["id"], month(), t["rent"]))
    # welcome voice note + one link for deposit + first rent, in tenant's language
    link = await make_link(t, t["rent"] + t["deposit"], month(), f"Deposit + first rent Room {room}")
    msg = (f"Welcome {name}! Room {room}. Please pay deposit and first month's rent, Rs {t['rent'] + t['deposit']}, "
           f"using this link: {link['url']}")
    text = await tr(msg, language)
    return {"tenant_id": t["id"], "link": link, "welcome_text": text, "welcome_audio": await tts(text, language)}


async def t_get_dues(tenant_id=None, only_pending=True):
    ensure_month()
    sql = ("select t.id tenant_id,t.name,t.room,t.language,t.rent,l.due,l.paid,l.due-l.paid pending,l.status,l.promise_date "
           "from tenants t join ledger l on l.tenant_id=t.id and l.month=? where t.status='active'")
    a = [month()]
    if tenant_id:
        sql += " and t.id=?"
        a.append(int(tenant_id))
    rows = q(sql + " order by t.room", a)
    return {"dues": [r for r in rows if r["pending"] > 0] if only_pending else rows}


async def t_create_rent_link(tenant_id, amount=None, month_=None):
    t = tenant_row(int(tenant_id))
    d = (await t_get_dues(t["id"], False))["dues"]
    pending = d[0]["pending"] if d else t["rent"]
    amount = int(amount or pending)
    if amount <= 0 or amount > pending:
        raise ToolError(f"amount must be between 1 and pending ₹{pending}")
    return await make_link(t, amount, month_ or month())


async def t_log_promise(tenant_id, amount, date, reason=""):
    t = tenant_row(int(tenant_id))
    dt.date.fromisoformat(date)  # validates
    q("insert into promises(tenant_id,amount,date,reason) values(?,?,?,?)", (t["id"], int(amount), date, reason))
    pid = q.last
    q("update ledger set promise_date=?, status=case when paid=0 then 'promised' else status end where tenant_id=? and month=?",
      (date, t["id"], month()))
    await publish("promise_logged", tenant_id=t["id"], room=t["room"], name=t["name"], amount=int(amount), date=date, reason=reason)
    return {"promise_id": pid, "date": date}


async def t_create_ticket(tenant_id, issue):
    t = tenant_row(int(tenant_id))
    q("insert into tickets(tenant_id,issue) values(?,?)", (t["id"], issue))
    tid = q.last
    await publish("ticket_created", f"Room {t['room']}: {issue}", tenant_id=t["id"], room=t["room"], issue=issue, ticket_id=tid)
    return {"ticket_id": tid, "status": "open"}


async def t_send_reminders(tenant_ids=None):
    dues = (await t_get_dues())["dues"]
    if tenant_ids:
        dues = [d for d in dues if d["tenant_id"] in [int(x) for x in tenant_ids]]
    calls = []
    for d in dues:
        t = tenant_row(d["tenant_id"])
        calls.append({"name": t["name"], "room": t["room"], "lang": t["language"], **await place_call(t, d["pending"])})
    return {"calls": calls}


async def t_record_payment(tenant_id, amount, method="cash"):
    t = tenant_row(int(tenant_id))
    d = (await t_get_dues(t["id"], False))["dues"][0]
    amount = int(amount)
    if amount <= 0 or amount > d["pending"]:
        raise ToolError(f"amount must be between 1 and pending ₹{d['pending']}")
    link_id = f"manual_{t['id']}_{uuid.uuid4().hex[:8]}"
    q("insert into payments(tenant_id,link_id,amount,month,url,method) values(?,?,?,?,'',?)", (t["id"], link_id, amount, month(), method))
    return await apply_payment(link_id, amount, f"{method.upper()}-{uuid.uuid4().hex[:8].upper()}")


async def tenant_detail(tid):
    t = tenant_row(int(tid))
    return {"tenant": t,
            "ledger": q("select month,due,paid,due-paid pending,status,promise_date from ledger where tenant_id=? order by month desc", (tid,)),
            "payments": q("select amount,paid,month,method,status,paid_ts,ts,txn_id,receipt_no from payments where tenant_id=? order by id desc", (tid,)),
            "promises": q("select amount,date,reason,ts from promises where tenant_id=? order by id desc", (tid,)),
            "tickets": q("select id,issue,status,ts from tickets where tenant_id=? order by id desc", (tid,)),
            "calls": q("select id,month,status,outcome,ts,transcript,reason,promise_date from calls where tenant_id=? order by id desc", (tid,)),
            "profile": next(iter(q("select id,form_json,aadhaar_file is not null has_aadhaar,photo_file is not null has_photo from onboarding where tenant_id=?", (tid,))), None)}


async def t_tenant_info(tenant_id):
    return await tenant_detail(tenant_id)


async def t_verify_payee(name, account_no=None, ifsc=None):
    if MOCK_VERIFY:
        ok, bank_name = True, name
    else:
        if not (account_no and ifsc):
            raise ToolError("account_no and ifsc required")
        j = await cf("POST", "/verification/bank-account/sync", "2023-12-18",
                     credentials=(CF_VERIFY_ID, CF_VERIFY_SECRET),
                     json={"bank_account": account_no, "ifsc": ifsc, "name": name})
        ok, bank_name = j.get("account_status") == "VALID", j.get("name_at_bank")
    q("insert into payees(name,account_no,ifsc,verified,bank_name) values(?,?,?,?,?)",
      (name, account_no, ifsc, int(ok), bank_name))
    return {"payee_id": q.last, "verified": ok, "bank_name_match": bank_name}


def spent_today():
    return q("select coalesce(sum(amount),0) s from payouts where day=? and status in ('success','processing')",
             (dt.date.today().isoformat(),))[0]["s"]


async def t_prepare_payout(amount, reason="repair", payee_id=None, payee_name=None, kind="vendor"):
    amount = int(amount)
    p = (q("select * from payees where id=?", (payee_id,)) if payee_id else
         q("select * from payees where lower(name) like lower(?)", (f"%{payee_name}%",)))
    if not p:
        raise ToolError("payee not saved; verify the payee first")
    p = p[0]
    if not p["verified"]:
        raise ToolError(f"{p['name']} is not a verified payee; payout blocked")
    if amount <= 0:
        raise ToolError("amount must be positive")
    if spent_today() + amount > DAILY_LIMIT:
        raise ToolError(f"daily payout limit ₹{DAILY_LIMIT} would be exceeded")
    q("insert into payouts(payee_id,amount,reason,kind,status,day) values(?,?,?,?,'pending_confirm',?)",
      (p["id"], amount, reason, kind, dt.date.today().isoformat()))
    return {"payout_id": q.last, "readback": f"{p['name']}, ₹{amount}, {reason}", "requires_pin": True,
            "status": "pending_confirm"}


async def confirm_payout(payout_id, pin):
    if not hmac.compare_digest(str(pin), PIN):
        audit("owner", "payout_bad_pin", {"payout_id": payout_id})
        raise ToolError("wrong PIN")
    r = q("select o.*, p.name, p.account_no, p.ifsc from payouts o join payees p on p.id=o.payee_id where o.id=?", (payout_id,))
    if not r or r[0]["status"] != "pending_confirm":
        raise ToolError("payout not awaiting confirmation")
    o = r[0]
    wallet_refund = o["kind"] == "deposit" and o.get("offboard_id")
    if wallet_refund and o["amount"] > (await cashfree_wallet())["available_balance"]:
        raise ToolError("owner wallet balance is too low for this refund")
    if not wallet_refund and spent_today() + o["amount"] > DAILY_LIMIT:
        raise ToolError("daily payout limit exceeded")
    tid = f"wallet_refund_{o['id']}" if wallet_refund else f"payout_{o['id']}_{uuid.uuid4().hex[:6]}"
    status = "success"
    if not wallet_refund and not MOCK_PAYOUT:
        q("update payouts set status='processing', cf_transfer_id=? where id=?", (tid, o["id"]))
        try:
            j = await cf("POST", "/payout/transfers", "2024-01-01", idempotency_key=tid,
                         credentials=(CF_PAYOUT_ID, CF_PAYOUT_SECRET), json={
                "transfer_id": tid, "transfer_amount": o["amount"], "transfer_currency": "INR", "transfer_mode": "imps",
                "beneficiary_details": {"beneficiary_id": f"payee_{o['payee_id']}", "beneficiary_name": o["name"],
                                        "beneficiary_instrument_details": {"bank_account_number": o["account_no"],
                                                                           "bank_ifsc": o["ifsc"]}}})
            status = ("success" if str(j.get("status", "")).upper() == "SUCCESS" and
                      str(j.get("status_code", "")).upper() == "COMPLETED" else "processing")
        except ToolError as e:
            audit("owner", "payout_status_unknown", {"payout_id": o["id"], "transfer_id": tid, "err": str(e)})
            raise ToolError(f"payout submitted but status is unknown; reconcile transfer {tid}")
    q("update payouts set status=?, cf_transfer_id=? where id=?", (status, tid, o["id"]))
    refresh_wallet()
    audit("owner", "payout_confirmed", {"payout_id": o["id"], "amount": o["amount"], "to": o["name"], "status": status})
    if status == "success":
        if wallet_refund:
            q("update offboards set status='refunded' where id=?", (o["offboard_id"],))
            q("update tenants set status='moved_out' where id=(select tenant_id from offboards where id=?)", (o["offboard_id"],))
        await publish("payout_done", f"Paid {o['name']} {o['amount']} rupees", payee=o["name"], amount=o["amount"], reason=o["reason"])
    return {"status": status, "cashfree_transfer_id": tid}


async def t_settle_deposit(tenant_id, deductions=None, account_no=None, ifsc=None):
    t = tenant_row(int(tenant_id))
    deductions = deductions or []
    ded = sum(int(d["amount"]) for d in deductions)
    dues = (await t_get_dues(t["id"], False))["dues"]
    pending = dues[0]["pending"] if dues else 0
    refund = max(t["deposit"] - ded - pending, 0)
    out = {"deposit": t["deposit"], "deductions": deductions, "deductions_total": ded, "unpaid_dues": pending, "refund": refund,
           "tenant_language": t["language"]}
    if refund and account_no and ifsc:
        v = await t_verify_payee(t["name"], account_no, ifsc)
        if v["verified"]:
            out["payout"] = await t_prepare_payout(refund, f"Deposit refund Room {t['room']}", payee_id=v["payee_id"], kind="deposit")
        else:
            out["error"] = "refund account not verified"
    return out


async def t_start_offboarding(tenant_id):
    t = tenant_row(int(tenant_id))
    old = q("select * from offboards where tenant_id=? and status in ('awaiting_deductions','pending_refund') order by id desc limit 1", (t["id"],))
    if old:
        oid = old[0]["id"]
    else:
        q("insert into offboards(tenant_id) values(?)", (t["id"],))
        oid = q.last
    return {"offboard_id": oid, "tenant_id": t["id"], "tenant": t["name"], "deposit": t["deposit"],
            "question": f"What deductions should I make from {t['name']}'s deposit of ₹{t['deposit']}? Say no deductions, or give each reason and amount."}


async def t_finish_offboarding(tenant_id, deductions=None):
    t = tenant_row(int(tenant_id))
    ob = q("select * from offboards where tenant_id=? and status='awaiting_deductions' order by id desc limit 1", (t["id"],))
    if not ob:
        raise ToolError("start offboarding this tenant first")
    deductions = deductions or []
    clean = []
    for d in deductions:
        reason, amount = str(d.get("reason") or "deduction").strip()[:100], int(d.get("amount") or 0)
        if amount < 0:
            raise ToolError("deductions cannot be negative")
        if amount:
            clean.append({"reason": reason, "amount": amount})
    deducted = sum(d["amount"] for d in clean)
    if deducted > t["deposit"]:
        raise ToolError("deductions cannot exceed the deposit")
    dues = (await t_get_dues(t["id"], False))["dues"]
    unpaid = max(dues[0]["pending"], 0) if dues else 0
    refund = max(t["deposit"] - deducted - unpaid, 0)
    balance = (await cashfree_wallet())["available_balance"]
    if refund > balance:
        raise ToolError(f"owner wallet has ₹{balance:g}, but the refund is ₹{refund}")
    oid = ob[0]["id"]
    q("update offboards set deductions_json=?, refund=?, status=? where id=?",
      (json.dumps(clean), refund, "pending_refund" if refund else "complete", oid))
    if not refund:
        q("update tenants set status='moved_out' where id=?", (t["id"],))
        return {"offboard_id": oid, "tenant": t["name"], "deposit": t["deposit"], "deductions": clean,
                "unpaid_dues": unpaid, "refund": 0, "status": "moved_out", "wallet_balance": balance}
    q("insert into payees(name,verified,bank_name) values(?,1,?)", (f"Tenant refund - {t['name']}", t["name"]))
    payee_id = q.last
    q("insert into payouts(payee_id,amount,reason,kind,status,day,offboard_id) values(?,?,?,'deposit','pending_confirm',?,?)",
      (payee_id, refund, f"Deposit refund Room {t['room']}", dt.date.today().isoformat(), oid))
    payout = {"payout_id": q.last, "readback": f"Refund {t['name']} ₹{refund} from owner wallet",
              "requires_pin": True, "status": "pending_confirm"}
    return {"offboard_id": oid, "tenant": t["name"], "deposit": t["deposit"], "deductions": clean,
            "unpaid_dues": unpaid, "refund": refund, "wallet_balance": balance, "payout": payout}


async def t_monthly_summary(month_=None):
    m = month_ or month()
    l = q("select coalesce(sum(paid),0) c, coalesce(sum(due-paid),0) p from ledger where month=?", (m,))[0]
    rep = q("select coalesce(sum(amount),0) s from payouts where kind='vendor' and status in ('success','processing') and substr(day,1,7)=?", (m,))[0]["s"]
    act = q("select count(*) n, coalesce(sum(deposit),0) d from tenants where status='active'")[0]
    tot = l["c"] + l["p"]
    try:
        balance = (await cashfree_wallet())["available_balance"]
        wallet_status = "live"
    except ToolError:
        balance, wallet_status = None, "unavailable"
    return {"collected": l["c"], "pending": l["p"], "collection_rate": round(100 * l["c"] / tot) if tot else 0,
            "repairs_spent": rep, "beds_vacant": PROPERTY["beds"] - act["n"], "deposits_held": act["d"],
            "wallet_balance": balance, "wallet_status": wallet_status, "month": m}


def P(**props):  # schema helper: P(name="string", amount="integer")
    return {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": list(props)}


# name -> (fn, description, schema, who may call it)
TOOLS = {
    "add_tenant": (t_add_tenant, "Add a tenant to a room (rent and deposit default from the room's sharing rate). language: kn hi bn ml en.",
                   {**P(name="string", phone="string", room="string", language="string"), "required": ["name", "phone", "room"]}, {"owner"}),
    "get_dues": (t_get_dues, "List tenants with pending rent this month. Use for 'who hasn't paid'.", P(), {"owner"}),
    "create_rent_link": (t_create_rent_link, "Create a Cashfree payment link for a tenant. Omit amount for full pending; give a smaller amount for partial.",
                         P(tenant_id="integer", amount="integer"), {"owner", "tenant"}),
    "send_reminders": (t_send_reminders, "Phone-call ALL late tenants in their own language with a rent reminder. Tenants press a key to get a pay link, pay half, or pay later.", P(), {"owner"}),
    "record_payment": (t_record_payment, "Record rent received outside the app (cash or direct UPI) for a tenant.",
                       P(tenant_name="string", amount="integer", method="string"), {"owner"}),
    "start_onboarding": (lambda **kw: t_start_onboarding(**kw),  # defined further down, resolved at call time
                          "Prepare onboarding of a new tenant: the voice agent will phone them to confirm name, phone and WhatsApp, then the details form goes on WhatsApp. Needs name, 10 digit phone and a room with a free bed. Nothing happens until the owner says yes, so read the result back and ask the owner to confirm.",
                         P(name="string", phone="string", room="string"), {"owner"}),
    "tenant_info": (t_tenant_info, "Full details and month-wise rent history for one tenant (name or room number).",
                    P(tenant_name="string"), {"owner"}),
    "log_promise": (t_log_promise, "Record a tenant's promise to pay amount on date (YYYY-MM-DD).",
                    P(tenant_id="integer", amount="integer", date="string"), {"owner", "tenant"}),
    "create_ticket": (t_create_ticket, "Log a repair/complaint ticket.", P(tenant_id="integer", issue="string"), {"owner", "tenant"}),
    "prepare_payout": (t_prepare_payout, "Prepare a payment to a saved verified payee (vendor). Does NOT send money; the owner must confirm with a PIN in the app.",
                       P(payee_name="string", amount="integer", reason="string"), {"owner"}),
    "settle_deposit": (t_settle_deposit, "Compute deposit refund at move-out. deductions=[{reason,amount}].", P(tenant_id="integer"), {"owner"}),
    "start_offboarding": (t_start_offboarding, "Start moving out a tenant and ask the owner for deposit deductions.",
                           P(tenant_name="string"), {"owner"}),
    "finish_offboarding": (t_finish_offboarding, "Apply move-out deductions and prepare the remaining deposit refund after checking the live Cashfree wallet. Refunds require PIN confirmation.",
                            {"type": "object", "properties": {"tenant_id": {"type": "integer"}, "deductions": {"type": "array", "items": {
                                "type": "object", "properties": {"reason": {"type": "string"}, "amount": {"type": "integer"}},
                                "required": ["reason", "amount"]}}}, "required": ["tenant_id", "deductions"]}, {"owner"}),
    "monthly_summary": (t_monthly_summary, "This month's collected, pending, repairs, vacant beds, deposits held.", P(), {"owner"}),
    "verify_payee": (t_verify_payee, "Verify and save a payee's bank account.", P(name="string", account_no="string", ifsc="string"), {"owner"}),
}


async def call_tool(name, args, role="owner", tenant_id=None):
    if name not in TOOLS or role not in TOOLS[name][3]:
        return {"error": f"tool {name} not allowed"}
    args = dict(args or {})
    if role == "tenant":
        args["tenant_id"] = tenant_id  # tenants can only act on themselves
    elif "tenant_name" in args:  # owner may say "Ankit" or "204"
        try:
            args["tenant_id"] = find_tenant(name=str(args.pop("tenant_name")))["id"]
        except ToolError as e:
            return {"error": str(e)}
    try:
        res = await TOOLS[name][0](**args)
    except ToolError as e:
        res = {"error": str(e)}
    except TypeError as e:
        res = {"error": f"bad arguments: {e}"}
    audit(role, name, {"args": args, "result": res})
    return res


# ---------- agent ----------
def sys_prompt(role, t):
    base = (f"You are Kiraya Mitra, a PG rent assistant. Today is {dt.date.today().isoformat()}. The user may write in any Indian language, even in Roman letters. "
            "ALWAYS reply in plain English only (it is translated afterwards), in 1-2 short sentences, no markdown. Never invent data: call tools. ")
    if role == "owner":
        pending = q("select t.id tenant_id, t.name from offboards o join tenants t on t.id=o.tenant_id "
                    "where o.status='awaiting_deductions' order by o.id desc limit 1")
        move = (f" {pending[0]['name']} (tenant id {pending[0]['tenant_id']}) is awaiting move-out deductions. "
                "Ask for reasons and amounts, then call finish_offboarding with a deductions array; use an empty array for no deductions."
                if pending else " For move-out, call start_offboarding first and ask for deductions before calling finish_offboarding.")
        return base + ("You talk to the PG owner. Never claim money was sent: prepare_payout only prepares; tell the owner to confirm with PIN in the app. "
                       "For 'who hasn't paid' call get_dues." + move)
    return base + (f"You talk to tenant {t['name']} (room {t['room']}, id {t['id']}). If they want to pay now, create_rent_link. "
                   "If they say pay half now, create_rent_link with half the pending amount and log_promise for the remainder on the day they name. "
                   "If they promise a later date, log_promise. For problems, create_ticket.")


async def llm_agent(text, role, tenant):
    schemas = [{"type": "function", "function": {"name": n, "description": d, "parameters": s}}
               for n, (_, d, s, who) in TOOLS.items() if role in who]
    msgs = [{"role": "system", "content": sys_prompt(role, tenant)}, {"role": "user", "content": text}]
    calls = []
    for _ in range(5):
        j = await sarvam("/v1/chat/completions", json={"model": LLM, "messages": msgs, "tools": schemas, "temperature": 0.2})
        m = j["choices"][0]["message"]
        content = re.sub(r"<think>.*?</think>", "", m.get("content") or "", flags=re.S).strip()
        if not m.get("tool_calls"):
            return content, calls
        msgs.append({"role": "assistant", "content": content, "tool_calls": m["tool_calls"]})
        for tc in m["tool_calls"]:
            args = json.loads(tc["function"].get("arguments") or "{}")
            res = await call_tool(tc["function"]["name"], args, role, tenant["id"] if tenant else None)
            calls.append({"tool": tc["function"]["name"], "args": args, "result": res})
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, ensure_ascii=False, default=str)})
    return "Done.", calls


def next_friday():
    d = dt.date.today()
    return (d + dt.timedelta((4 - d.weekday()) % 7 or 7)).isoformat()


def day_of_month(n):
    d = dt.date.today()
    y, m = (d.year, d.month) if n > d.day else (d.year + (d.month == 12), d.month % 12 + 1)
    return dt.date(y, m, min(n, 28)).isoformat()


async def rules(text, role, tenant):  # offline/demo fallback when no Sarvam key or the LLM call fails
    t, calls = text.lower(), []

    async def use(name, args):
        r = await call_tool(name, args, role, tenant["id"] if tenant else None)
        calls.append({"tool": name, "args": args, "result": r})
        return r

    if role == "owner":
        pending_move = q("select t.id tenant_id, t.name from offboards o join tenants t on t.id=o.tenant_id "
                         "where o.status='awaiting_deductions' order by o.id desc limit 1")
        if pending_move:
            deductions = []
            if not re.search(r"\b(no|zero) deductions?\b|\bnothing\b", t):
                pairs = re.findall(r"([a-z][a-z ]{0,40}?)\s+₹?\s*(\d[\d,]*)", t)
                if not pairs:
                    return f"Tell me each deduction and amount for {pending_move[0]['name']}, or say no deductions.", calls
                deductions = [{"reason": reason.strip(" ,"), "amount": int(amount.replace(",", ""))}
                              for reason, amount in pairs]
            r = await use("finish_offboarding", {"tenant_id": pending_move[0]["tenant_id"], "deductions": deductions})
            if r.get("error"):
                return r["error"], calls
            if r.get("payout"):
                return (f"Deposit ₹{r['deposit']}, deductions ₹{sum(x['amount'] for x in r['deductions'])}, unpaid rent ₹{r['unpaid_dues']}. "
                        f"Refund ₹{r['refund']} from the owner wallet. Confirm with your PIN."), calls
            return f"No refund is due. {r['tenant']} has been moved out.", calls
        if re.search(r"remind|kalsi|ellarigu|call (all|them)", t):
            r = await use("send_reminders", {})
            s = r.get("calls", [])
            return (f"Calling {len(s)} tenants now in their own languages: " + ", ".join(x["name"] for x in s) + "." if s
                    else "Nobody has pending rent."), calls
        who = next((x for x in q("select name from tenants where status='active'") if x["name"].lower() in t), None)
        if who and re.search(r"offboard|move.?out|vacat|check.?out", t):
            r = await use("start_offboarding", {"tenant_name": who["name"]})
            return r.get("error") or r["question"], calls
        if who and re.search(r"cash|received|got|record", t) and re.search(r"\d", t):
            r = await use("record_payment", {"tenant_name": who["name"], "amount": int(re.search(r"(\d[\d,]*)", t).group(1).replace(",", "")),
                                             "method": "cash" if "cash" in t else "upi"})
            return (r.get("error") or f"Recorded. {who['name']} still owes ₹{r['pending']}."), calls
        if who and re.search(r"detail|about|history|how is|status", t):
            r = await use("tenant_info", {"tenant_name": who["name"]})
            tn, led = r["tenant"], r["ledger"]
            return (f"{tn['name']}, room {tn['room']}, rent ₹{tn['rent']}, deposit ₹{tn['deposit']}. This month: {led[0]['status']}, "
                    f"paid ₹{led[0]['paid']} of ₹{led[0]['due']}. {sum(1 for x in led if x['status'] == 'paid')} of {len(led)} months paid in full."), calls
        if re.search(r"kottilla|not paid|n't paid|hasn't|pending|dues|unpaid|yaaru", t):
            d = (await use("get_dues", {}))["dues"]
            return (f"{len(d)} tenants have not paid: " + ", ".join(f"{x['name']} room {x['room']} ₹{x['pending']}" for x in d) + "."
                    if d else "Everyone has paid."), calls
        if re.search(r"summary|lekka|accounts|report", t):
            s = await use("monthly_summary", {})
            wallet = f"₹{s['wallet_balance']:g}" if s["wallet_balance"] is not None else "unavailable"
            return (f"Collected ₹{s['collected']}, pending ₹{s['pending']}, repairs ₹{s['repairs_spent']}, "
                    f"{s['beds_vacant']} beds vacant, deposits held ₹{s['deposits_held']}, Cashfree wallet {wallet}."), calls
        m = re.search(r"onboard (\w[\w ]*?) (\d{10}) room (\w+)", t)
        if m:
            r = await use("start_onboarding", {"name": m.group(1).title(), "phone": m.group(2), "room": m.group(3)})
            return (r.get("error") or f"{r['readback']}. Say yes to confirm, or no to cancel."), calls
        m = re.search(r"add tenant (\w+) room (\w+) rent (\d+) deposit (\d+) (kannada|hindi|bengali|malayalam|english)", t)
        if m:
            n, room, rent, dep, lang = m.groups()
            r = await use("add_tenant", {"name": n.title(), "phone": "9800000999", "room": room, "rent": int(rent),
                                         "deposit": int(dep), "language": lang})
            return (r.get("error") or f"Added {n.title()} to room {room}. Welcome voice note and payment link sent."), calls
        amt = re.search(r"(\d[\d,]*)", t)
        if amt and re.search(r"kodi|pay|give|send", t):
            for p in q("select name from payees"):
                if p["name"].split()[0].lower() in t:
                    r = await use("prepare_payout", {"payee_name": p["name"], "amount": int(amt.group(1).replace(",", "")),
                                                     "reason": "repair"})
                    return (r.get("error") or f"{r['readback']}. Waiting for your confirmation."), calls
            return "I could not find that payee in your saved list.", calls
        return "Try: who hasn't paid, send reminders, pay Raju 800, or this month's summary.", calls

    # tenant
    if re.search(r"geyser|not working|broken|leak|repair|fan|water|wifi|light", t):
        r = await use("create_ticket", {"issue": text})
        return "Ticket logged. The owner has been told." if "error" not in r else r["error"], calls
    if "half" in t:
        pend = (await t_get_dues(tenant["id"]))["dues"]
        if not pend:
            return "You have no pending rent.", calls
        h = pend[0]["pending"] // 2
        link = await use("create_rent_link", {"amount": h})
        await use("log_promise", {"amount": pend[0]["pending"] - h, "date": next_friday()})
        return f"Here is a link for ₹{h} now. I noted the remaining ₹{pend[0]['pending'] - h} for {next_friday()}.", calls
    m = re.search(r"(\d{1,2})(st|nd|rd|th)", t)
    if m or "salary" in t or "later" in t:
        pend = (await t_get_dues(tenant["id"]))["dues"]
        if not pend:
            return "You have no pending rent.", calls
        date = day_of_month(int(m.group(1))) if m else next_friday()
        await use("log_promise", {"amount": pend[0]["pending"], "date": date})
        return f"Noted. I will remind you on {date} for ₹{pend[0]['pending']}.", calls
    if re.search(r"pay|now|link|full|rent", t):
        r = await use("create_rent_link", {})
        return (r.get("error") or f"Here is your payment link for ₹{r['amount']}."), calls
    return "You can say: pay now, half now half Friday, salary on the 10th, or report a problem.", calls


async def agent(text, role, tenant=None):
    if SK:
        try:
            reply, calls = await llm_agent(text, role, tenant)
            if reply or calls:
                return reply or "Done.", calls
        except Exception as e:
            print("llm failed, using rules:", e)
    return await rules(text, role, tenant)


async def transcribe(audio: bytes | None, name, ctype, text):
    if audio is not None:
        if not SK:
            raise ToolError("no Sarvam key: speech-to-text unavailable, send text")
        return await stt(audio, name, ctype)
    text = text or ""
    return await tr(text, "en", src="auto") if SK and not text.isascii() else text


async def voice(role, tenant_id, audio, text):
    tenant = tenant_row(int(tenant_id)) if role == "tenant" else None
    try:
        transcript = await transcribe(await audio.read() if audio else None, getattr(audio, "filename", None) or "a.webm",
                                      getattr(audio, "content_type", None) or "audio/webm", text)
    except ToolError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"speech failed: {e}")
    return {"transcript": transcript, **await respond(role, tenant, transcript)}


async def respond(role, tenant, transcript, codec="wav"):
    reply_en, calls = await agent(transcript, role, tenant)
    lang = "kn" if role == "owner" else tenant["language"]
    reply = await tr(reply_en, lang)
    pending = None
    for c in calls:  # a prepared payout waits for PIN confirmation in the UI
        r = c["result"].get("payout") or c["result"]
        if isinstance(r, dict) and r.get("status") == "pending_confirm" and "payout_id" in r:
            pending = r
    return {"reply_en": reply_en, "reply_text": reply, "lang": lang,
            "reply_audio_url": await tts(reply, lang, codec), "tool_calls": calls, "pending_payout": pending,
            "links": [c["result"]["url"] for c in calls if isinstance(c["result"], dict) and "url" in c["result"]]}


# ---------- whatsapp (owner voice-note chat) ----------
def log_msg(phone, role, direction, kind, text, audio_url=None, channel="whatsapp", wa_id=None):
    q("insert or ignore into messages(phone,role,direction,kind,text,audio_url,channel,wa_id) values(?,?,?,?,?,?,?,?)",
      (last10(phone), role, direction, kind, text, audio_url, channel, wa_id))


async def wa_send(to, text=None, audio_url=None):
    if not WA_TOKEN:
        return True
    h, to = {"Authorization": f"Bearer {WA_TOKEN}"}, re.sub(r"\D", "", e164(to))
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            if audio_url:
                f = AUDIO / Path(audio_url).name
                mime = MIME.get(f.suffix[1:], "audio/mpeg")
                r = await c.post(f"{GRAPH}/{WA_PHONE_ID}/media", headers=h, data={"messaging_product": "whatsapp", "type": mime},
                                 files={"file": (f.name, f.read_bytes(), mime)})
                r.raise_for_status()
                (await c.post(f"{GRAPH}/{WA_PHONE_ID}/messages", headers=h, json={
                    "messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"id": r.json()["id"]}})).raise_for_status()
            if text:
                (await c.post(f"{GRAPH}/{WA_PHONE_ID}/messages", headers=h, json={
                    "messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})).raise_for_status()
        return True
    except Exception as e:
        print("whatsapp send failed:", e)
        return False


async def wa_template(to, name, lang, params):
    """Business-initiated message outside the 24h window must be an approved template."""
    body = {"messaging_product": "whatsapp", "to": re.sub(r"\D", "", e164(to)), "type": "template", "template": {
        "name": name, "language": {"code": lang},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}]}}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            (await c.post(f"{GRAPH}/{WA_PHONE_ID}/messages", headers={"Authorization": f"Bearer {WA_TOKEN}"}, json=body)).raise_for_status()
        return True
    except Exception as e:
        print("whatsapp template failed:", e)
        return False


async def say(to, text_en, lang, role="owner", deliver=True, extra=""):
    """Voice note + text, in the listener's language, over WhatsApp."""
    text = await tr(text_en, lang)
    url = await tts(text, lang, WA_CODEC if (WA_TOKEN and deliver) else "wav")
    shown = text + ("\n" + extra if extra else "")  # extra = exact figures/IDs, never translated
    log_msg(to, role, "out", "audio" if url else "text", shown, url)
    if deliver:
        await wa_send(to, shown, url)


async def wa_download(media_id):
    h = {"Authorization": f"Bearer {WA_TOKEN}"}
    async with httpx.AsyncClient(timeout=60) as c:
        meta = (await c.get(f"{GRAPH}/{media_id}", headers=h)).json()
        return (await c.get(meta["url"], headers=h)).content


async def handle_incoming(frm, kind, text=None, media=None, wa_id=None, deliver=True):
    """media = (bytes, filename, mimetype). Owner phone -> owner agent; a tenant's phone -> tenant agent; anyone else ignored."""
    phone = last10(frm)
    tenant = (q("select * from tenants where status='active' and (phone like ? or whatsapp like ?)", ("%" + phone, "%" + phone)) or [None])[0]
    if phone == last10(OWNER_PHONE):
        role = "owner"
    elif tenant:
        role = "tenant"
    else:
        return
    try:
        transcript = await transcribe(media[0] if media else None, *(media[1:] if media else (None, None)), text)
    except Exception as e:
        log_msg(phone, role, "in", kind, "[voice note]", wa_id=wa_id)
        return await say(phone, "Sorry, I could not understand that voice note. Please try again or type.", "kn" if role == "owner" else tenant["language"], role, deliver)
    log_msg(phone, role, "in", kind, transcript if kind == "audio" else text, wa_id=wa_id)
    m = re.fullmatch(r"\s*confirm\s+(\d{3,8})\s*", transcript, re.I) if role == "owner" else None
    if m:  # PIN is typed, never spoken: a voice note could be overheard or replayed
        p = q("select id from payouts where status='pending_confirm' order by id desc limit 1")
        try:
            if not p:
                raise ToolError("nothing waiting for confirmation")
            r = await confirm_payout(p[0]["id"], m.group(1))
            return await say(phone, f"Done. Payment sent, status {r['status']}.", "kn", role, deliver)
        except ToolError as e:
            return await say(phone, f"Could not confirm: {e}", "kn", role, deliver)
    if role == "owner" and re.fullmatch(r"\s*(yes|yeah|yep|ok|okay|confirm|go ahead|do it|haan|houdu|sari|no|cancel|stop|nahi|illa)[.!\s]*", transcript, re.I):
        p = q("select id,name from onboarding where status='pending_confirm' and created > datetime('now','-15 minutes') order by id desc limit 1")
        if p:
            if re.match(r"\s*(no|cancel|stop|nahi|illa)", transcript, re.I):
                q("update onboarding set status='cancelled' where id=?", (p[0]["id"],))
                return await say(phone, f"Cancelled. {p[0]['name']} will not be contacted.", "kn", role, deliver)
            try:
                r = await confirm_onboarding(p[0]["id"])
                return await say(phone, f"Calling {r['name']} now to confirm the details." if r["status"] == "calling"
                                 else f"The form was sent to {r['name']} on WhatsApp.", "kn", role, deliver)
            except ToolError as e:
                return await say(phone, str(e), "kn", role, deliver)
    r = await respond(role, tenant, transcript, WA_CODEC if (WA_TOKEN and deliver) else "wav")
    reply = r["reply_text"] + ("\n" + "\n".join(r["links"]) if r["links"] else "")
    log_msg(phone, role, "out", "audio" if r["reply_audio_url"] else "text", reply, r["reply_audio_url"])
    if deliver:
        await wa_send(phone, reply, r["reply_audio_url"])
    if r["pending_payout"]:
        await say(phone, f"{r['pending_payout']['readback']}. To send, type: CONFIRM and your PIN.", "kn" if role == "owner" else "en", role, deliver)


# ---------- phone calls to tenants (Twilio; simulated when no keys) ----------
async def twilio(path, data):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"https://api.twilio.com/2010-04-01/Accounts/{TW_SID}/{path}.json", data=data, auth=(TW_SID, TW_TOKEN))
        r.raise_for_status()
        return r.json()


async def send_to_tenant(t, text, tpl, params):
    """WhatsApp to a tenant from the business number: free-form if they messaged us in the last 24h, else the approved template."""
    number = t.get("whatsapp") or t["phone"]
    log_msg(number, "tenant", "out", "text", text, channel="whatsapp")
    if not WA_TOKEN:
        return True  # mock mode: logged only
    if await wa_send(number, text):
        return True
    return bool(tpl) and await wa_template(number, tpl, WA_TEMPLATE_LANG, params)


async def send_link(t, text_en, amount, url):
    return await send_to_tenant(t, f"{await tr(text_en, t['language'])}\n{url}", WA_LINK_TEMPLATE, [t["name"], amount, url])


async def place_call(t, pending):
    return await place_call_samvaad(t, pending) if VOICE else await place_call_twilio(t, pending)


PROPERTY_ADDRESS = os.getenv("PROPERTY_ADDRESS", "")


def pg_facts():
    """Live facts about the property, handed to the voice agent so it can answer residents' questions."""
    occ = {r["room"]: r["n"] for r in q("select room, count(*) n from tenants where status='active' group by room")}
    floors, vacant = [], 0
    for f in (1, 2, 3):
        rooms = [(r, v["sharing"] - occ.get(r, 0)) for r, v in ROOMS.items() if v["floor"] == f]
        free = [f"room {r} ({n} vacant)" for r, n in rooms if n > 0]
        vacant += sum(n for _, n in rooms)
        floors.append(f"Floor {f}, {f + 1}-sharing, {RATES[f + 1]} rupees per bed per month: " + (", ".join(free) if free else "full"))
    return {"total_rooms": str(len(ROOMS)), "total_beds": str(PROPERTY["beds"]), "vacant_beds": str(vacant),
            "vacancy_details": ". ".join(floors), "property_address": PROPERTY_ADDRESS or "not available yet"}


def voice_key():  # secret carried in the webhook URLs we give Sarvam
    return hmac.new((SV_KEY or TW_TOKEN).encode(), b"voice", hashlib.sha256).hexdigest()[:20]


async def samvaad_outbound(app_id, app_version, variables, language, phone, hook, metadata):
    """Ask Sarvam Voice Agents to place one call. Returns (status, attempt_id)."""
    body = {"app_config": {"app_id": app_id, "app_version": app_version,
                           "connection_config": {"connection_id": SV_CONN, "agent_phone_number": SV_NUM},
                           "agent_variables": variables,
                           "app_overrides": {"initial_language_name": LANG_NAMES.get(language, "English")}},
            "user_config": {"user_phone_number": e164(phone)},
            "webhook_config": {"url": f"{PUBLIC_URL}{hook}?k={voice_key()}", "metadata": metadata}}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"https://apps.sarvam.ai/api/outbounds/v1/orgs/{SV_ORG}/workspaces/{SV_WS}/outbounds",
                             headers={"X-API-Key": SV_KEY}, json=body)
            r.raise_for_status()
            return "ringing", r.json().get("attempt_id")
    except Exception as e:
        print("sarvam call failed:", e, getattr(getattr(e, "response", None), "text", "")[:300])
        return "failed", None


async def place_call_samvaad(t, pending):
    """The Samvaad agent holds the whole conversation; the result comes back on /webhooks/sarvam/call."""
    q("insert into calls(tenant_id,month,status,text,turn) values(?,?,'ringing','',3)", (t["id"], month()))
    cid = q.last
    status, attempt = await samvaad_outbound(SV_APP, SV_VER, {
        "tenant_name": t["name"], "room": str(t["room"]), "pending_amount": str(pending), "property_name": PROPERTY["name"],
        "month": month(), "current_date": dt.date.today().isoformat(), **pg_facts()}, t["language"], t["phone"],
        "/webhooks/sarvam/call", {"call_id": cid})
    q("update calls set status=?, call_sid=? where id=?", (status, attempt, cid))
    audit("system", "call_placed", {"call_id": cid, "tenant": t["name"], "status": status, "provider": "sarvam"})
    await publish("call_placed", tenant_id=t["id"], room=t["room"], name=t["name"], status=status)
    return {"call_id": cid, "status": status}


async def place_call_twilio(t, pending):
    msg = (f"Hello {t['name']}. This is Kiraya Mitra from {PROPERTY['name']}. Your rent of {pending} rupees for room {t['room']} "
           "is pending. When will you be able to pay?")
    text = await tr(msg, t["language"])
    url = await tts(text, t["language"])
    q("insert into calls(tenant_id,month,status,text,audio_url) values(?,?,?,?,?)", (t["id"], month(), "ringing", text, url))
    cid, status, sid = q.last, "simulated", None
    if TW_SID:
        try:
            j = await twilio("Calls", {"To": e164(t["phone"]), "From": TW_FROM, "Url": f"{PUBLIC_URL}/calls/twiml/{cid}?k={call_key(cid)}",
                                       "StatusCallback": f"{PUBLIC_URL}/calls/status/{cid}?k={call_key(cid)}"})
            status, sid = "ringing", j["sid"]
        except Exception as e:
            print("call failed:", e)
            status = "failed"
    q("update calls set status=?, call_sid=? where id=?", (status, sid, cid))
    audit("system", "call_placed", {"call_id": cid, "tenant": t["name"], "status": status})
    await publish("call_placed", tenant_id=t["id"], room=t["room"], name=t["name"], status=status)
    return {"call_id": cid, "status": status}


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_date(v):
    try:
        d = dt.date.fromisoformat(str(v)[:10])
    except Exception:
        return None
    return d.isoformat() if dt.date.today() <= d <= dt.date.today() + dt.timedelta(days=90) else None


def rule_classify(said):
    """Offline fallback for the LLM. Returns {intent, reason, date}."""
    t, today = said.lower().strip(), dt.date.today()
    if not t:
        return {"intent": "unclear"}
    date = None
    if "day after tomorrow" in t:
        date = today + dt.timedelta(2)
    elif "tomorrow" in t:
        date = today + dt.timedelta(1)
    elif "next week" in t:
        date = today + dt.timedelta(7)
    elif (m := re.search(r"(\d{1,2})(st|nd|rd|th)", t)):
        date = dt.date.fromisoformat(day_of_month(int(m.group(1))))
    else:
        for i, w in enumerate(WEEKDAYS):
            if w in t:
                date = today + dt.timedelta((i - today.weekday()) % 7 or 7)
    if date or re.search(r"salary|later|not now|can't|cannot|need time|few days|after", t):
        return {"intent": "needs_time", "reason": said[:200], "date": date.isoformat() if date else None}
    if re.search(r"\bnow\b|today|link|ready|\byes\b|\bok(ay)?\b|\bpay\b", t):
        return {"intent": "pay_now"}
    return {"intent": "unclear"}


async def classify(convo, pending):
    if SK and convo.strip():
        try:
            j = await sarvam("/v1/chat/completions", json={"model": LLM, "temperature": 0, "messages": [
                {"role": "system", "content": (
                    f"Today is {dt.date.today().isoformat()}. A PG tenant owes rent of {pending} rupees and was asked when they can pay. "
                    "Read what the tenant said (machine-translated to English) and answer ONLY with JSON: "
                    '{"intent":"pay_now|needs_time|unclear","reason":"short reason or empty","date":"YYYY-MM-DD or null","amount":integer or null}. '
                    "pay_now = ready to pay right now/today. needs_time = asks for time, waiting for salary, or will pay later; "
                    "resolve relative dates (next Friday, the 10th) to a real date, null if no date was given. "
                    "amount only if they offer to pay part of the rent. unclear = reply is not about paying.")},
                {"role": "user", "content": convo}]})
            txt = re.sub(r"<think>.*?</think>", "", j["choices"][0]["message"]["content"] or "", flags=re.S)
            r = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            if r.get("intent") in ("pay_now", "needs_time", "unclear"):
                return r
        except Exception as e:
            print("classify failed, using rules:", e)
    return rule_classify(convo.rsplit("Tenant:", 1)[-1])


async def tenant_turn(cid, said, pre=None, dialogue=None):
    """One exchange of the collection call. Returns (kind, text_en, lang): kind 'ask' keeps the call going, 'end' hangs up."""
    c = q("select * from calls where id=?", (cid,))
    if not c:
        raise HTTPException(404, "unknown call")
    c = c[0]
    t = tenant_row(c["tenant_id"])
    pending = (await t_get_dues(t["id"], False))["dues"][0]["pending"]
    convo = dialogue or (c["transcript"] or "") + f"Tenant: {said or '(silence)'}\n"

    async def finish(outcome, tell, note, reason=None, date=None):
        q("update calls set status='completed', outcome=?, transcript=?, reason=?, promise_date=? where id=?", (outcome, convo, reason, date, cid))
        await say(OWNER_PHONE, f"{t['name']}, room {t['room']}: {note}.", "kn", extra=f"Tenant said: {convo.strip()}")
        return "end", tell, t["language"]

    def ask(tell, reason=None):
        q("update calls set turn=turn+1, transcript=?, reason=coalesce(?,reason) where id=?", (convo, reason, cid))
        return "ask", tell, t["language"]

    if pending <= 0:
        return await finish("already_paid", "Your rent is already paid. Thank you.", "already paid")
    r = pre or await classify(convo, pending)
    if r.get("intent") == "pay_now":
        amt = int(r.get("amount") or pending)
        amt = pending if amt <= 0 or amt > pending else amt
        link = await make_link(t, amt, month())
        ok = await send_link(t, f"Rent of Rs {amt} for room {t['room']}. Pay here:", amt, link["url"])
        return await finish("will_pay_now" if ok else "link_not_delivered",
                            "I have sent the payment link on WhatsApp. Thank you." if ok else "Thank you. The owner will send you the payment link.",
                            f"ready to pay ₹{amt} now, link sent on WhatsApp" if ok else f"ready to pay ₹{amt} now, but WhatsApp could not deliver the link. Please share it: {link['url']}")
    if r.get("intent") == "needs_time":
        reason = c["reason"] or (r.get("reason") or said or "no reason given")[:200]
        date = parse_date(r.get("date"))
        if date:
            await t_log_promise(t["id"], pending, date, reason)
            return await finish("promised", f"Noted. We will expect your payment on {date}. Thank you.",
                                f"needs time because: {reason}. Promised ₹{pending} on {date}", reason, date)
        if c["turn"] < 3:
            return ask("Which date will you be able to pay?", reason)
        return await finish("needs_time_no_date", "Noted. The owner will follow up. Thank you.", f"needs time because: {reason}, but gave no date", reason)
    if c["turn"] < 3:
        return ask("Sorry, I did not catch that. When will you be able to pay?")
    return await finish("unclear", "Thank you. The owner will contact you.", "the reply could not be understood")


def twiml(body):
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="application/xml")


def call_key(cid):  # unguessable per-call secret carried in the URLs we hand to Twilio
    return hmac.new(TW_TOKEN.encode(), f"call{cid}".encode(), hashlib.sha256).hexdigest()[:20]


async def twilio_form(request, path, cid):
    form = dict(await request.form())
    if TW_TOKEN and not hmac.compare_digest(request.query_params.get("k", ""), call_key(cid)):  # X-Twilio-Signature: base64(HMAC-SHA1(url + sorted key/value pairs))
        body = "".join(k + str(form[k]) for k in sorted(form))
        sig = request.headers.get("x-twilio-signature", "")
        # Twilio may sign the https URL with or without the explicit :443 port
        urls = [PUBLIC_URL + path, re.sub(r"^(https://[^/:]+)(/|$)", r"\1:443\2", PUBLIC_URL + path)]
        if not any(hmac.compare_digest(base64.b64encode(hmac.new(TW_TOKEN.encode(), (u + body).encode(), hashlib.sha1).digest()).decode(), sig)
                   for u in urls):
            raise HTTPException(403, "bad twilio signature")
    return form


# ---------- tenant onboarding ----------
import secrets

LANG_CODES = {"kannada": "kn", "hindi": "hi", "bengali": "bn", "malayalam": "ml", "english": "en"}
FILE_MAGIC = {b"\xff\xd8\xff": ".jpg", b"\x89PNG": ".png", b"%PDF": ".pdf"}
MAX_UPLOAD = 5 * 1024 * 1024


def ob_url(ob):
    return f"{PUBLIC_URL}/onboard/{ob['token']}"


def next_rent_charge(move_in):
    try:
        d = dt.date.fromisoformat(move_in)
    except (TypeError, ValueError):
        d = dt.date.today()
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return dt.datetime(y, m, PROPERTY["due_day"], 10, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat()


def autopay_url(row):
    return f"{PUBLIC_URL}/autopay/{row['token']}"


async def setup_autopay(t, form):
    if t["rent"] > 15000:
        raise ToolError("UPI AutoPay supports this property only up to ₹15,000 per debit")
    sub_id, token = f"rent_{t['id']}_{uuid.uuid4().hex[:10]}", secrets.token_urlsafe(24)
    first_charge = next_rent_charge(form.get("move_in"))
    q("insert into autopay(tenant_id,subscription_id,token,first_charge) values(?,?,?,?)",
      (t["id"], sub_id, token, first_charge))
    if MOCK_CF:
        q("update autopay set status='setup_failed' where tenant_id=?", (t["id"],))
        raise ToolError("Cashfree Subscriptions are not configured")
    try:
        j = await cf("POST", "/pg/subscriptions", "2026-01-01", idempotency_key=str(uuid.uuid4()), json={
            "subscription_id": sub_id,
            "customer_details": {"customer_name": t["name"], "customer_email": form["email"], "customer_phone": t["phone"]},
            "plan_details": {"plan_name": f"{PROPERTY['name']} rent"[:40], "plan_type": "PERIODIC",
                             "plan_currency": "INR", "plan_amount": t["rent"], "plan_max_amount": t["rent"],
                             "plan_intervals": 1, "plan_interval_type": "MONTH",
                             "plan_note": f"Monthly rent for Room {t['room']}"},
            "authorization_details": {"authorization_amount": 1, "authorization_amount_refund": True,
                                      "payment_methods": ["upi"]},
            "subscription_meta": {"return_url": f"{PUBLIC_URL}/autopay/{token}/return",
                                  "notification_channel": ["EMAIL", "SMS"]},
            "subscription_first_charge_time": first_charge,
            "subscription_tags": {"tenant_id": str(t["id"]), "room": t["room"],
                                  "psp_note": f"{PROPERTY['name']} monthly rent"}})
        if not j.get("subscription_session_id"):
            raise ToolError("Cashfree did not return an AutoPay session")
        q("update autopay set cf_subscription_id=?, session_id=?, status=? where tenant_id=?",
          (j.get("cf_subscription_id"), j["subscription_session_id"],
           str(j.get("subscription_status") or "initialized").lower(), t["id"]))
    except Exception as e:
        q("update autopay set status='setup_failed' where tenant_id=?", (t["id"],))
        if isinstance(e, ToolError):
            raise
        raise ToolError("Cashfree AutoPay is temporarily unavailable")
    row = q("select * from autopay where tenant_id=?", (t["id"],))[0]
    await send_to_tenant(t, f"Set up UPI AutoPay for your monthly rent of ₹{t['rent']} due on the {PROPERTY['due_day']}th. "
                              f"Approve the mandate securely with Cashfree: {autopay_url(row)}", "", [])
    return row


def ob_reserved(room):  # beds held for people who are mid-onboarding
    return q("select count(*) n from onboarding where room=? and status in ('invited','link_sent','submitted')", (room,))[0]["n"]


async def t_start_onboarding(name, phone, room, language="hi", call=True):
    room, phone, name = str(room), last10(phone), str(name).strip()
    if room not in ROOMS:
        raise ToolError(f"room {room} does not exist; rooms are {', '.join(ROOMS)}")
    if len(phone) != 10 or not name:
        raise ToolError("a name and a 10 digit phone number are needed")
    language = LANGS.get(str(language).lower(), language)
    if language not in LC:
        raise ToolError("language must be one of kn hi bn ml en")
    taken = q("select count(*) n from tenants where status='active' and room=?", (room,))[0]["n"] + ob_reserved(room)
    if taken >= ROOMS[room]["sharing"]:
        raise ToolError(f"room {room} has no free bed ({ROOMS[room]['sharing']}-sharing)")
    if q("select 1 from onboarding where phone=? and status in ('invited','link_sent','submitted')", (phone,)) or \
            q("select 1 from tenants where status='active' and phone=?", (phone,)):
        raise ToolError("this phone number is already being onboarded or is already a tenant")
    rent = ROOMS[room]["rent"]
    expires = (dt.datetime.now() + dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    q("delete from onboarding where phone=? and status='pending_confirm'", (phone,))  # a repeated request replaces the earlier one
    q("insert into onboarding(token,name,phone,room,sharing,rent,deposit,call_language,expires,status,call_outcome) values(?,?,?,?,?,?,?,?,?,'pending_confirm',?)",
      (secrets.token_urlsafe(24), name, phone, room, ROOMS[room]["sharing"], rent, 2 * rent, language, expires, "will_call" if call else "form_only"))
    oid = q.last
    audit("owner", "onboarding_prepared", {"id": oid, "name": name, "room": room})
    # nothing is called or sent until the owner says yes: a misheard number must not ring a stranger
    return {"onboarding_id": oid, "status": "pending_confirm",
            "readback": f"{'Call' if call else 'Send the form to'} {name} on {' '.join(phone)} for room {room}, {ROOMS[room]['sharing']}-sharing"}


async def confirm_onboarding(oid):
    r = q("select * from onboarding where id=? and status='pending_confirm' and created > datetime('now','-15 minutes')", (oid,))
    if not r:
        raise ToolError("nothing is waiting for confirmation, or it expired. Please ask again")
    ob, call = r[0], r[0]["call_outcome"] == "will_call"
    room = ob["room"]
    if q("select count(*) n from tenants where status='active' and room=?", (room,))[0]["n"] + ob_reserved(room) >= ob["sharing"]:
        raise ToolError(f"room {room} has no free bed any more")
    q("update onboarding set status='invited', call_outcome=null where id=?", (oid,))
    name, phone, language, rent = ob["name"], ob["phone"], ob["call_language"], ob["rent"]
    if call and VOICE and SV_ONB_APP:  # the agent confirms name, number and WhatsApp, then the webhook sends the form
        status, _ = await samvaad_outbound(SV_ONB_APP, SV_ONB_VER, {
            "tenant_name": name, "phone_number": phone, "room": room, "sharing": str(ROOMS[room]["sharing"]),
            "monthly_rent": str(rent), "deposit_amount": str(2 * rent), "property_name": PROPERTY["name"]},
            language, phone, "/webhooks/sarvam/onboarding", {"onboarding_id": ob["id"]})
        if status == "ringing":
            return {"onboarding_id": ob["id"], "status": "calling", "name": name}
        q("update onboarding set call_outcome='call_failed' where id=?", (ob["id"],))
    await send_form_link(ob["id"])
    return {"onboarding_id": ob["id"], "status": "link_sent", "name": name}


async def send_form_link(oid):
    ob = q("select * from onboarding where id=?", (oid,))[0]
    lang = ob["call_language"] or "en"
    msg = await tr(f"Welcome to {PROPERTY['name']}, {ob['name']}. Please fill this short form for your room {ob['room']} move-in. It takes about 5 minutes.", lang)
    ok = await send_to_tenant({"phone": ob["phone"], "whatsapp": ob["whatsapp"], "name": ob["name"], "language": lang},
                              f"{msg}\n{ob_url(ob)}", WA_ONBOARD_TEMPLATE, [ob["name"], ob_url(ob)])
    q("update onboarding set status='link_sent' where id=? and status='invited'", (oid,))
    if not ok:
        await say(OWNER_PHONE, f"WhatsApp could not deliver the onboarding form to {ob['name']}. Please share this link with them.", "kn", extra=ob_url(ob))
    return ok


def sniff(data):
    for magic, ext in FILE_MAGIC.items():
        if data.startswith(magic):
            return ext
    return None


async def save_upload(f, kinds, oid, label):
    data = await f.read(MAX_UPLOAD + 1) if hasattr(f, "read") else b""
    if not data:
        raise HTTPException(400, f"{label} is required")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, f"{label} is larger than 5 MB")
    ext = sniff(data)
    if ext not in kinds:
        raise HTTPException(400, f"{label} must be a {' / '.join(k[1:].upper() for k in kinds)} file")
    name = f"{oid}_{label.split()[0].lower()}_{secrets.token_hex(6)}{ext}"
    (UPLOADS / name).write_bytes(data)
    return name


def ob_live(token):
    r = q("select * from onboarding where token=?", (token,))
    if not r:
        raise HTTPException(404, "This link is not valid.")
    if r[0]["expires"] < dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") and r[0]["status"] in ("invited", "link_sent"):
        raise HTTPException(410, "This link has expired. Please ask the owner for a new one.")
    return r[0]


# ---------- payments ----------
async def apply_payment(link_id, total_paid, txn=None, background_tasks=None):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        c.execute("begin immediate")
        row = c.execute("select p.*, t.name, t.room from payments p join tenants t on t.id=p.tenant_id where link_id=?",
                        (link_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown link")
        p = dict(row)
        txn = txn or f"LINK-{link_id}"
        if c.execute("select 1 from payments where txn_id=?", (txn,)).fetchone():
            c.commit()
            return {"ok": True, "duplicate": True}
        total_paid = min(int(total_paid), p["amount"])
        delta = total_paid - p["paid"]
        if delta <= 0:
            c.commit()
            return {"ok": True, "duplicate": True}
        receipt_no = f"KM-{p['month'].replace('-', '')}-{p['id']:04d}"
        c.execute("update payments set paid=?, status=?, paid_ts=datetime('now','localtime'), txn_id=?, receipt_no=? where link_id=?",
                  (total_paid, "paid" if total_paid >= p["amount"] else "partial", txn, receipt_no, link_id))
        c.execute("update ledger set paid=paid+?, status=case when paid+?>=due then 'paid' else 'partial' end where tenant_id=? and month=?",
                  (delta, delta, p["tenant_id"], p["month"]))
        left = max(c.execute("select due-paid from ledger where tenant_id=? and month=?",
                             (p["tenant_id"], p["month"])).fetchone()[0], 0)
        if left <= 0:
            c.execute("update ledger set promise_date=null where tenant_id=? and month=?", (p["tenant_id"], p["month"]))
        c.commit()
    finally:
        c.close()
    if background_tasks is not None:
        background_tasks.add_task(payment_notifications, p, delta, left, txn, receipt_no)
    else:
        await payment_notifications(p, delta, left, txn, receipt_no)
    return {"ok": True, "pending": left, "receipt_no": receipt_no}


async def payment_notifications(p, delta, left, txn, receipt_no):
    refresh_wallet()
    audit("cashfree", "payment_received", {"link_id": p["link_id"], "delta": delta, "txn": txn, "receipt": receipt_no})
    await publish("payment_received", f"Room {p['room']}, {p['name']}, payment of {delta} rupees received.",
                  f"ಕೊಠಡಿ {p['room']}, {p['name']}, ₹{delta} ಬಂದಿದೆ", tenant_id=p["tenant_id"], room=p["room"], name=p["name"],
                  amount=delta, pending=left)
    await send_receipts(p, delta, left, txn, receipt_no)


async def send_receipts(p, delta, left, txn, receipt_no):
    """Receipt + transaction details to both the owner and the tenant on WhatsApp."""
    t = tenant_row(p["tenant_id"])
    lines = (f"Receipt: {receipt_no}\nTenant: {t['name']} (Room {t['room']})\nFor: {p['month']}\nPaid: ₹{delta}\nBalance: ₹{left}\n"
             f"Method: {p['method'].upper()}\nTransaction ID: {txn}\nDate: {dt.datetime.now().strftime('%d %b %Y %H:%M')}\n"
             f"{PUBLIC_URL}/receipt/{receipt_no}")
    await say(OWNER_PHONE, f"{t['name']}, room {t['room']}, paid {delta} rupees. Receipt and transaction details are below.", "kn", extra=lines)
    thanks = await tr(f"Thank you {t['name']}. We have received your rent payment of Rs {delta}.", t["language"])
    await send_to_tenant(t, f"{thanks}\n{lines}", WA_RECEIPT_TEMPLATE, [t["name"], delta, receipt_no, txn])


# ---------- app ----------
@asynccontextmanager
async def lifespan(_):
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    for migration in ("alter table tenants add column whatsapp text", "alter table payouts add column offboard_id int"):
        try:
            c.execute(migration)
            c.commit()
        except sqlite3.OperationalError:
            pass
    c.close()
    seed()
    ensure_month()
    yield


app = FastAPI(title="Kiraya Mitra", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/config")
def config():
    return {"mock_cashfree": MOCK_CF, "sarvam": bool(SK), "whatsapp": bool(WA_TOKEN), "twilio": bool(TW_SID), "voice": VOICE, "property": PROPERTY,
            "owner_phone": last10(OWNER_PHONE)}


@app.post("/tools/{name}")
async def tool(name: str, request: Request):
    return await call_tool(name, await request.json() if await request.body() else {}, "owner")


@app.get("/dues")
async def dues(tenant_id: int | None = None, all: int = 1):
    return await t_get_dues(tenant_id, not all)


@app.get("/tenants")
def tenants():
    return q("select id,name,room,language from tenants where status='active' order by room")


@app.get("/payees")
def payees():
    return q("select id,name,verified from payees")


@app.get("/summary")
async def summary():
    return await t_monthly_summary()


@app.get("/wallet")
async def wallet():
    try:
        return await cashfree_wallet()
    except ToolError as e:
        raise HTTPException(503, str(e))


@app.get("/events")
def events(after: int | None = None):
    last = len(EVENTS)
    return {"events": [] if after is None else [e for e in EVENTS if e["id"] > after], "last": last}


@app.post("/payouts/confirm")
async def payouts_confirm(request: Request):
    b = await request.json()
    try:
        return await confirm_payout(int(b["payout_id"]), b.get("pin", ""))
    except ToolError as e:
        raise HTTPException(400, str(e))


@app.post("/payouts/cancel")
async def payouts_cancel(request: Request):
    b = await request.json()
    q("update payouts set status='cancelled' where id=? and status='pending_confirm'", (int(b["payout_id"]),))
    return {"status": "cancelled"}


@app.post("/voice/owner")
async def voice_owner(audio: UploadFile | None = File(None), text: str = Form("")):
    return await voice("owner", None, audio, text)


@app.post("/voice/tenant")
async def voice_tenant(tenant_id: int = Form(...), audio: UploadFile | None = File(None), text: str = Form("")):
    return await voice("tenant", tenant_id, audio, text)


@app.post("/tts")
async def tts_ep(request: Request):
    b = await request.json()
    return {"audio_url": await tts(b["text"], b.get("lang", "kn"))}


def verify_cashfree_webhook(request, raw, secret):
    if not secret:
        raise HTTPException(503, "Cashfree webhook disabled in mock mode")
    ts = request.headers.get("x-webhook-timestamp", "")
    sig = request.headers.get("x-webhook-signature", "")
    try:
        sent = float(ts)
        sent = sent / 1000 if sent > 10**12 else sent
    except ValueError:
        raise HTTPException(401, "bad webhook timestamp")
    if abs(dt.datetime.now(dt.timezone.utc).timestamp() - sent) > 300:
        raise HTTPException(401, "stale webhook")
    exp = base64.b64encode(hmac.new(secret.encode(), ts.encode() + raw, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(sig, exp):
        raise HTTPException(401, "bad signature")


@app.post("/webhooks/cashfree/payment")
async def webhook_payment(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    verify_cashfree_webhook(request, raw, CF_SECRET)
    try:
        d = json.loads(raw).get("data", {})
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")
    link_id = d.get("link_id")
    if not link_id:
        return {"ok": True, "ignored": True}
    payment = d.get("payment") or {}
    status = str(d.get("link_status") or d.get("payment_status") or payment.get("payment_status") or "").upper()
    if status not in ("PAID", "PARTIALLY_PAID", "SUCCESS"):
        return {"ok": True, "ignored": True}
    if d.get("link_currency") and d["link_currency"] != "INR":
        raise HTTPException(400, "unexpected currency")
    paid = d.get("link_amount_paid", d.get("link_amount", payment.get("payment_amount", 0)))
    if float(paid or 0) <= 0:
        raise HTTPException(400, "invalid paid amount")
    txn = d.get("cf_payment_id") or payment.get("cf_payment_id") or (d.get("order") or {}).get("transaction_id")
    return await apply_payment(link_id, paid, txn, background_tasks)


@app.post("/webhooks/cashfree/payout")
async def webhook_payout(request: Request):
    raw = await request.body()
    verify_cashfree_webhook(request, raw, CF_PAYOUT_SECRET)
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")
    data = body.get("data") or {}
    transfer = data.get("transfer") or data
    transfer_id = transfer.get("transfer_id")
    if not transfer_id:
        return {"ok": True, "ignored": True}
    rows = q("select o.*, p.name from payouts o join payees p on p.id=o.payee_id where o.cf_transfer_id=?", (transfer_id,))
    if not rows:
        raise HTTPException(404, "unknown transfer")
    old = rows[0]
    event = str(body.get("type") or body.get("event_type") or "").upper()
    status = str(transfer.get("status") or "").upper()
    code = str(transfer.get("status_code") or "").upper()
    if status == "SUCCESS" and code == "COMPLETED":
        new = "success"
    elif "REVERSE" in event or status == "REVERSED":
        new = "reversed"
    elif "FAIL" in event or status == "FAILED":
        new = "failed"
    else:
        new = "processing"
    q("update payouts set status=? where id=?", (new, old["id"]))
    refresh_wallet()
    audit("cashfree", "payout_status", {"payout_id": old["id"], "transfer_id": transfer_id, "status": new})
    if new == "success" and old["status"] != "success":
        await publish("payout_done", f"Paid {old['name']} {old['amount']} rupees",
                      payee=old["name"], amount=old["amount"], reason=old["reason"])
    return {"ok": True, "status": new}


@app.post("/dev/simulate-payment/{link_id}")
async def simulate(link_id: str, request: Request):
    if not MOCK_CF:
        raise HTTPException(403, "mock mode only")
    b = await request.json() if await request.body() else {}
    p = q("select amount from payments where link_id=?", (link_id,))
    if not p:
        raise HTTPException(404, "unknown link")
    return await apply_payment(link_id, b.get("amount") or p[0]["amount"], "TXN" + uuid.uuid4().hex[:10].upper())


@app.get("/pay/{link_id}", response_class=HTMLResponse)
def pay_page(link_id: str):
    p = q("select p.amount, t.name, t.room from payments p join tenants t on t.id=p.tenant_id where link_id=?", (link_id,))
    if not p:
        raise HTTPException(404, "unknown link")
    p = p[0]
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Pay rent</title>
<body style="font-family:system-ui;max-width:380px;margin:40px auto;padding:0 16px">
<h2>Rent payment (demo)</h2><p>{p['name']} · Room {p['room']}</p><p style="font-size:2em">₹{p['amount']}</p>
<button id=b style="font-size:1.2em;padding:12px 24px">Pay ₹{p['amount']}</button><p id=m></p>
<script>b.onclick=async()=>{{b.disabled=true;const r=await fetch('/dev/simulate-payment/{link_id}',{{method:'POST'}});
m.textContent=r.ok?'Paid. You can close this tab.':'Failed';}}</script>"""


@app.get("/receipt/{rno}", response_class=HTMLResponse)
def receipt_page(rno: str):
    r = q("select p.*, t.name, t.room from payments p join tenants t on t.id=p.tenant_id where receipt_no=?", (rno,))
    if not r:
        raise HTTPException(404, "unknown receipt")
    p = r[0]
    return (f"<!doctype html><title>Receipt {rno}</title><body style='font-family:system-ui;max-width:420px;margin:30px auto;padding:0 16px'>"
            f"<h2>{PROPERTY['name']}</h2><h3>Rent receipt {rno}</h3><table cellpadding=6>"
            f"<tr><td>Tenant</td><td>{p['name']} (Room {p['room']})</td></tr><tr><td>Month</td><td>{p['month']}</td></tr>"
            f"<tr><td>Amount paid</td><td>₹{p['paid']}</td></tr><tr><td>Method</td><td>{p['method'].upper()}</td></tr>"
            f"<tr><td>Transaction ID</td><td>{p['txn_id']}</td></tr><tr><td>Paid on</td><td>{p['paid_ts']}</td></tr></table>"
            "<p><button onclick='print()'>Print / Save PDF</button></p>")


@app.get("/report", response_class=HTMLResponse)
async def report():
    s, d = await t_monthly_summary(), (await t_get_dues(None, False))["dues"]
    rows = "".join(f"<tr><td>{x['room']}</td><td>{x['name']}</td><td>{x['due']}</td><td>{x['paid']}</td><td>{x['status']}</td></tr>" for x in d)
    return (f"<!doctype html><title>Report {s['month']}</title><body style='font-family:system-ui;max-width:700px;margin:24px auto'>"
            f"<h2>{PROPERTY['name']} — {s['month']}</h2><p>Collected ₹{s['collected']} · Pending ₹{s['pending']} · Repairs ₹{s['repairs_spent']} · "
            f"Vacant beds {s['beds_vacant']} · Deposits held ₹{s['deposits_held']}</p>"
            f"<table border=1 cellpadding=6 style='border-collapse:collapse'><tr><th>Room</th><th>Tenant</th><th>Due</th><th>Paid</th><th>Status</th></tr>{rows}</table>"
            "<p><button onclick='print()'>Print / Save PDF</button></p>")


# ---------- whatsapp + call webhooks ----------
@app.get("/webhooks/whatsapp")
def wa_verify(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == WA_VERIFY:
        return Response(p.get("hub.challenge", ""))
    raise HTTPException(403, "bad verify token")


async def process_wa(msg):
    try:
        media = None
        if msg["type"] == "audio":
            media = (await wa_download(msg["audio"]["id"]), "voice.ogg", msg["audio"].get("mime_type", "audio/ogg").split(";")[0])
        elif msg["type"] != "text":
            return
        await handle_incoming(msg["from"], msg["type"].replace("text", "text"), msg.get("text", {}).get("body"), media, msg["id"])
    except Exception as e:
        print("whatsapp handling failed:", e)


@app.post("/webhooks/whatsapp")
async def wa_hook(request: Request, bg: BackgroundTasks):
    raw = await request.body()
    if WA_APP_SECRET:
        exp = "sha256=" + hmac.new(WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(exp, request.headers.get("x-hub-signature-256", "")):
            raise HTTPException(401, "bad signature")
    for e in json.loads(raw).get("entry", []):
        for ch in e.get("changes", []):
            for m in ch.get("value", {}).get("messages", []):
                if not q("select 1 from messages where wa_id=?", (m["id"],)):  # Meta retries; process each message once
                    bg.add_task(process_wa, m)
    return {"ok": True}


@app.post("/whatsapp/simulate")
async def wa_simulate(audio: UploadFile | None = File(None), text: str = Form(""), tenant_phone: str = Form("")):
    """Dashboard chat: behaves like the owner (or a tenant) messaging the WhatsApp number; nothing is sent out."""
    media = (await audio.read(), audio.filename or "a.webm", audio.content_type or "audio/webm") if audio else None
    await handle_incoming(tenant_phone or OWNER_PHONE, "audio" if media else "text", text, media, deliver=False)
    return {"ok": True}


@app.get("/messages")
def messages(after: int = 0, channel: str = "whatsapp"):
    return q("select * from messages where id>? and channel=? and role='owner' order by id", (after, channel))


def record_xml(cid):  # listen for the tenant's answer; silence ends it after 3s
    return (f'<Record action="{PUBLIC_URL}/calls/reply/{cid}?k={call_key(cid)}" method="POST" maxLength="12" timeout="3" '
            'playBeep="false" trim="trim-silence"/>')


async def speak_xml(text_en, lang):
    text = await tr(text_en, lang)
    url = await tts(text, lang)
    return f"<Play>{PUBLIC_URL}{url}</Play>" if url else f"<Say>{text.replace('<', '')}</Say>"


@app.post("/calls/twiml/{cid}")
async def call_twiml(cid: int, request: Request):
    await twilio_form(request, f"/calls/twiml/{cid}", cid)
    c = q("select * from calls where id=?", (cid,))
    if not c:
        raise HTTPException(404, "unknown call")
    play = f"<Play>{PUBLIC_URL}{c[0]['audio_url']}</Play>" if c[0]["audio_url"] else f"<Say>{c[0]['text'].replace('<', '')}</Say>"
    return twiml(play + record_xml(cid))


async def fetch_recording(url):
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        for _ in range(4):  # the file can lag the webhook by a second
            r = await c.get(url + ".wav", auth=(TW_SID, TW_TOKEN))
            if r.status_code == 200:
                return await stt(r.content, "reply.wav", "audio/wav")
            await asyncio.sleep(1)
    return ""


@app.post("/calls/reply/{cid}")
async def call_reply(cid: int, request: Request):
    form = await twilio_form(request, f"/calls/reply/{cid}", cid)
    said = ""
    if form.get("RecordingUrl") and int(form.get("RecordingDuration") or 0) > 0:
        try:
            said = await fetch_recording(form["RecordingUrl"])
        except Exception as e:
            print("recording/stt failed:", e)
    kind, tell, lang = await tenant_turn(cid, said)
    xml = await speak_xml(tell, lang)
    return twiml(xml + (record_xml(cid) if kind == "ask" else "<Hangup/>"))


@app.post("/calls/status/{cid}")
async def call_status(cid: int, request: Request):
    form = await twilio_form(request, f"/calls/status/{cid}", cid)
    c = q("select * from calls where id=?", (cid,))
    if c and not c[0]["outcome"] and form.get("CallStatus") in ("no-answer", "busy", "failed", "canceled", "completed"):
        t = tenant_row(c[0]["tenant_id"])
        spoke = "Tenant:" in (c[0]["transcript"] or "")
        q("update calls set status='completed', outcome=? where id=?", ("hung_up" if spoke else "no_answer", cid))
        await say(OWNER_PHONE, f"{t['name']}, room {t['room']}: " + ("hung up before finishing the reminder call." if spoke else "did not pick up the reminder call."), "kn")
    return {"ok": True}


@app.post("/dev/simulate-call/{cid}")
async def simulate_call(cid: int, said: str = ""):
    """Mock mode: type what the tenant would say on the call."""
    if TW_SID or VOICE:
        raise HTTPException(403, "simulation is only for mock mode")
    kind, tell, _ = await tenant_turn(cid, said)
    return {"kind": kind, "reply": tell}


def incoming_key():  # secret in the voice webhook URL set on the Twilio number
    return hmac.new(TW_TOKEN.encode(), b"incoming", hashlib.sha256).hexdigest()[:20]


@app.post("/calls/incoming")
async def call_incoming(request: Request):
    """A tenant phones the Twilio number to report a problem. Caller ID identifies them."""
    if not hmac.compare_digest(request.query_params.get("k", ""), incoming_key()):
        raise HTTPException(403, "bad key")
    form = dict(await request.form())
    t = q("select * from tenants where status='active' and phone like ?", ("%" + last10(form.get("From")),))
    if not t:
        return twiml(await speak_xml("Sorry, this number is not registered with the property. Goodbye.", "en") + "<Hangup/>")
    t = t[0]
    q("insert into calls(tenant_id,month,status,text,turn) values(?,?,'inbound','',1)", (t["id"], month()))
    cid = q.last
    greet = await speak_xml(f"Hello {t['name']}. This is Kiraya Mitra. Please tell me your problem after the pause, and I will inform the owner.", t["language"])
    return twiml(greet + (f'<Record action="{PUBLIC_URL}/calls/grievance/{cid}?k={call_key(cid)}" method="POST" maxLength="40" timeout="4" '
                          'playBeep="true" trim="trim-silence"/>'))


async def file_grievance(t, said, cid, transcript=None):
    r = await t_create_ticket(t["id"], said[:500])
    q("update calls set status='completed', outcome='grievance', transcript=?, reason=? where id=?", (transcript or f"Tenant: {said}\n", said[:200], cid))
    await say(OWNER_PHONE, f"{t['name']}, room {t['room']}, reported a problem: {said[:300]}.", "kn", extra=f"Ticket #{r['ticket_id']}")
    return r


def dialogue_of(d):
    turns = d.get("interaction_transcript") or []
    return "".join(f"{'Agent' if x.get('role') == 'agent' else 'Tenant'}: {x.get('en_text', '')}\n" for x in turns), \
        " / ".join(x.get("en_text", "") for x in turns if x.get("role") == "user")


@app.post("/webhooks/sarvam/call")
async def sarvam_call_hook(request: Request):
    """Result of a reminder call placed through Sarvam Voice Agents."""
    if not hmac.compare_digest(request.query_params.get("k", ""), voice_key()):
        raise HTTPException(403, "bad key")
    d = await request.json()
    cid = int(((d.get("webhook_config") or {}).get("metadata") or {}).get("call_id") or 0)
    c = q("select * from calls where id=?", (cid,))
    if not c or c[0]["outcome"]:
        return {"ok": True, "ignored": True}  # unknown call, or a repeated delivery
    t = tenant_row(c[0]["tenant_id"])
    if d.get("status") != "connected":
        failed = d.get("status") == "failed"
        q("update calls set status='completed', outcome=? where id=?", ("failed" if failed else "no_answer", cid))
        why = f" ({d['failure_reason']})" if d.get("failure_reason") else ""
        await say(OWNER_PHONE, f"{t['name']}, room {t['room']}: " + (f"the reminder call failed{why}." if failed else "did not pick up the reminder call."), "kn")
        return {"ok": True}
    dialogue, said = dialogue_of(d)
    v = d.get("final_agent_variables") or {}
    pre = None
    if str(v.get("intent", "")).lower() in ("pay_now", "needs_time", "unclear"):  # what the agent itself extracted
        pre = {"intent": str(v["intent"]).lower(), "reason": v.get("reason") or "", "date": v.get("promise_date") or None,
               "amount": int(v["amount"]) if str(v.get("amount", "")).isdigit() else None}
    q("update calls set turn=3 where id=?", (cid,))
    await tenant_turn(cid, said, pre, dialogue)
    return {"ok": True}


@app.post("/webhooks/sarvam/inbound")
async def sarvam_inbound_hook(request: Request):
    """A tenant phoned the Sarvam number to report a problem."""
    if not hmac.compare_digest(request.query_params.get("k", ""), voice_key()):
        raise HTTPException(403, "bad key")
    d = await request.json()
    t = q("select * from tenants where status='active' and phone like ?", ("%" + last10(d.get("user_phone_number")),))
    iid = d.get("interaction_id")
    if not t or (iid and q("select 1 from calls where call_sid=?", (iid,))):
        return {"ok": True, "ignored": True}
    t = t[0]
    dialogue, said = dialogue_of(d)
    v = d.get("final_agent_variables") or d.get("output_agent_variables") or {}
    issue = str(v.get("issue") or said).strip()
    if not issue:
        return {"ok": True, "ignored": True}
    if str(v.get("urgency", "")).lower() == "high":
        issue = "[URGENT] " + issue
    q("insert into calls(tenant_id,month,status,text,turn,call_sid) values(?,?,'inbound','',1,?)", (t["id"], month(), iid))
    await file_grievance(t, issue, q.last, dialogue)
    return {"ok": True}


@app.post("/calls/grievance/{cid}")
async def call_grievance(cid: int, request: Request):
    form = await twilio_form(request, f"/calls/grievance/{cid}", cid)
    c = q("select * from calls where id=?", (cid,))
    if not c:
        raise HTTPException(404, "unknown call")
    t = tenant_row(c[0]["tenant_id"])
    said = ""
    if form.get("RecordingUrl") and int(form.get("RecordingDuration") or 0) > 0:
        try:
            said = await fetch_recording(form["RecordingUrl"])
        except Exception as e:
            print("recording/stt failed:", e)
    if not said.strip():
        return twiml(await speak_xml("I could not hear you. Please call again.", t["language"]) + "<Hangup/>")
    r = await file_grievance(t, said, cid)
    done = f"Thank you. I have noted your complaint and informed the owner. Your ticket number is {r['ticket_id']}."
    return twiml(await speak_xml(done, t["language"]) + "<Hangup/>")


@app.post("/cron/reminders")  # hit from a scheduler a couple of days before the due day
async def cron_reminders():
    return await call_tool("send_reminders", {})


# ---------- dashboard data ----------
@app.get("/overview")
async def overview(month_: str | None = Query(None, alias="month")):
    ensure_month()
    m = month_ or month()
    return {"summary": await t_monthly_summary(m),
            "series": q("select month, sum(due) due, sum(paid) paid from ledger group by month order by month desc limit 6")[::-1],
            "statuses": q("select status, count(*) n from ledger where month=? group by status", (m,)),
            "open_tickets": q("select count(*) n from tickets where status='open'")[0]["n"],
            "tenants": q("select count(*) n from tenants where status='active'")[0]["n"],
            "recent_calls": q("select c.id,c.status,c.outcome,c.ts,t.name,t.room from calls c join tenants t on t.id=c.tenant_id order by c.id desc limit 5")}


@app.get("/rooms")
def rooms():
    occ = q("select t.id,t.name,t.room,t.language,t.phone,l.status rent_status,l.due-l.paid pending from tenants t "
            "left join ledger l on l.tenant_id=t.id and l.month=? where t.status='active' order by t.id", (month(),))
    return [{"room": r, **v, "occupants": [o for o in occ if o["room"] == r]} for r, v in ROOMS.items()]


@app.get("/tenants/all")
def tenants_all():
    ensure_month()
    return q("select t.*, l.due, l.paid, l.status rent_status, l.promise_date from tenants t "
             "left join ledger l on l.tenant_id=t.id and l.month=? where t.status='active' order by t.room", (month(),))


@app.get("/tenants/{tid}")
async def tenant_get(tid: int):
    try:
        return await tenant_detail(tid)
    except ToolError as e:
        raise HTTPException(404, str(e))


@app.get("/ledger")
def ledger(month_: str | None = Query(None, alias="month")):
    ensure_month()
    m = month_ or month()
    return {"month": m, "months": [r["month"] for r in q("select distinct month from ledger order by month desc")],
            "rows": q("select t.id tenant_id,t.name,t.room,t.language,l.due,l.paid,l.due-l.paid pending,l.status,l.promise_date,"
                      "(select max(paid_ts) from payments p where p.tenant_id=l.tenant_id and p.month=l.month and p.paid>0) paid_on,"
                      "(select group_concat(distinct method) from payments p where p.tenant_id=l.tenant_id and p.month=l.month and p.paid>0) method "
                      "from ledger l join tenants t on t.id=l.tenant_id where l.month=? order by t.room", (m,))}


@app.get("/activity")
def activity():
    return {"payments": q("select p.id,t.name,t.room,p.month,p.amount,p.paid,p.method,p.status,p.paid_ts,p.ts,p.txn_id,p.receipt_no from payments p "
                          "join tenants t on t.id=p.tenant_id order by coalesce(p.paid_ts,p.ts) desc, p.id desc limit 150"),
            "payouts": q("select o.id,p.name payee,o.amount,o.reason,o.kind,o.status,o.day from payouts o join payees p on p.id=o.payee_id order by o.id desc limit 100"),
            "tickets": q("select k.id,t.name,t.room,k.issue,k.status,k.ts from tickets k join tenants t on t.id=k.tenant_id order by k.id desc limit 100"),
            "calls": q("select c.id,t.name,t.room,t.language,c.status,c.outcome,c.ts,c.transcript,c.reason,c.promise_date from calls c join tenants t on t.id=c.tenant_id order by c.id desc limit 100"),
            "audit": q("select ts,actor,action,payload from audit_log order by id desc limit 100")}


# ---------- Cashfree UPI AutoPay ----------
def autopay_row(token):
    rows = q("select a.*,t.name,t.phone,t.room,t.rent from autopay a join tenants t on t.id=a.tenant_id where a.token=?", (token,))
    if not rows:
        raise HTTPException(404, "AutoPay link not found")
    return rows[0]


@app.get("/autopay/{token}", response_class=HTMLResponse)
def autopay_page(token: str):
    a = autopay_row(token)
    active = a["status"] == "active"
    if not active and not a["session_id"]:
        raise HTTPException(409, "AutoPay setup is unavailable. Please ask the owner for a new link.")
    mode = "sandbox" if "sandbox" in CF_BASE else "production"
    session = json.dumps(a["session_id"])
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rent AutoPay</title><script src="https://sdk.cashfree.com/js/v3/cashfree.js"></script>
<style>:root{{--bg:#faf9f6;--card:#fff;--ink:#1a1a1a;--mut:#666;--line:#e8e6df;--pri:#1f5e55}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}}main{{max-width:440px;margin:48px auto;padding:0 18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px}}h1{{font-size:26px;margin:0 0 6px}}p{{color:var(--mut)}}
dl{{display:grid;grid-template-columns:1fr auto;gap:10px;margin:24px 0}}dd{{margin:0;font-weight:600}}button{{width:100%;border:0;border-radius:12px;padding:14px;background:var(--pri);color:white;font:inherit;font-weight:600;cursor:pointer}}button:disabled{{opacity:.6}}</style></head>
<body><main><div class="card"><h1>{"AutoPay is active" if active else "Set up rent AutoPay"}</h1>
<p>{"Your monthly rent mandate is ready." if active else "Approve a secure UPI mandate with Cashfree. A refundable ₹1 authorisation may appear during setup."}</p>
<dl><dt>Tenant</dt><dd>{html.escape(a["name"])}</dd><dt>Room</dt><dd>{html.escape(a["room"])}</dd>
<dt>Monthly rent</dt><dd>₹{a["rent"]:,}</dd><dt>Due every month</dt><dd>{PROPERTY["due_day"]}th</dd></dl>
{'' if active else '<button id="approve">Continue to Cashfree</button><p id="error"></p>'}</div></main>
<script>const b=document.getElementById("approve");if(b) b.onclick=async()=>{{b.disabled=true;b.textContent="Opening Cashfree…";
const result=await Cashfree({{mode:{json.dumps(mode)}}}).subscriptionsCheckout({{subsSessionId:{session},redirectTarget:"_self"}});
if(result?.error){{document.getElementById("error").textContent=result.error.message||"Could not open Cashfree. Please try again.";b.disabled=false;b.textContent="Continue to Cashfree"}}}};</script>
</body></html>"""


@app.api_route("/autopay/{token}/return", methods=["GET", "POST"], response_class=HTMLResponse)
async def autopay_return(token: str):
    a = autopay_row(token)
    try:
        j = await cf("GET", f"/pg/subscriptions/{a['subscription_id']}", "2026-01-01")
        status = str(j.get("subscription_status") or a["status"]).lower()
        q("update autopay set status=?, cf_subscription_id=coalesce(?,cf_subscription_id) where id=?",
          (status, j.get("cf_subscription_id"), a["id"]))
    except ToolError:
        status = a["status"]
    title = "AutoPay active" if status == "active" else "Mandate submitted"
    detail = ("Your monthly rent will be collected automatically." if status == "active"
              else "Cashfree is confirming your mandate. You can close this page; we will update you on WhatsApp.")
    return f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>{title}</title><body style='font:16px/1.5 system-ui;max-width:440px;margin:64px auto;padding:0 18px'><h1>{title}</h1><p>{detail}</p>"


@app.post("/webhooks/cashfree/subscription")
async def webhook_subscription(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    verify_cashfree_webhook(request, raw, CF_SECRET)
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")
    event, data = str(body.get("type") or "").upper(), body.get("data") or {}
    wrapper = data.get("subscription_status_webhook") or {}
    details = data.get("subscription_details") or wrapper.get("subscription_details") or {}
    sub_id = data.get("subscription_id") or details.get("subscription_id")
    rows = q("select * from autopay where subscription_id=?", (sub_id,))
    if not rows:
        return {"ok": True, "ignored": True}
    a = rows[0]
    auth = data.get("authorization_details") or wrapper.get("authorization_details") or {}
    status = str(details.get("subscription_status") or "").lower()
    auth_status = str(auth.get("authorization_status") or auth.get("authorizationStatus") or "").lower()
    if event == "SUBSCRIPTION_AUTH_STATUS" and (auth_status == "failed" or str(data.get("payment_status") or "").lower() == "failed"):
        q("update autopay set status='failed' where id=? and status!='active'", (a["id"],))
    elif auth_status == "active":
        q("update autopay set status='active' where id=?", (a["id"],))
    elif status:
        q("update autopay set status=? where id=?", (status, a["id"]))
    if event in ("SUBSCRIPTION_PAYMENT_FAILED", "SUBSCRIPTION_PAYMENT_CANCELLED"):
        q("update autopay set last_payment_status=? where id=?", (event.removeprefix("SUBSCRIPTION_PAYMENT_").lower(), a["id"]))
    if event == "SUBSCRIPTION_PAYMENT_SUCCESS" and str(data.get("payment_type") or "").upper() == "CHARGE":
        if str(data.get("payment_currency") or "INR").upper() != "INR":
            raise HTTPException(400, "unexpected currency")
        try:
            raw_amount = float(data["payment_amount"])
            amount = int(raw_amount)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "invalid payment amount")
        if amount <= 0 or raw_amount != amount:
            raise HTTPException(400, "invalid payment amount")
        payment_id = str(data.get("cf_payment_id") or data.get("payment_id") or "")
        if not payment_id:
            raise HTTPException(400, "missing payment id")
        scheduled = str(data.get("payment_schedule_date") or "")
        mon = scheduled[:7] if re.fullmatch(r"\d{4}-\d{2}.*", scheduled) else month()
        tenant = tenant_row(a["tenant_id"])
        q("insert or ignore into ledger(tenant_id,month,due) values(?,?,?)", (tenant["id"], mon, tenant["rent"]))
        link_id = f"autopay_{a['subscription_id']}_{payment_id}"
        q("insert or ignore into payments(tenant_id,link_id,amount,month,url,method) values(?,?,?,?,?,'autopay')",
          (tenant["id"], link_id, amount, mon, autopay_url(a)))
        q("update autopay set status='active', last_payment_status='success' where id=?", (a["id"],))
        audit("cashfree", "autopay_payment", {"tenant_id": tenant["id"], "subscription_id": sub_id,
                                              "payment_id": payment_id, "amount": amount, "month": mon})
        return await apply_payment(link_id, amount, payment_id, background_tasks)
    current = q("select status from autopay where id=?", (a["id"],))[0]["status"]
    audit("cashfree", "autopay_status", {"tenant_id": a["tenant_id"], "subscription_id": sub_id,
                                         "event": event, "status": current})
    return {"ok": True, "status": current}


# ---------- onboarding endpoints ----------
@app.post("/onboarding/start")
async def onboarding_start(request: Request):
    """Dashboard button: the owner typed everything, so the read-back step is skipped."""
    b = await request.json()
    try:
        r = await t_start_onboarding(b["name"], b["phone"], b["room"], b.get("language", "hi"), b.get("call", True))
        return await confirm_onboarding(r["onboarding_id"])
    except ToolError as e:
        raise HTTPException(400, str(e))


@app.get("/onboard/{token}")
def onboard_page(token: str):
    return FileResponse(ROOT / "static" / "onboard.html")


@app.get("/onboard-api/{token}")
def onboard_prefill(token: str):
    ob = ob_live(token)
    return {"property": PROPERTY["name"], "address": PROPERTY_ADDRESS, "name": ob["name"], "phone": ob["phone"], "whatsapp": ob["whatsapp"] or "",
            "room": ob["room"], "sharing": ob["sharing"], "rent": ob["rent"], "deposit": ob["deposit"],
            "due_day": PROPERTY["due_day"], "status": ob["status"]}


REQUIRED = ["name", "phone", "email", "dob", "gender", "occupation", "org_name", "org_role", "primary_language",
            "address", "emergency_name", "emergency_phone", "emergency_relation", "move_in", "food"]


@app.post("/onboard-api/{token}")
async def onboard_submit(token: str, request: Request, bg: BackgroundTasks):
    ob = ob_live(token)
    if ob["status"] not in ("invited", "link_sent"):
        raise HTTPException(409, "This form has already been submitted.")
    form = await request.form()
    f = {k: str(v).strip() for k, v in form.items() if not hasattr(v, "filename")}
    missing = [k for k in REQUIRED if not f.get(k)]
    if missing:
        raise HTTPException(400, "Please fill: " + ", ".join(m.replace("_", " ") for m in missing))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]):
        raise HTTPException(400, "Email address looks wrong.")
    for k in ("phone", "emergency_phone"):
        f[k] = last10(f[k])
        if len(f[k]) != 10:
            raise HTTPException(400, f"{k.replace('_', ' ')} must be a 10 digit number.")
    f["whatsapp_same"] = f.get("whatsapp_same", "yes")
    f["whatsapp"] = f["phone"] if f["whatsapp_same"] == "yes" else last10(f.get("whatsapp", ""))
    if len(f["whatsapp"]) != 10:
        raise HTTPException(400, "WhatsApp number must be a 10 digit number.")
    if f.get("consent") not in ("on", "true", "yes"):
        raise HTTPException(400, "Please accept the declaration to continue.")
    aadhaar = await save_upload(form.get("aadhaar"), (".jpg", ".png", ".pdf"), ob["id"], "Aadhaar card")
    photo = await save_upload(form.get("photo"), (".jpg", ".png"), ob["id"], "Photo")
    f["autopay"] = "yes" if f.get("autopay") == "yes" else "no"
    keep = ["name", "phone", "whatsapp", "email", "dob", "gender", "occupation", "org_name", "org_role", "org_location", "primary_language",
            "secondary_language", "address", "emergency_name", "emergency_phone", "emergency_relation", "move_in", "food", "health_notes", "vehicle", "autopay"]
    q("update onboarding set status='submitted', whatsapp=?, form_json=?, aadhaar_file=?, photo_file=?, submitted_at=datetime('now','localtime') where id=?",
      (f["whatsapp"], json.dumps({k: f.get(k, "") for k in keep}, ensure_ascii=False), aadhaar, photo, ob["id"]))
    audit("tenant", "onboarding_submitted", {"id": ob["id"], "name": f["name"]})
    async def notify():  # voice note and translation take seconds; the tenant should not wait for them
        await say(OWNER_PHONE, f"{f['name']} submitted the onboarding form for room {ob['room']}. Please review and approve it in the dashboard.", "kn",
                  extra=f"Name: {f['name']}\nPhone: {f['phone']}\nEmail: {f['email']}\n{f['occupation'].title()}: {f['org_name']}\nRoom: {ob['room']} ({ob['sharing']}-sharing)")
        lang = ob["call_language"] or "en"
        thanks = await tr(f"Thank you {f['name']}. Your details are received. The owner will confirm your room shortly. "
                          "You can use the address of our PG as your present address:", lang)
        await send_to_tenant({"phone": ob["phone"], "whatsapp": f["whatsapp"], "name": f["name"], "language": lang},
                             f"{thanks}\n{PROPERTY_ADDRESS}" if PROPERTY_ADDRESS else thanks, "", [])
    bg.add_task(notify)
    return {"ok": True}


@app.get("/onboarding")
def onboarding_list():
    rows = q("select o.id,o.name,o.phone,o.room,o.sharing,o.status,o.call_outcome,o.created,o.submitted_at,o.tenant_id,o.form_json,a.status autopay_status "
             "from onboarding o left join autopay a on a.tenant_id=o.tenant_id order by o.id desc")
    for row in rows:
        requested = json.loads(row.pop("form_json") or "{}").get("autopay") == "yes"
        row["autopay_status"] = row["autopay_status"] or ("requested" if requested else "not_requested")
    return rows


@app.get("/onboarding/{oid}")
def onboarding_get(oid: int):
    r = q("select * from onboarding where id=?", (oid,))
    if not r:
        raise HTTPException(404, "unknown onboarding")
    ob = r[0]
    autopay = next(iter(q("select status,first_charge,last_payment_status from autopay where tenant_id=?", (ob["tenant_id"],))), None)
    return {**{k: ob[k] for k in ("id", "name", "phone", "room", "sharing", "rent", "deposit", "status", "call_outcome", "whatsapp",
                                  "created", "submitted_at", "tenant_id", "call_language")},
            "form": json.loads(ob["form_json"] or "{}"), "has_aadhaar": bool(ob["aadhaar_file"]), "has_photo": bool(ob["photo_file"]),
            "link": ob_url(ob), "autopay": autopay}


@app.get("/onboarding/{oid}/file/{kind}")
def onboarding_file(oid: int, kind: str):
    r = q("select aadhaar_file, photo_file from onboarding where id=?", (oid,))
    name = r and (r[0]["aadhaar_file"] if kind == "aadhaar" else r[0]["photo_file"] if kind == "photo" else None)
    if not name or not (UPLOADS / name).exists():
        raise HTTPException(404, "no such file")
    return FileResponse(UPLOADS / name)


@app.post("/onboarding/{oid}/resend")
async def onboarding_resend(oid: int):
    if not q("select 1 from onboarding where id=? and status in ('invited','link_sent')", (oid,)):
        raise HTTPException(400, "form already submitted or closed")
    return {"delivered": await send_form_link(oid)}


@app.post("/onboarding/{oid}/reject")
async def onboarding_reject(oid: int):
    q("update onboarding set status='rejected' where id=? and status in ('invited','link_sent','submitted')", (oid,))
    return {"status": "rejected"}


@app.post("/onboarding/{oid}/approve")
async def onboarding_approve(oid: int):
    r = q("select * from onboarding where id=?", (oid,))
    if not r or r[0]["status"] != "submitted":
        raise HTTPException(400, "only a submitted form can be approved")
    ob, form = r[0], json.loads(r[0]["form_json"])
    lang = LANG_CODES.get(form.get("primary_language", "").lower(), "en")
    if q("select count(*) n from tenants where status='active' and room=?", (ob["room"],))[0]["n"] >= ob["sharing"]:
        raise HTTPException(400, f"room {ob['room']} is full now")
    try:
        res = await t_add_tenant(form.get("name") or ob["name"], ob["phone"], ob["room"], language=lang)
    except ToolError as e:
        raise HTTPException(400, str(e))
    q("update tenants set whatsapp=? where id=?", (ob["whatsapp"], res["tenant_id"]))
    q("update onboarding set status='approved', tenant_id=? where id=?", (res["tenant_id"], oid))
    audit("owner", "onboarding_approved", {"id": oid, "tenant_id": res["tenant_id"]})
    t = tenant_row(res["tenant_id"])
    await send_to_tenant(t, res["welcome_text"], "", [])
    autopay_status = "not_requested"
    if form.get("autopay") == "yes":
        try:
            autopay_status = (await setup_autopay(t, form))["status"]
        except ToolError as e:
            autopay_status = "setup_failed"
            audit("cashfree", "autopay_setup_failed", {"tenant_id": t["id"], "error": str(e)})
    return {"tenant_id": res["tenant_id"], "autopay_status": autopay_status}


@app.post("/webhooks/sarvam/onboarding")
async def sarvam_onboarding_hook(request: Request):
    """Result of the onboarding call: confirmed name, phone and WhatsApp number. Then the form link goes out."""
    if not hmac.compare_digest(request.query_params.get("k", ""), voice_key()):
        raise HTTPException(403, "bad key")
    d = await request.json()
    oid = int(((d.get("webhook_config") or {}).get("metadata") or {}).get("onboarding_id") or 0)
    r = q("select * from onboarding where id=? and status='invited'", (oid,))
    if not r:
        return {"ok": True, "ignored": True}
    ob = r[0]
    if d.get("status") != "connected":
        q("update onboarding set call_outcome=? where id=?", ("failed" if d.get("status") == "failed" else "no_answer", oid))
        await send_form_link(oid)
        await say(OWNER_PHONE, f"{ob['name']} did not pick up the onboarding call. The form link was sent on WhatsApp instead.", "kn")
        return {"ok": True}
    v = d.get("final_agent_variables") or {}
    name = ob["name"]
    if str(v.get("name_confirmed", "")).lower() == "no" and str(v.get("corrected_name", "")).strip():
        name = str(v["corrected_name"]).strip()
    wa = last10(v.get("whatsapp_number")) if str(v.get("whatsapp_same", "")).lower() == "no" else ""
    interest = str(v.get("form_ok", "")).lower()
    q("update onboarding set name=?, whatsapp=?, call_outcome=? where id=?", (name, wa if len(wa) == 10 else None, interest or "connected", oid))
    if interest == "not_interested":
        q("update onboarding set status='declined' where id=?", (oid,))
        await say(OWNER_PHONE, f"{name} said they are not interested in room {ob['room']}.", "kn")
        return {"ok": True}
    await send_form_link(oid)
    await say(OWNER_PHONE, f"{name} confirmed the details on the call. The onboarding form was sent on WhatsApp.", "kn",
              extra=f"Phone: {ob['phone']}\nWhatsApp: {wa if len(wa) == 10 else 'same as phone'}")
    return {"ok": True}
