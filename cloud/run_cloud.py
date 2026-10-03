# -*- coding: utf-8 -*-
"""Cloud update of the phone app (runs on GitHub Actions every 15 minutes, no PC needed).

  python cloud/run_cloud.py <state dir> <pc-feed dir> <site out dir>

- state dir (kept between runs in the Actions cache): the cloud directory.sqlite, the awards list,
  the CAPT meetings list
- pc-feed dir (branch pc-feed, pushed by the FAWAZ PC): the PC's public directory export (gazette
  reports...), its news and awards, and private.enc (encrypted - passed through untouched)
- site out dir: the phone web app + data, published to gh-pages by the workflow
Sources collected here: CAPT open tenders + awards + minutes list, PAHW, Etimad, Dubai eSupply,
Google News (incl. Fawaz / KJAC). Everything else comes from the PC feed.
"""
import sys, os, json, shutil, datetime, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE, FEEDDIR, SITE = (Path(a).resolve() for a in sys.argv[1:4])
LOCAL = STATE / "local"
(LOCAL / "FAWAZ Tenders").mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(LOCAL)
(LOCAL / "FAWAZ Tenders" / "settings.json").write_text(json.dumps({
    "archive": str(STATE / "archive"), "gazette_dirs": [], "gazette_pdf_dir": "", "adham_reports_dir": "",
    "auto_update_minutes": 0, "awards_update_minutes": 0, "check_program_updates": False,
    "mobile_publish": False, "fawaz_watch": False}, ensure_ascii=False), encoding="utf-8")
sys.path.insert(0, str(ROOT / "app"))
sys.stdout.reconfigure(encoding="utf-8")

import fawaz_config as cfg          # noqa: E402
import capt_tool as ct              # noqa: E402
import gulf_directory as gd         # noqa: E402
import mobile_export as me          # noqa: E402

AWARDS = STATE / "awards.json"
FEED = FEEDDIR / "data"


def load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ----------------------------------------------------------------- awards (no Excel in the cloud)
def award_key(r):
    return ct.row_key(r["date"], r["tno"], r["winner"], r["total"], r["notes"])


def merged_awards():
    rows = [{"row": 0, "tno": a["n"], "subject": a["s"], "org": a["o"], "winner": a["w"], "date": a["d"],
             "total": a["v"], "notes": a.get("x", "")} for a in load(FEED / "awards.json", [])]   # the PC's list since 2006
    have = {award_key(r) for r in rows}
    for r in load(AWARDS, []):                              # what the cloud fetched that the PC has not yet
        if award_key(r) not in have:
            rows.append(r)
            have.add(award_key(r))
    return rows


AW = {"rows": merged_awards()}


def refresh_awards(store, progress):
    rows = AW["rows"]
    last = max((r["date"] for r in rows if r["date"]), default=(datetime.date.today() - datetime.timedelta(days=30)).isoformat())
    d0 = datetime.date.fromisoformat(last) - datetime.timedelta(days=2)
    have = {award_key(r) for r in rows}
    new = []
    for r in ct.fetch_awards_since(d0):
        r = {"row": 0, "tno": r["tno"], "subject": r["subject"], "org": r["org"], "winner": r["winner"],
             "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else r["date"], "total": r["total"],
             "notes": r["notes"]}
        k = award_key(r)
        if k not in have and not (r["notes"].startswith("بنود") and ct.row_key(r["date"], r["tno"], "", "", "بنود") in have):
            new.append(r)
            have.add(k)
    rows = sorted(new + rows, key=lambda r: r["date"] or "", reverse=True)
    for i, r in enumerate(rows):
        r["row"] = i + 3                                     # same numbering idea as the Excel (newest on top)
    AW["rows"] = rows
    AWARDS.write_text(json.dumps([dict(r, row=0) for r in rows if r["date"] >= "2020"], ensure_ascii=False), encoding="utf-8")
    try:
        ct.fetch_meetings()
    except Exception as e:                                   # noqa: BLE001
        progress(f"قائمة المحاضر: {e}")
    return len(new)


ct.read_excel_rows = lambda: AW["rows"]


# ----------------------------------------------------------------- what only the PC knows
DEFINITIVE = {"مترسية", "ملغاة", "أسعار معلنة", "اتوافق على طرحها", "إعلان مسبق", "عقد جاري (قرار الجهاز)"}


def collect_pc_feed(store, progress):
    n = 0
    for r in load(FEED / "directory.json", []):
        evs = r.get("ev") or []
        if not evs:
            continue
        src0 = evs[-1][1] or "الكمبيوتر"
        it = store.add(src0, r["n"], r["o"], r["s"], r["st"] if r["st"] in DEFINITIVE else "",
                       country=r["c"], kind=r.get("k") or "مناقصة",
                       official=(2, r["off"], r.get("ol", "")) if r.get("off") else None,
                       publish=r.get("p", ""), closing=r.get("cl", ""), fees=r.get("f", ""), bond=r.get("b", ""),
                       ttype=r.get("t", ""), value=r.get("v", ""), winner=r.get("w", ""), award_date=r.get("a", ""))
        if it is None:
            continue
        for d, src, etype, text, url in evs:
            it["sources"].add(src)
            it["ev"].append({"date": d, "source": src, "etype": etype, "text": text, "url": url})
        n += 1
    # the PC's news (incl. what it found before the cloud existed)
    con = gd.db()
    for x in load(FEED / "news.json", []):
        con.execute("INSERT OR IGNORE INTO news(country,date,source,title,summary,url,query,cats,fawaz,seen_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)", (x["c"], x["d"], x["src"], x["t"], "", x["u"],
                                                     "شركة: الكمبيوتر" if x.get("co") else "الكمبيوتر",
                                                     x.get("cat", ""), x.get("fz", 0), x.get("fs", "")))
    con.commit()
    con.close()
    progress(f"من الكمبيوتر: {n}")
    return n


gd.SOURCES["KW"] = [("ترسيات جديدة من الموقع", refresh_awards), ("الترسيات", gd.collect_awards),
                    ("من الكمبيوتر", collect_pc_feed), ("الجهاز المركزي", gd.collect_capt),
                    ("الرعاية السكنية", gd.collect_pahw)]


def main():
    t0 = time.time()
    summary = gd.run_update(progress=lambda m: print(m, flush=True))
    meets = load(FEED / "meetings.json", {})
    meetings = {v["no"]: {"date": d, "url": v["url"]} for d, v in meets.items()}
    meetings.update(ct.load_meetings())
    shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(ROOT / "app" / "mobile", SITE)
    meta = me.export(SITE, award_rows=AW["rows"], meetings=meetings)
    meta["by"] = "cloud"
    if (FEED / "private.enc").exists():
        shutil.copy2(FEED / "private.enc", SITE / "data" / "private.enc")
    pc_meta = load(FEED / "meta.json", {})
    meta["pc_updated"] = pc_meta.get("updated", "")
    meta["sources"] = {k: v for k, v in summary.items() if k != "متابعة فواز"}
    meta["seconds"] = round(time.time() - t0)
    (SITE / "data" / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
