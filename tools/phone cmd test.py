# -*- coding: utf-8 -*-
"""Plays the phone: sends one signed request (docs / pdf / sum) for an item to the running PC program
through the phone channel and waits for the sealed file to come back, then says what arrived."""
import sys, json, time, hmac, hashlib, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import phone_lock as pl

kind = sys.argv[1] if len(sys.argv) > 1 else "docs"
iid = sys.argv[2] if len(sys.argv) > 2 else "5332"
user = sys.argv[3] if len(sys.argv) > 3 else "ahmed"
ts = str(int(time.time()))
sig = hmac.new(pl.routines_key().encode(), f"{kind}|{user}|{iid}|{ts}".encode(), hashlib.sha256).hexdigest()[:32]
urllib.request.urlopen(urllib.request.Request(pl.NTFY + pl.topic(), data=f"{kind}|{user}|{iid}|{ts}|{sig}".encode(), method="POST"), timeout=20).read()
print("sent", kind, iid, "- waiting for the PC...")
since, name = int(ts) - 5, sig[:16] + ".bin"
for t in range(60):
    time.sleep(5)
    try:
        lines = urllib.request.urlopen(f"{pl.NTFY}{pl.topic()}-files/json?poll=1&since={since}", timeout=20).read().decode().splitlines()
    except Exception as e:
        print("poll error", e)
        continue
    for m in (json.loads(x) for x in lines if x.strip()):
        if (m.get("attachment") or {}).get("name") == name:
            raw = urllib.request.urlopen(m["attachment"]["url"], timeout=60).read()
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = hashlib.sha256((pl.routines_key() + "|file").encode()).digest()
            data = AESGCM(key).decrypt(raw[:12], raw[12:], None)
            print(f"ARRIVED after {(t + 1) * 5}s: {len(data)} bytes, starts with {data[:4]!r}")
            if data[:4] != b"PK\x03\x04" and data[:4] != b"%PDF":
                print(data[:400].decode("utf-8", "ignore"))
            sys.exit(0)
print("NOTHING came back in 5 minutes")
