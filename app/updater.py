# -*- coding: utf-8 -*-
"""Program self-update from GitHub.

The build writes the address of updates/latest.json (raw.githubusercontent.com of the repo) into
_build_info.json. latest.json = {"version": "1.0.1", "setup_url": "...exe", "notes": "..."}.
When a newer version exists the setup is downloaded and started silently (/S /restart); it
closes the running programs, installs over them and starts the directory again.
"""
import os, sys, json, subprocess, tempfile, urllib.request
import fawaz_config as cfg

UA = {"User-Agent": "FAWAZ-Tenders-Updater", "Cache-Control": "no-cache"}


def vtuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def check():
    """-> latest.json dict when a newer version is published, else None"""
    info = cfg.build_info()
    url = info.get("update_url")
    if not url or not cfg.S.get("check_program_updates", True):
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            latest = json.loads(r.read())
    except Exception:                   # noqa: BLE001 - offline / repo not published yet
        return None
    if vtuple(latest.get("version")) > vtuple(info.get("version")):
        return latest
    return None


def apply(latest, log=print):
    """download the new setup and run it silently - only for the installed (frozen) programs"""
    if not getattr(sys, "frozen", False):
        log(f"نسخة جديدة {latest.get('version')} متاحة (التحديث التلقائي بيشتغل في النسخة المتسطبة بس)")
        return False
    try:
        dst = os.path.join(tempfile.gettempdir(), f"FAWAZ-Tenders-Setup-{latest['version']}.exe")
        with urllib.request.urlopen(urllib.request.Request(latest["setup_url"], headers=UA), timeout=600) as r, \
                open(dst, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        log(f"اتنزّلت النسخة {latest['version']} - بيتسطب...")
        subprocess.Popen([dst, "/S", "/restart"], close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        return True
    except Exception as e:              # noqa: BLE001
        log(f"فشل تحديث البرنامج: {e}")
        return False


def check_and_apply(log=print):
    latest = check()
    if latest:
        return apply(latest, log)
    return False
