# -*- coding: utf-8 -*-
"""شغل المشاريع - the weekly Kuwait projects report (Adham's "General Report") inside the program.

Source on the owner's PC: <adham_reports_dir>\\<year>\\<MM-DD> report\\<no>-General Report-<MM-DD>.xlsx
(the base of all the files it links to is D:\\1-Work\\1-Masharea Tenders\\1- Kuwait). Every sheet comes in as a
table (sections kept), with its file links resolved to real paths; the week's "Report Changes" file and the
code folders (N519 ...) of the week are listed too. Any earlier week can be opened.

On the phone the latest report goes sealed (only accounts allowed "شغل المشاريع" get its key).
"""
import re, datetime, urllib.parse
from pathlib import Path

import fawaz_config as cfg

REPORTS = Path(cfg.S.get("adham_reports_dir") or r"D:\1-Work\1-Masharea Tenders\1- Kuwait\0-Reports")
BASE = REPORTS.parent
SKIP = re.compile(r"BACKUP|old|PRE|short|Mashaarea|Tarek|only|Merged|before|Segregation", re.I)
_cache = {}


def reports():
    """every weekly report, newest first -> [{no, week, year, path}]"""
    out = []
    if not REPORTS.is_dir():
        return out
    for f in REPORTS.glob("*/*/*-General Report-*.xlsx"):
        m = re.match(r"(\d+)-General Report-(\d\d-\d\d)\.xlsx$", f.name)
        if m and not SKIP.search(f.name) and not f.name.startswith("~$"):
            out.append({"no": int(m.group(1)), "week": m.group(2), "year": f.parent.parent.name, "path": str(f)})
    return sorted(out, key=lambda r: (r["no"], r["year"]), reverse=True)


def _cell(c, folder):
    v = c.value
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        t = v.date().isoformat()
    elif isinstance(v, float) and v.is_integer():
        t = str(int(v))
    else:
        t = str(v).strip()
    link = ""
    if c.hyperlink and c.hyperlink.target:
        tg = urllib.parse.unquote(c.hyperlink.target)
        link = tg if re.match(r"https?:|[A-Za-z]:\\", tg) else str((folder / tg).resolve())
    elif re.match(r"[A-Za-z]:\\", t):
        link = t
    return {"t": t, "l": link} if link else t


def _sheet(ws, folder):
    """header row = the first of the top 5 rows with 4+ filled cells; one-cell rows below it are section titles"""
    rows = list(ws.iter_rows())
    hi = next((i for i, r in enumerate(rows[:5]) if sum(1 for c in r if c.value not in (None, "")) >= 4), None)
    if hi is None:
        return None
    width = max(c.column for c in rows[hi] if c.value not in (None, ""))
    headers = [str(c.value or "").strip() for c in rows[hi][:width]]
    title = next((str(c.value).strip() for r in rows[:hi] for c in r if c.value not in (None, "")), ws.title)
    out, sec = [], ""
    for r in rows[hi + 1:]:
        vals = [_cell(c, folder) for c in r[:width]]
        filled = [v for v in vals if v]
        if not filled:
            continue
        if len(filled) == 1 and isinstance(filled[0], str) and len(filled[0]) > 6 and not vals[0]:
            sec = filled[0]
            continue
        if len(filled) == 1 and isinstance(filled[0], str) and ("القسم" in filled[0] or "·" in filled[0]):
            sec = filled[0]
            continue
        out.append({"sec": sec, "c": vals + [""] * (width - len(vals))})
    keep = [i for i, h in enumerate(headers) if h or any(r["c"][i] for r in out)]
    return {"name": ws.title, "title": title, "headers": [headers[i] or f"عمود {i + 1}" for i in keep],
            "rows": [{"sec": r["sec"], "c": [r["c"][i] for i in keep]} for r in out]}


def load(path=None):
    """one report (default: the latest) -> {no, week, path, sheets, files}"""
    import openpyxl
    reps = reports()
    if not reps:
        return {"no": 0, "week": "", "sheets": [], "files": [], "weeks": []}
    rep = next((r for r in reps if r["path"] == path), reps[0])
    f = Path(rep["path"])
    key = (str(f), f.stat().st_mtime)
    if _cache.get("key") != key:
        wb = openpyxl.load_workbook(f, data_only=True)
        sheets = [s for s in (_sheet(ws, f.parent) for ws in wb.worksheets) if s and s["rows"]]
        wb.close()
        ch = next(iter(f.parent.glob(f"{rep['no']}-Report Changes-*.xlsx")), None)
        if ch:
            try:
                wb = openpyxl.load_workbook(ch, data_only=True)
                for ws in wb.worksheets:
                    s = _sheet(ws, ch.parent)
                    if s and s["rows"]:
                        s["name"] = "تغييرات الأسبوع - " + ws.title
                        sheets.append(s)
                wb.close()
            except Exception:                       # noqa: BLE001 - a changes file still open in Excel
                pass
        files = sorted(({"name": p.name, "path": str(p), "dir": p.is_dir()} for p in f.parent.iterdir()
                        if not p.name.startswith("~$") and p != f), key=lambda x: (not x["dir"], x["name"]))
        _cache.update(key=key, data={"no": rep["no"], "week": rep["week"], "year": rep["year"], "path": str(f),
                                     "sheets": sheets, "files": files})
    return dict(_cache["data"], weeks=[{"no": r["no"], "week": r["week"], "year": r["year"], "path": r["path"]} for r in reps])


def code_folder(code):
    """the folder of a report code (N519, L233 ...) anywhere under the projects base"""
    code = str(code or "").strip().split("/")[0].split("-")[0]
    if not re.match(r"^[A-Z]{1,2}\d+$", code):
        return ""
    for sub in ("3-NEW Tenders", "4-Closed Tenders", "Tenders Bank", "0-Reports"):
        for p in (BASE / sub).glob(f"**/{code}"):
            if p.is_dir():
                return str(p)
    return ""


def phone_bundle():
    """the latest report for the phone (no local paths)"""
    d = load()
    strip = lambda v: v["t"] if isinstance(v, dict) else v
    return {"no": d["no"], "week": d["week"], "year": d.get("year", ""),
            "updated": datetime.datetime.now().isoformat(timespec="minutes"),
            "sheets": [{"name": s["name"], "title": s["title"], "headers": s["headers"],
                        "rows": [{"sec": r["sec"], "c": [strip(v) for v in r["c"]]} for r in s["rows"]]}
                       for s in d["sheets"]]}
