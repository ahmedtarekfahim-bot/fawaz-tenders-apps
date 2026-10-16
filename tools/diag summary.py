# -*- coding: utf-8 -*-
"""Runs the tender summary (and a BNB into a temp folder) on one real open CAPT tender and prints what happens."""
import sys, os, traceback, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import gulf_directory as gd, tender_summary as ts

con = gd.db()
row = con.execute("SELECT id, number, org, subject, official FROM items WHERE country='KW' AND status='مطروحة' "
                  "AND official LIKE '%capt.gov.kw%' ORDER BY closing DESC LIMIT 1").fetchone()
con.close()
iid = int(sys.argv[1]) if len(sys.argv) > 1 else row["id"]
print("item", iid, row["number"], row["org"], row["subject"][:80])
try:
    d = gd.item_docs(iid)
    print("docs listed:", [(x.get("label"), bool(x.get("url"))) for x in d["docs"]][:10])
    r = ts.summarize(iid, print)
    print("SUMMARY OK:", {k: r[k] for k in ("files", "pages", "found")})
except Exception:
    traceback.print_exc()
try:
    out = Path(tempfile.gettempdir()) / "gcc bnb test"
    out.mkdir(exist_ok=True)
    b = ts.make_bnb(iid, print, out_dir=out)
    print("BNB OK:", b.get("bnb"), b.get("pdf"))
except Exception:
    traceback.print_exc()
