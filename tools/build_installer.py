"""Build ONE Windows installer that contains everything: Python, the libraries, ffmpeg,
khvcemu and the game files.

    python tools/build_installer.py [--target win64|win32|all] [--game DIR] [--out DIR]

Result: dist/KH-ReCast-Windows-x64.exe (or ...-x86.exe for 32-bit Windows), a self-extracting file. Double-click it; it asks
once, installs for the current user only (no administrator rights), adds Start Menu and
desktop shortcuts and an entry in Settings > Apps, and offers to start the game.

--game is the folder holding mif/ and mod/ (default: this project folder). The game files
are put into the installer; they are never added to git (dist/ and build/ are ignored).

Needs on the building PC: Windows, Python 3.10+ with tkinter (the same Python version is
bundled), 7-Zip (7z.exe), and internet access the first time (Python, ffmpeg and the 7-Zip
self-extractor stub are downloaded and kept in build/installer/cache).
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build", "installer")
CACHE = os.path.join(BUILD, "cache")
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
NAME = "Kingdom Hearts Re:Cast"

SETUP_PS1 = r'''# Installs Kingdom Hearts Re:Cast for the current user. Run by the installer exe.
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\khvcemu"),
    [string]$StartMenuDir = (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [switch]$Silent, [switch]$NoRegistry
)
$ErrorActionPreference = "Stop"
# test hooks: redirect everything and stay silent (unset in normal use)
if ($env:KHV_TEST_ROOT) {
    $InstallDir = Join-Path $env:KHV_TEST_ROOT "install"
    $StartMenuDir = Join-Path $env:KHV_TEST_ROOT "startmenu"
    $DesktopDir = Join-Path $env:KHV_TEST_ROOT "desktop"
    $Silent = $true; $NoRegistry = $true
}
Add-Type -AssemblyName System.Windows.Forms
function Ask($text, $buttons = "OK", $icon = "Information") {
    if ($Silent) { return "Yes" }
    return [System.Windows.Forms.MessageBox]::Show($text, "__NAME__", $buttons, $icon).ToString()
}
$src = Join-Path $PSScriptRoot "app"
$marker = Join-Path $InstallDir "uninstall.ps1"
try {
    if ((Test-Path $InstallDir) -and (Get-ChildItem $InstallDir -Force | Select-Object -First 1)) {
        if (-not (Test-Path $marker)) {
            throw "The folder $InstallDir already exists and is not a Kingdom Hearts Re:Cast install, so it was left alone."
        }
        Remove-Item $InstallDir -Recurse -Force          # an earlier install of this program: replace it
    }
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    & robocopy $src $InstallDir /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the files failed (robocopy code $LASTEXITCODE)." }
    Copy-Item (Join-Path $PSScriptRoot "uninstall.ps1") $marker -Force

    $pyw = Join-Path $InstallDir "python\pythonw.exe"
    $work = Join-Path $InstallDir "khvcemu"
    $ico = Join-Path $work "khvcemu\assets\recast_icon.ico"
    $sh = New-Object -ComObject WScript.Shell
    foreach ($dir in @($StartMenuDir, $DesktopDir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        $lnk = $sh.CreateShortcut((Join-Path $dir "__NAME_FILE__.lnk"))
        $lnk.TargetPath = $pyw
        $lnk.Arguments = "-m khvcemu.launcher"
        $lnk.WorkingDirectory = $work
        $lnk.IconLocation = $ico
        $lnk.Description = "__NAME__"
        $lnk.Save()
    }
    if (-not $NoRegistry) {
        $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\khvcemu"
        New-Item -Path $key -Force | Out-Null
        $uninst = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$marker`""
        $vals = @{ DisplayName = "__NAME__"; DisplayVersion = "__VERSION__"; InstallLocation = $InstallDir;
                   DisplayIcon = $ico; UninstallString = $uninst; Publisher = "khvcemu" }
        foreach ($k in $vals.Keys) { Set-ItemProperty -Path $key -Name $k -Value $vals[$k] }
        Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord
        Set-ItemProperty -Path $key -Name NoRepair -Value 1 -Type DWord
    }
    if ((Ask "__NAME__ is installed.`n`nStart it now?" "YesNo" "Question") -eq "Yes" -and -not $Silent) {
        Start-Process $pyw -ArgumentList "-m khvcemu.launcher" -WorkingDirectory $work
    }
} catch {
    Ask ("Installation failed:`n`n" + $_.Exception.Message) "OK" "Error" | Out-Null
    exit 1
}
'''

INSTALL_CMD = r'''@echo off
title Installing __NAME__
echo Installing __NAME__. This takes about a minute, please wait...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
exit /b %errorlevel%
'''

UNINSTALL_PS1 = r'''# Removes Kingdom Hearts Re:Cast. Your saves and settings (in your user folder) stay unless you ask.
param(
    [string]$StartMenuDir = (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [switch]$Silent, [switch]$NoRegistry, [switch]$KeepFiles
)
Add-Type -AssemblyName System.Windows.Forms
$dir = $PSScriptRoot
if (-not $Silent) {
    $r = [System.Windows.Forms.MessageBox]::Show("Remove __NAME__ from this PC?`n`nYour saves and settings are kept.",
        "__NAME__", "YesNo", "Question")
    if ($r -ne "Yes") { exit 0 }
}
foreach ($d in @($StartMenuDir, $DesktopDir)) { Remove-Item (Join-Path $d "__NAME_FILE__.lnk") -Force -ErrorAction SilentlyContinue }
if (-not $NoRegistry) {
    Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\khvcemu" -Recurse -Force -ErrorAction SilentlyContinue
}
if (-not $KeepFiles) {
    # this script lives in the folder being deleted, so a detached command finishes the job
    Start-Process cmd.exe -WindowStyle Hidden -ArgumentList "/c ping -n 3 127.0.0.1 >nul & rmdir /s /q `"$dir`""
}
'''


def project_version() -> str:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', open(os.path.join(ROOT, "khvcemu", "__init__.py"), encoding="utf-8").read(), re.M)
    return m.group(1) if m else "0"


def find_7zip() -> str:
    for cand in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if cand and os.path.isfile(cand):
            return cand
    sys.exit("7-Zip (7z.exe) was not found. Install it from https://www.7-zip.org/")


def find_sfx(sevenz: str) -> str:
    """The self-extracting stub. The 7z.sfx that comes with 7-Zip ignores the 'run this after
    extracting' instructions; 7zSD.sfx from the LZMA SDK follows them. It can only run a file
    that is inside the package (RunProgram="install.cmd"), not a program on the PATH."""
    sfx = os.path.join(CACHE, "7zSD.sfx")
    if not os.path.isfile(sfx):
        sdk = download("https://www.7-zip.org/a/lzma2301.7z", "lzma2301.7z")
        subprocess.run([sevenz, "e", "-y", "-bso0", "-bsp0", f"-o{CACHE}", sdk, "bin/7zSD.sfx"], check=True)
    return sfx


MANIFEST = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
    <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
  </requestedPrivileges></security></trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application>
    <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"/>
    <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"/>
    <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"/>
    <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
    <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
  </application></compatibility>
</assembly>
"""


def with_manifest(stub: str) -> str:
    """A copy of the stub carrying an application manifest. Without one, Windows treats it as
    a legacy installer and shows the 'Program Compatibility Assistant: this program might
    not have installed correctly' box afterwards. Done before the archive is attached,
    because rewriting a file's resources would drop data appended to it."""
    import ctypes
    from ctypes import wintypes as w
    out = os.path.join(CACHE, "7zSD-manifest.sfx")
    shutil.copyfile(stub, out)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.BeginUpdateResourceW.restype = w.HANDLE
    k.BeginUpdateResourceW.argtypes = [w.LPCWSTR, w.BOOL]
    k.UpdateResourceW.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, w.WORD, ctypes.c_void_p, w.DWORD]
    k.EndUpdateResourceW.argtypes = [w.HANDLE, w.BOOL]
    h = k.BeginUpdateResourceW(out, False)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    ok = k.UpdateResourceW(h, 24, 1, 0, MANIFEST, len(MANIFEST))      # RT_MANIFEST, id 1, language-neutral
    if not (ok and k.EndUpdateResourceW(h, False)):
        raise ctypes.WinError(ctypes.get_last_error())
    return out


def download(url: str, name: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.isfile(path):
        print("downloading", url)
        req = urllib.request.Request(url, headers={"User-Agent": "khvcemu-build"})
        with urllib.request.urlopen(req) as r, open(path + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(path + ".part", path)
    return path


def requirement_lines() -> list:
    """The runtime requirements from requirements.txt, one string each (comments removed)."""
    out = []
    for line in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line:
            out.append(line)
    return out


def pip_install(target: str, platforms: list):
    """Install the requirements as wheels for another platform (this PC can build for them all).
    --no-deps is safe: unicorn, pygame-ce and numpy need nothing else on Python 3.10+."""
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
           "--only-binary=:all:", "--no-deps", "--target", target,
           "--python-version", "%d.%d" % sys.version_info[:2], "--implementation", "cp"]
    for p in platforms:
        cmd += ["--platform", p]
    subprocess.run(cmd + requirement_lines(), check=True)


def trim_site(site: str):
    """Drop what a player never needs (tests, examples, docs) from installed packages."""
    for d, dirs, _ in os.walk(site):
        for name in list(dirs):
            if name in ("tests", "test", "__pycache__", "examples", "docs"):
                shutil.rmtree(os.path.join(d, name), ignore_errors=True)
                dirs.remove(name)


def win32_tk(sevenz: str, v: str) -> str:
    """32-bit Tcl/Tk (the embeddable Python has no tkinter, and this PC's Python is 64-bit).
    Unpacks python.org's 32-bit installer: its packages sit in an attached cabinet, and a
    bundle manifest maps their anonymous names back to tcltk.msi, which Windows Installer
    can then extract (/a) without installing anything."""
    out = os.path.join(CACHE, f"tk32-{v}")
    if os.path.isfile(os.path.join(out, "DLLs", "_tkinter.pyd")):
        return out
    exe = download(f"https://www.python.org/ftp/python/{v}/python-{v}.exe", f"python-{v}-x86-installer.exe")
    work = os.path.join(CACHE, "tk32-work")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    q = ["-y", "-bso0", "-bsp0"]
    subprocess.run([sevenz, "x", *q, f"-o{work}\\ux", exe], check=True)          # the bundle manifest ("0")
    listing = subprocess.run([sevenz, "l", "-t#", exe], capture_output=True, text=True, check=True).stdout
    cabs = [(int(m.group(1)), m.group(2)) for m in re.finditer(r"\s(\d+)\s+\d+\s+(\S+\.cab)\s*$", listing, re.M)]
    big = max(cabs)[1]
    subprocess.run([sevenz, "e", "-t#", *q, f"-o{work}\\cab", exe, big], check=True)
    subprocess.run([sevenz, "x", *q, f"-o{work}\\files", os.path.join(work, "cab", big)], check=True)
    manifest = open(os.path.join(work, "ux", "0"), encoding="utf-8-sig").read()
    m = re.search(r'<Payload Id="tcltk_AllUsers" FilePath="tcltk.msi"[^>]*SourcePath="([^"]+)"', manifest)
    if not m:
        sys.exit("Could not find tcltk.msi in the Python installer (its layout changed).")
    msi = os.path.join(work, "tcltk.msi")
    shutil.copy2(os.path.join(work, "files", m.group(1)), msi)
    shutil.rmtree(out, ignore_errors=True)
    subprocess.run(["msiexec", "/a", msi, "/qn", f"TARGETDIR={out}"], check=True)
    if not os.path.isfile(os.path.join(out, "DLLs", "_tkinter.pyd")):
        sys.exit("Extracting 32-bit Tcl/Tk failed.")
    shutil.rmtree(work, ignore_errors=True)
    return out


TARGETS = {
    "win64": dict(embed="amd64", pip_platform="win_amd64", exe="KH-ReCast-Windows-x64.exe",
                  ffmpeg=("ffmpeg-release-essentials.zip", FFMPEG_URL)),
    # Windows on 32-bit hardware. The only maintained 32-bit ffmpeg build is a community one
    # (GitHub: sudo-nautilus/FFmpeg-Builds-Win32, ffmpeg 6.0); the game needs only its decoders.
    "win32": dict(embed="win32", pip_platform="win32", exe="KH-ReCast-Windows-x86.exe",
                  ffmpeg=("ffmpeg-n6.0-win32-lgpl.zip",
                          "https://github.com/sudo-nautilus/FFmpeg-Builds-Win32/releases/download/latest/"
                          "ffmpeg-n6.0-latest-win32-lgpl-6.0.zip")),
}


def build_python(dest: str, target: str, sevenz: str):
    t = TARGETS[target]
    v = "%d.%d.%d" % sys.version_info[:3]
    z = download(f"https://www.python.org/ftp/python/{v}/python-{v}-embed-{t['embed']}.zip",
                 f"python-{v}-embed-{t['embed']}.zip")
    with zipfile.ZipFile(z) as zf:
        zf.extractall(dest)
    pth = glob.glob(os.path.join(dest, "python*._pth"))[0]
    zipname = os.path.basename(pth).replace("._pth", ".zip")
    with open(pth, "w", encoding="ascii", newline="\r\n") as f:
        f.write(f"{zipname}\n.\nLib\\site-packages\n..\\khvcemu\nimport site\n")
    # tkinter is not part of the embeddable Python: borrow it from a matching full install
    if target == "win32":
        tk = win32_tk(sevenz, v)
        for fn in os.listdir(os.path.join(tk, "DLLs")):
            shutil.copy2(os.path.join(tk, "DLLs", fn), dest)
        tkinter_dir = os.path.join(tk, "Lib", "tkinter")
    else:
        tkinter_dir = os.path.join(sys.base_prefix, "Lib", "tkinter")
        for fn in ("_tkinter.pyd", "tcl90.dll", "tcl9tk90.dll", "zlib1.dll", "libffi-8.dll"):
            src = os.path.join(sys.base_prefix, "DLLs", fn)
            if os.path.isfile(src):
                shutil.copy2(src, dest)
    site = os.path.join(dest, "Lib", "site-packages")
    os.makedirs(site, exist_ok=True)
    if not os.path.isdir(tkinter_dir):                  # pure Python, the same on every architecture
        tkinter_dir = os.path.join(sys.base_prefix, "Lib", "tkinter")
    shutil.copytree(tkinter_dir, os.path.join(site, "tkinter"),
                    ignore=shutil.ignore_patterns("__pycache__", "test*"))
    pip_install(site, [t["pip_platform"]])
    trim_site(site)


def build_ffmpeg(dest: str, target: str):
    name, url = TARGETS[target]["ffmpeg"]
    z = download(url, name)
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            base = os.path.basename(n)
            if base == "ffmpeg.exe" or (base in ("LICENSE", "README.txt") and n.count("/") == 1):
                with zf.open(n) as src, open(os.path.join(dest, "FFMPEG-" + base if base != "ffmpeg.exe" else base), "wb") as out:
                    shutil.copyfileobj(src, out)


def build_app(dest: str, game: str):
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(ROOT, "khvcemu"), os.path.join(dest, "khvcemu"), ignore=ignore)
    for fn in ("README.md", "CHANGELOG.md", "LICENSE", "requirements.txt"):
        shutil.copy2(os.path.join(ROOT, fn), dest)
    for sub in ("mif", "mod", "wonderland"):
        if os.path.isdir(os.path.join(game, sub)):
            shutil.copytree(os.path.join(game, sub), os.path.join(dest, sub))
    for f in glob.glob(os.path.join(game, "savegame*.dat")):
        shutil.copy2(f, dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", default=ROOT, help="folder containing mif/ and mod/ (default: this project)")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"), help="where to write the installer")
    ap.add_argument("--version", default=project_version())
    ap.add_argument("--target", choices=[*TARGETS, "all"], default="win64",
                    help="win64 (default), win32 (32-bit Windows), or all")
    ap.add_argument("--no-prompt", action="store_true", help="skip the 'Install?' question (unattended test builds)")
    args = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("The installer is a Windows program and has to be built on Windows.")
    game = os.path.abspath(args.game)
    if not (os.path.isdir(os.path.join(game, "mif")) and os.path.isdir(os.path.join(game, "mod"))):
        sys.exit(f"{game} does not contain mif/ and mod/ (the game files).")
    sevenz = find_7zip()
    sfx = with_manifest(find_sfx(sevenz))
    for target in (list(TARGETS) if args.target == "all" else [args.target]):
        print(f"=== {target}")
        build_target(args, target, game, sevenz, sfx)


def build_target(args, target: str, game: str, sevenz: str, sfx: str):
    STAGE = os.path.join(BUILD, "stage-" + target)
    shutil.rmtree(STAGE, ignore_errors=True)
    app = os.path.join(STAGE, "app")
    print("1/5 Python and libraries"); build_python(os.path.join(app, "python"), target, sevenz)
    print("2/5 khvcemu and the game files"); build_app(os.path.join(app, "khvcemu"), game)
    print("3/5 ffmpeg"); build_ffmpeg(os.path.join(app, "khvcemu", "bin"), target)
    print("4/5 install scripts")
    subs = {"__NAME__": NAME, "__NAME_FILE__": "Kingdom Hearts Re-Cast", "__VERSION__": args.version}
    for fn, text in (("setup.ps1", SETUP_PS1), ("uninstall.ps1", UNINSTALL_PS1), ("install.cmd", INSTALL_CMD)):
        for k, v in subs.items():
            text = text.replace(k, v)
        with open(os.path.join(STAGE, fn), "w", encoding="ascii" if fn.endswith(".cmd") else "utf-8-sig",
                  newline="\r\n") as f:
            f.write(text)

    print("5/5 compressing (this takes a few minutes)")
    os.makedirs(args.out, exist_ok=True)
    archive = os.path.join(BUILD, f"payload-{target}.7z")
    if os.path.exists(archive):
        os.remove(archive)
    subprocess.run([sevenz, "a", "-t7z", "-mx=9", "-m0=lzma2", "-ms=on", "-bso0", "-bsp0", archive, "*"],
                   cwd=STAGE, check=True)
    prompt = "" if args.no_prompt else (
        f'BeginPrompt="Install {NAME} on this PC?\\n\\nIt installs for your user account only '
        'and includes everything it needs: Python, ffmpeg and the game files."\n')
    config = (';!@Install@!UTF-8!\n'
              f'Title="{NAME}"\n' + prompt +
              'RunProgram="install.cmd"\n'
              ';!@InstallEnd@!\n')
    exe = os.path.join(args.out, TARGETS[target]["exe"])
    with open(exe, "wb") as out:
        for part in (open(sfx, "rb").read(), config.encode("utf-8"), open(archive, "rb").read()):
            out.write(part)
    print(f"\nBuilt {exe}  ({os.path.getsize(exe) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
