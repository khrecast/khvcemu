"""Packs one Android download: the signed APK, the game files and a README.

  python android/tools/make_android_zip.py --apk build/android-release/app-arm64-v8a.apk --abi arm64-v8a --out dist/KH-ReCast-Android.zip
  python android/tools/make_android_zip.py --apk build/android-release/app-x86_64.apk --abi x86_64 --out dist/KH-ReCast-Android-x86_64.zip

The game files (KH-ReCast-game/) come from the folder the desktop installers are made from (mif/, mod/ and the three
chapter saves in the repository root, all gitignored), or from an earlier download with --game-from <zip>.
"""
import argparse
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WHO = {
    "arm64-v8a": "phones and tablets with a 64-bit ARM chip (almost every Android phone today)",
    "x86_64": "Chromebooks and PC Android emulators with a 64-bit Intel or AMD chip. Phones should use the other download",
}

README = """Kingdom Hearts Re:Cast for Android
==================================

An unofficial, non-profit fan preservation project. Not affiliated with Disney, Square Enix, Superscape, Verizon or any
rights holder. Free: it should never be sold. https://khrecast.com

What is in here
- KH-ReCast-Android.apk: the Re:Cast app {version} (Android 7 or newer). This copy is for {who}.
- KH-ReCast-game: the game files (the mif and mod folders and the game's chapter saves).

How to install
1. Extract this zip on the phone (in the Files app, tap the zip, then Extract).
2. Tap KH-ReCast-Android.apk. The first time, Android asks you to allow installing apps from your file manager:
   allow it, then tap Install.
3. Open Re:Cast and choose smartphone or flip phone style. When it asks for the game files, tap "Set up the game
   files" and pick the KH-ReCast-game folder. The app copies them into its own storage, so you can delete the zip
   and the folder afterwards.

Your saves stay in the app: uninstalling it deletes them, so export them first from the Saved games screen.
Help, the source code and the leaderboard: https://khrecast.com
"""


def game_files(game_from):
    """Yields (archive name, bytes) for everything under KH-ReCast-game/."""
    if game_from:
        with zipfile.ZipFile(game_from) as z:
            for n in z.namelist():
                if n.startswith("KH-ReCast-game/") and not n.endswith("/"):
                    yield n, z.read(n)
        return
    for sub in ("mif", "mod"):
        for dp, dirs, fs in os.walk(os.path.join(ROOT, sub)):
            dirs.sort()
            for f in sorted(fs):
                full = os.path.join(dp, f)
                with open(full, "rb") as fh:
                    yield "KH-ReCast-game/" + os.path.relpath(full, ROOT).replace(os.sep, "/"), fh.read()
    for w in ("agrabah", "island", "maleficient"):
        name = f"savegame({w}).dat"
        with open(os.path.join(ROOT, name), "rb") as f:
            yield "KH-ReCast-game/" + name, f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", required=True)
    ap.add_argument("--abi", required=True, choices=sorted(WHO))
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", default="0.2.0")
    ap.add_argument("--game-from", help="an earlier KH-ReCast-Android zip to take the game files from")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    text = README.format(version=a.version, who=WHO[a.abi]).replace("\n", "\r\n")
    with zipfile.ZipFile(a.out, "w") as z:
        z.write(a.apk, "KH-ReCast-Android.apk", compress_type=zipfile.ZIP_STORED)    # an APK is already compressed
        for name, data in game_files(a.game_from):
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("README.txt", text, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(a.out) as z:
        assert z.testzip() is None
        print(a.out, os.path.getsize(a.out), len(z.namelist()), "entries")


if __name__ == "__main__":
    main()
