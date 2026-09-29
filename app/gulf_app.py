# -*- coding: utf-8 -*-
"""FAWAZ Gulf Directory.exe - Kuwait / Saudi / UAE tenders & projects directory.
No arguments = open the program in its own window (the server runs in the background).
--background = server only (Windows start-up) so the automatic updates keep running.
Any gulf_directory command also works (update, search ...).
"""
import sys

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        import window_launcher
        window_launcher.open_window("دليل مناقصات الخليج", 8766, ["--background"])
    else:
        import gulf_directory
        if args[0] == "--background":
            args = ["serve", "--nobrowser", "1"]
        gulf_directory.main(args)
