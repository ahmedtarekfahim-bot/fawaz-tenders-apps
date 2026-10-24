# -*- coding: utf-8 -*-
"""One tender's summary: which files were read and every point it picked (to check nothing comes from other tenders)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import tender_summary as ts

iid = int(sys.argv[1]) if len(sys.argv) > 1 else 5332
r = ts.summarize(iid, print)
print("folder:", r["folder"])
print("files read:", r["files"], "| pages:", r["pages"])
for title, pts in ts._last_sections:
    for p in pts:
        print(f"[{title}] {p['file']} p{p['page']}: {p['text'][:150]}")
