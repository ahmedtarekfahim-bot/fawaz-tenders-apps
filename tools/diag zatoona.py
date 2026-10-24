# -*- coding: utf-8 -*-
"""Runs one الزتونة search the way the program does and prints where the report went."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import zatoona

q = " ".join(sys.argv[1:]) or "مناقصة و ك م 22/2025/2026 وزارة الكهرباء بطاريات محطات التحويل"
t = time.time()
j = zatoona.start(q, "test", hint="الترسية والمقاول الحالي والأسعار", wait=True)
print("state:", j.get("state"), "| msg:", j.get("msg"), "| seconds:", int(time.time() - t))
print("file:", j.get("path"))
if j.get("state") == "done":
    print(Path(j["path"]).read_text(encoding="utf-8")[:1500])
