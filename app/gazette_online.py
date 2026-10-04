# -*- coding: utf-8 -*-
"""Kuwait Al-Youm online (kuwaitalyawm.media.gov.kw) with the owner's subscription.

The owner types the subscription user / password once in the directory window (Fawaz tab); the password
is kept with Windows DPAPI (tender_docs). With it the program signs in by itself, finds the current
issue and saves its PDF into the gazette folder - then the directory indexes it and the Fawaz watch
searches it, with nobody downloading anything by hand.
"""
import re, html, datetime, urllib.request, urllib.parse, http.cookiejar
from pathlib import Path
import fawaz_config as cfg

SITE = "https://kuwaitalyawm.media.gov.kw"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "ar,en;q=0.9"}
_S = {"op": None, "at": None}


def set_account(user, password):
    import tender_docs as td
    cfg.save_setting("gz_user", (user or "").strip())
    cfg.save_setting("gz_pass", td._protect(password) if password else "")
    _S.update(op=None, at=None)


def account():
    return cfg.S.get("gz_user", ""), bool(cfg.S.get("gz_pass"))


def login(force=False):
    import tender_docs as td
    if _S["op"] and not force and (datetime.datetime.now() - _S["at"]).seconds < 1200:
        return _S["op"]
    user, has = account()
    if not user or not has:
        raise PermissionError("اشتراك الكويت اليوم مش متسجّل في البرنامج")
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    h = op.open(urllib.request.Request(SITE + "/online/MainEditions", headers=UA), timeout=60).read().decode("utf-8", "replace")
    i = h.find('action="/Account/LoginOnline"')
    tok = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', h[i:] if i > 0 else h)
    data = urllib.parse.urlencode({"__RequestVerificationToken": tok.group(1) if tok else "", "UserName": user,
                                   "Password": td._unprotect(cfg.S["gz_pass"]), "RememberMe": "false"}).encode()
    r = op.open(urllib.request.Request(SITE + "/Account/LoginOnline", data=data, headers=dict(
        UA, **{"Content-Type": "application/x-www-form-urlencoded", "Referer": SITE + "/online/MainEditions"})), timeout=60)
    body = r.read().decode("utf-8", "replace")
    names = {c.name.lower() for c in jar}
    if "UserName" in body and 'action="/Account/LoginOnline"' in body and not any("auth" in n or "identity" in n for n in names):
        err = re.search(r'validation-summary-errors[^>]*>(.*?)</div>', body, re.S)
        raise PermissionError("الدخول على الكويت اليوم ما نجحش" + (": " + re.sub(r"<[^>]+>|\s+", " ", err.group(1)).strip() if err else
                                                                     " - راجع اسم المستخدم وكلمة السر"))
    _S.update(op=op, at=datetime.datetime.now())
    return op


def test_login():
    try:
        login(force=True)
        return {"ok": True, "msg": "اتدخل على الكويت اليوم بنجاح"}
    except Exception as e:                       # noqa: BLE001
        return {"ok": False, "msg": str(e)}


def _links(h):
    out = []
    for href, label in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', h, re.S):
        t = re.sub(r"<[^>]+>|\s+", " ", html.unescape(label)).strip()
        out.append((html.unescape(href), t))
    return out


def explore():
    """after login: the links of the edition pages (to find how the issue is offered)"""
    try:
        op = login(force=True)
    except Exception as e:                       # noqa: BLE001
        return {"ok": False, "msg": str(e)}
    pages = {}
    for path in ("/online/MainEditions", "/online/editions", "/Online"):
        try:
            with op.open(urllib.request.Request(SITE + path, headers=UA), timeout=60) as r:
                h = r.read().decode("utf-8", "replace")
            pages[path] = [(u, t) for u, t in _links(h) if not u.startswith(("/assets", "/Content", "http://www", "https://www"))][:120]
            pages[path + " #pdf"] = sorted(set(re.findall(r'["\'](/[^"\']*(?:pdf|Pdf|PDF|Download|download|File|file)[^"\']*)["\']', h)))[:40]
        except Exception as e:                   # noqa: BLE001
            pages[path] = [("error", str(e)[:120])]
    return {"ok": True, "pages": pages}


def fetch_issue_pdf(issue, dest_dir):
    """save the current issue's PDF as <dest>/<issue>.pdf -> path, or raises with what was found"""
    op = login()
    h = op.open(urllib.request.Request(SITE + "/online/MainEditions", headers=UA), timeout=60).read().decode("utf-8", "replace")
    cands = [u for u in re.findall(r'["\'](/[^"\']*(?:\.pdf|Pdf|PDF|Download|download)[^"\']*)["\']', h)]
    cands += [u for u, t in _links(h) if re.search(r"تحميل|PDF|العدد|الإصدار", t)]
    tried = []
    for u in dict.fromkeys(cands):
        url = u if u.startswith("http") else SITE + u
        try:
            with op.open(urllib.request.Request(url, headers=UA), timeout=300) as r:
                data = r.read()
            if data[:4] == b"%PDF" and len(data) > 1_000_000:
                dst = Path(dest_dir) / f"{issue}.pdf"
                dst.write_bytes(data)
                return dst
            tried.append(url)
        except Exception:                        # noqa: BLE001
            tried.append(url)
    raise FileNotFoundError(f"ملقيتش ملف العدد بعد الدخول (جربت {len(tried)} لينك)")
