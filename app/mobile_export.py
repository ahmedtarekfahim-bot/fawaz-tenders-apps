# -*- coding: utf-8 -*-
"""Phone app data.

The phone app (GitHub Pages, branch gh-pages) is published by a cloud job (GitHub Actions, see
.github/workflows/phone-data.yml + cloud/run_cloud.py) that collects the public sources by itself
every 15 minutes - the phone stays fresh with this PC switched off.

This PC adds what only it has, on the branch pc-feed:
  - the public part of its directory (gazette reports etc.) - Adham's report codes, notes and local
    paths are left out
  - private.enc: our own tenders, Sanjay's e-mails and the Fawaz / KJAC follow-up, encrypted with
    AES-GCM (key = PBKDF2 of the phone passphrase in settings.json); the phone asks for it once
If the cloud copy is more than an hour old this PC also publishes gh-pages itself (fallback).
Each publish force-pushes one fresh commit, so the repo does not grow with every update.
"""
import json, shutil, subprocess, datetime, re, os, stat, base64, gzip, hashlib, secrets, time, urllib.request
from pathlib import Path
import fawaz_config as cfg

INTERNAL_SOURCES = {"تقرير مشاريع"}
SITE = cfg.GULF_DIR / "mobile site"
FEED = cfg.GULF_DIR / "mobile feed"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PAGES = "https://ahmedtarekfahim-bot.github.io/fawaz-tenders-apps/"
_last_feed = {}


def repo_url():
    m = re.search(r"githubusercontent\.com/([^/]+)/([^/]+)/", cfg.build_info().get("update_url") or "")
    if not m:
        try:
            c = json.loads((Path(__file__).resolve().parent.parent / "build_config.json").read_text(encoding="utf-8"))
            if c.get("github_owner"):
                return f"https://github.com/{c['github_owner']}/{c['repo']}.git"
        except (OSError, ValueError):
            pass
        return ""
    return f"https://github.com/{m.group(1)}/{m.group(2)}.git"


def export(out_dir, award_rows=None, meetings=None):
    import gulf_directory as gd
    import capt_tool as ct
    data = Path(out_dir) / "data"
    data.mkdir(parents=True, exist_ok=True)
    con = gd.db()
    items = []
    for r in con.execute("SELECT * FROM items"):
        srcs = set((r["notes"] or "").split("المصادر: ")[-1].split("، ")) if "المصادر: " in (r["notes"] or "") else set()
        if srcs and srcs <= INTERNAL_SOURCES:
            continue                                   # known only from the internal report
        off = r["official"] or ""
        ev = [[e["date"], e["source"], e["etype"], e["text"], e["url"] if (e["url"] or "").startswith("http") else ""]
              for e in con.execute("SELECT date, source, etype, text, url FROM events WHERE item_id=? ORDER BY date DESC", (r["id"],))
              if e["source"] not in INTERNAL_SOURCES]
        chg = [[c["at"][:16], c["field"], c["old"], c["new"]]
               for c in con.execute("SELECT at, field, old, new FROM changes WHERE item_id=? ORDER BY at DESC", (r["id"],))]
        items.append({"i": r["id"], "c": r["country"], "k": r["kind"], "n": r["number"], "o": r["org"], "s": r["subject"],
                      "st": r["status"], "p": r["publish"], "cl": r["closing"], "f": r["fees"], "b": r["bond"],
                      "t": r["ttype"], "v": r["value"], "w": r["winner"], "a": r["award_date"], "cat": r["cats"],
                      "fz": r["fawaz"], "off": off if off.startswith("http") else "",
                      "ol": r["official_label"] if off.startswith("http") else "",
                      "fs": "" if (r["first_seen"] or "").startswith("2000") else (r["first_seen"] or "")[:16],
                      "ch": (r["changed"] or "")[:16], "ev": ev, "chg": chg})
    news = [{"c": n["country"], "d": n["date"], "src": n["source"], "t": n["title"], "u": n["url"], "cat": n["cats"],
             "fz": n["fawaz"], "fs": (n["seen_at"] or "")[:16], "co": int((n["query"] or "").startswith("شركة:"))}
            for n in con.execute("SELECT * FROM news WHERE query<>'تقرير مشاريع' ORDER BY date DESC")]
    con.close()
    rows = award_rows if award_rows is not None else ct.read_excel_rows()
    awards = [{"r": a["row"], "n": a["tno"], "s": a["subject"], "o": a["org"], "w": a["winner"], "d": a["date"],
               "v": a["total"], "x": (a["notes"] or "")[:200]} for a in rows]
    meets = meetings if meetings is not None else ct.load_meetings()
    meetings = {v["date"]: {"no": k, "url": v["url"]} for k, v in meets.items() if v.get("url")}
    meta = {"updated": datetime.datetime.now().isoformat(timespec="minutes"), "items": len(items), "news": len(news),
            "awards": len(awards), "version": cfg.build_info().get("version"), "by": "pc"}
    for name, obj in (("directory", items), ("news", news), ("awards", awards), ("meetings", meetings), ("meta", meta)):
        (data / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return meta


# ----------------------------------------------------------------- private part (encrypted)
def passphrase():
    """the phone passphrase - created once, kept in settings.json on this PC"""
    p = cfg.S.get("mobile_passphrase")
    if not p:
        abc = "abcdefghjkmnpqrstuvwxyz23456789"
        p = "-".join("".join(secrets.choice(abc) for _ in range(4)) for _ in range(3))
        cfg.save_setting("mobile_passphrase", p)
    return p


def encrypt(obj, pw):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000, 32)
    raw = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())
    ct = AESGCM(key).encrypt(iv, raw, None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": 200_000, "salt": b(salt), "iv": b(iv), "data": b(ct)}


def private_bundle():
    import fawaz_watch as fw
    d = fw.data(limit_feed=600)
    return {"updated": datetime.datetime.now().isoformat(timespec="minutes"),
            "feed": [[f["id"], f["at"][:16], f["kind"], f["title"], f["text"], f["url"], f["tender_key"]] for f in d["feed"]],
            "tenders": [{"k": t["key"], "src": t["src"], "t": t["title"], "c": t["client"], "n": t["number"], "nk": t["numkey"],
                         "cl": t["closing"], "st": t["status"], "rm": t["remarks"], "lv": t["live"], "rk": t["fawaz_rank"],
                         "b": t["bidders"], "ln": [[l["kind"], l["title"], l["url"]] for l in t["links"]]} for t in d["tenders"]],
            "emails": [{"d": e["received"], "f": e["sender"], "s": e["subject"], "b": e["body"][:1800],
                        "a": Path(e["attachment"]).name if e["attachment"] else ""} for e in d["emails"]]}


# ----------------------------------------------------------------- publishing
def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NOWIN)


def _rmtree(p):
    def unlock(func, path, _exc):                      # git marks its objects read-only on Windows
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if p.exists():
        shutil.rmtree(p, onerror=unlock)


def push_dir(folder, branch, url, msg, log):
    for cmd in (["init", "-q", "-b", branch], ["add", "-A"],
                ["-c", "user.name=FAWAZ Tenders", "-c", "user.email=ahmedtarekfahim@gmail.com", "commit", "-q", "-m", msg],
                ["push", "-q", "-f", url, branch]):
        r = git(*cmd, cwd=folder)
        if r.returncode != 0:
            log(f"نشر {branch} فشل: {(r.stderr or r.stdout)[-300:]}")
            return False
    return True


def cloud_age_minutes():
    """how old the phone data on GitHub Pages is (1e9 = unknown)"""
    try:
        with urllib.request.urlopen(urllib.request.Request(PAGES + f"data/meta.json?t={int(time.time())}",
                                                           headers={"Cache-Control": "no-cache"}), timeout=20) as r:
            m = json.loads(r.read())
        return (datetime.datetime.now() - datetime.datetime.fromisoformat(m["updated"])).total_seconds() / 60
    except Exception:                                   # noqa: BLE001
        return 1e9


def publish(log=print):
    if not cfg.S.get("mobile_publish") or not shutil.which("git"):
        return None
    url = repo_url()
    if not url:
        return None
    # 1) pc-feed: our public extras + the encrypted private part, for the cloud job
    _rmtree(FEED)
    meta = export(FEED)
    try:
        (FEED / "data" / "private.enc").write_text(json.dumps(encrypt(private_bundle(), passphrase())), encoding="utf-8")
    except Exception as e:                              # noqa: BLE001
        log(f"بيانات فواز المشفرة: {e}")
    sig = hashlib.sha256(b"".join((FEED / "data" / n).read_bytes() for n in ("directory.json", "news.json", "awards.json"))
                         ).hexdigest()
    # the private file changes every time (new salt) - push when the data changed or every 30 minutes
    if sig != _last_feed.get("sig") or time.time() - _last_feed.get("at", 0) > 1800:
        if push_dir(FEED, "pc-feed", url, f"pc feed {meta['updated']}", log):
            _last_feed.update(sig=sig, at=time.time())
    # 2) fallback: cloud copy stale -> publish the phone site from here too
    if cloud_age_minutes() > 60:
        _rmtree(SITE)
        shutil.copytree(cfg.res_dir() / "mobile", SITE)
        shutil.copytree(FEED / "data", SITE / "data", dirs_exist_ok=True)
        (SITE / ".nojekyll").write_text("", encoding="utf-8")
        if push_dir(SITE, "gh-pages", url, f"data {meta['updated']} (pc)", log):
            log(f"نسخة التليفون اتحدثت من الكمبيوتر ({meta['items']} مناقصة)")
    else:
        log("نسخة التليفون بتتحدث من السحابة - الكمبيوتر بعت إضافاته بس")
    return meta


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        print(export(sys.argv[2] if len(sys.argv) > 2 else "mobile_out"))
    else:
        print(publish())
