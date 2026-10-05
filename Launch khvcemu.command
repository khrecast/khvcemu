#!/bin/bash
# Double-click in Finder to open the khvcemu launcher (needs Python 3.10+ with tkinter).
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    echo "Python was not found. Install it from https://www.python.org/downloads/ or: brew install python"
    read -n 1 -s -r -p "Press any key to close."
    exit 1
fi
if ! "$PY" -c "import tkinter" 2>/dev/null; then
    echo "This Python has no tkinter (the launcher's window toolkit)."
    echo "Fix:  brew install python-tk    (or install Python from python.org, which includes it)"
    read -n 1 -s -r -p "Press any key to close."
    exit 1
fi
exec "$PY" -m khvcemu.launcher
