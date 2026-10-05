"""Virtual filesystem + IFileMgr/IFile.

The game's own directory (mod/<id>/ in the dump) is mounted read-only; every
write goes to an overlay directory, so the original dump is never modified.
Lookups are case-insensitive, like the phone's EFS.
"""

from __future__ import annotations

import os
from typing import Optional

from .hle import EFAILED, EFILEEXISTS, EFILENOEXISTS, SUCCESS, HleObject

_OFM_READ = 0x1
_OFM_READWRITE = 0x2
_OFM_CREATE = 0x4
_OFM_APPEND = 0x8

_SEEK_START, _SEEK_END, _SEEK_CURRENT = 0, 1, 2


def canon(name: str) -> str:
    s = name.replace("\\", "/")
    for pre in ("fs:/~/", "fs:/", "~/"):
        if s.lower().startswith(pre):
            s = s[len(pre):]
    parts = [p for p in s.split("/") if p not in ("", ".")]
    return "/".join(parts)


# game files holding progress; copies are kept before any change (see backup_progress_file)
PROGRESS_FILES = ("savegame.dat", "replaygame.dat", "scoredata.dat")
BACKUPS_KEPT = 30


def backup_progress_file(path: str, backup_dir: str, log=None) -> Optional[str]:
    """Copy `path` into `backup_dir` as <name>.<timestamp>.bak before it is
    overwritten or deleted, so progress can never be lost silently. Skips empty
    files and files identical to the newest backup; keeps the newest few."""
    import glob
    import time
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return None
        base = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        os.makedirs(backup_dir, exist_ok=True)
        old = sorted(glob.glob(os.path.join(backup_dir, glob.escape(base) + ".*.bak")))
        if old:
            with open(old[-1], "rb") as f:
                if f.read() == data:
                    return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(backup_dir, f"{base}.{stamp}.bak")
        n = 1
        while os.path.exists(dest):
            n += 1
            dest = os.path.join(backup_dir, f"{base}.{stamp}-{n}.bak")
        with open(dest, "wb") as f:
            f.write(data)
        for stale in old[: max(0, len(old) + 1 - BACKUPS_KEPT)]:
            os.remove(stale)
        if log:
            log(f"[save] backed up {base} -> {dest}")
        return dest
    except OSError as e:          # a failed backup must never stop the game
        if log:
            log(f"[save] could not back up {path}: {e}")
        return None


class Vfs:
    def __init__(self, base_dirs: list, overlay: str, log=print):
        self.base_dirs = [d for d in base_dirs if d]
        self.overlay = overlay
        self.log = log
        os.makedirs(overlay, exist_ok=True)
        self.deleted: set = set()
        # name (lower-case, canonical) -> fn(bytes) -> bytes, applied on read
        self.patchers: dict = {}
        self._patched: dict = {}
        self.protect_base = True
        # name (lower-case, canonical) -> fn() -> bytes: files khvcemu supplies that
        # are in neither the dump nor the overlay (e.g. the stand-in Wonderland world)
        self.virtual: dict = {}
        self._virtual_cache: dict = {}

    def _find_ci(self, root: str, rel: str) -> Optional[str]:
        cur = root
        for part in rel.split("/"):
            if not os.path.isdir(cur):
                return None
            direct = os.path.join(cur, part)
            if os.path.exists(direct):
                cur = direct
                continue
            low = part.lower()
            match = next((e for e in os.listdir(cur) if e.lower() == low), None)
            if match is None:
                return None
            cur = os.path.join(cur, match)
        return cur

    def resolve(self, name: str) -> Optional[str]:
        rel = canon(name)
        if not rel:
            return None
        p = self._find_ci(self.overlay, rel)
        if p and os.path.isfile(p):
            return p
        if rel.lower() in self.deleted:
            return None
        for d in self.base_dirs:
            p = self._find_ci(d, rel)
            if p and os.path.isfile(p):
                return p
        if rel.lower() in self.virtual:
            return "virtual:" + rel.lower()
        return None

    def exists_dir(self, name: str) -> bool:
        rel = canon(name)
        if not rel:
            return True
        for d in [self.overlay] + self.base_dirs:
            p = self._find_ci(d, rel)
            if p and os.path.isdir(p):
                return True
        return False

    def read_file(self, name: str) -> Optional[bytes]:
        p = self.resolve(name)
        if p is None:
            return None
        if p.startswith("virtual:"):
            key = p[len("virtual:"):]
            if key not in self._virtual_cache:
                self._virtual_cache[key] = self.virtual[key]()
            return self._virtual_cache[key]
        with open(p, "rb") as f:
            data = f.read()
        key = canon(name).lower()
        fn = self.patchers.get(key)
        if fn is not None and not p.startswith(self.overlay):
            cached = self._patched.get(key)
            if cached is None or cached[0] != len(data):
                cached = (len(data), fn(data))
                self._patched[key] = cached
            data = cached[1]
        return data

    def write_file(self, name: str, data: bytes):
        rel = canon(name)
        path = os.path.join(self.overlay, rel)
        os.makedirs(os.path.dirname(path) or self.overlay, exist_ok=True)
        existing = self._find_ci(self.overlay, rel)
        if existing:
            path = existing
        self._backup_before_change(rel, path, new_data=data)
        with open(path, "wb") as f:
            f.write(data)
        self.deleted.discard(rel.lower())

    def _backup_before_change(self, rel: str, path: str, new_data: Optional[bytes] = None):
        if rel.lower() not in PROGRESS_FILES:
            return
        if new_data is not None and os.path.isfile(path):
            with open(path, "rb") as f:
                if f.read() == new_data:         # rewriting identical content loses nothing
                    return
        backup_progress_file(path, os.path.join(os.path.dirname(self.overlay), "save_backups"), self.log)

    def remove(self, name: str) -> bool:
        """Delete from the overlay. Files that come from the dump itself are
        protected: before downloading an episode the game deletes every other
        world's files (the phones only had room for one), and with all
        recovered worlds merged in one folder that would wipe them."""
        rel = canon(name)
        found = self.resolve(name) is not None
        p = self._find_ci(self.overlay, rel)
        removed_overlay = False
        if p and os.path.isfile(p):
            self._backup_before_change(rel, p)
            os.remove(p)
            removed_overlay = True
        in_base = any(self._find_ci(d, rel) for d in self.base_dirs)
        if in_base and not self.protect_base:
            self.deleted.add(rel.lower())
        elif in_base and not removed_overlay:
            self.log(f"[file] kept '{rel}' (part of the game dump; delete ignored)")
        return found

    def listdir(self, name: str) -> list:
        rel = canon(name)
        seen = {}
        for d in self.base_dirs + [self.overlay]:
            p = self._find_ci(d, rel) if rel else d
            if p and os.path.isdir(p):
                for e in os.listdir(p):
                    full = os.path.join(p, e)
                    key = (rel + "/" + e if rel else e)
                    if key.lower() in self.deleted:
                        continue
                    seen[e.lower()] = (key, os.path.isdir(full),
                                       os.path.getsize(full) if os.path.isfile(full) else 0)
        prefix = (rel.lower() + "/") if rel else ""
        for vname in self.virtual:          # khvcemu-supplied files are listed like real ones
            if vname.startswith(prefix) and "/" not in vname[len(prefix):]:
                leaf = vname[len(prefix):]
                if leaf not in seen:
                    seen[leaf] = (vname, False, len(self.read_file(vname) or b""))
        return sorted(seen.values())


def write_fileinfo(cpu, p, name: str, size: int, is_dir=False):
    # FileInfo { char attrib; uint32 dwCreationDate; uint32 dwSize; char szName[64]; }
    cpu.w8(p, 0x10 if is_dir else 0)
    cpu.w32(p + 4, 0)
    cpu.w32(p + 8, size)
    cpu.write(p + 12, name.encode("latin-1")[:63] + b"\0")


class File(HleObject):
    IFACE = "IFile"
    SLOTS = ("AddRef", "Release", "Readable", "Read", "Cancel", "Write", "GetInfo", "Seek",
             "Truncate", "GetInfoEx", "SetCacheSize", "Map")

    def __init__(self, emu, name: str, data: bytearray, writable: bool):
        super().__init__(emu)
        self.name, self.data, self.writable = name, data, writable
        self.pos = 0
        self.dirty = False

    def flush(self):
        if self.dirty:
            self.emu.vfs.write_file(self.name, bytes(self.data))
            self.dirty = False

    def on_final_release(self):
        self.flush()
        self.emu.objects.pop(self.ptr, None)

    def Readable(self, c):
        fn, user = c.arg(1), c.arg(2)
        if fn:
            self.emu.call_soon(fn, user)
        return None

    def Cancel(self, c):
        return None

    def Read(self, c):
        buf, n = c.arg(1), c.arg(2)
        if buf == 0:
            # Read(NULL, ...) reports the bytes left. KH uses Read(NULL, 0) != 0
            # as its "is this episode installed?" test.
            return len(self.data) - self.pos
        chunk = bytes(self.data[self.pos:self.pos + n])
        self.cpu.write(buf, chunk)
        self.pos += len(chunk)
        return len(chunk)

    def Write(self, c):
        buf, n = c.arg(1), c.arg(2)
        if not self.writable:
            return 0
        chunk = self.cpu.read(buf, n)
        end = self.pos + n
        if end > len(self.data):
            self.data.extend(b"\0" * (end - len(self.data)))
        self.data[self.pos:end] = chunk
        self.pos = end
        self.dirty = True
        self.flush()  # phones write through; keeps saves safe if we crash
        return n

    def GetInfo(self, c):
        write_fileinfo(self.cpu, c.arg(1), os.path.basename(self.name), len(self.data))
        return SUCCESS

    def Seek(self, c):
        how, dist = c.arg(1), c.sarg(2)
        if how == _SEEK_CURRENT and dist == 0:
            return self.pos
        base = {_SEEK_START: 0, _SEEK_END: len(self.data)}.get(how, self.pos)
        new = base + dist
        if new < 0 or (new > len(self.data) and not self.writable):
            return EFAILED
        if new > len(self.data):
            self.data.extend(b"\0" * (new - len(self.data)))
            self.dirty = True
        self.pos = new
        return SUCCESS

    def Truncate(self, c):
        n = c.arg(1)
        if not self.writable:
            return EFAILED
        del self.data[n:]
        self.pos = min(self.pos, n)
        self.dirty = True
        self.flush()
        return SUCCESS


class FileMgr(HleObject):
    IFACE = "IFileMgr"
    SLOTS = ("AddRef", "Release", "OpenFile", "GetInfo", "Remove", "MkDir", "RmDir", "Test",
             "GetFreeSpace", "GetLastError", "EnumInit", "EnumNext", "Rename", "EnumNextEx",
             "SetDescription", "GetInfoEx", "Use", "GetFileUseInfo", "ResolvePath",
             "CheckPathAccess", "GetFreeSpaceEx")

    def __init__(self, emu):
        super().__init__(emu)
        self.last_error = 0
        self.enum: list = []

    @property
    def vfs(self) -> Vfs:
        return self.emu.vfs

    def OpenFile(self, c):
        name, mode = self.cpu.cstr(c.arg(1)), c.arg(2)
        data = self.vfs.read_file(name)
        writable = bool(mode & (_OFM_READWRITE | _OFM_CREATE | _OFM_APPEND))
        if mode & _OFM_CREATE:
            if data is not None:
                self.last_error = EFILEEXISTS
                self.emu.logv(f"[file] create '{name}' -> exists")
                return 0
            data = b""
            self.vfs.write_file(name, b"")
        elif data is None:
            self.last_error = EFILENOEXISTS
            self.emu.logv(f"[file] open '{name}' -> missing")
            self.emu.on_missing_file(name)
            return 0
        f = File(self.emu, canon(name), bytearray(data), writable)
        self.emu.recent_files[len(data)] = canon(name)   # lets IMedia name buffers in logs
        if mode & _OFM_APPEND:
            f.pos = len(f.data)
        self.emu.logv(f"[file] open '{name}' mode={mode} size={len(data)} -> 0x{f.ptr:08x}")
        self.emu.on_file_opened(name, mode)
        return f.ptr

    def GetInfo(self, c):
        name, p = self.cpu.cstr(c.arg(1)), c.arg(2)
        data = self.vfs.read_file(name)
        if data is None:
            if self.vfs.exists_dir(name):
                write_fileinfo(self.cpu, p, name, 0, True)
                return SUCCESS
            self.last_error = EFILENOEXISTS
            return EFILENOEXISTS
        write_fileinfo(self.cpu, p, os.path.basename(canon(name)), len(data))
        return SUCCESS

    def Remove(self, c):
        name = self.cpu.cstr(c.arg(1))
        ok = self.vfs.remove(name)
        self.emu.logv(f"[file] remove '{name}' -> {ok}")
        return SUCCESS if ok else EFILENOEXISTS

    def MkDir(self, c):
        os.makedirs(os.path.join(self.vfs.overlay, canon(self.cpu.cstr(c.arg(1)))), exist_ok=True)
        return SUCCESS

    def RmDir(self, c):
        return SUCCESS

    def Test(self, c):
        name = self.cpu.cstr(c.arg(1))
        ok = self.vfs.resolve(name) is not None or self.vfs.exists_dir(name)
        self.emu.logv(f"[file] test '{name}' -> {ok}")
        if not ok:
            self.last_error = EFILENOEXISTS
        return SUCCESS if ok else EFILENOEXISTS

    def GetFreeSpace(self, c):
        p = c.arg(1)
        if p:
            self.cpu.w32(p, 8 << 20)
        return 4 << 20

    def GetLastError(self, c):
        return self.last_error

    def EnumInit(self, c):
        name, dirs = self.cpu.cstr(c.arg(1)), c.arg(2)
        self.enum = [e for e in self.vfs.listdir(name) if bool(e[1]) == bool(dirs)]
        return SUCCESS

    def EnumNext(self, c):
        p = c.arg(1)
        if not self.enum:
            return 0
        key, is_dir, size = self.enum.pop(0)
        write_fileinfo(self.cpu, p, key, size, is_dir)
        return 1

    def Rename(self, c):
        a, b = self.cpu.cstr(c.arg(1)), self.cpu.cstr(c.arg(2))
        data = self.vfs.read_file(a)
        if data is None:
            return EFILENOEXISTS
        self.vfs.write_file(b, data)
        self.vfs.remove(a)
        return SUCCESS
