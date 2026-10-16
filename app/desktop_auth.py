# -*- coding: utf-8 -*-
"""Login for the desktop program - the same accounts (user name, password, permissions, countries, end date)
as the phone app, managed from the window (👥 الحسابات).

Where the list comes from:
  - the owner's PC: the master list (<archive>\\متابعة فواز\\phone users.json)
  - any other PC: the list the phone site publishes (data/users.json - user names hashed, private keys sealed
    with each password), cached locally so the program also opens without internet
The password is checked by opening the user's sealed private key with it, exactly like the phone does,
so no password is ever stored or sent anywhere.

A login gives an HttpOnly cookie; the session (hashed) is kept in %LOCALAPPDATA%\\FAWAZ Tenders so it
survives the window closing. Every few minutes the account is checked again: stopped / expired accounts
are logged out and changed permissions apply without a new login.
"""
import json, time, hashlib, secrets, threading, datetime, urllib.request
import fawaz_config as cfg
import accounts

SESS_FILE = cfg.LOCAL / "desktop sessions.json"
CACHE_FILE = cfg.LOCAL / "accounts cache.json"
COOKIE = "gt"
REMEMBER_DAYS = 30
SHORT_HOURS = 12
RECHECK = 300                                       # seconds between account re-checks of a session
_lock = threading.Lock()
_site = {"at": 0, "users": None}
_fails = {}                                         # user -> [count, until]


# ----------------------------------------------------------------- the account list
def master_mode():
    """owner's PC: the master list exists (or this is the PC that publishes the phone site)"""
    return accounts._master_file().exists() or bool(cfg.S.get("mobile_publish"))


def _site_users(force=False):
    """published list {uid: {...}} - from the site at most every RECHECK seconds, else the local copy"""
    if not force and _site["users"] is not None and time.time() - _site["at"] < RECHECK:
        return _site["users"]
    import mobile_export as me
    try:
        req = urllib.request.Request(me.PAGES + f"data/users.json?t={int(time.time())}", headers={"User-Agent": "GCC Tenders"})
        with urllib.request.urlopen(req, timeout=10) as r:
            users = json.loads(r.read().decode("utf-8"))["users"]
        try:
            cfg.LOCAL.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps({"at": datetime.datetime.now().isoformat(timespec="minutes"), "users": users}),
                                  encoding="utf-8")
        except OSError:
            pass
    except Exception:                               # noqa: BLE001 - offline: the last copy we got
        try:
            users = json.loads(CACHE_FILE.read_text(encoding="utf-8"))["users"]
        except (OSError, ValueError, KeyError):
            users = _site["users"]
    _site.update(at=time.time(), users=users)
    return users


def lookup(name):
    """-> (account dict, error) with perms / countries / admin; no password check"""
    u = accounts.norm_name(name)
    if not u:
        return None, "اكتب اسم المستخدم"
    if master_mode():
        if cfg.S.get("mobile_publish"):
            accounts.ensure_owner()
        d = accounts.load()["users"].get(u)
        if not d:
            return None, "اسم المستخدم أو كلمة السر غلط"
        if not d.get("active"):
            return None, "الحساب ده متوقف - كلّم الأدمن"
        if d.get("expires") and d["expires"] < accounts.today():
            return None, f"الاشتراك انتهى يوم {d['expires']} - كلّم الأدمن يجدده"
        return {"u": u, "priv": d["priv"], "perms": accounts.perms_of(d), "rids": [] if d.get("admin") else (d.get("routines") or []),
                "countries": d.get("countries") or list(accounts.COUNTRIES), "expires": d.get("expires", ""),
                "admin": bool(d.get("admin"))}, ""
    users = _site_users()
    if users is None:
        return None, "مفيش اتصال بالنت - أول دخول على الجهاز ده محتاج نت"
    d = users.get(accounts.uid(u))
    if not d:
        return None, "اسم المستخدم أو كلمة السر غلط"
    if d.get("off"):
        return None, "الحساب ده متوقف - كلّم الأدمن"
    if d.get("expired") or (d.get("expires") and d["expires"] < accounts.today()):
        return None, f"الاشتراك انتهى يوم {d.get('expired') or d.get('expires')} - كلّم الأدمن يجدده"
    return {"u": u, "priv": d["priv"], "perms": accounts.perms_of({"perms": d.get("perms")}), "rids": d.get("rids") or [],
            "countries": d.get("countries") or list(accounts.COUNTRIES), "expires": d.get("expires", ""),
            "admin": False}, ""


def password_ok(priv, password):
    """the password opens the user's sealed private key (PBKDF2-SHA256 + AES-GCM, same as the phone)"""
    try:
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), accounts.unb64(priv["salt"]),
                                  int(priv.get("iter") or accounts.ITER), 32)
        accounts._aes(key).decrypt(accounts.unb64(priv["iv"]), accounts.unb64(priv["data"]), None)
        return True
    except Exception:                               # noqa: BLE001 - wrong password (InvalidTag) or bad data
        return False


# ----------------------------------------------------------------- sessions
def _load_sessions():
    try:
        return json.loads(SESS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_sessions(s):
    try:
        cfg.LOCAL.mkdir(parents=True, exist_ok=True)
        tmp = SESS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(s), encoding="utf-8")
        tmp.replace(SESS_FILE)
    except OSError:
        pass


_sessions = _load_sessions()
_h = lambda tok: hashlib.sha256(tok.encode()).hexdigest()


def public(s):
    return {k: s.get(k) for k in ("u", "perms", "countries", "expires", "admin", "rids")} if s else None


def login(name, password, remember=False):
    """-> (token, session, error)"""
    u = accounts.norm_name(name)
    f = _fails.get(u)
    if f and f[1] > time.time():
        return None, None, f"محاولات غلط كتير - استنى {int(f[1] - time.time()) + 1} ثانية"
    acc, err = lookup(u)
    if acc and not password_ok(acc["priv"], password or ""):
        acc, err = None, "اسم المستخدم أو كلمة السر غلط"
    if not acc:
        n = (f[0] if f else 0) + 1
        _fails[u] = [n, time.time() + (30 if n >= 5 else 0)]
        time.sleep(0.6)
        return None, None, err
    _fails.pop(u, None)
    tok = secrets.token_urlsafe(32)
    now = time.time()
    s = {k: acc[k] for k in ("u", "perms", "countries", "expires", "admin", "rids")}
    s.update(remember=bool(remember), until=now + (REMEMBER_DAYS * 86400 if remember else SHORT_HOURS * 3600), checked=now)
    with _lock:
        for k in [k for k, v in _sessions.items() if v.get("until", 0) < now]:
            _sessions.pop(k)
        _sessions[_h(tok)] = s
        _save_sessions(_sessions)
    _note_open(u)
    return tok, s, ""


def logout(tok):
    with _lock:
        if tok and _sessions.pop(_h(tok), None):
            _save_sessions(_sessions)


def session(tok):
    """the logged-in account for this cookie (re-checked every few minutes) or None"""
    if not tok:
        return None
    key = _h(tok)
    s = _sessions.get(key)
    if not s or s.get("until", 0) < time.time():
        return None
    if time.time() - s.get("checked", 0) >= RECHECK:
        try:
            acc, err = lookup(s["u"])
        except Exception:                           # noqa: BLE001 - can't check now: keep it until the next try
            acc, err = s, ""
        with _lock:
            if not acc:
                _sessions.pop(key, None)
                _save_sessions(_sessions)
                return None
            s.update({k: acc[k] for k in ("perms", "countries", "expires", "admin", "rids")}, checked=time.time())
            _save_sessions(_sessions)
    return s


def _ntfy(kind, u):
    """a message to the owner's PC through the phone app's channel (open / forgot)"""
    import mobile_export as me
    with urllib.request.urlopen(me.PAGES + f"data/ntfy.json?t={int(time.time())}", timeout=10) as r:
        topic = json.loads(r.read().decode())["topic"]
    urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/" + topic, data=f"{kind}|{u}".encode(),
                                                  method="POST"), timeout=10).read()


def _note_open(u):
    """'last opened' in the accounts list: written directly on the owner's PC, through the phone channel elsewhere"""
    def job():
        try:
            if master_mode():
                accounts.seen(u, datetime.datetime.now().isoformat(timespec="minutes"))
            else:
                _ntfy("open", u)
        except Exception:                           # noqa: BLE001
            pass
    threading.Thread(target=job, daemon=True).start()


def forgot(name):
    """'نسيت كلمة السر': the owner gets a new password on his Gmail; anyone else -> the owner is told by mail
    and gives a new one from the accounts list (same as the phone)"""
    u = accounts.norm_name(name)
    if not u:
        return "اكتب اسم المستخدم الأول"
    if master_mode():
        import phone_lock
        if u == (cfg.S.get("phone_owner") or "ahmed"):
            _pw, err = phone_lock.reset_owner("طلبت كلمة سر جديدة من برنامج الكمبيوتر (نسيت كلمة السر).")
            return f"الإيميل ما اتبعتش: {err}" if err else f"اتبعتتلك كلمة سر جديدة على {phone_lock.owner_email()}"
        if u in accounts.load()["users"]:
            accounts.seen(u, datetime.datetime.now().isoformat(timespec="minutes"), "forgot")
            phone_lock.send_mail(f"{u} نسي كلمة سر GCC Tenders",
                                 f"المستخدم {u} داس \"نسيت كلمة السر\" في برنامج الكمبيوتر.\n"
                                 "لو موافق: الدليل ← متابعة فواز و KJAC ← 👥 الحسابات ← كلمة سر جديدة، وابعتهاله.")
        return "الأدمن وصله طلبك - هيبعتلك كلمة سر جديدة"
    try:
        _ntfy("forgot", u)
    except Exception:                               # noqa: BLE001
        return "مفيش اتصال بالنت - جرّب تاني"
    return "الأدمن وصله طلبك - هيبعتلك كلمة سر جديدة"


# ----------------------------------------------------------------- permissions
def has(s, need):
    """need: a FEATURES key, 'admin', or 'any:a,b'"""
    if not s:
        return False
    if need == "admin":
        return bool(s.get("admin"))
    if need.startswith("any:"):
        return any(has(s, x) for x in need[4:].split(","))
    p = s.get("perms") or []
    return need in p or (need == "awards" and "watch" in p)   # "ترسيات لينا" in the Fawaz tab uses the awards list


def routine_ok(s, rid):
    return bool(s.get("admin")) or not s.get("rids") or rid in s["rids"]


def country_ok(s, c):
    return not c or c in (s.get("countries") or list(accounts.COUNTRIES))
