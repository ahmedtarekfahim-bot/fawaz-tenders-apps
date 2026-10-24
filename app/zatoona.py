# -*- coding: utf-8 -*-
"""الزتونة - when the program's own data is not enough, Claude digs the tender / company / project out:
the official CAPT pages (winning bids, minutes), the gazette, the press - and writes a short report in the house
style (like "هـ ط 241 الطريق الإقليمي - الترسية والبيانات.md"): the award table, the news, the project data, the
timeline and notes, every fact with its link. It runs Claude Code on this PC (signed in once) in the background;
one at a time, with a time limit, and it never stops the program whatever happens.
"""
import re, json, time, threading, datetime, subprocess
from pathlib import Path

import fawaz_config as cfg

TIME_LIMIT = 25 * 60
_jobs, _lock = {}, threading.Lock()


def out_dir():
    import capt_tool as ct
    ct.OUT.mkdir(parents=True, exist_ok=True)
    return ct.OUT


def safe(s, n=90):
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s or "").strip()[:n].strip() or "بحث"


def _context(q):
    """what our own data already has about it - Claude starts from there"""
    lines = []
    try:
        import gulf_directory as gd, capt_tool as ct
        for r in gd.search(q, limit=6):
            lines.append(f"- دليل: {r['number']} | {r['org']} | {r['subject'][:140]} | {r['status']} | طرح {r['publish']} | "
                         f"إقفال {r['closing']} | {r['winner'][:60]} {r['value']} | {r.get('official') or ''}")
        for a in ct.search_awards(q, limit=6):
            lines.append(f"- ترسية: {a['date']} | {a['tno']} | {a['org']} | {a['subject'][:120]} | {a['winner'][:60]} | {a['total']}")
        for h in ct.minutes_free_search(q, limit=4):
            lines.append(f"- محضر {h.get('meeting')} ({h.get('mdate')}): {h['snippet'][:220]}")
    except Exception as e:                          # noqa: BLE001
        lines.append(f"(داتا البرنامج ما اتقرتش: {e})")
    return "\n".join(lines) or "(مفيش حاجة في داتا البرنامج)"


PROMPT = """إنت باحث مناقصات لشركة فواز للتجارة والخدمات الهندسية (الكويت). المستخدم بيدوّر على:
«{q}»
{hint}
ده اللي برنامج الدليل لقاه عندنا (ابدأ منه، وكمّل اللي ناقص):
{ctx}

المطلوب: دوّر بنفسك على النت وفي الملفات اللي على الجهاز لو تنفع، في:
- موقع الجهاز المركزي للمناقصات capt.gov.kw (المطروح، الترسيات winning-bids بتاريخ الاجتماع، المحاضر، فض العطاءات)
- جريدة الكويت اليوم، والأخبار (الأنباء، الراي، القبس، أرقام، MEED...)
- الفولدر D:\\شغل فواز\\11 - أرشيف العمل والهندسة\\التسعير والعطاءات (ترسيات CAPT والمحاضر عندنا)

واكتب تقرير ماركداون بالعامية المصرية بالشكل ده بالظبط، واحفظه بأداة Write في:
{path}

# <رقم المناقصة/الاسم>: <الموضوع>
**الجهة:** ...
---
## 1. الترسية الرسمية (لو اترست) - جدول: تاريخ الاجتماع | رقم المناقصة | الجهة | الفائز | القيمة، ولينك الجهاز
## 2. الأخبار (لو فيه) - ملخص كل خبر في سطرين ولينكه
## 3. بيانات المشروع - جدول: الطرح | الإقفال | التأمين | سعر الوثائق | النطاق | المدة | الإشراف ...
## 4. اللي حصل من أول ما اتطرحت - جدول تواريخ وأحداث (تأجيلات، تظلمات، قرارات الجهاز، ديوان المحاسبة)
**الوضع دلوقتي:** سطر واحد
## 5. ملاحظات - اللي مش متاح وليه، ومن فين يتجاب

قواعد: كل معلومة جنبها مصدرها (لينك). متألفش أرقام ولا تواريخ - اللي مش لاقيه قول إنه مش لاقيه. ولو البحث
عن شركة: اعمل جدول بعقودها وترسياتها من الأحدث للأقدم بدل قسم 1. متبعتش إيميلات، ومتعدّلش أي ملف غير ملف التقرير.
"""


FAIL = re.compile(r"session limit|usage limit|rate limit|hit your|resets \d|not logged in|please run /login|"
                  r"invalid api key|credit balance|error:|overloaded", re.I)


def _why(text):
    t = (text or "").strip()
    if re.search(r"limit|resets", t, re.I):
        return "حد استخدام Claude خلص دلوقتي - جرّب بعد ما يرجع: " + t[:160]
    if re.search(r"login|logged in|api key", t, re.I):
        return "Claude محتاج تسجيل دخول - تبويب الروتينات ← 🔑 سجّل دخول Claude"
    return "Claude ما طلّعش تقرير: " + (t[:240] or "مفيش رد")


def start(q, user="", hint="", wait=False):
    q = (q or "").strip()
    if len(q) < 2:
        return {"state": "error", "msg": "اكتب اللي عاوز تدوّر عليه"}
    import routines
    cl = routines.claude_exe()
    if not cl:
        return {"state": "error", "msg": "الزتونة محتاجة Claude Code على الجهاز ده (بييجي مع برنامج Claude)"}
    if not routines.claude_signed_in():
        return {"state": "error", "msg": "Claude محتاج تسجيل دخول مرة واحدة - تبويب الروتينات ← 🔑 سجّل دخول Claude"}
    with _lock:
        busy = next((j for j in _jobs.values() if j["state"] == "running"), None)
        if busy:
            return dict(busy, msg=f"فيه زتونة شغالة دلوقتي على «{busy['q']}» - استنى لما تخلص")
        jid = str(int(time.time() * 1000))
        path = out_dir() / f"{safe(q)} - الزتونة.md"
        job = {"id": jid, "q": q, "user": user, "state": "running", "path": str(path),
               "started": datetime.datetime.now().isoformat(timespec="seconds"), "msg": "Claude بيدوّر..."}
        _jobs[jid] = job
    t = threading.Thread(target=_run, args=(job, cl, hint), daemon=True)
    t.start()
    if wait:
        t.join(TIME_LIMIT + 60)
    return dict(job)


def _run(job, cl, hint):
    import routines
    path = Path(job["path"])
    before = path.stat().st_mtime if path.exists() else 0
    prompt = PROMPT.format(q=job["q"], hint=f"ملاحظة من المستخدم: {hint}" if hint else "", ctx=_context(job["q"]), path=str(path))
    try:
        r = subprocess.run([cl, "-p", prompt, "--permission-mode", cfg.S.get("routine_permission_mode", "auto")],
                           cwd=str(path.parent), capture_output=True, timeout=TIME_LIMIT, env=routines._clean_env(),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = r.stdout.decode("utf-8", "ignore").strip()
        saved = path.exists() and path.stat().st_mtime > before
        if not saved:                                   # Claude answered without saving
            if r.returncode != 0 or not out or FAIL.search(out[:400]) or len(out) < 200:
                raise RuntimeError(_why(out or r.stderr.decode("utf-8", "ignore")))
            path.write_text(out, encoding="utf-8")
        elif len(path.read_text(encoding="utf-8").strip()) < 200:
            raise RuntimeError(_why(path.read_text(encoding="utf-8")))
        job.update(state="done", msg="خلصت")
    except subprocess.TimeoutExpired:
        job.update(state="error", msg="Claude طوّل أكتر من 25 دقيقة - جرّب تاني بكلام أدق")
    except Exception as e:                          # noqa: BLE001
        job.update(state="error", msg=f"الزتونة ما خلصتش: {str(e)[:300]}")
    job["finished"] = datetime.datetime.now().isoformat(timespec="seconds")


def status(jid=""):
    if jid and jid in _jobs:
        j = dict(_jobs[jid])
        if j["state"] == "done":
            try:
                j["md"] = Path(j["path"]).read_text(encoding="utf-8")
            except OSError:
                j["md"] = ""
        j["elapsed"] = int((datetime.datetime.now() - datetime.datetime.fromisoformat(j["started"])).total_seconds())
        return j
    files = sorted(out_dir().glob("*الزتونة*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:30]
    running = next((dict(j) for j in _jobs.values() if j["state"] == "running"), None)
    return {"recent": [{"name": f.stem, "path": str(f), "at": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes")}
                       for f in files], "running": running}
