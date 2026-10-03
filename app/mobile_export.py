# -*- coding: utf-8 -*-
"""Phone app data.

The phone app (GitHub Pages, branch gh-pages) is published by a cloud job (GitHub Actions, see
.github/workflows/phone-data.yml + cloud/run_cloud.py) that collects the public sources by itself
every 15 minutes - the phone stays fresh with this PC switched off.

This PC adds what only it has, on the branch pc-feed:
  - the public part of its directory (gazette reports etc.) - Adham's report codes, notes and local
    paths are left out
  - users_pub.json: the phone accounts' public login material (accounts.py) - only active accounts
  - private.enc + fkeys.json: our own tenders, Sanjay's e-mails and the Fawaz / KJAC follow-up,
    sealed for the accounts allowed to see them
Everything published on gh-pages is encrypted per account (accounts.seal_dir); nobody without an
active account can read the phone data. If the cloud copy is more than an hour old, or the accounts
changed, this PC also publishes gh-pages itself.
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
_PUB = __import__("threading").Lock()


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
                      "ch": (r["changed"] or "")[:16], "ev": ev, "chg": chg,
                      "dc": [[d.get("label", ""), d.get("url", ""), d.get("date", ""), d.get("src", "")]
                             for d in json.loads(r["docs"] or "[]") if str(d.get("url", "")).startswith("http")]})
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


# ----------------------------------------------------------------- private part (sealed per account, see accounts.py)
def capt_docs_map():
    """CAPT tender files seen with the owner's account -> {"number|org": [[label, url, date]]}"""
    import gulf_directory as gd
    con = gd.db()
    out = {}
    for r in con.execute("SELECT i.number, i.org, c.docs FROM capt_docs c JOIN items i ON i.id=c.item_id WHERE c.logged=1"):
        files = [[d.get("label", ""), d["url"], d.get("date", "")] for d in json.loads(r["docs"] or "[]") if d.get("url")]
        if files:
            out[f"{r['number']}|{r['org']}"] = files
    con.close()
    return out


def private_bundle():
    import fawaz_watch as fw
    d = fw.data(limit_feed=600)
    return {"updated": datetime.datetime.now().isoformat(timespec="minutes"),
            "feed": [[f["id"], f["at"][:16], f["kind"], f["title"], f["text"], f["url"], f["tender_key"]] for f in d["feed"]],
            "tenders": [{"k": t["key"], "src": t["src"], "t": t["title"], "c": t["client"], "n": t["number"], "nk": t["numkey"],
                         "cl": t["closing"], "st": t["status"], "rm": t["remarks"], "lv": t["live"], "rk": t["fawaz_rank"],
                         "b": t["bidders"], "ln": [[l["kind"], l["title"], l["url"]] for l in t["links"]]} for t in d["tenders"]],
            "cd": capt_docs_map(),
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


def publish(log=print, force=False):
    """force=True (accounts changed): push pc-feed and the phone site right away"""
    with _PUB:                                          # an update and an accounts change may meet here
        return _publish(log, force)


def ntfy_info():
    import phone_lock
    mail = phone_lock.owner_email()
    return {"topic": phone_lock.topic(), "mail": mail[:3] + "***" + mail[mail.find("@"):]}


def build_feed(log=print):
    """pc-feed folder: the PC's public extras (plain - the cloud merges them), the active users' public
    login material, and the Fawaz-confidential part sealed for the users allowed to see it"""
    import accounts
    _rmtree(FEED)
    meta = export(FEED)
    accounts.ensure_owner()
    users = accounts.public_users()
    data = FEED / "data"
    (data / "users_pub.json").write_text(json.dumps(users), encoding="utf-8")
    (data / "ntfy.json").write_text(json.dumps(ntfy_info()), encoding="utf-8")
    try:
        raw = json.dumps(private_bundle(), ensure_ascii=False, separators=(",", ":")).encode()
        enc, fkeys = accounts.seal_private(raw, users)
        (data / "private.enc").write_text(json.dumps(enc), encoding="utf-8")
        (data / "fkeys.json").write_text(json.dumps(fkeys), encoding="utf-8")
    except Exception as e:                              # noqa: BLE001
        log(f"بيانات فواز المشفرة: {e}")
    return meta


def build_site(feed_data, site, log=print):
    """the phone site from a feed folder: app files + every data file encrypted for the active users"""
    import accounts
    _rmtree(site)
    shutil.copytree(cfg.res_dir() / "mobile", site)
    shutil.copytree(feed_data, site / "data", dirs_exist_ok=True)
    d = site / "data"
    users = json.loads((d / "users_pub.json").read_text(encoding="utf-8"))
    fkeys = json.loads((d / "fkeys.json").read_text(encoding="utf-8")) if (d / "fkeys.json").exists() else {}
    (d / "users_pub.json").unlink()
    n = accounts.seal_dir(d, users, fkeys)
    (site / ".nojekyll").write_text("", encoding="utf-8")
    return n


def _publish(log, force):
    if not cfg.S.get("mobile_publish") or not shutil.which("git"):
        return None
    url = repo_url()
    if not url:
        return None
    # 1) pc-feed: our extras + accounts + the sealed Fawaz part, for the cloud job
    meta = build_feed(log)
    sig = hashlib.sha256(b"".join((FEED / "data" / n).read_bytes() for n in
                                  ("directory.json", "news.json", "awards.json", "users_pub.json"))).hexdigest()
    if force or sig != _last_feed.get("sig") or time.time() - _last_feed.get("at", 0) > 1800:
        if push_dir(FEED, "pc-feed", url, f"pc feed {meta['updated']}", log):
            _last_feed.update(sig=sig, at=time.time())
    # 2) accounts changed, first sealed publish, or the cloud copy is stale -> publish the phone site from here too
    first_sealed = not cfg.S.get("sealed_published")
    if force or first_sealed or cloud_age_minutes() > 60:
        n = build_site(FEED / "data", SITE, log)
        if push_dir(SITE, "gh-pages", url, f"data {meta['updated']} (pc)", log):
            log(f"نسخة التليفون اتحدثت من الكمبيوتر ({meta['items']} مناقصة، {n} حساب متفعّل)")
            if first_sealed:
                cfg.save_setting("sealed_published", True)
    else:
        log("نسخة التليفون بتتحدث من السحابة - الكمبيوتر بعت إضافاته بس")
    return meta


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        print(export(sys.argv[2] if len(sys.argv) > 2 else "mobile_out"))
    else:
        print(publish())
