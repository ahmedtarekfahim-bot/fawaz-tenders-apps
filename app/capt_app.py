# -*- coding: utf-8 -*-
"""FAWAZ CAPT Awards.exe - Kuwait awards (CAPT winning bids) + CAPT minutes search.
No arguments = open the program in the browser. Any capt_tool command also works:
  "FAWAZ CAPT Awards.exe" update | index | search "..." | report "..." | serve --nobrowser 1
"""
import sys
import capt_tool

if __name__ == "__main__":
    capt_tool.main(sys.argv[1:] or ["serve"])
