# -*- coding: utf-8 -*-
"""Checks that the program can start Claude Code by itself (the same way the routines button does):
finds it, checks the sign-in, runs one tiny prompt in the background mode the routines use."""
import sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import routines

exe = routines.claude_exe()
print("Claude Code:", exe or "مش موجود")
print("signed in:", routines.claude_signed_in(force=True))
if exe:
    r = subprocess.run([exe, "-p", "رد بكلمة واحدة بس: تمام", "--permission-mode", "auto"], capture_output=True, timeout=180,
                       env=routines._clean_env(), cwd=r"D:\شغل فواز")
    print("exit:", r.returncode)
    print("reply:", r.stdout.decode("utf-8", "ignore").strip()[:200], r.stderr.decode("utf-8", "ignore").strip()[:300])
