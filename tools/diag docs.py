# -*- coding: utf-8 -*-
"""Shows what happens when the program downloads one tender's documents (CAPT login, each file)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import gulf_directory as gd, tender_docs as td

iid = int(sys.argv[1]) if len(sys.argv) > 1 else 5332
d = gd.item_docs(iid)
for x in d["docs"]:
    print("doc:", x.get("label"), "|", (x.get("url") or "")[:120], "| local" if x.get("local") else "")
print("capt account:", td.account())
try:
    td.login()
    print("capt login: OK")
except Exception as e:
    print("capt login FAILED:", type(e).__name__, str(e)[:200])
r = gd.download_docs(iid)
for f in r["files"]:
    print("file:", f)
print("locked:", r["locked"])
