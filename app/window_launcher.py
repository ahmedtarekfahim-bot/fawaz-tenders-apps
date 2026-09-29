# -*- coding: utf-8 -*-
"""Open a program in its own window (not a browser tab).

The local server keeps running in a separate background process (so the automatic updates go on
after the window is closed); the window itself is a native Edge WebView2 window via pywebview.
Fallbacks: Edge in app mode (no tabs / address bar), then the default browser.
"""
import os, sys, time, socket, subprocess, shutil, webbrowser
from pathlib import Path

DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_background(bg_args):
    """start the server as its own process: <exe> <bg_args> (or python <script> <bg_args> from source)"""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, *bg_args]
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        cmd = [str(pyw if pyw.exists() else sys.executable), str(Path(sys.argv[0]).resolve()), *bg_args]
    subprocess.Popen(cmd, cwd=str(Path(cmd[0]).parent), creationflags=DETACHED, close_fds=True)


def edge_path():
    for p in (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe")):
        if os.path.exists(p):
            return p
    return shutil.which("msedge")


def open_window(title, port, bg_args, width=1440, height=920):
    url = f"http://127.0.0.1:{port}/"
    if not port_open(port):
        start_background(bg_args)
        for _ in range(100):                      # up to ~25 s on a slow first start
            if port_open(port):
                break
            time.sleep(0.25)
    try:
        import webview
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.create_window(title, url, width=width, height=height, min_size=(900, 600), text_select=True)
        webview.start(private_mode=False, storage_path=os.path.join(
            os.environ.get("LOCALAPPDATA", str(Path.home())), "FAWAZ Tenders", "webview"))
        return
    except Exception:                             # noqa: BLE001 - no WebView2 / pywebview: next option
        pass
    edge = edge_path()
    if edge:
        subprocess.Popen([edge, f"--app={url}", f"--window-size={width},{height}"], close_fds=True)
        return
    webbrowser.open(url)
