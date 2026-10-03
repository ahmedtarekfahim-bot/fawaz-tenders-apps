# -*- coding: utf-8 -*-
"""Messages from the phone app to this PC, through a private ntfy.sh topic (polled about once a minute):

  open|<user>     - the user opened the app            -> "last seen" + number of opens in the accounts list
  forgot|<user>   - "forgot my password" on the login  -> the owner: new password mailed to his Gmail;
                                                          anybody else: the owner gets a mail + a mark in
                                                          the accounts list, and resets it from the window
The messages carry only a user name; the worst a stranger can do with the topic is cause a reset mail
to the owner (at most one every 10 minutes per user).
"""
import json, time, secrets, threading, urllib.request, datetime
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


def poll(log=print):
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
