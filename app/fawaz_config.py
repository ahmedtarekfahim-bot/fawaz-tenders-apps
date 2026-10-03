# -*- coding: utf-8 -*-
"""Where each program keeps its data, on this machine or on any other one.

settings.json lives in %LOCALAPPDATA%\\FAWAZ Tenders and is created on first run:
  - on the original FAWAZ PC the data stays where it always was (D:\\شغل فواز\\...\\التسعير والعطاءات)
  - on a new PC everything goes under %LOCALAPPDATA%\\FAWAZ Tenders\\data and is built from the internet
    (the awards Excel ships with the installer as a starting point)
Edit settings.json to point several PCs at a shared folder.
"""
import os, sys, json, shutil
from pathlib import Path

APP_NAME = "FAWAZ Tenders"
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
SETTINGS = LOCAL / "settings.json"
LEGACY_ARCHIVE = Path(r"D:\شغل فواز\11 - أرشيف العمل والهندسة\التسعير والعطاءات")


def res_dir():
    """folder with the bundled files (ui, seed, build info) - works frozen or from source"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def build_info():
    try:
        return json.loads((res_dir() / "_build_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": "dev", "update_url": ""}


def _defaults():
    archive = LEGACY_ARCHIVE if LEGACY_ARCHIVE.exists() else LOCAL / "data"
    gz = [p for p in (Path(r"D:\شغل فواز\01 - الكويت اليوم"), Path(r"D:\شغل فواز")) if p.exists()]
    return {
        "archive": str(archive),
        "gazette_dirs": [str(p) for p in gz],                       # weekly Kuwait Al-Youm report files
        "gazette_pdf_dir": r"D:\Download 2026",                      # gazette issue PDFs (<issue>.pdf)
        "adham_reports_dir": r"D:\1-Work\1-Masharea Tenders\1- Kuwait\0-Reports",
        # automatic data refresh while the program runs, in minutes (0 = off); changeable from the window
        "auto_update_minutes": 5,                                    # Gulf directory
        "awards_update_minutes": 5,                                  # CAPT awards + minutes
        "check_program_updates": True,
        # send the PC-only public data (gazette reports) to the cloud job that feeds the phone app
        "mobile_publish": LEGACY_ARCHIVE.exists(),
    }


def settings():
    s = _defaults()
    try:
        s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        try:
            LOCAL.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return s


def save_setting(key, value):
    """change one setting in settings.json (and in memory) - used by the windows' auto-update option"""
    S[key] = value
    try:
        cur = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {}
    cur[key] = value
    LOCAL.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


S = settings()
ARCHIVE = Path(S["archive"])
CAPT_DIR = ARCHIVE / "أداة ترسيات CAPT"
GULF_DIR = ARCHIVE / "دليل مناقصات الخليج"
AWARDS_XLSX = ARCHIVE / "CAPT Winning Bids from 2006.xlsx"
for _d in (ARCHIVE, CAPT_DIR, GULF_DIR, ARCHIVE / "CAPT MOM"):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
# a fresh PC starts from the awards file shipped in the installer
if not AWARDS_XLSX.exists():
    seed = res_dir() / "seed" / AWARDS_XLSX.name
    if seed.exists():
        try:
            shutil.copy2(seed, AWARDS_XLSX)
        except OSError:
            pass
