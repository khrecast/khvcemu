"""Screenshot the launcher's tabs for the website (Windows only).

    python tools/launcher_screenshots.py [--all] [output folder, default site/assets]

Opens the launcher on screen for a few seconds and captures each tab with Windows'
PrintWindow (ordinary screen grabs of a Tk window come out blank here). It runs from a
temporary profile holding copies of your save states, so the pictures show your newest save
but no personal paths or settings, and nothing is written to your real profile. Writes the
four pictures the website uses, launcher_play/saves/options/sound.png; --all also writes
launcher_controls.png, launcher_speed.png and launcher_advanced.png (not used on the site: check them before
putting them in site/assets, which is published as a whole).
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def capture(window, path):
    """Save what a Tk window (root or Toplevel) shows, title bar included."""
    import ctypes.wintypes as wt
    import numpy as np
    import pygame
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    window.update()
    time.sleep(0.4)
    window.update()
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(hwnd, mdc, 2)                  # PW_RENDERFULLCONTENT
    bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    if not ok:
        raise RuntimeError("PrintWindow failed")
    rgb = np.frombuffer(buf.raw, np.uint8).reshape(h, w, 4)[:, :, [2, 1, 0]]
    pygame.image.save(pygame.surfarray.make_surface(rgb.transpose(1, 0, 2).copy()), path)
    print(f"{path}  {w}x{h}")


def main(out: str, everything: bool = False):
    if sys.platform != "win32":
        sys.exit("This uses Windows' PrintWindow; on other systems take the screenshots by hand.")
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)    # real pixels, not scaled
    except Exception:
        pass
    sys.path.insert(0, ROOT)
    from khvcemu.paths import folder_name, game_data_dir
    real = game_data_dir(ROOT)                        # before HOME is pointed elsewhere
    tmp = tempfile.mkdtemp(prefix="khv_shots_")
    try:
        os.environ["HOME"] = os.environ["USERPROFILE"] = tmp
        data = os.path.join(tmp, ".khvcemu", folder_name(ROOT))   # where the launcher will look
        if os.path.isdir(os.path.join(real, "states")):
            shutil.copytree(os.path.join(real, "states"), os.path.join(data, "states"))
        os.makedirs(os.path.join(data, "files"), exist_ok=True)
        if os.path.isfile(os.path.join(real, "files", "savegame.dat")):
            shutil.copy(os.path.join(real, "files", "savegame.dat"), os.path.join(data, "files", "savegame.dat"))
        # the Options tab lists the screenshot folder: show a few of the frames F12 saved here (khvcemu_*.png in the
        # repository folder, if there are any) from the profile's own Pictures/khvcemu, which is the default folder
        import glob
        shots = os.path.join(tmp, "Pictures", "khvcemu")
        os.makedirs(shots, exist_ok=True)
        for f in sorted(glob.glob(os.path.join(ROOT, "khvcemu_*.png")))[-3:]:
            shutil.copy2(f, shots)
        with open(os.path.join(tmp, ".khvcemu", "launcher.json"), "w") as f:
            json.dump({"dump": ROOT, "tab": "play"}, f)

        sys.path.insert(0, ROOT)
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import tkinter as tk
        from khvcemu import launcher as L
        L.save_config = lambda c: None                     # never write anything
        L.missing_packages = lambda: []
        root = tk.Tk()
        app = L.Launcher(root)
        root.geometry("+40+40")
        os.makedirs(out, exist_ok=True)
        for key in ("play", "saves", "options", "sound") + (("controls",) if everything else ()):
            app.tabs.select(app.tab_frames[key])
            capture(root, os.path.join(out, f"launcher_{key}.png"))
        if everything:
            app.tabs.select(app.tab_frames["options"])
            app.open_speed_window()
            app.speed_win.geometry("+700+60")
            capture(app.speed_win, os.path.join(out, "launcher_speed.png"))
            app.close_speed_window()
            app.open_advanced()
            app.adv_win.geometry("+700+60")
            capture(app.adv_win, os.path.join(out, "launcher_advanced.png"))
            app.close_advanced()
        root.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--all"]
    main(args[0] if args else os.path.join(ROOT, "site", "assets"), everything="--all" in sys.argv[1:])
