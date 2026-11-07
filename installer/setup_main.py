# -*- coding: utf-8 -*-
"""FAWAZ Tenders Setup.exe - installs / updates / uninstalls both programs (per user, no admin).

  Setup.exe                 normal install with a small window
  Setup.exe /S [/restart]   silent install (used by the automatic program update)
  uninstall.exe /uninstall  remove programs, shortcuts, start-up entry (the data is kept)

Installs to %LOCALAPPDATA%\\Programs\\FAWAZ Tenders, adds Desktop + Start-menu shortcuts, a
Start-up entry for the Gulf directory (background, for its automatic updates) and an entry in
Windows "Installed apps".
"""
import os, sys, json, shutil, zipfile, subprocess, re, time
from pathlib import Path

APP = "FAWAZ Tenders"
PUBLISHER = "FAWAZ Trading & Engineering Services"
TARGET = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / APP
UNINST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FAWAZTenders"
EXES = {"capt": "FAWAZ CAPT Awards.exe", "gulf": "FAWAZ Gulf Directory.exe"}
NAMES = {"capt": "برنامج ترسيات CAPT", "gulf": "دليل مناقصات الخليج"}
PORTS = (8765, 8766)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def res(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def version():
    try:
        return json.loads(res("_build_info.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return "0"


def folders():
    from win32com.shell import shell, shellcon
    get = lambda csidl: Path(shell.SHGetFolderPath(0, csidl, None, 0))
    return {"desktop": get(shellcon.CSIDL_DESKTOPDIRECTORY), "programs": get(shellcon.CSIDL_PROGRAMS) / APP,
            "startup": get(shellcon.CSIDL_STARTUP)}


def make_lnk(path, target, args="", desc=""):
    import pythoncom
    from win32com.shell import shell
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(str(target))
    link.SetArguments(args)
    link.SetWorkingDirectory(str(Path(target).parent))
    link.SetDescription(desc)
    link.SetIconLocation(str(target), 0)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 0)


def stop_running():
    """close the installed programs and the old script versions (they hold the same ports)"""
    for exe in EXES.values():
        subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True, creationflags=NOWIN)
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=NOWIN).stdout
        pids = {m.group(2) for m in re.finditer(r"127\.0\.0\.1:(%s)\s+\S+\s+LISTENING\s+(\d+)" % "|".join(map(str, PORTS)), out)}
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, creationflags=NOWIN)
    except OSError:
        pass
    time.sleep(1.5)


def legacy_cleanup(f):
    """the script versions used on the first PC: logon task + start-up shortcut"""
    subprocess.run(["schtasks", "/Delete", "/TN", "FAWAZ Gulf Tenders Directory", "/F"], capture_output=True, creationflags=NOWIN)
    for p in (f["startup"] / "Gulf tenders directory.lnk",):
        try:
            p.unlink()
        except OSError:
            pass


def copy_over(src, dst):
    """file by file; a file still locked keeps its old copy instead of stopping the whole install"""
    failed = []
    for f in src.rglob("*"):
        to = dst / f.relative_to(src)
        if f.is_dir():
            to.mkdir(parents=True, exist_ok=True)
            continue
        for _ in range(5):
            try:
                to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, to)
                break
            except OSError:
                time.sleep(1)
        else:
            failed.append(to)
    return failed


def swap_in(new):
    """the old folder is never deleted before the new one is in place: rename old -> (old), new -> target;
    when something keeps the old folder locked, copy over it. Ends with both programs present."""
    old = TARGET.with_name(APP + " (old)")
    shutil.rmtree(old, ignore_errors=True)
    for _ in range(15):
        try:
            if TARGET.exists():
                TARGET.rename(old)
            new.rename(TARGET)
            break
        except OSError:
            stop_running()
            time.sleep(1)
    else:
        copy_over(new, TARGET)
    if new.exists() and not TARGET.exists():
        new.rename(TARGET)
    missing = [e for e in EXES.values() if not (TARGET / e).exists()]
    if missing:                         # never leave the user without a program
        with zipfile.ZipFile(res("payload.zip")) as z:
            z.extractall(TARGET)
    shutil.rmtree(new, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    missing = [e for e in EXES.values() if not (TARGET / e).exists()]
    if missing:
        raise RuntimeError("ملفات ناقصة بعد التسطيب: " + "، ".join(missing))


def one_setup():
    """only one Setup at a time (both programs may start the same update): -> lock handle or None"""
    import msvcrt
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    fh = open(TARGET.parent / "FAWAZ Tenders setup.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh
    except OSError:
        fh.close()
        return None


def register(ver):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINST_KEY) as k:
        for name, val in {"DisplayName": "FAWAZ Tenders (ترسيات CAPT + دليل مناقصات الخليج)", "DisplayVersion": ver,
                          "Publisher": PUBLISHER, "InstallLocation": str(TARGET),
                          "DisplayIcon": str(TARGET / EXES["gulf"]),
                          "UninstallString": f'"{TARGET / "uninstall.exe"}" /uninstall'}.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def install(autostart=True, log=print):
    ver = version()
    f = folders()
    log("بقفل النسخ الشغالة ...")
    stop_running()
    legacy_cleanup(f)
    log("بنسخ الملفات ...")
    new = TARGET.with_name(APP + " (new)")
    shutil.rmtree(new, ignore_errors=True)
    with zipfile.ZipFile(res("payload.zip")) as z:
        z.extractall(new)
    swap_in(new)
    try:
        shutil.copy2(sys.executable, TARGET / "uninstall.exe")
    except OSError:                     # uninstall.exe itself running the update
        pass
    log("بعمل الاختصارات ...")
    for key in ("gulf", "capt"):
        exe = TARGET / EXES[key]
        make_lnk(f["desktop"] / f"{NAMES[key]}.lnk", exe, desc=NAMES[key])
        make_lnk(f["programs"] / f"{NAMES[key]}.lnk", exe, desc=NAMES[key])
    make_lnk(f["programs"] / "إزالة FAWAZ Tenders.lnk", TARGET / "uninstall.exe", "/uninstall")
    start = f["startup"] / f"{NAMES['gulf']} (خلفية).lnk"
    if autostart:
        make_lnk(start, TARGET / EXES["gulf"], "--background", "تحديث دليل المناقصات تلقائي")
    elif start.exists():
        start.unlink()
    register(ver)
    log(f"اتسطب الإصدار {ver}")
    return ver


def uninstall(log=print):
    f = folders()
    stop_running()
    for key in ("gulf", "capt"):
        for p in (f["desktop"] / f"{NAMES[key]}.lnk", f["programs"] / f"{NAMES[key]}.lnk"):
            try:
                p.unlink()
            except OSError:
                pass
    for p in (f["startup"] / f"{NAMES['gulf']} (خلفية).lnk",):
        try:
            p.unlink()
        except OSError:
            pass
    shutil.rmtree(f["programs"], ignore_errors=True)
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINST_KEY)
    except OSError:
        pass
    # the running uninstall.exe lives in TARGET: remove the folder once it has exited
    subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{TARGET}"', shell=True, creationflags=NOWIN)
    log("اتشال البرنامج (الداتا فضلت زي ما هي)")


def gui():
    import tkinter as tk
    from tkinter import messagebox
    ver = version()
    root = tk.Tk()
    root.title(f"تسطيب FAWAZ Tenders {ver}")
    root.geometry("520x330")
    root.resizable(False, False)
    tk.Label(root, text="FAWAZ Tenders", font=("Segoe UI", 18, "bold"), fg="#0f5c4d").pack(pady=(18, 4))
    tk.Label(root, text=f"الإصدار {ver}", font=("Segoe UI", 10)).pack()
    tk.Label(root, justify="right", font=("Segoe UI", 11), wraplength=470, text=(
        "هيتسطب برنامجين:\n"
        "• دليل مناقصات الخليج (الكويت - السعودية - الإمارات)\n"
        "• برنامج ترسيات CAPT (ترسيات ومحاضر الجهاز المركزي)\n"
        "مع اختصارات على سطح المكتب وقايمة ابدأ، والبرنامجين بيحدّثوا نفسهم من النت.")).pack(pady=12, padx=20, anchor="e")
    auto = tk.BooleanVar(value=True)
    tk.Checkbutton(root, text="شغّل الدليل مع ويندوز (عشان التحديث التلقائي)", variable=auto,
                   font=("Segoe UI", 10)).pack(anchor="e", padx=24)
    status = tk.Label(root, text="", font=("Segoe UI", 10), fg="#555")
    status.pack(pady=8)

    def say(m):
        status.config(text=m)
        root.update()

    def go():
        btn.config(state="disabled")
        try:
            install(auto.get(), say)
        except Exception as e:          # noqa: BLE001
            messagebox.showerror("خطأ", f"التسطيب فشل:\n{e}")
            btn.config(state="normal")
            return
        if messagebox.askyesno("خلص", "البرنامجين اتسطبوا.\nأفتح دليل مناقصات الخليج دلوقتي؟"):
            subprocess.Popen([str(TARGET / EXES["gulf"])], cwd=str(TARGET))
        root.destroy()

    btn = tk.Button(root, text="تسطيب", font=("Segoe UI", 11, "bold"), bg="#16806b", fg="white", width=16, command=go)
    btn.pack(pady=6)
    root.mainloop()


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "/uninstall" in args:
        if "/s" in args:
            uninstall()
            return
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        if messagebox.askyesno("إزالة", "تشيل برنامج ترسيات CAPT ودليل مناقصات الخليج؟\n(الداتا والتقارير هتفضل زي ما هي)"):
            uninstall()
            messagebox.showinfo("إزالة", "اتشال.")
        return
    lock = one_setup()
    if lock is None:                    # another Setup is already installing
        if "/s" not in args:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo("تسطيب", "فيه تسطيب تاني شغال دلوقتي، استنى دقيقة وجرّب تاني.")
        return
    if "/s" in args:
        install(autostart=True, log=lambda m: None)
        if "/restart" in args:
            subprocess.Popen([str(TARGET / EXES["gulf"]), "--background"], cwd=str(TARGET))
        return
    gui()


if __name__ == "__main__":
    main()
