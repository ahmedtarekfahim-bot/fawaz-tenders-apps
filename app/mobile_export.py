# -*- coding: utf-8 -*-
"""Phone app data: export the public part of the directory + Kuwait awards to JSON and publish the
mobile web app (app/mobile) to the gh-pages branch of the GitHub repo.

Only public sources go out (CAPT, Etimad, Dubai eSupply, PAHW, the official gazette, news, the
CAPT awards list). Internal material - Adham's report codes, notes, local file paths - is left out.
Each publish force-pushes one fresh commit, so the repo does not grow with every update.
Runs after every Gulf directory update on the PC where settings.json has "mobile_publish": true.
"""
import json, shutil, subprocess, datetime, re
from pathlib import Path
import fawaz_config as cfg

INTERNAL_SOURCES = {"تقرير مشاريع"}
SITE = cfg.GULF_DIR / "mobile site"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def export(out_dir):
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
    news = [{"c": n["country"], "d": n["date"], "src": n["source"], "t": n["title"], "u": n["url"], "cat": n["cats"], "fz": n["fawaz"]}
            for n in con.execute("SELECT * FROM news WHERE query<>'تقرير مشاريع' ORDER BY date DESC")]
    con.close()
    awards = [{"r": a["row"], "n": a["tno"], "s": a["subject"], "o": a["org"], "w": a["winner"], "d": a["date"],
               "v": a["total"], "x": a["notes"][:200]} for a in ct.read_excel_rows()]
    meetings = {v["date"]: {"no": k, "url": v["url"]} for k, v in ct.load_meetings().items() if v.get("url")}
    meta = {"updated": datetime.datetime.now().isoformat(timespec="minutes"), "items": len(items), "news": len(news),
            "awards": len(awards), "version": cfg.build_info().get("version")}
    for name, obj in (("directory", items), ("news", news), ("awards", awards), ("meetings", meetings), ("meta", meta)):
        (data / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return meta


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NOWIN)


def publish(log=print):
    if not cfg.S.get("mobile_publish") or not shutil.which("git"):
        return None
    url = repo_url()
    if not url:
        return None
    src = cfg.res_dir() / "mobile"
    if SITE.exists():
        shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(src, SITE)
    meta = export(SITE)
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    for cmd in (["init", "-b", "gh-pages"], ["add", "-A"],
                ["-c", "user.name=FAWAZ Tenders", "-c", "user.email=ahmedtarekfahim@gmail.com", "commit", "-q", "-m",
                 f"data {meta['updated']}"], ["push", "-f", url, "gh-pages"]):
        r = git(*cmd, cwd=SITE)
        if r.returncode != 0:
            log(f"نشر نسخة التليفون فشل: {(r.stderr or r.stdout)[-300:]}")
            return None
    log(f"نسخة التليفون اتحدثت ({meta['items']} مناقصة، {meta['awards']} ترسية)")
    return meta


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        print(export(sys.argv[2] if len(sys.argv) > 2 else "mobile_out"))
    else:
        print(publish())
