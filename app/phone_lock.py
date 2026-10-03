# -*- coding: utf-8 -*-
"""The phone passphrase (it unlocks the encrypted Fawaz part of the phone app).

- shown in the directory window (tab متابعة فواز و KJAC -> كلمة سر الموبايل), with "send it to my Gmail"
  and "make a new one"
- "forgot the passphrase" on the phone: the phone posts a request to a private ntfy.sh topic; this PC
  (while the directory runs) picks it up within a minute, makes a NEW passphrase, e-mails it to the
  owner's Gmail through the local Outlook and republishes the phone data with it. The request carries
  no data - the worst a stranger can do with the topic name is trigger a reset that mails the owner.
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


def send_mail(pw, why):
    """mail the passphrase to the owner's Gmail through the local Outlook -> '' or the error"""
    try:
        import pythoncom
        import win32com.client.dynamic
    except ImportError as e:
        return f"pywin32: {e}"
    pythoncom.CoInitialize()
    try:
        ol = win32com.client.dynamic.Dispatch("Outlook.Application")
        m = ol.CreateItem(0)
        m.To = owner_email()
        m.Subject = "كلمة سر تطبيق مناقصات فواز على الموبايل"
        m.Body = (f"{why}\n\nكلمة السر: {pw}\n\nاكتبها في تبويب \"فواز و KJAC\" على الموبايل. "
                  f"بعدها تقدر تفعّل الفتح بالبصمة من نفس التبويب.\n\n"
                  f"{datetime.datetime.now():%Y-%m-%d %H:%M} - برنامج دليل مناقصات الخليج")
        m.Send()
        return ""
    except Exception as e:                      # noqa: BLE001
        return str(e)[:200]
    finally:
        pythoncom.CoUninitialize()


def reset(why, log=print):
    """new passphrase -> settings, phone data republished with it, mailed to the owner"""
    import mobile_export as me
    with _lock:
        pw = me.new_passphrase()
        try:
            me.publish(log, force=True)
        except Exception as e:                  # noqa: BLE001
            log(f"نشر نسخة التليفون بعد تغيير كلمة السر: {e}")
        err = send_mail(pw, why)
        log("كلمة سر الموبايل اتغيرت" + (f" - الإيميل ما اتبعتش: {err}" if err else f" واتبعتت على {owner_email()}"))
        return pw, err


def poll(log=print):
    """check the phone's 'forgot the passphrase' requests (called about once a minute)"""
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
    last = float(cfg.S.get("reset_last") or 0)
    if time.time() - last < 600:                # at most one reset every 10 minutes
        log("طلب تغيير كلمة سر الموبايل اتجاهل (اتعمل تغيير من أقل من 10 دقايق)")
        return
    cfg.save_setting("reset_last", time.time())
    reset("طلبت كلمة سر جديدة من الموبايل (نسيت كلمة السر).", log)
