# -*- coding: utf-8 -*-
"""FAWAZ CAPT Awards.exe - Kuwait awards (CAPT winning bids) + CAPT minutes search.
No arguments = open the program in its own window (the server runs in the background).
Any capt_tool command also works:
  "FAWAZ CAPT Awards.exe" update | index | search "..." | report "..." | serve --nobrowser 1
"""
import sys

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        import window_launcher
        window_launcher.open_window("برنامج ترسيات CAPT", 8765, ["serve", "--nobrowser", "1"])
    else:
        import capt_tool
        capt_tool.main(args)
