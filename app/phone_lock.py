# -*- coding: utf-8 -*-
"""Messages from the phone app to this PC, through a private ntfy.sh topic (polled about once a minute):

  open|<user>     - the user opened the app            -> "last seen" + number of opens in the accounts list
  forgot|<user>   - "forgot my password" on the login  -> the owner: new password mailed to his Gmail;
                                                          anybody else: the owner gets a mail + a mark in
                                                          the accounts list, and resets it from the window
The messages carry only a user name; the worst a stranger can do with the topic is cause a reset mail
to the owner (at most one every 10 minutes per user).

Commands from the routines tab of the phone are signed, so knowing the topic is not enough:
  run|<user>|<routine id>|<unix time>|<sig>             - start a routine on this PC
  send|<user>|<routine id>,<report no>,<email no>|...    - e-mail a report to one of the saved addresses
  summary|<user>|<item id>,<email no>|...                 - make a tender summary and e-mail it
  get|<user>|<routine id>,<report no>|...                 - a report for the phone: sealed with the routines
                                                            key, posted as a short-lived ntfy attachment
sig = HMAC-SHA256(routines key, "kind|user|arg|time") - the key reaches only accounts allowed the routines
(inside their sealed part); the PC checks the account, the time (10 minutes) and never runs one twice.
"""
import hmac, hashlib
import json, time, secrets, threading, urllib.request, datetime
from pathlib import Path
import fawaz_config as cfg

NTFY = "https://ntfy.sh/"
_lock = threading.Lock()


def topic():
    t = cfg.S.get("reset_topic")
    if not t:
        t = "fawaz-phone-" + secrets.token_hex(10)
        cfg.save_setting("reset_topic", t)
    return t


def owner_email():
    return cfg.S.get("reset_email", "ahmedtarekfahim@gmail.com")


def send_mail(subject, body):
    """mail the owner's Gmail through the local Outlook -> '' or the error"""
    try:
        import pythoncom
        import win32com.client.dynamic
    except ImportError as e:
        return f"pywin32: {e}"
    pythoncom.CoInitialize()
    try:
        m = win32com.client.dynamic.Dispatch("Outlook.Application").CreateItem(0)
        m.To, m.Subject = owner_email(), subject
        m.Body = body + f"\n\n{datetime.datetime.now():%Y-%m-%d %H:%M} - برنامج دليل مناقصات الخليج"
        m.Send()
        return ""
    except Exception as e:                      # noqa: BLE001
        return str(e)[:200]
    finally:
        pythoncom.CoUninitialize()


def mail_password(user, pw, why):
    return send_mail("حساب تطبيق مناقصات فواز على الموبايل",
                     f"{why}\n\nاسم المستخدم: {user}\nكلمة السر: {pw}\n\n"
                     "ادخل بيهم في تطبيق الموبايل. بعد أول دخول تقدر تستخدم البصمة بدل كلمة السر.")


def reset_owner(why, log=print):
    """new password for the owner's account -> phone data republished with it, mailed to his Gmail"""
    import accounts, mobile_export as me
    with _lock:
        owner = accounts.ensure_owner()
        pw = accounts.set_password(owner)
        try:
            me.publish(log, force=True)
        except Exception as e:                  # noqa: BLE001
            log(f"نشر نسخة التليفون بعد تغيير كلمة السر: {e}")
        err = mail_password(owner, pw, why)
        log("كلمة سر حسابك على الموبايل اتغيرت" + (f" - الإيميل ما اتبعتش: {err}" if err else f" واتبعتت على {owner_email()}"))
        return pw, err


def routines_key():
    k = cfg.S.get("routines_key")
    if not k:
        k = secrets.token_hex(24)
        cfg.save_setting("routines_key", k)
    return k


_done = set()
NEEDS = {"run": ["routines", "run"], "send": ["routines", "send"], "get": ["routines", "share"], "summary": ["summary", "send"],
         "docs": ["docs"], "pdf": ["pdf"], "sum": ["summary"], "zt": ["zatoona"]}


def upload_file(f, sig, log=print):
    """a file for the phone: sealed with the routines key, posted as a short-lived ntfy attachment named after the request"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os
    raw = Path(f).read_bytes() if not isinstance(f, (bytes, bytearray)) else bytes(f)
    if len(raw) > 14_000_000:
        raise ValueError("الملف أكبر من 14 ميجا - ابعته بالإيميل")
    key = hashlib.sha256((routines_key() + "|file").encode()).digest()
    iv = os.urandom(12)
    req = urllib.request.Request(f"{NTFY}{topic()}-files", data=iv + AESGCM(key).encrypt(iv, raw, None), method="PUT",
                                 headers={"Filename": sig[:16] + ".bin", "Title": "file"})
    urllib.request.urlopen(req, timeout=180).read()


def _phone_job(kind, arg, sig, user, log):
    """documents (zipped) / PDF report / summary / الزتونة for the phone"""
    import gulf_directory as gd
    try:
        if kind == "docs":
            import io, zipfile
            r = gd.download_docs(int(arg))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for n, ok, _x in r["files"]:
                    if ok:
                        z.write(Path(r["folder"]) / n, n)
            upload_file(buf.getvalue(), sig, log)
        elif kind == "pdf":
            upload_file(gd.build_pdf(int(arg)), sig, log)
        elif kind == "sum":
            import tender_summary
            upload_file(tender_summary.summarize(int(arg), log)["path"], sig, log)
        elif kind == "zt":
            import zatoona, base64
            q = base64.urlsafe_b64decode(arg.encode()).decode("utf-8")
            job = zatoona.start(q, user, wait=True)
            upload_file(Path(job["path"]), sig, log)
        log(f"الموبايل ({user}): اتبعتله {kind}")
    except Exception as e:                      # noqa: BLE001
        log(f"طلب الموبايل ({kind}) ما اتنفذش: {e}")
        try:
            upload_file(("خطأ: " + str(e)).encode("utf-8"), sig, log)
        except Exception:                       # noqa: BLE001
            pass


def _command(msg, hooks, log):
    """a signed command from the phone -> True when it was one (handled or refused)"""
    parts = msg.split("|")
    if len(parts) != 5 or parts[0] not in ("run", "send", "summary", "get", "docs", "pdf", "sum", "zt"):
        return False
    kind, user, arg, ts, sig = parts
    import accounts
    good = hmac.new(routines_key().encode(), f"{kind}|{user}|{arg}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]
    d = accounts.load()["users"].get(accounts.norm_name(user))
    if not (hmac.compare_digest(good, sig) and ts.isdigit() and abs(time.time() - int(ts)) < 600 and sig not in _done
            and d and accounts.is_live(d)
            and all(p in accounts.perms_of(d) for p in NEEDS[kind])
            and (kind not in ("run", "send", "get") or accounts.routine_ok(d, arg.split(",")[0]))):
        log(f"طلب من الموبايل اترفض ({kind} - {user})")
        return True
    _done.add(sig)
    import routines
    try:
        if kind == "run":
            log(f"الموبايل ({user}): {routines.run(arg, hooks or {}, f'الموبايل ({user})')}")
        elif kind == "send":
            rid, k, e, *f = arg.split(",")
            lst = routines.listing()
            r = next(x for x in lst["routines"] if x["id"] == rid)
            to = routines.recipients()[int(e)]
            frm = lst["senders"][int(f[0])] if f and f[0] != "" else None
            err = routines.send([r["reports"][int(k)]["path"]], [to], sender_addr=frm)
            log(f"الموبايل ({user}): " + (f"الإرسال ما تمش: {err}" if err else f"اتبعت {r['reports'][int(k)]['name']} على {to}"))
        elif kind in ("docs", "pdf", "sum", "zt"):
            threading.Thread(target=_phone_job, args=(kind, arg, sig, user, log), daemon=True).start()
        elif kind == "get":                      # the phone opens / shares a report: sealed upload, gone in hours
            rid, k = arg.split(",")[:2]
            r = next(x for x in routines.listing()["routines"] if x["id"] == rid)
            f = Path(r["reports"][int(k)]["path"])
            if f.stat().st_size > 14_000_000:
                log(f"الملف {f.name} أكبر من إن الموبايل يفتحه - اتبعت على الإيميل بدل كده")
                return True
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import os
            key = hashlib.sha256((routines_key() + "|file").encode()).digest()
            iv = os.urandom(12)
            data = iv + AESGCM(key).encrypt(iv, f.read_bytes(), None)
            req = urllib.request.Request(f"{NTFY}{topic()}-files", data=data, method="PUT",
                                         headers={"Filename": sig[:16] + ".bin", "Title": "file"})
            urllib.request.urlopen(req, timeout=120).read()
            log(f"الموبايل ({user}) فتح {f.name}")
        elif kind == "summary":
            iid, e, *f = arg.split(",")
            to = routines.recipients()[int(e)]
            frm = routines.senders()[int(f[0])] if f and f[0] != "" else None

            def job():
                import tender_summary
                res = tender_summary.summarize(int(iid), log)
                err = routines.send([res["path"]], [to], f"ملخص المناقصة - {Path(res['folder']).name[:120]}", sender_addr=frm)
                log(f"ملخص من الموبايل ({user}): " + (f"الإرسال ما تمش: {err}" if err else f"اتبعت على {to}"))
            threading.Thread(target=job, daemon=True).start()
    except Exception as e:                      # noqa: BLE001
        log(f"طلب الموبايل ({kind}) ما اتنفذش: {e}")
    return True


def poll(log=print, hooks=None):
    since = int(cfg.S.get("reset_since") or time.time() - 600)
    try:
        with urllib.request.urlopen(f"{NTFY}{topic()}/json?poll=1&since={since}", timeout=20) as r:
            lines = r.read().decode("utf-8", "replace").splitlines()
    except Exception:                           # noqa: BLE001 - offline
        return
    msgs = [json.loads(x) for x in lines if x.strip()]
    msgs = [m for m in msgs if m.get("event") == "message" and int(m.get("time", 0)) > since]
    if not msgs:
        return
    cfg.save_setting("reset_since", max(int(m["time"]) for m in msgs))
    import accounts
    owner = accounts.ensure_owner()
    for m in msgs:
        if _command(str(m.get("message", "")), hooks, log):
            continue
        kind, _, user = str(m.get("message", "")).partition("|")
        user = accounts.norm_name(user) or owner
        when = datetime.datetime.fromtimestamp(int(m["time"])).isoformat(timespec="minutes")
        if kind == "open":
            accounts.seen(user, when)
        elif kind in ("forgot", "reset"):
            last = float(cfg.S.get(f"forgot_last_{user}") or 0)
            if time.time() - last < 600:
                continue
            cfg.save_setting(f"forgot_last_{user}", time.time())
            if user == owner:
                reset_owner("طلبت كلمة سر جديدة من الموبايل (نسيت كلمة السر).", log)
            elif user in accounts.load()["users"]:
                accounts.seen(user, when, "forgot")
                send_mail(f"{user} نسي كلمة سر تطبيق الموبايل",
                          f"المستخدم {user} داس \"نسيت كلمة السر\" على الموبايل.\n"
                          "لو موافق: افتح دليل مناقصات الخليج ← متابعة فواز و KJAC ← 👥 حسابات الموبايل ← كلمة سر جديدة، وابعتهاله.")
                log(f"{user} طلب كلمة سر جديدة - مستني موافقتك من حسابات الموبايل")
