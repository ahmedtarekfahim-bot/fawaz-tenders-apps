# -*- coding: utf-8 -*-
"""الروتينات والتقارير - every recurring job of the tendering work as a button in the program:
see its reports (Excel / Word / PDF as they are made), open / print them, send them by e-mail to the saved
addresses, share them (copy the file to paste in WhatsApp / mail, or the folder), and run the routine now -
from the PC, or from the phone (the request goes to this PC through the phone channel).

Two kinds of routine:
  - built in: the program does it itself (directory update, CAPT awards + minutes, the new Kuwait Al-Youm
    issue, a tender summary) - they run right away.
  - Claude routines (the weekly Kuwait Al-Youm report, Adham's projects report, BNB Fawaz, KIPIC watch,
    reminders check): their steps are in ~/.claude/scheduled-tasks/<id>/SKILL.md and Claude does the work.
    "Run now" starts Claude Code in the background with that prompt (needs Claude Code on this PC).
"""
import os, re, json, shutil, datetime, subprocess, threading
from pathlib import Path

import fawaz_config as cfg

HOME = Path.home()
TASKS = HOME / ".claude" / "scheduled-tasks"
WORK = Path(r"D:\شغل فواز")
ADHAM = Path(cfg.S.get("adham_reports_dir") or r"D:\1-Work\1-Masharea Tenders\1- Kuwait\0-Reports")
RUN_LOG = cfg.LOCAL / "routine runs.json"
DOC_EXT = {".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".pdf", ".html", ".pptx", ".csv", ".txt"}

# id -> what it is, where its reports land (glob patterns, newest first), how it runs
REGISTRY = [
    {"id": "kuwait-alyawm-weekly-report", "title": "تقرير الكويت اليوم الأسبوعي", "icon": "📰", "kind": "claude",
     "when": "كل أحد بعد صدور العدد", "out": [(WORK / "01 - الكويت اليوم", "Kuwait Al-Youm *.xlsx"),
                                            (WORK / "01 - الكويت اليوم", "FAWAZ News*.xlsx"),
                                            (WORK / "01 - الكويت اليوم", "Kuwait Alyoum tenders*.xlsx")]},
    {"id": "adham-kuwait-tenders-weekly-report", "title": "ريبورت مشاريع ادهم (مناقصات الكويت)", "icon": "🏗", "kind": "claude",
     "when": "كل جمعة", "out": [(ADHAM, "*/*/*-General Report-*.xlsx"), (ADHAM, "*/*/*-Report Changes-*.xlsx")]},
    {"id": "bnb-fawaz", "title": "BNB Fawaz (مناقصات Sanjay)", "icon": "📄", "kind": "claude",
     "when": "كل نص ساعة الأحد-الخميس", "out": [(WORK / "04 - BNB", "BNB-T-*.doc"), (WORK / "04 - BNB", "BNB-T-*.pdf"),
                                                 (WORK / "04 - BNB" / "_BNB Fawaz" / "jobs", "*/*.xlsx"),
                                                 (WORK / "04 - BNB" / "_BNB Fawaz" / "jobs", "*/*.pdf")]},
    {"id": "kipic-fawaz-weekly-watch", "title": "متابعة كيبيك وفواز في الجريدة", "icon": "🛢", "kind": "claude",
     "when": "كل أحد بعد الضهر", "out": [(WORK / "06 - تقارير وتحليلات", "KIPIC-FAWAZ Watch*.xlsx")]},
    {"id": "capt-winning-bids-weekly-update", "title": "ترسيات الجهاز المركزي والمحاضر", "icon": "🏆", "kind": "builtin",
     "when": "كل سبت (والبرنامج بيحدّثها كل شوية)", "out": [(cfg.ARCHIVE, "CAPT Winning Bids from 2006.xlsx"),
                                                             (cfg.ARCHIVE / "CAPT MOM", "*.pdf")]},
    {"id": "directory-update", "title": "تحديث الدليل (كل المواقع)", "icon": "🔄", "kind": "builtin",
     "when": "تلقائي كل كام دقيقة", "out": []},
    {"id": "gazette-issue", "title": "جيب عدد الكويت اليوم الجديد", "icon": "🗞", "kind": "builtin",
     "when": "تلقائي مع التحديث", "out": [(Path(cfg.S.get("gazette_pdf_dir") or r"D:\Download 2026"), "1[0-9][0-9][0-9].pdf")]},
    {"id": "tender-summaries", "title": "ملخصات المناقصات", "icon": "📝", "kind": "builtin",
     "when": "بزرار من تفاصيل أي مناقصة", "out": [(cfg.GULF_DIR / "مستندات المناقصات", "*/ملخص المناقصة.html")]},
    {"id": "directory-reports", "title": "تقارير PDF من الدليل", "icon": "🖨", "kind": "builtin",
     "when": "بزرار اعمل PDF من أي مناقصة", "out": [(cfg.GULF_DIR / "تقارير الدليل", "*.pdf"),
                                                    (cfg.CAPT_DIR / "تقارير المناقصات", "*.pdf")]},
    {"id": "reminder-sync-daily-check", "title": "فحص المواعيد والإيميلات اليومي", "icon": "⏰", "kind": "claude",
     "when": "كل يوم الصبح", "out": []},
]


# ----------------------------------------------------------------- the routines and their reports
def _skill(rid):
    f = TASKS / rid / "SKILL.md"
    try:
        t = f.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.match(r"---\s*\n(.*?)\n---\s*\n(.*)", t, re.S)
    meta = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M)) if m else {}
    return {"description": meta.get("description", ""), "prompt": (m.group(2) if m else t).strip()}


def reports(r, limit=40):
    out = []
    for folder, pat in r["out"]:
        try:
            for f in Path(folder).glob(pat):
                if f.is_file() and f.suffix.lower() in DOC_EXT and not f.name.startswith("~$"):
                    st = f.stat()
                    out.append({"name": f.name, "path": str(f), "size": st.st_size, "ext": f.suffix.lower()[1:],
                                "at": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"),
                                "folder": f.parent.name})
        except OSError:
            continue
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:limit]


def runs():
    try:
        return json.loads(RUN_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _note_run(rid, status, msg=""):
    d = runs()
    d[rid] = {"at": datetime.datetime.now().isoformat(timespec="minutes"), "status": status, "msg": msg[:400]}
    try:
        cfg.LOCAL.mkdir(parents=True, exist_ok=True)
        RUN_LOG.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def claude_exe():
    """Claude Code on this PC (the program starts the Claude routines with it)"""
    for c in (cfg.S.get("claude_exe"), shutil.which("claude"), HOME / ".local" / "bin" / "claude.exe",
              Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"):
        if c and Path(c).exists():
            return str(c)
    return ""


def listing():
    rn, cl = runs(), claude_exe()
    out = []
    for r in REGISTRY:
        sk = _skill(r["id"]) if r["kind"] == "claude" else None
        reps = reports(r)
        out.append({"id": r["id"], "title": r["title"], "icon": r["icon"], "kind": r["kind"], "when": r["when"],
                    "description": (sk or {}).get("description", ""), "has_prompt": bool(sk),
                    "can_run": r["kind"] == "builtin" or bool(sk and cl), "reports": reps,
                    "last_report": reps[0]["at"] if reps else "", "last_run": rn.get(r["id"])})
    return {"routines": out, "claude": bool(cl), "recipients": recipients(), "sender": sender(), "senders": senders()}


def run(rid, hooks, who="الكمبيوتر"):
    """start a routine now -> message. hooks: {'update': fn, 'awards': fn, 'gazette': fn} from the server"""
    r = next((x for x in REGISTRY if x["id"] == rid), None)
    if not r:
        return "روتين مش معروف"
    if r["kind"] == "builtin":
        fn = {"directory-update": "update", "capt-winning-bids-weekly-update": "awards", "gazette-issue": "gazette"}.get(rid)
        if not fn:
            return "الروتين ده بيتعمل من تفاصيل المناقصة (زرار 📝 ملخص المناقصة)"
        threading.Thread(target=_builtin, args=(rid, hooks[fn]), daemon=True).start()
        _note_run(rid, "running", f"اتشغّل من {who}")
        return "اشتغل - النتيجة هتظهر هنا لما يخلص"
    sk, cl = _skill(rid), claude_exe()
    if not sk:
        return "ملقتش خطوات الروتين ده على الجهاز"
    if not cl:
        return "الروتين ده بيعمله Claude - محتاج Claude Code متسطب على الجهاز ده عشان يشتغل من الزرار"
    log = cfg.LOCAL / "routine logs"
    log.mkdir(parents=True, exist_ok=True)
    lf = open(log / f"{rid} {datetime.datetime.now():%Y-%m-%d %H%M}.log", "w", encoding="utf-8")
    p = subprocess.Popen([cl, "-p", sk["prompt"], "--permission-mode", cfg.S.get("routine_permission_mode", "auto")],
                         cwd=str(WORK if WORK.exists() else HOME), stdout=lf, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _note_run(rid, "running", f"اتشغّل من {who}")
    threading.Thread(target=_wait, args=(rid, p, lf), daemon=True).start()
    return "Claude بدأ يشتغل على الروتين في الخلفية - التقارير هتظهر هنا لما يخلص"


def _builtin(rid, fn):
    try:
        fn()
        _note_run(rid, "done", "خلص")
    except Exception as e:                          # noqa: BLE001
        _note_run(rid, "error", str(e))


def _wait(rid, p, lf):
    code = p.wait()
    lf.close()
    _note_run(rid, "done" if code == 0 else "error", "خلص" if code == 0 else f"وقف بخطأ ({code}) - شوف السجل")


# ----------------------------------------------------------------- send / share
def recipients():
    return list(cfg.S.get("mail_recipients") or [])


def senders():
    """the accounts in this PC's Outlook that mail can go out from"""
    try:
        import pythoncom
        import win32com.client.dynamic
        pythoncom.CoInitialize()
        try:
            ns = win32com.client.dynamic.Dispatch("Outlook.Application").GetNamespace("MAPI")
            return [str(a.SmtpAddress or a.DisplayName) for a in ns.Accounts]
        finally:
            pythoncom.CoUninitialize()
    except Exception:                               # noqa: BLE001 - no Outlook here
        return []


def sender():
    return cfg.S.get("mail_from", "")


def save_sender(addr):
    cfg.save_setting("mail_from", str(addr or "").strip())
    return sender()


def save_recipients(lst):
    clean = []
    for x in lst:
        x = str(x).strip()
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", x) and x not in clean:
            clean.append(x)
    cfg.save_setting("mail_recipients", clean)
    return clean


def allowed_file(path):
    """only report files of the routines (never any path)"""
    f = Path(path).resolve()
    if not f.is_file():
        return None
    for r in REGISTRY:
        for folder, _pat in r["out"]:
            try:
                if str(f).startswith(str(Path(folder).resolve())):
                    return f
            except OSError:
                continue
    return None


def send(paths, to, subject="", note="", sender_addr=None):
    """e-mail report files through this PC's Outlook (from the chosen account) -> '' or the error"""
    files = [f for f in (allowed_file(p) for p in paths) if f]
    if not files:
        return "مفيش ملف مسموح"
    to = [x for x in to if "@" in x]
    if not to:
        return "اختار إيميل"
    try:
        import pythoncom
        import win32com.client.dynamic
    except ImportError as e:
        return f"pywin32: {e}"
    pythoncom.CoInitialize()
    try:
        app = win32com.client.dynamic.Dispatch("Outlook.Application")
        m = app.CreateItem(0)
        frm = (sender_addr if sender_addr is not None else sender()).lower()
        if frm:
            acc = next((a for a in app.GetNamespace("MAPI").Accounts
                        if frm in (str(a.SmtpAddress).lower(), str(a.DisplayName).lower())), None)
            if acc is None:
                return f"الإيميل {frm} مش متضاف في Outlook على الجهاز ده"
            try:
                m.SendUsingAccount = acc
            except Exception:                       # noqa: BLE001 - late-bound property set
                m._oleobj_.Invoke(64209, 0, 8, 0, acc)
        m.To = "; ".join(to)
        m.Subject = subject or " + ".join(f.stem for f in files)[:180]
        m.Body = (note + "\n\n" if note else "") + "مرفق: " + "، ".join(f.name for f in files)
        for f in files:
            m.Attachments.Add(str(f))
        m.Send()
        return ""
    except Exception as e:                          # noqa: BLE001
        return str(e)[:200]
    finally:
        pythoncom.CoUninitialize()


def copy_files(paths):
    """put the files on the clipboard (paste them in WhatsApp / an e-mail / a folder)"""
    files = [str(f) for f in (allowed_file(p) for p in paths) if f]
    if not files:
        return "مفيش ملف مسموح"
    lst = ",".join("'" + f.replace("'", "''") + "'" for f in files)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Path {lst}"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return "" if r.returncode == 0 else (r.stderr.decode("utf-8", "ignore")[:200] or "ما اتنسخش")


def phone_index():
    """the reports list for the phone (names + dates only, no paths)"""
    d = listing()
    return {"updated": datetime.datetime.now().isoformat(timespec="minutes"), "claude": d["claude"],
            "routines": [{"id": r["id"], "title": r["title"], "icon": r["icon"], "kind": r["kind"], "when": r["when"],
                          "can_run": r["can_run"], "last_run": r["last_run"],
                          "reports": [{"k": i, "name": x["name"], "at": x["at"], "size": x["size"], "ext": x["ext"]}
                                      for i, x in enumerate(r["reports"][:12])]} for r in d["routines"]],
            "recipients": d["recipients"], "senders": d["senders"], "sender": d["sender"]}
