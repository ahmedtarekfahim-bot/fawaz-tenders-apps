# -*- coding: utf-8 -*-
"""FAWAZ Gulf Directory.exe - Kuwait / Saudi / UAE tenders & projects directory.
No arguments = open it in the browser.  --background = run the server only (Windows start-up),
so the automatic updates keep running.  Any gulf_directory command also works (update, search ...).
"""
import sys
import gulf_directory

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = ["serve"]
    elif args[0] == "--background":
        args = ["serve", "--nobrowser", "1"]
    gulf_directory.main(args)
