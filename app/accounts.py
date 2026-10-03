# -*- coding: utf-8 -*-
"""Phone app accounts - only people the owner adds can open the phone app.

Every phone data file is encrypted (AES-GCM, gzip inside) with a fresh content key on every publish.
That content key is wrapped (RSA-OAEP-SHA256) for each ACTIVE user's public key -> data/keys.json.
Each user's private key sits in data/users.json encrypted with his password (PBKDF2-SHA256 + AES-GCM),
so the phone logs in with user name + password, unwraps its key and decrypts. Deactivating a user drops
him from keys.json: from the next publish on he cannot open anything (the app wipes its copy).
The Fawaz-confidential part (private.enc) has its own content key, wrapped only for users allowed to see it.

The master list (with the "active / Fawaz / last seen" flags) lives on the owner's PC:
  <archive>\\متابعة فواز\\phone users.json      - managed from the directory window (حسابات الموبايل)
The cloud job only receives the public part (users.json) through the PC feed, enough to encrypt for
the active users - it never sees a password or a private key.
"""
import os, json, base64, gzip, secrets, datetime, hashlib
from pathlib import Path

ITER = 200_000
# what an account may use - every part of the phone data is sealed with its own key, so a user only
# receives the keys of the parts he is allowed (and nothing once his subscription ends)
FEATURES = {"dir": "الدليل", "news": "الأخبار", "awards": "ترسيات الكويت", "watch": "متابعة فواز و KJAC",
            "fawaz": "بيانات فواز السرية"}
COUNTRIES = {"KW": "الكويت", "SA": "السعودية", "AE": "الإمارات"}
DEFAULT_PERMS = ["dir", "news", "awards", "watch"]
b64 = lambda x: base64.b64encode(x).decode()
unb64 = base64.b64decode


def _master_file():
    import fawaz_config as cfg
    return cfg.ARCHIVE / "متابعة فواز" / "phone users.json"


# ----------------------------------------------------------------- crypto helpers
def _aes(key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def seal_bytes(raw, key):
    iv = os.urandom(12)
    return {"iv": b64(iv), "data": b64(_aes(key).encrypt(iv, gzip.compress(raw), None))}


def wrap_for(pub_b64, key):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    pub = serialization.load_der_public_key(unb64(pub_b64))
    return b64(pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)))


def new_keypair(password):
    """-> (public key DER b64, private key PKCS8 encrypted with the password)"""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    pk8 = k.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER, 32)
    return b64(pub), {"salt": b64(salt), "iv": b64(iv), "iter": ITER, "data": b64(_aes(key).encrypt(iv, pk8, None))}


def new_password():
    abc = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(abc) for _ in range(4)) for _ in range(3))


# ----------------------------------------------------------------- master list (owner's PC)
def load():
    f = _master_file()
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"users": {}}


def save(m):
    f = _master_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def uid(u):
    """what the phone site shows instead of the user name (the list of names stays private)"""
    return hashlib.sha256(("fawaz:" + norm_name(u)).encode()).hexdigest()[:20]


def today():
    return datetime.date.today().isoformat()


def is_live(d):
    return bool(d.get("active")) and (not d.get("expires") or d["expires"] >= today())


def perms_of(d):
    p = list(d.get("perms") or DEFAULT_PERMS)
    if d.get("fawaz") and "fawaz" not in p:
        p.append("fawaz")
    return p


def norm_name(u):
    return "".join(ch for ch in str(u or "").strip().lower() if ch.isalnum() or ch in "._-")


def ensure_owner():
    """the owner's own account (admin, sees the Fawaz part) - created once; its password is kept in
    settings.json so the window can always show it"""
    import fawaz_config as cfg
    m = load()
    owner = cfg.S.get("phone_owner") or "ahmed"
    if owner not in m["users"]:
        pw = new_password()
        add_user(owner, pw, admin=True, note="صاحب البرنامج", perms=list(FEATURES))
        cfg.save_setting("phone_owner", owner)
        cfg.save_setting("phone_owner_password", pw)
    return owner


def add_user(name, password=None, fawaz=False, admin=False, note="", perms=None, countries=None, expires=""):
    u = norm_name(name)
    if not u:
        raise ValueError("اسم المستخدم فاضي - استخدم حروف إنجليزي وأرقام")
    m = load()
    if u in m["users"]:
        raise ValueError(f"المستخدم {u} موجود")
    pw = password or new_password()
    pub, priv = new_keypair(pw)
    perms = [x for x in (perms or DEFAULT_PERMS) if x in FEATURES]
    if fawaz and "fawaz" not in perms:
        perms.append("fawaz")
    m["users"][u] = {"active": True, "fawaz": "fawaz" in perms, "admin": bool(admin), "note": note,
                     "perms": perms, "countries": [c for c in (countries or list(COUNTRIES)) if c in COUNTRIES],
                     "expires": expires or "",
                     "created": datetime.datetime.now().isoformat(timespec="minutes"),
                     "pub": pub, "priv": priv, "last_seen": "", "opens": 0, "forgot": ""}
    save(m)
    return u, pw


def set_password(name, password=None):
    """new password = new key pair (the old one stops working at the next publish)"""
    import fawaz_config as cfg
    m = load()
    u = norm_name(name)
    pw = password or new_password()
    m["users"][u]["pub"], m["users"][u]["priv"] = new_keypair(pw)
    m["users"][u]["forgot"] = ""
    save(m)
    if u == cfg.S.get("phone_owner"):
        cfg.save_setting("phone_owner_password", pw)
    return pw


def update(name, **flags):
    m = load()
    u = norm_name(name)
    d = m["users"][u]
    for k in ("active", "note", "expires"):
        if k in flags:
            d[k] = flags[k]
    if "perms" in flags:
        d["perms"] = [x for x in flags["perms"] if x in FEATURES]
    if "countries" in flags:
        d["countries"] = [c for c in flags["countries"] if c in COUNTRIES] or ["KW"]
    if "fawaz" in flags:                             # the old single switch
        d["perms"] = [x for x in perms_of(d) if x != "fawaz"] + (["fawaz"] if flags["fawaz"] else [])
    d["fawaz"] = "fawaz" in perms_of(d)
    save(m)


def delete(name):
    import fawaz_config as cfg
    u = norm_name(name)
    if u == cfg.S.get("phone_owner"):
        raise ValueError("ده حسابك - مينفعش يتمسح")
    m = load()
    m["users"].pop(u, None)
    save(m)


def seen(name, when, what="open"):
    m = load()
    u = norm_name(name)
    if u in m["users"]:
        if what == "open":
            m["users"][u]["last_seen"] = max(m["users"][u].get("last_seen") or "", when)
            m["users"][u]["opens"] = int(m["users"][u].get("opens") or 0) + 1
        elif what == "forgot":
            m["users"][u]["forgot"] = when
        save(m)


def listing():
    """for the window - no keys"""
    return [{"u": u, **{k: v for k, v in d.items() if k not in ("pub", "priv")}, "perms": perms_of(d),
             "countries": d.get("countries") or list(COUNTRIES), "expires": d.get("expires", ""), "live": is_live(d)}
            for u, d in sorted(load()["users"].items())]


def public_users():
    """what goes to the phone (and the cloud): login material for active users, nothing for the others"""
    out = {}
    for u, d in load()["users"].items():
        out[u] = {"active": bool(d["active"]), "expires": d.get("expires", ""), "perms": perms_of(d),
                  "countries": d.get("countries") or list(COUNTRIES), "fawaz": "fawaz" in perms_of(d)}
        if d["active"]:
            out[u].update(pub=d["pub"], priv=d["priv"])
    return {"v": 2, "users": out}


# ----------------------------------------------------------------- sealing a phone site folder
PLAIN_KEEP = {"users.json", "keys.json", "ntfy.json", "meta.json"}


def seal_private(raw, users_pub):
    """(PC) the Fawaz-confidential bundle -> (encrypted file, {user: wrapped key}) for allowed live users"""
    fk = os.urandom(32)
    users = users_pub.get("users", {})
    return seal_bytes(raw, fk), {u: wrap_for(d["pub"], fk) for u, d in users.items()
                                 if is_live(d) and "fawaz" in perms_of(d) and d.get("pub")}


def _parts(data_dir):
    """split the phone data into separately sealed parts -> {part: (json bytes, needed permission, country)}"""
    def load_j(n):
        f = data_dir / n
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    parts = {}
    dirs = load_j("directory.json") or []
    for c in COUNTRIES:
        parts[f"directory_{c}"] = ([r for r in dirs if r.get("c") == c], "dir", c)
    news = load_j("news.json") or []
    for c in COUNTRIES:
        parts[f"news_{c}"] = ([n for n in news if n.get("c") == c and not n.get("co")], "news", c)
    parts["news_co"] = ([n for n in news if n.get("co")], "watch", None)
    parts["awards"] = (load_j("awards.json") or [], "awards", None)
    parts["meetings"] = (load_j("meetings.json") or {}, "awards", None)
    for n in ("directory.json", "news.json", "awards.json", "meetings.json"):
        (data_dir / n).unlink(missing_ok=True)
    return {k: (json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode(), need, c)
            for k, (v, need, c) in parts.items()}


def allowed(d, need, country):
    p = perms_of(d)
    if need == "awards" and "watch" in p:            # "ترسيات لينا" in the Fawaz tab uses the awards list
        return True
    return need in p and (country is None or country in (d.get("countries") or list(COUNTRIES)))


def seal_dir(data_dir, users_pub, fawaz_keys=None):
    """encrypt the phone data part by part; every live user gets the keys of the parts he may open.
    Users are published under uid() - not by name. Expired / stopped users get no keys at all."""
    data_dir = Path(data_dir)
    users = users_pub.get("users", {})
    live = {u: d for u, d in users.items() if is_live(d) and d.get("pub")}
    keys = {uid(u): {} for u in live}
    for name, (raw, need, country) in _parts(data_dir).items():
        k = os.urandom(32)
        (data_dir / f"{name}.enc").write_text(json.dumps(seal_bytes(raw, k)), encoding="utf-8")
        for u, d in live.items():
            if allowed(d, need, country):
                keys[uid(u)][name] = wrap_for(d["pub"], k)
    for u, w in (fawaz_keys or {}).items():
        if u in live and "fawaz" in perms_of(live[u]):
            keys[uid(u)]["private"] = w
    (data_dir / "keys.json").write_text(json.dumps({"v": 2, "keys": keys}), encoding="utf-8")
    pub = {}
    for u, d in users.items():
        if u in live:
            pub[uid(u)] = {"priv": d["priv"], "perms": perms_of(d), "countries": d.get("countries") or list(COUNTRIES),
                           "expires": d.get("expires", "")}
        elif d.get("active") and d.get("expires"):
            pub[uid(u)] = {"expired": d["expires"]}
        else:
            pub[uid(u)] = {"off": 1}
    (data_dir / "users.json").write_text(json.dumps({"v": 2, "users": pub}), encoding="utf-8")
    (data_dir / "fkeys.json").unlink(missing_ok=True)
    return len(live)
