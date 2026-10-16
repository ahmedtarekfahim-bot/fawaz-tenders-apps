# -*- coding: utf-8 -*-
"""Diagnostics (no passwords printed): the program's saved sessions and what each account may do."""
import os, json
from pathlib import Path
local = Path(os.environ["LOCALAPPDATA"]) / "FAWAZ Tenders"
try:
    for k, s in json.loads((local / "desktop sessions.json").read_text(encoding="utf-8")).items():
        print("session:", s.get("u"), "admin" if s.get("admin") else "", sorted(s.get("perms") or []))
except Exception as e:
    print("sessions:", e)
st = json.loads((local / "settings.json").read_text(encoding="utf-8"))
print("settings keys:", sorted(k for k in st if "pass" not in k and "key" not in k and "topic" not in k))
print("capt account saved:", bool(st.get("capt_user")), "| gazette account saved:", bool(st.get("gz_user")))
m = Path(st.get("archive", "")) / "متابعة فواز" / "phone users.json"
for u, d in json.loads(m.read_text(encoding="utf-8"))["users"].items():
    print("account:", u, "admin" if d.get("admin") else "", d.get("perms"), "pw kept" if d.get("pw") else "")
