"""BREW virtual key codes (AEEVCodes.h) and the default keyboard mapping."""

AVK = {
    "0": 0xE021, "1": 0xE022, "2": 0xE023, "3": 0xE024, "4": 0xE025, "5": 0xE026,
    "6": 0xE027, "7": 0xE028, "8": 0xE029, "9": 0xE02A, "STAR": 0xE02B, "POUND": 0xE02C,
    "POWER": 0xE02D, "END": 0xE02E, "SEND": 0xE02F, "CLR": 0xE030, "UP": 0xE031,
    "DOWN": 0xE032, "LEFT": 0xE033, "RIGHT": 0xE034, "SELECT": 0xE035, "SOFT1": 0xE036,
    "SOFT2": 0xE037,
}


# ---------------------------------------------------------------------------------------------- rebinding
# The keys the player can change (the launcher's Controls tab, `--key ACTION=KEY`): action, what it does, the key
# it has unless changed (a pygame key name). Everything else on the keyboard keeps its job.
REBINDABLE = (
    ("UP", "Move up", "w"), ("DOWN", "Move down", "s"), ("LEFT", "Move left", "a"), ("RIGHT", "Move right", "d"),
    ("SELECT", "Action, attack", "space"), ("STAR", "Magic", "f"), ("0", "Status + items", "z"), ("SOFT1", "Pause, Continue", "q"),
    ("SOFT2", "Back, Options", "e"), ("CLR", "Back, pause", "backspace"),
)
DEFAULT_KEYS = {action: key for action, _what, key in REBINDABLE}
ACTION_NAMES = {action: what for action, what, _key in REBINDABLE}
# what also does the same job and cannot be changed
ALSO = {"UP": "also the Up arrow", "DOWN": "also the Down arrow", "LEFT": "also the Left arrow",
        "RIGHT": "also the Right arrow", "SELECT": "also Enter and 5", "STAR": "also [ and the number pad *", "0": "also the 0 key",
        "SOFT1": "also F1", "SOFT2": "also F2",
        "CLR": "twice: back to the title screen"}
# keys that may be chosen: letters, Space, Tab, Backspace and a few punctuation keys. Digits, arrows, Enter, brackets,
# the number pad, Esc and the F keys already have a job (the game's, or Re:Cast's) and stay as they are.
ALLOWED_KEYS = frozenset("abcdefghijklmnopqrstuvwxyz") | frozenset(";'/,.-=`\\") | {"tab", "space", "backspace"}
# Tk key names (event.keysym) to pygame key names
_TK_PUNCTUATION = {"semicolon": ";", "apostrophe": "'", "slash": "/", "comma": ",", "period": ".", "minus": "-",
                   "equal": "=", "grave": "`", "backslash": "\\", "Tab": "tab", "space": "space",
                   "BackSpace": "backspace"}


def key_from_tk(keysym: str):
    """A Tk keysym as a rebindable pygame key name, or None when that key cannot be chosen."""
    name = _TK_PUNCTUATION.get(keysym) or (keysym.lower() if len(keysym) == 1 else None)
    return name if name in ALLOWED_KEYS else None


def display_key(name: str) -> str:
    """How a key is shown to the player."""
    return name.upper() if len(name) == 1 and name.isalpha() else name.capitalize() if len(name) > 1 else name


def parse_key_options(items) -> dict:
    """['UP=i', 'STAR=g'] -> {'UP': 'i', 'STAR': 'g'}; raises ValueError saying what is wrong. A key may be given
    to one action only, and an action's own default may be given back."""
    out = {}
    for item in items:
        action, _, key = item.partition("=")
        action = action.strip().upper() if action.strip().upper() in DEFAULT_KEYS else action.strip()
        key = key.strip().lower()
        if action not in DEFAULT_KEYS:
            raise ValueError(f"--key {item!r}: unknown action {action!r} (known: {', '.join(DEFAULT_KEYS)})")
        if key not in ALLOWED_KEYS:
            raise ValueError(f"--key {item!r}: {key!r} cannot be used (letters, space, tab, backspace and the keys ; ' / , . - = ` can)")
        out[action] = key
    full = {**DEFAULT_KEYS, **out}
    seen = {}
    for action, key in full.items():
        if key in seen:
            raise ValueError(f"--key: {key!r} is given to both {ACTION_NAMES[seen[key]]} and {ACTION_NAMES[action]}")
        seen[key] = action
    return {a: k for a, k in out.items() if k != DEFAULT_KEYS[a]}


def key_owner(custom: dict, key: str, except_action: str = ""):
    """The action that currently uses `key` (a rebindable one), or None."""
    full = {**DEFAULT_KEYS, **(custom or {})}
    for action, k in full.items():
        if k == key and action != except_action:
            return action
    return None
