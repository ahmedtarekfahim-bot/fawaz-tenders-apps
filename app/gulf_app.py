# -*- coding: utf-8 -*-
"""FAWAZ Gulf Directory.exe - Kuwait / Saudi / UAE tenders & projects directory.
No arguments = open the program in its own window (the server runs in the background).
--background = server only (Windows start-up) so the automatic updates keep running.
Any gulf_directory command also works (update, search ...).
"""
import sys



def full_program():
    """the full program (collects from the sites, the owner's files, routines) runs only on the owner's PC;
    every other PC opens the sealed subscriber app: no account / an ended subscription = no data at all"""
    import desktop_auth
    import fawaz_config as cfg
    return desktop_auth.master_mode() or bool(cfg.S.get("full_program"))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        import window_launcher
        if full_program():
            window_launcher.open_window("GCC Tenders - دليل مناقصات الخليج", 8766, ["--background"])
        else:
            import mobile_export
            window_launcher.open_url("GCC Tenders - دليل مناقصات الخليج", mobile_export.PAGES)
    else:
        if args[0] == "--background" and not full_program():
            sys.exit(0)                            # subscriber PCs: nothing runs in the background
        import gulf_directory
        if args[0] == "--background":
            args = ["serve", "--nobrowser", "1"]
        gulf_directory.main(args)
