#!/bin/sh
# Opens the khvcemu launcher (needs Python 3.10+ with tkinter).
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    echo "Python was not found. Install it with your package manager, e.g.: sudo apt install python3" >&2
    exit 1
fi
if ! "$PY" -c "import tkinter" 2>/dev/null; then
    echo "This Python has no tkinter (the launcher's window toolkit). Install it, e.g.:" >&2
    echo "  Debian/Ubuntu: sudo apt install python3-tk" >&2
    echo "  Fedora:        sudo dnf install python3-tkinter" >&2
    echo "  Arch:          sudo pacman -S tk" >&2
    exit 1
fi
exec "$PY" -m khvcemu.launcher
