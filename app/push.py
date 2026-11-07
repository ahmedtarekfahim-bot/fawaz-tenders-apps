# -*- coding: utf-8 -*-
"""Notifications on the phone (Web Push) for everything new - sent by the main PC right after each update.

  - the phone app subscribes (the browser's own push service, works with the app closed) and sends the
    subscription + its choices through the phone channel, signed with the account's notify key:
        push|<user>|<base64 json {s: subscription, p: choices, d: device}>|<unix time>|<sig>
    notify key = HMAC(routines key, "notify|<user>"), handed to each account wrapped for its own public key
    (ntfy.json "nk") - only that account's phone can open it.
  - after each update: new tenders, awards, postponements / status changes, CAPT + Kuwait Al-Youm notices,
    newspaper news, new reports (routines / weekly projects report), a new program version
    -> filtered per account (its permissions and countries, then its own choices) -> one push per thing,
    at most MAX a run (then one "and N more").
  - the message is encrypted for the phone (RFC 8291, aes128gcm) and signed with this PC's VAPID key.
  - the cloud (GitHub Actions, every 15 minutes) sends the same notifications when the PC is off: the PC
    hands it push.enc on pc-feed (VAPID key, notify keys, phones, choices, account rules) sealed with
    cloud_key() (from the routines key), which the cloud gets as the secret FAWAZ_PUSH_KEY. With that on, the PC leaves the
    data notifications to the cloud (one sender, no doubles) and keeps reports / program updates.
"""
import os, json, time, hmac, hashlib, base64, threading, datetime, urllib.request, urllib.parse
from pathlib import Path
import fawaz_config as cfg

FILE = cfg.LOCAL / "push.json"
MAX = 6
KINDS = {"new": "🆕 مناقصات جديدة", "award": "🏆 ترسيات", "date": "📅 تأجيل ومواعيد", "status": "⚠️ إلغاء وتغيير حالة",
         "official": "🏛 الجهاز المركزي والكويت اليوم", "news": "📰 أخبار الجرايد", "reports": "📊 تقارير جديدة",
         "app": "⬆️ تحديث البرنامج"}
OFFICIAL = ("جريدة الكويت اليوم", "قرارات الجهاز (الكويت اليوم)", "فض العطاءات (الجهاز المركزي)",
            "الجهاز المركزي (المطروح)", "ترسيات الجهاز المركزي")
_lock = threading.RLock()


# ----------------------------------------------------------------- state: subscriptions, choices, last seen
def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("users", {})
    d.setdefault("mark", {})
    return d


def save(d):
    cfg.LOCAL.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, FILE)


def default_prefs():
    return {"kinds": [k for k in KINDS], "countries": [], "fawaz": False, "words": []}


def clean_prefs(p):
    p = p or {}
    return {"kinds": [k for k in (p.get("kinds") or []) if k in KINDS],
            "countries": [c for c in (p.get("countries") or []) if c in ("KW", "SA", "AE")],
            "fawaz": bool(p.get("fawaz")),
            "words": [str(w).strip()[:40] for w in (p.get("words") or []) if str(w).strip()][:20]}


def user_entry(d, user):
    return d["users"].setdefault(user, {"subs": [], "prefs": default_prefs()})


# ----------------------------------------------------------------- keys
def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def vapid():
    """this PC's VAPID key pair (P-256) -> (private key, public key raw b64url)"""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    pem = os.environ.get("FAWAZ_VAPID_PEM") or cfg.S.get("vapid_key")
    if pem:
        k = serialization.load_pem_private_key(pem.encode(), None)
    else:
        k = ec.generate_private_key(ec.SECP256R1())
        cfg.save_setting("vapid_key", k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()).decode())
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return k, _b64u(pub)


def notify_key(user):
    import phone_lock
    return hmac.new(phone_lock.routines_key().encode(), f"notify|{user}".encode(), hashlib.sha256).digest()


def phone_info(users_pub):
    """for ntfy.json: the VAPID public key + each active account's notify key wrapped for its own public key"""
    import accounts
    nk = {}
    for u, e in (users_pub.get("users") or {}).items():
        if e.get("active") and e.get("pub"):
            try:
                nk[accounts.uid(u)] = accounts.wrap_for(e["pub"], notify_key(u))
            except Exception:           # noqa: BLE001
                pass
    return {"vapid": vapid()[1], "nk": nk}


# ----------------------------------------------------------------- Web Push (RFC 8291 + RFC 8292)
def _hkdf(salt, ikm, info, n):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]


def encrypt(sub, payload, eph=None, salt=None):
    """eph / salt only for checking against the RFC 8291 example"""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua_pub = _unb64u(sub["keys"]["p256dh"])
    auth = _unb64u(sub["keys"]["auth"])
    eph = eph or ec.generate_private_key(ec.SECP256R1())
    as_pub = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_pub)]) + as_pub + body


def _jwt(aud):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    k, pub = vapid()
    head = _b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = _b64u(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600,
                               "sub": "https://ahmedtarekfahim-bot.github.io/"}).encode())
    r, s = decode_dss_signature(k.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{claims}.{_b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}", pub


def send_one(sub, msg):
    """-> HTTP status (201 = delivered to the push service; 404 / 410 = the subscription is gone)"""
    u = urllib.parse.urlparse(sub["endpoint"])
    tok, pub = _jwt(f"{u.scheme}://{u.netloc}")
    data = encrypt(sub, json.dumps(msg, ensure_ascii=False).encode("utf-8"))
    req = urllib.request.Request(sub["endpoint"], data=data, method="POST", headers={
        "TTL": "86400", "Urgency": "high", "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "Authorization": f"vapid t={tok}, k={pub}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:                   # noqa: BLE001 - offline: try again next time
        return 0


def deliver(user, msgs, log=print):
    """send to every device of one account; drop the devices the push service says are gone"""
    with _lock:
        d = load()
        e = d["users"].get(user)
        if not e or not e["subs"] or not msgs:
            return 0
        keep, sent = [], 0
        for s in e["subs"]:
            gone = False
            for m in msgs:
                st = send_one(s["sub"], m)
                if st in (404, 410):
                    gone = True
                    break
                sent += 200 <= st < 300
            if not gone:
                keep.append(s)
        if len(keep) != len(e["subs"]):
            e["subs"] = keep
            save(d)
        return sent


# ----------------------------------------------------------------- the phone registers / changes its choices
def register(user, arg, log=print, test_ok=True):
    raw = json.loads(base64.urlsafe_b64decode(arg + "=" * (-len(arg) % 4)).decode("utf-8"))
    with _lock:
        d = load()
        e = user_entry(d, user)
        sub = raw.get("s")
        known = bool(sub) and any(x["sub"].get("endpoint") == sub.get("endpoint") for x in e["subs"])
        if raw.get("off") and sub:
            e["subs"] = [x for x in e["subs"] if x["sub"].get("endpoint") != sub.get("endpoint")]
        elif sub and str(sub.get("endpoint", "")).startswith("https://") and sub.get("keys"):
            e["subs"] = [x for x in e["subs"] if x["sub"].get("endpoint") != sub["endpoint"]]
            e["subs"].append({"sub": {"endpoint": sub["endpoint"], "keys": sub["keys"]}, "device": str(raw.get("d", ""))[:60],
                              "at": datetime.datetime.now().isoformat(timespec="minutes")})
            e["subs"] = e["subs"][-5:]
        if "p" in raw:
            e["prefs"] = clean_prefs(raw["p"])
        e["upd"] = datetime.datetime.now().isoformat(timespec="seconds")
        save(d)
    if test_ok and (raw.get("test") or (sub and not raw.get("off") and not known)):     # a new phone: show it works
        deliver(user, [{"t": "🔔 الإشعارات شغالة", "b": "هيوصلك هنا كل جديد حسب اختياراتك", "u": "#", "tag": "test"}], log)
    log(f"إشعارات الموبايل ({user}): " + ("اتقفلت على جهاز" if raw.get("off") else "اتسجلت / اتحدثت"))


def check(user, arg, ts, sig):
    good = hmac.new(notify_key(user), f"push|{user}|{arg}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(good, sig) and ts.isdigit() and abs(time.time() - int(ts)) < 600


# ----------------------------------------------------------------- what is new since last time
def _cut(s, n=140):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _maxes(con):
    q = lambda t: con.execute(f"SELECT COALESCE(MAX(id),0) FROM {t}").fetchone()[0]
    return {"items": q("items"), "changes": q("changes"), "events": q("events"), "news": q("news")}


def collect(gd, mark):
    """-> list of things: {kind, country, fawaz, text(for words), need, msg}"""
    con = gd.db()
    out, done = [], set()
    cname = gd.COUNTRIES
    for r in con.execute("SELECT * FROM items WHERE id>? AND first_seen<>? ORDER BY id", (mark["items"], gd.BASELINE)):
        r = dict(r)
        done.add(r["id"])
        closing = f" · يقفل {r['closing']}" if r.get("closing") else ""
        out.append({"kind": "new", "country": r["country"], "fawaz": r["fawaz"], "need": "dir", "item": r["id"],
                    "text": f"{r['subject']} {r['org']} {r['number']}",
                    "msg": {"t": f"🆕 مناقصة جديدة - {cname.get(r['country'], '')}",
                            "b": _cut(f"{r['number']} - {r['subject']}") + f"\n{_cut(r['org'], 60)}{closing}",
                            "u": f"#i={r['id']}", "tag": f"i{r['id']}"}})
    per = {}
    for c in con.execute("SELECT c.*, i.subject, i.org, i.number, i.country, i.fawaz FROM changes c JOIN items i ON i.id=c.item_id "
                         "WHERE c.id>? ORDER BY c.id", (mark["changes"],)):
        c = dict(c)
        if c["item_id"] in done:
            continue
        per.setdefault(c["item_id"], []).append(c)
    for iid, cs in per.items():
        r = cs[0]
        fields = {c["field"]: c for c in cs}
        if "winner" in fields or "award_date" in fields or "مترسي" in str(fields.get("status", {}).get("new", "")):
            kind, head = "award", "🏆 ترسية"
            w = fields.get("winner", {}).get("new")
            line = f"الفائز: {w}" if w else str(fields.get("status", {}).get("new") or "اترست")
            v = fields.get("value", {}).get("new")
            if v:
                line += f" · {v}"
        elif "closing" in fields:
            kind, head = "date", "📅 تأجيل / موعد جديد"
            f = fields["closing"]
            line = f"الإقفال بقى {f['new']}" + (f" بدل {f['old']}" if f.get("old") else "")
        elif "status" in fields:
            kind, head = "status", "⚠️ الحالة اتغيرت"
            f = fields["status"]
            line = f"{f.get('old') or ''} ← {f['new']}".strip(" ←")
        else:
            continue
        done.add(iid)
        out.append({"kind": kind, "country": r["country"], "fawaz": r["fawaz"], "need": "dir", "item": iid,
                    "text": f"{r['subject']} {r['org']} {r['number']}",
                    "msg": {"t": f"{head} - {cname.get(r['country'], '')}", "b": _cut(f"{r['number']} - {r['subject']}") + f"\n{_cut(line, 90)}",
                            "u": f"#i={iid}", "tag": f"i{iid}"}})
    marks = ",".join("?" * len(OFFICIAL))
    for e in con.execute(f"SELECT e.*, i.subject, i.org, i.number, i.country, i.fawaz FROM events e JOIN items i ON i.id=e.item_id "
                         f"WHERE e.id>? AND e.source IN ({marks}) ORDER BY e.id", (mark["events"], *OFFICIAL)):
        e = dict(e)
        if e["item_id"] in done:
            continue
        done.add(e["item_id"])
        out.append({"kind": "official", "country": e["country"], "fawaz": e["fawaz"], "need": "dir", "item": e["item_id"],
                    "text": f"{e['subject']} {e['org']} {e['number']} {e['text']}",
                    "msg": {"t": f"🏛 {e['source']}" + (f" - {e['etype']}" if e.get("etype") else ""),
                            "b": _cut(f"{e['number']} - {e['subject']}") + f"\n{_cut(e['text'], 90)}",
                            "u": f"#i={e['item_id']}", "tag": f"i{e['item_id']}"}})
    for n in con.execute("SELECT * FROM news WHERE id>? AND query NOT LIKE 'شركة:%' ORDER BY id", (mark["news"],)):
        n = dict(n)
        out.append({"kind": "news", "country": n["country"], "fawaz": n["fawaz"], "need": "news",
                    "text": f"{n['title']} {n['summary']}",
                    "msg": {"t": f"📰 {_cut(n['source'], 40)}", "b": _cut(n["title"], 160),
                            "u": n["url"] if str(n["url"]).startswith("http") else "#news", "tag": f"n{n['id']}"}})
    now = _maxes(con)
    con.close()
    return out, now


def collect_reports(mark):
    """new report files: the routines' reports and Adham's weekly projects report"""
    out, newest = [], mark
    try:
        import routines
        for r in routines.REGISTRY:
            for rep in routines.reports(r, 5):
                if rep["at"] > mark:
                    newest = max(newest, rep["at"])
                    out.append({"kind": "reports", "country": "", "fawaz": 1, "need": "routines", "rid": r["id"],
                                "text": f"{r['title']} {rep['name']}",
                                "msg": {"t": f"📊 تقرير جديد - {r['title']}", "b": _cut(rep["name"], 140), "u": "#routines",
                                        "tag": f"r{r['id']}"}})
    except Exception:                   # noqa: BLE001
        pass
    try:
        import projects
        for p in projects.reports()[:3]:
            at = datetime.datetime.fromtimestamp(Path(p["path"]).stat().st_mtime).isoformat(timespec="minutes")
            if at > mark:
                newest = max(newest, at)
                out.append({"kind": "reports", "country": "", "fawaz": 1, "need": "projects", "text": Path(p["path"]).name,
                            "msg": {"t": "📊 تقرير المشاريع الأسبوعي", "b": _cut(f"تقرير جديد: {Path(p['path']).name}", 140),
                                    "u": "#projects", "tag": "projects"}})
    except Exception:                   # noqa: BLE001
        pass
    return out, newest


# ----------------------------------------------------------------- who gets what
def rules():
    """each account's permissions as plain data (also handed to the cloud)"""
    import accounts
    return {u: {"perms": accounts.perms_of(d), "countries": d.get("countries") or ["KW", "SA", "AE"],
                "rids": [] if d.get("admin") else (d.get("routines") or []), "live": accounts.is_live(d)}
            for u, d in accounts.load()["users"].items()}


def wanted(thing, d, prefs, norm):
    if thing["kind"] not in prefs["kinds"]:
        return False
    if thing["kind"] == "app":
        return True
    need, cc = thing["need"], thing["country"]
    if not ((need == "awards" and "watch" in d["perms"]) or (need in d["perms"] and (not cc or cc in d["countries"]))):
        return False
    if thing.get("rid") and d["rids"] and thing["rid"] not in d["rids"]:
        return False
    if thing["country"] and prefs["countries"] and thing["country"] not in prefs["countries"]:
        return False
    if prefs["fawaz"] and not thing["fawaz"]:
        return False
    if prefs["words"]:
        t = norm(thing["text"])
        if not any(norm(w) in t for w in prefs["words"]):
            return False
    return True


def dispatch(things, log=print, users=None):
    from capt_tool import norm
    if not things:
        return 0
    with _lock:                         # never the same notification twice (PC + cloud, or a value flipping back)
        d = load()
        sent = d.setdefault("sent", [])
        seen = set(sent)
        fresh = []
        for t in things:
            k = hashlib.sha1((t["msg"]["t"] + "|" + t["msg"]["b"]).encode("utf-8")).hexdigest()[:16]
            if k not in seen:
                seen.add(k)
                sent.append(k)
                fresh.append(t)
        d["sent"] = sent[-6000:]
        save(d)
    things = fresh
    if not things:
        return 0
    users = users if users is not None else rules()
    total = 0
    for u, e in d["users"].items():
        du = users.get(u)
        if not e["subs"] or not du or not du.get("live"):
            continue
        mine = [t["msg"] for t in things if wanted(t, du, e["prefs"], norm)]
        if len(mine) > MAX:
            more = len(mine) - (MAX - 1)
            mine = mine[:MAX - 1] + [{"t": f"🔔 و {more} حاجة جديدة كمان", "b": "افتح التطبيق تشوف كل الجديد", "u": "#", "tag": "more"}]
        total += deliver(u, mine, log)
    if total:
        log(f"🔔 اتبعت {total} إشعار للموبايل")
    return total


def after_update(gd, log=print, cloud=None):
    """called at the end of each update on the main PC (cloud = the cloud's rules, from push.enc)"""
    if not (cfg.S.get("mobile_publish") or cloud is not None):
        return 0
    with _lock:
        d = load()
        mark = d["mark"]
        first = "items" not in mark
        if first:                       # first time: start from now, don't flood the phone with the whole history
            con = gd.db()
            mark.update(_maxes(con))
            con.close()
            mark.setdefault("reports", datetime.datetime.now().isoformat(timespec="minutes"))
            save(d)
            return 0
        things, now = collect(gd, mark)
        if cloud is None and cloud_active():
            things = []                 # the cloud sends the data notifications (the PC only reports / updates)
        rep, newest = collect_reports(mark.get("reports", "")) if cloud is None else ([], "")
        mark.update(now)
        mark["reports"] = newest or mark.get("reports", "")
        save(d)
    return dispatch(things + rep, log, cloud)


def check_reports(log=print):
    """between updates: a routine may finish its report at any time"""
    if not cfg.S.get("mobile_publish"):
        return 0
    with _lock:
        d = load()
        if "reports" not in d["mark"]:
            return 0
        rep, newest = collect_reports(d["mark"]["reports"])
        if newest == d["mark"]["reports"]:
            return 0
        d["mark"]["reports"] = newest
        save(d)
    return dispatch(rep, log)


def app_version(log=print):
    """once per new program version"""
    if not cfg.S.get("mobile_publish"):
        return 0
    ver = cfg.build_info().get("version", "")
    with _lock:
        d = load()
        old = d["mark"].get("app")
        if not ver or old == ver:
            return 0
        d["mark"]["app"] = ver
        save(d)
    if not old:
        return 0
    return dispatch([{"kind": "app", "country": "", "fawaz": 1, "need": "", "text": "",
                      "msg": {"t": f"⬆️ البرنامج اتحدّث لـ {ver}", "b": _cut(cfg.build_info().get("notes") or "نسخة جديدة", 160),
                              "u": "#", "tag": "app"}}], log)


# ----------------------------------------------------------------- the PC window
def view(user, is_admin):
    import accounts
    d = load()
    every = accounts.load()["users"]
    names = list(every) if is_admin else [user]
    out = []
    for u in names:
        e = d["users"].get(u) or {"subs": [], "prefs": default_prefs()}
        out.append({"user": u, "prefs": e["prefs"], "countries": (every.get(u) or {}).get("countries") or ["KW", "SA", "AE"], "devices": [{"device": s.get("device") or "موبايل", "at": s.get("at", "")}
                                                                for s in e["subs"]]})
    return {"kinds": KINDS, "users": out}


def set_prefs(user, prefs):
    with _lock:
        d = load()
        e = user_entry(d, user)
        e["prefs"] = clean_prefs(prefs)
        e["upd"] = datetime.datetime.now().isoformat(timespec="seconds")
        save(d)


def remove_device(user, i):
    with _lock:
        d = load()
        e = user_entry(d, user)
        if 0 <= i < len(e["subs"]):
            e["subs"].pop(i)
            e["upd"] = datetime.datetime.now().isoformat(timespec="seconds")
            save(d)


# ----------------------------------------------------------------- the cloud's share (PC off)
SITE_META = "https://ahmedtarekfahim-bot.github.io/fawaz-tenders-apps/data/meta.json"


def cloud_active():
    """the cloud sent notifications in the last hour -> the PC leaves the data notifications to it"""
    try:
        with urllib.request.urlopen(urllib.request.Request(SITE_META + f"?t={int(time.time())}", headers={"Cache-Control": "no-cache"}), timeout=15) as r:
            at = json.loads(r.read()).get("push_cloud") or ""
        return bool(at) and (datetime.datetime.now() - datetime.datetime.fromisoformat(at)).total_seconds() < 3600
    except Exception:                   # noqa: BLE001 - can't tell: the PC sends (better twice than never)
        return False


def cloud_key():
    """the key push.enc is sealed with (the cloud has it as the secret FAWAZ_PUSH_KEY)"""
    import phone_lock
    return hmac.new(phone_lock.routines_key().encode(), b"cloud-push|v1", hashlib.sha256).hexdigest()


def feed_blob():
    """push.enc for pc-feed: everything the cloud needs to notify, sealed with cloud_push_key"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import accounts, gzip
    d = load()
    users = {u: e for u, e in d["users"].items() if e.get("subs")}
    k, _pub = vapid()
    from cryptography.hazmat.primitives import serialization
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    body = {"vapid": pem, "rules": rules(), "users": users, "at": datetime.datetime.now().isoformat(timespec="seconds"),
            "nk": {u: notify_key(u).hex() for u, du in accounts.load()["users"].items() if accounts.is_live(du)}}
    raw = gzip.compress(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    iv = os.urandom(12)
    return {"iv": base64.b64encode(iv).decode(), "data": base64.b64encode(AESGCM(bytes.fromhex(cloud_key())).encrypt(iv, raw, None)).decode()}


def cloud_open(feed_file, key_hex):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import gzip
    enc = json.loads(Path(feed_file).read_text(encoding="utf-8"))
    raw = AESGCM(bytes.fromhex(key_hex)).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["data"]), None)
    return json.loads(gzip.decompress(raw).decode("utf-8"))


def cloud_run(gd, feed_dir, log=print):
    """on GitHub Actions after the cloud update: merge the PC's phones, read new registrations from the
    phone channel, then notify what is new in the cloud's own data"""
    key = os.environ.get("FAWAZ_PUSH_KEY", "").strip()
    f = Path(feed_dir) / "push.enc"
    if not key or not f.exists():
        log("🔔 إشعارات السحابة: مفيش مفتاح أو push.enc من الكمبيوتر")
        return None
    try:
        pc = cloud_open(f, key)
    except Exception as e:              # noqa: BLE001
        log(f"🔔 إشعارات السحابة: push.enc ما اتفتحش ({e})")
        return None
    os.environ["FAWAZ_VAPID_PEM"] = pc["vapid"]
    with _lock:
        d = load()
        for u, e in pc["users"].items():                 # the newer side wins per account
            mine = d["users"].get(u)
            if not mine or (e.get("upd") or "") >= (mine.get("upd") or ""):
                d["users"][u] = {"subs": e.get("subs") or [], "prefs": e.get("prefs") or default_prefs(), "upd": e.get("upd", "")}
        save(d)
    # registrations made while the PC was off (the phone channel keeps messages about 12 hours)
    try:
        import phone_lock
        topic = json.loads((Path(feed_dir) / "ntfy.json").read_text(encoding="utf-8"))["topic"]
        since = int(load()["mark"].get("ntfy", 0)) or int(time.time()) - 12 * 3600
        with urllib.request.urlopen(f"{phone_lock.NTFY}{topic}/json?poll=1&since={since}", timeout=30) as r:
            msgs = [json.loads(x) for x in r.read().decode("utf-8", "replace").splitlines() if x.strip()]
        pc_on = (datetime.datetime.now() - datetime.datetime.fromisoformat(pc["at"])).total_seconds() < 2400
        last = since
        for m in msgs:
            last = max(last, int(m.get("time", 0)))
            parts = str(m.get("message", "")).split("|")
            if m.get("event") != "message" or len(parts) != 5 or parts[0] != "push":
                continue
            _k, user, arg, ts, sig = parts
            nk = pc["nk"].get(user)
            good = nk and hmac.compare_digest(hmac.new(bytes.fromhex(nk), f"push|{user}|{arg}|{ts}".encode(), hashlib.sha256).hexdigest()[:32], sig)
            if good:
                register(user, arg, log, test_ok=not pc_on)      # the PC answers the test itself when it is on
        with _lock:
            d = load()
            d["mark"]["ntfy"] = last
            save(d)
    except Exception as e:              # noqa: BLE001
        log(f"🔔 قراءة تسجيلات الموبايل: {e}")
    n = after_update(gd, log, cloud=pc["rules"])
    log(f"🔔 إشعارات السحابة: {n}")
    return n
