# -*- coding: utf-8 -*-
"""Tender documents: find them on the official sites and download them.

  - CAPT (capt.gov.kw): the files of a tender ("كراسة الشروط", addenda ...) are only shown to a logged-in
    company account. The owner types his CAPT e-mail / password once in the directory window; the
    password is kept encrypted with Windows DPAPI (only this Windows user on this PC can read it).
  - PAHW: the files are public - collected with every update (gulf_directory.collect_pahw).
  - Etimad / Dubai eSupply: booklets are bought / need a supplier login - only the official page.
Downloads go to <directory>\\مستندات المناقصات\\<number - subject>\\.
"""
import re, json, html, base64, datetime, urllib.request, urllib.parse, http.cookiejar
from pathlib import Path
import fawaz_config as cfg

SITE = "https://capt.gov.kw"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "ar,en;q=0.9"}
_S = {"opener": None, "at": None}


# ----------------------------------------------------------------- the CAPT account (DPAPI-protected)
def _protect(s):
    import win32crypt
    return base64.b64encode(win32crypt.CryptProtectData(s.encode("utf-8"), "capt", None, None, None, 0)).decode()


def _unprotect(b):
    import win32crypt
    return win32crypt.CryptUnprotectData(base64.b64decode(b), None, None, None, 0)[1].decode("utf-8")


def set_account(user, password):
    cfg.save_setting("capt_user", (user or "").strip())
    cfg.save_setting("capt_pass", _protect(password) if password else "")
    _S.update(opener=None, at=None)


def account():
    """-> (user, has password)"""
    return cfg.S.get("capt_user", ""), bool(cfg.S.get("capt_pass"))


def login(force=False):
    """a logged-in CAPT session (kept ~25 minutes) -> opener, or raises with the reason"""
    if _S["opener"] and not force and (datetime.datetime.now() - _S["at"]).seconds < 1500:
        return _S["opener"]
    user, has = account()
    if not user or not has:
        raise PermissionError("حساب الجهاز المركزي مش متسجّل في البرنامج")
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    h = op.open(urllib.request.Request(SITE + "/ar/tenders/opening-tenders/", headers=UA), timeout=60).read().decode("utf-8", "replace")
    tok = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', h)
    csrf = next((c.value for c in jar if c.name == "csrftoken"), tok.group(1) if tok else "")
    data = urllib.parse.urlencode({"csrfmiddlewaretoken": tok.group(1) if tok else csrf, "username": user,
                                   "password": _unprotect(cfg.S["capt_pass"])}).encode()
    req = urllib.request.Request(SITE + "/ar/account/login/", data=data, headers=dict(
        UA, **{"Accept": "application/json", "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest",
               "Referer": SITE + "/ar/tenders/opening-tenders/", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}))
    try:
        body = op.open(req, timeout=60).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        msg = re.sub(r"<[^>]+>", " ", body)[:200]
        raise PermissionError(f"الدخول على الجهاز المركزي رفض ({e.code}): {msg.strip()}")
    if not any(c.name == "sessionid" for c in jar):
        raise PermissionError("الدخول على الجهاز المركزي ما نجحش - راجع الإيميل وكلمة السر: " + body[:150])
    _S.update(opener=op, at=datetime.datetime.now())
    return op


def test_login():
    try:
        login(force=True)
        return {"ok": True, "msg": "اتدخل على الجهاز المركزي بنجاح"}
    except Exception as e:                       # noqa: BLE001
        return {"ok": False, "msg": str(e)}


# ----------------------------------------------------------------- finding the files
def _cards(h):
    for blk in h.split('class="content-box green tender-info"')[1:]:
        blk = blk.split('class="content-box grey"')[0]
        no = re.search(r"<li>\s*الرقم\s*</li>\s*<li[^>]*>(.*?)</li>", blk, re.S)
        yield (re.sub(r"<[^>]+>|\s+", " ", no.group(1)).strip() if no else ""), blk


def _files(blk):
    out = []
    m0 = re.search(r'<li[^>]*class="file-list"[^>]*>(.*?)</li>', blk, re.S)
    seg = m0.group(1) if m0 else ""
    for m in re.finditer(r"<a([^>]*)>(.*?)</a>\s*(?:<span[^>]*file-upload-date[^>]*>([^<]*)</span>)?", seg, re.S):
        attrs, label, date = m.group(1), re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip(), (m.group(3) or "").strip()
        href = re.search(r'href="([^"]+)"', attrs)
        url = html.unescape(href.group(1)) if href else ""
        if url.startswith("/"):
            url = SITE + url
        out.append({"label": html.unescape(label) or "ملف", "url": url if url.startswith("http") else "", "date": date,
                    "locked": not url.startswith("http")})
    return out


def capt_docs(number, ministry_code=""):
    """files of one CAPT tender -> {"docs": [...], "login": True/False, "error": ""}"""
    q = {"tender_no": number}
    if ministry_code:
        q = {"ministry_code": ministry_code, "tender_no": number}
    url = SITE + "/ar/tenders/opening-tenders/?" + urllib.parse.urlencode(q)
    err, logged = "", False
    try:
        op = login()
        logged = True
    except PermissionError as e:
        op, err = urllib.request.build_opener(), str(e)
    h = op.open(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")
    want = "".join(re.findall(r"\d+", number))
    docs = []
    for no, blk in _cards(h):
        if "".join(re.findall(r"\d+", no)) == want or not want:
            docs += _files(blk)
    return {"docs": docs, "login": logged, "error": err, "page": url}


# ----------------------------------------------------------------- downloading
def safe(s, n=70):
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s or "").strip()[:n].strip() or "مناقصة"


def download(item, docs, out_root):
    """save every downloadable doc of an item into its own folder -> (folder, [(name, ok, note)])"""
    folder = Path(out_root) / safe(f"{item.get('number') or ''} - {item.get('subject') or ''}", 90)
    folder.mkdir(parents=True, exist_ok=True)
    res = []
    op = None
    for k, d in enumerate(docs, 1):
        if not d.get("url"):
            res.append((d.get("label", "ملف"), False, "محتاج دخول / شراء"))
            continue
        if op is None:
            try:
                op = login() if "capt.gov.kw" in d["url"] else urllib.request.build_opener()
            except PermissionError:
                op = urllib.request.build_opener()
        try:
            with op.open(urllib.request.Request(d["url"], headers=UA), timeout=180) as r:
                data = r.read()
                cd = r.headers.get("Content-Disposition", "")
            ext = Path(urllib.parse.urlparse(d["url"]).path).suffix or ".pdf"
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
            if m:
                ext = Path(urllib.parse.unquote(m.group(1))).suffix or ext
            name = safe(f"{k:02d} - {d.get('label', 'ملف')}", 80) + ext
            (folder / name).write_bytes(data)
            res.append((name, True, f"{len(data) // 1024} KB"))
        except Exception as e:                   # noqa: BLE001
            res.append((d.get("label", "ملف"), False, str(e)[:120]))
    return folder, res
