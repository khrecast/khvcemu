"""Turn a tap (or a mouse click) on the game's picture into the phone keys that do what the tapped thing says.

The game has no pointer: it is driven by the keypad. But it draws its own buttons, and the display records every
string it draws with its position and color (`Display.text_items`, after `build_overlay` has dropped the ones that are
no longer on screen). From those, a tap can be understood:

* a **softkey** is a label in the bottom corners (the left one is the Soft 1 key, the right one Soft 2): tapping near
  it presses that key. Only where the game drew a label, so a tap on a gauge during play never pauses the game;
* a **list entry** is one of a run of at least three strings at a regular spacing (the title menu, the Options menu, a
  shop). The selected entry is the one whose text color and background differ from the others. Tapping another entry
  moves the highlight there with Up or Down; tapping the highlighted entry presses Action. When the highlighted entry
  cannot be told (a paragraph of text, a list of two), a tap does nothing, rather than guess.

`resolve_tap` is pure: it takes the recorded items and the frame and returns key names, in order. The caller presses them
(a little apart, so the game sees each one).
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import numpy as np

WIDTH, HEIGHT = 176, 220
SOFTKEY_ROW = 196          # strings that start at or below this row sit on the softkey bars (a menu entry ends above it)
SOFTKEY_BAND = 190         # a tap at or below this row can be meant for a softkey
MIN_LIST = 3               # entries in a list
PITCH_SLACK = 2            # rows of difference allowed between neighbors' spacing


def softkey_labels(items: Sequence[dict]) -> List[dict]:
    return [it for it in items if it["box"][1] >= SOFTKEY_ROW]


def softkey_for_tap(x: float, y: float, items: Sequence[dict], width: int = WIDTH) -> Optional[str]:
    """Soft 1 or Soft 2 when the tap is on a bar that has a label, else None."""
    if y < SOFTKEY_BAND:
        return None
    for it in softkey_labels(items):
        x0, _y0, x1, _y1 = it["box"]
        left = (x0 + x1) / 2 < width / 2
        if left == (x < width / 2):
            return "SOFT1" if left else "SOFT2"
    return None


def _dominant(region: np.ndarray) -> int:
    values, counts = np.unique(region.reshape(-1), return_counts=True)
    return int(values[counts.argmax()])


def _background(frame: np.ndarray, box) -> int:
    """The color beside a string: just left of it, or just right of it when it starts at the edge."""
    x0, y0, x1, y1 = box
    h, w = frame.shape
    if x0 >= 3:
        strip = frame[y0:y1, max(0, x0 - 8):max(1, x0 - 2)]
    elif x1 + 2 < w:
        strip = frame[y0:y1, min(w - 1, x1 + 2):min(w, x1 + 8)]
    else:
        strip = frame[y0:y1, 0:1]
    return _dominant(strip)


def find_list(items: Sequence[dict]) -> List[dict]:
    """The longest run of entries (top to bottom, not the softkey labels) at a regular spacing, or []."""
    rows = sorted((it for it in items if it["box"][1] < SOFTKEY_ROW), key=lambda it: it["box"][1])
    best: List[dict] = []
    run: List[dict] = []
    for it in rows:
        if len(run) >= 2:
            pitch = run[-1]["box"][1] - run[-2]["box"][1]
            ok = abs((it["box"][1] - run[-1]["box"][1]) - pitch) <= PITCH_SLACK
        elif len(run) == 1:
            ok = 0 < it["box"][1] - run[-1]["box"][1] <= 40
        else:
            ok = False
        if ok:
            run.append(it)
        else:
            if len(run) > len(best):
                best = run
            # a failed step may start a new run with this item and the one before it
            run = [run[-1], it] if run and 0 < it["box"][1] - run[-1]["box"][1] <= 40 else [it]
    if len(run) > len(best):
        best = run
    return best if len(best) >= MIN_LIST else []


def selected_index(entries: Sequence[dict], frame: np.ndarray) -> Optional[int]:
    """Which entry is highlighted: the only one whose text color and background both differ from the rest."""
    marks = [(it["fg"], _background(frame, it["box"])) for it in entries]
    counts = {}
    for m in marks:
        counts[m] = counts.get(m, 0) + 1
    common = max(counts, key=counts.get)
    if counts[common] < 2:
        return None
    odd = [i for i, m in enumerate(marks) if m != common]
    return odd[0] if len(odd) == 1 else None


def resolve_tap(x: float, y: float, items: Sequence[dict], frame: Optional[np.ndarray],
                width: int = WIDTH) -> List[str]:
    """The key names to press, in order, for a tap at game pixel (x, y). An empty list: nothing to do."""
    soft = softkey_for_tap(x, y, items, width)
    if soft:
        return [soft]
    if frame is None:
        return []
    entries = find_list(items)           # (a last entry may reach down into the softkey band: that is fine)
    if not entries:
        return []
    pitch = (entries[-1]["box"][1] - entries[0]["box"][1]) / max(1, len(entries) - 1)
    left = min(it["box"][0] for it in entries) - 12
    right = max(it["box"][2] for it in entries) + 12
    if not left <= x <= right:
        return []
    centers = [(it["box"][1] + it["box"][3]) / 2 for it in entries]
    tapped = min(range(len(entries)), key=lambda i: abs(centers[i] - y))
    if abs(centers[tapped] - y) > pitch / 2 + 1:
        return []
    chosen = selected_index(entries, frame)
    if chosen is None:
        return []
    steps = tapped - chosen
    if steps == 0:
        return ["SELECT"]
    return ["DOWN"] * steps if steps > 0 else ["UP"] * (-steps)
