# -*- coding: utf-8 -*-
"""ملخص المناقصة - one button: download the tender's documents, read them (scanned pages through Windows' own
OCR, Arabic + English), and write a one-page summary of what matters for pricing - the same headings as the
BNB / study routine (bond, fees, closing + pre-bid, duration, qualification and experience, documents to
submit, subcontracting, manpower / vehicles, penalties, payments, contacts) - every point with its file and
page. No BNB, no e-mail, nothing leaves the PC: the summary is an HTML page saved next to the documents.
"""
import re, html, json, shutil, zipfile, datetime, subprocess, tempfile, unicodedata
from pathlib import Path

import fawaz_config as cfg

SECTIONS = [
    ("الكفالة الابتدائية", ["كفالة ابتدائية", "كفاله ابتدائيه", "ضمان ابتدائي", "تأمين ابتدائي", "كفالة مصرفية", "bid bond", "tender bond", "bid guarantee"]),
    ("ثمن الوثائق والرسوم", ["ثمن الوثائق", "ثمن المناقصة", "قيمة الوثائق", "ثمن نسخة", "رسوم", "document fee", "tender fee"]),
    ("الإقفال والاجتماع التمهيدي وزيارة الموقع", ["تاريخ الاقفال", "موعد الاقفال", "اخر موعد", "اجتماع تمهيدي", "الاجتماع التمهيدي", "زيارة الموقع", "closing date", "pre-bid", "pre bid", "site visit"]),
    ("مدة العقد والتنفيذ", ["مدة العقد", "مدة التنفيذ", "مدة الصيانة", "مدة الضمان", "فترة الصيانة", "contract period", "contract duration", "completion period"]),
    ("التأهيل والخبرة المطلوبة", ["المؤهلين", "التأهيل", "مؤهل", "خبرة", "اعمال مماثلة", "أعمال مماثلة", "سابقة اعمال", "شهادات خبرة", "تصنيف", "مصنف", "prequalif", "qualification", "experience", "similar works"]),
    ("مستندات التقديم المطلوبة", ["يجب ارفاق", "يجب إرفاق", "يرفق مع العطاء", "المستندات المطلوبة", "مستندات العطاء", "يقدم مع العطاء", "documents to be submitted", "shall submit", "to be submitted"]),
    ("مقاولي الباطن", ["مقاول الباطن", "مقاولي الباطن", "الباطن", "subcontract"]),
    ("العمالة والمعدات والسيارات", ["العمالة", "عدد العمال", "الجهاز الفني", "الجهاز الاداري", "مهندس", "سيارة", "سيارات", "معدات", "manpower", "staff", "vehicles", "equipment"]),
    ("الغرامات والجزاءات", ["غرامة", "غرامات", "جزاء", "جزاءات", "خصم من", "penalty", "penalties", "liquidated damages"]),
    ("الدفعات والمستخلصات", ["الدفعة", "الدفعات", "المستخلص", "مستخلصات", "طريقة السداد", "دفعة مقدمة", "payment", "invoice"]),
    ("الكفالة النهائية والتأمينات", ["كفالة نهائية", "كفالة حسن التنفيذ", "ضمان نهائي", "تأمين نهائي", "performance bond", "performance guarantee", "insurance"]),
    ("الاستفسارات والتواصل", ["الاستفسار", "للاستفسار", "الاستفسارات", "البريد الالكتروني", "هاتف", "enquir", "clarification", "contact"]),
]
_AR = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
OCR_PAGES = 80
_last_sections = []                                # the points of the last summary (the BNB form reuses them)                                     # scanned pages read per summary at most (Windows OCR ~1-2 s each)


def fold(s):
    s = unicodedata.normalize("NFKC", str(s or ""))       # PDF presentation forms -> plain letters
    s = re.sub(r"[ً-ْـ]", "", s).translate(_AR).lower()
    return re.sub(r"\s+", " ", s)


def _ocr_dir(png_dir):
    ps1 = cfg.res_dir() / "ocr" / "ocr.ps1"
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), str(png_dir), "ar-SA"],
                   capture_output=True, timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _flip(line):
    """Windows OCR returns Arabic lines in visual order - put the words back in reading order"""
    w = line.split()
    return " ".join(w[::-1]) if sum(1 for x in w if re.search(r"[؀-ۿ]", x)) > len(w) / 2 else line


def pdf_pages(f, budget):
    """-> [(page no, text)], OCR for pages with no text layer (budget = OCR pages left, a 1-item list)"""
    import pymupdf
    out, scan = [], []
    doc = pymupdf.open(f)
    for i, p in enumerate(doc):
        t = p.get_text()
        if len(t.strip()) >= 40:
            out.append((i + 1, t))
        elif budget[0] > 0:
            scan.append(i)
            budget[0] -= 1
    if scan:
        tmp = Path(tempfile.mkdtemp(prefix="gcc-ocr-"))
        try:
            for i in scan:
                doc[i].get_pixmap(dpi=170).save(tmp / f"p{i + 1:04d}.png")
            _ocr_dir(tmp)
            for i in scan:
                t = tmp / f"p{i + 1:04d}.txt"
                if t.exists():
                    out.append((i + 1, "\n".join(_flip(x) for x in t.read_text(encoding="utf-8-sig").splitlines())))
        except Exception:                          # noqa: BLE001 - OCR not available: text pages only
            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    doc.close()
    return sorted(out)


def docx_text(f):
    with zipfile.ZipFile(f) as z:
        x = z.read("word/document.xml").decode("utf-8", "ignore")
    return [(1, html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"</w:p>", "\n", x))))]


def xlsx_info(f):
    """a priced-items sheet (BOQ): how many items, per sheet"""
    import openpyxl
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    res = []
    for ws in wb.worksheets:
        n = sum(1 for r in ws.iter_rows(values_only=True) if sum(1 for v in r if v not in (None, "")) >= 3)
        if n:
            res.append(f"{ws.title}: {n} صف")
    wb.close()
    return res


def read_folder(folder):
    """every document in the folder (zips opened) -> ([(file, page, text)], boq notes, file list)"""
    folder = Path(folder)
    for z in list(folder.glob("*.zip")):
        dest = folder / z.stem
        if not dest.exists():
            try:
                with zipfile.ZipFile(z) as zz:
                    zz.extractall(dest)
            except Exception:                      # noqa: BLE001
                pass
    pages, boq, files, budget = [], [], [], [OCR_PAGES]
    for f in sorted(folder.rglob("*")):
        if not f.is_file() or f.name.startswith(("~$", "ملخص")):
            continue
        ext = f.suffix.lower()
        try:
            if ext == ".pdf":
                got = pdf_pages(f, budget)
            elif ext == ".docx":
                got = docx_text(f)
            elif ext in (".xlsx", ".xlsm"):
                boq += [f"{f.name} - {x}" for x in xlsx_info(f)]
                got = []
            elif ext == ".txt":
                got = [(1, f.read_text(encoding="utf-8", errors="ignore"))]
            else:
                continue
        except Exception:                          # noqa: BLE001 - a damaged / locked file
            continue
        files.append(f.name)
        pages += [(f.name, p, t) for p, t in got]
    return pages, boq, files


def find_points(pages, keys, limit=8):
    """the lines that carry a key word, the ones with numbers (amounts, dates, %) first"""
    fk = [fold(k) for k in keys]
    seen, hits = set(), []
    for name, page, text in pages:
        lines = [x.strip() for x in re.split(r"[\n\r]+|(?<=[.؛;])\s+", text) if len(x.strip()) > 12]
        for i, ln in enumerate(lines):
            fl = fold(ln)
            if not any(k in fl for k in fk):
                continue
            ctx = ln if len(ln) > 60 or i + 1 >= len(lines) else ln + " " + lines[i + 1]
            ctx = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", ctx))[:400]
            key = fold(ctx)[:120]
            if key in seen:
                continue
            seen.add(key)
            hits.append((bool(re.search(r"\d", ctx)), name, page, ctx))
    hits.sort(key=lambda h: not h[0])
    return [{"file": n, "page": p, "text": t} for _x, n, p, t in hits[:limit]]


def summarize(iid, progress=print):
    """download + read + summarize one directory item -> {path, html, sections, files}"""
    import gulf_directory as gd
    d = gd.detail(iid)
    it = d["item"]
    progress("بحمّل مستندات المناقصة...")
    try:
        dl = gd.download_docs(iid)
        folder = Path(dl["folder"])
    except Exception as e:                         # noqa: BLE001
        dl, folder = {"files": [], "locked": [], "error": str(e)}, None
    if folder is None or not folder.exists():
        import tender_docs as td
        folder = gd.DOCS_OUT / td.safe(f"{it['number']} - {it['subject']}", 90)
        folder.mkdir(parents=True, exist_ok=True)
    for f in gd.archived_files(iid):               # copies kept while it was open
        if f.is_file() and not (folder / f.name).exists():
            shutil.copy2(f, folder / f.name)
    progress("بقرا الملفات (والممسوح بالـ OCR)...")
    pages, boq, files = read_folder(folder)
    sections = [(title, find_points(pages, keys)) for title, keys in SECTIONS]
    _last_sections[:] = sections
    facts = [("الجهة", it["org"]), ("رقم المناقصة", it["number"]), ("الموضوع", it["subject"]), ("الحالة", it["status"]),
             ("تاريخ الطرح", it["publish"]), ("تاريخ الإقفال", it["closing"]), ("ثمن الوثائق", it.get("fees")),
             ("الكفالة", it.get("bond")), ("النوع", it.get("ttype")), ("الفائز", it.get("winner")), ("القيمة", it.get("value"))]
    out = folder / "ملخص المناقصة.html"            # short: the folder already names the tender (Windows path limit)
    page = render(it, facts, sections, d, boq, files, dl)
    out.write_text(page, encoding="utf-8")
    return {"path": str(out), "folder": str(folder), "html": page, "files": files, "pages": len(pages),
            "found": sum(1 for _t, p in sections if p)}


def render(it, facts, sections, d, boq, files, dl):
    e = html.escape
    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in facts if v)
    secs = ""
    for title, pts in sections:
        body = "".join(f"<li>{e(p['text'])}<span class=src>{e(p['file'])} · ص {p['page']}</span></li>" for p in pts) \
            or "<li class=none>مش مذكور في الملفات اللي اتقرت</li>"
        secs += f"<section><h2>{e(title)}</h2><ul>{body}</ul></section>"
    hist = d.get("history") or []
    if hist:
        secs += "<section><h2>ترسيات سابقة لنفس الشغل (للتسعير)</h2><table class=t><tr><th>التاريخ</th><th>الجهة</th><th>الفائز</th><th>القيمة</th></tr>" + \
                "".join(f"<tr><td>{e(str(h.get('date') or ''))}</td><td>{e(h.get('org') or '')}</td><td>{e((h.get('winner') or '')[:70])}</td><td>{e(str(h.get('total') or ''))}</td></tr>" for h in hist[:8]) + "</table></section>"
    bids = d.get("bids")
    if bids and bids.get("rows"):
        secs += f"<section><h2>أسعار فض العطاءات - اجتماع {e(str(bids.get('meeting') or ''))}</h2><table class=t><tr><th>#</th><th>المقاول</th><th>العرض</th></tr>" + \
                "".join(f"<tr><td>{i + 1}</td><td>{e(str(r[0]))}</td><td>{e(str(r[3] if len(r) > 3 else ''))}</td></tr>" for i, r in enumerate(json.loads(bids['rows']) if isinstance(bids['rows'], str) else bids['rows'])) + "</table></section>"
    if boq:
        secs += "<section><h2>جداول الكميات (BOQ)</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in boq) + "</ul></section>"
    missing = dl.get("locked") or []
    src = ("<p class=note>الملفات اللي اتقرت: " + e("، ".join(files)) + "</p>") if files else \
          "<p class=note warn>مفيش ملفات اتحمّلت للمناقصة دي - الملخص من بيانات الإعلان بس. " + \
          ("(محتاج دخول: " + e("، ".join(missing)) + ")" if missing else "") + "</p>"
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>ملخص المناقصة {e(it['number'] or '')}</title>
<style>body{{font:14px/1.7 "IBM Plex Sans Arabic","Segoe UI",Tahoma,sans-serif;color:#1d2433;max-width:960px;margin:24px auto;padding:0 18px}}
h1{{font-size:20px;margin:0 0 4px;color:#14325c}}.sub{{color:#5f6b7a;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}th,td{{border:1px solid #d9dee7;padding:6px 9px;text-align:right;vertical-align:top}}
th{{background:#eef2f8;width:22%;color:#14325c}}.t th{{width:auto}}
section{{break-inside:avoid;margin:14px 0;border-right:4px solid #e07a1f;padding:2px 12px 2px 0}}
h2{{font-size:15.5px;margin:6px 0;color:#e07a1f}}ul{{margin:4px 0;padding-right:18px}}li{{margin:4px 0}}
.src{{display:inline-block;margin-right:8px;font-size:11.5px;color:#7a8594;background:#f3f5f9;border-radius:6px;padding:0 6px}}
.none{{color:#9aa3af}}.note{{font-size:12.5px;color:#5f6b7a}}.warn{{color:#a4451a}}
@media print{{body{{margin:0}}.np{{display:none}}}}</style></head><body>
<button class=np onclick="print()" style="float:left;padding:6px 14px;border-radius:8px;border:1px solid #d9dee7;background:#14325c;color:#fff;cursor:pointer">🖨 طباعة</button>
<h1>ملخص المناقصة</h1><div class=sub>{e(it['subject'] or '')}<br>اتعمل {now}</div>
<table>{rows}</table>{src}{secs}</body></html>"""


# ----------------------------------------------------------------- BNB form (optional, its own button)
BNB_TOOL = Path(r"D:\شغل فواز\04 - BNB\_BNB Fawaz\bnb fawaz.py")
COUNTRY_EN = {"KW": "Kuwait", "SA": "Saudi Arabia", "AE": "UAE"}


def make_bnb(iid, progress=print, out_dir=None):
    """the BNB form for one tender from the house template (the form itself is never changed): the
    announcement's facts + the summary's points -> BNB-T-<yy>-<nn>.doc + .pdf in 04 - BNB and a copy next to
    the tender's documents. Only on the PC that has the BNB tool and Word."""
    import importlib.util, io, contextlib
    if not BNB_TOOL.exists():
        raise RuntimeError("أداة الـ BNB مش على الجهاز ده")
    res = summarize(iid, progress)
    import gulf_directory as gd
    it = gd.detail(iid)["item"]
    pts = {t: p for t, p in _last_sections}
    first = lambda t, n=160: (pts.get(t) or [{"text": ""}])[0]["text"][:n]
    dm = lambda d: "/".join(reversed(d[:10].split("-"))) if d else "-"
    ptm = next((p["text"][:90] for p in pts.get("الإقفال والاجتماع التمهيدي وزيارة الموقع", [])
                if re.search(r"تمهيد|pre.?bid|زيارة", p["text"], re.I)), "N/A")
    lines = [f"- {t}: {p[0]['text'][:220]}" for t, p in _last_sections if p and t not in
             ("الإقفال والاجتماع التمهيدي وزيارة الموقع", "الاستفسارات والتواصل")][:6]
    spec = {"profit_center": "FM", "tender": f"Tender No. {it['number']} - {it['subject']}", "client": it["org"],
            "country": COUNTRY_EN.get(it["country"], "Kuwait"), "consultant": "N/A",
            "announcement_date": dm(it["publish"]), "source": it.get("official_label") or "CAPT",
            "document_fee": it.get("fees") or first("ثمن الوثائق والرسوم", 80) or "-",
            "qualified_bidders": first("التأهيل والخبرة المطلوبة", 200),
            "pre_tender_meeting": ptm, "bid_bond": it.get("bond") or first("الكفالة الابتدائية", 120) or "-",
            "currency": "KWD" if it["country"] == "KW" else ("SAR" if it["country"] == "SA" else "AED"),
            "closing_date": dm(it["closing"]),
            "comments": "\r".join(lines) or "(من ملخص البرنامج - مفيش نقط اتلقطت من الملفات)",
            "type_line": f"Type of tender: {it.get('ttype') or '-'}", "copy_to": [res["folder"]]}
    tmp = Path(res["folder"]) / "bnb spec.json"
    tmp.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    sp = importlib.util.spec_from_file_location("bnb_fawaz_tool", BNB_TOOL)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    if out_dir:                                    # tests: never touch the real BNB folder / numbering
        mod.BNB_DIR = Path(out_dir)
    buf = io.StringIO()
    progress("بعمل فورمة الـ BNB من القالب...")
    with contextlib.redirect_stdout(buf):
        mod.cmd_make_bnb(str(tmp))
    txt = buf.getvalue()
    out = json.loads(txt[txt.index("{"):])
    return {"bnb": out.get("bnb"), "doc": out.get("doc"), "pdf": out.get("pdf"), "folder": res["folder"], "summary": res["path"]}
