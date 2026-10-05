"""IMedia (MIDI music, CMX .pmd / PCM sound effects) backed by audio.AudioEngine."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Optional

from .hle import EFAILED, EUNSUPPORTED, SUCCESS, HleObject

if TYPE_CHECKING:
    from .runtime import Emulator

MM_PARM_MEDIA_DATA = 1
MM_PARM_VOLUME = 4
MM_PARM_PLAY_REPEAT = 11
MM_PARM_CHANNEL_SHARE = 16

MMD_FILE_NAME = 0
MMD_BUFFER = 1
MMD_ISOURCE = 2

MM_CMD_SETMEDIAPARM = 1
MM_CMD_GETMEDIAPARM = 2
MM_CMD_PLAY = 4
MM_STATUS_START = 1
MM_STATUS_DONE = 2
MM_STATUS_ABORT = 3

MM_STATE_IDLE, MM_STATE_READY, MM_STATE_PLAY, MM_STATE_PLAY_PAUSE = 0, 1, 2, 3


class Media(HleObject):
    IFACE = "IMedia"
    SLOTS = ("AddRef", "Release", "QueryInterface", "RegisterNotify", "SetMediaParm",
             "GetMediaParm", "Play", "Record", "Stop", "Seek", "Pause", "Resume",
             "GetTotalTime", "GetState")

    def __init__(self, emu: "Emulator", clsid: int):
        super().__init__(emu)
        self.clsid = clsid
        self.data: Optional[bytes] = None
        self.name = ""
        self.notify_fn = 0
        self.notify_user = 0
        self.volume = 100
        self.repeat = 0
        self.state = MM_STATE_IDLE
        self.voice = None
        self.notify_block = emu.cpu.hle_alloc(32, 8)

    def on_final_release(self):
        self._stop(notify=False)
        self.emu.objects.pop(self.ptr, None)

    @property
    def audio(self):
        return self.emu.audio

    def RegisterNotify(self, c):
        self.notify_fn, self.notify_user = c.arg(1), c.arg(2)
        return SUCCESS

    def SetMediaParm(self, c):
        parm, p1, p2 = c.arg(1), c.arg(2), c.arg(3)
        if parm == MM_PARM_MEDIA_DATA:
            cls_data, pdata, size = struct.unpack("<III", self.cpu.read(p1, 12))
            if cls_data == MMD_FILE_NAME:
                self.name = self.cpu.cstr(pdata)
                self.data = self.emu.vfs.read_file(self.name)
                if self.data is None:
                    self.emu.log(f"[media] file '{self.name}' not found")
                    return EFAILED
            elif cls_data == MMD_BUFFER:
                self.data = self.cpu.read(pdata, size)
                self.name = self.emu.recent_files.get(size, f"<buffer {size}B>")
            else:
                self.emu.log_once(("mmd", cls_data), f"[media] media data type {cls_data} unsupported")
                return EUNSUPPORTED
            self.state = MM_STATE_READY
            self.emu.logv(f"[media] {self.name} ({len(self.data)} bytes) ready")
            return SUCCESS
        if parm == MM_PARM_VOLUME:
            self.volume = p1
            if self.voice is not None:
                self.audio.set_volume(self.voice, p1)
            return SUCCESS
        if parm == MM_PARM_PLAY_REPEAT:
            self.repeat = p1
            return SUCCESS
        self.emu.log_once(("mmparm", parm), f"[media] SetMediaParm({parm}, 0x{p1:x}, 0x{p2:x}) ignored")
        return SUCCESS

    def GetMediaParm(self, c):
        parm, pp1, pp2 = c.arg(1), c.arg(2), c.arg(3)
        if parm == MM_PARM_VOLUME and pp1:
            self.cpu.w32(pp1, self.volume)
            return SUCCESS
        return EUNSUPPORTED

    def _notify(self, cmd, status):
        if not self.notify_fn:
            return
        b = self.notify_block
        self.cpu.write(b, struct.pack("<IIiiiII", self.clsid, self.ptr, cmd, 0, status, 0, 0))
        self.emu.call_soon_args(self.notify_fn, self.notify_user, b)

    def Play(self, c):
        if self.data is None:
            return EFAILED
        self._stop(notify=False)
        if self.data[:4] == b"MThd":
            # Phones had one MIDI player: starting a tune cuts off any other MIDI
            # still playing (e.g. the title music under a world's splash tune).
            for other in list(self.emu.objects.values()):
                if (other is not self and isinstance(other, Media) and other.voice is not None
                        and other.data is not None and other.data[:4] == b"MThd"):
                    other._stop(notify=True)
        loops =-1 if self.repeat == 0xFFFFFFFF else max(0, self.repeat - 1) if self.repeat > 1 else 0
        self.voice = self.audio.play(self.data, self.name, self.volume, loops, on_done=self._done)
        self.state = MM_STATE_PLAY
        self._notify(MM_CMD_PLAY, MM_STATUS_START)
        return SUCCESS

    # save states: the playing voice is stored as a small record and restarted
    # (mid-way) on load, since the pygame channel itself can't be saved
    def voice_record(self) -> Optional[dict]:
        v = self.voice
        if v is None or v.done:
            return None
        return {"start_ms": v.start_ms, "loops": v.loops, "paused_at": v.paused_at}

    def resume_voice(self, rec: dict):
        if self.data is None:
            return
        self.voice = self.audio.play(self.data, self.name, self.volume, rec["loops"],
                                     on_done=self._done, start_ms=rec["start_ms"],
                                     paused_at=rec["paused_at"])
        self.state = MM_STATE_PLAY_PAUSE if rec["paused_at"] is not None else MM_STATE_PLAY

    def _done(self, voice):
        if voice is self.voice:
            self.voice = None
            self.state = MM_STATE_READY
            self._notify(MM_CMD_PLAY, MM_STATUS_DONE)

    def _stop(self, notify=True):
        if self.voice is not None:
            v, self.voice = self.voice, None
            self.audio.stop(v)
            if notify:
                self._notify(MM_CMD_PLAY, MM_STATUS_ABORT)
        self.state = MM_STATE_READY if self.data else MM_STATE_IDLE

    def Stop(self, c):
        self._stop(notify=True)
        return SUCCESS

    def Pause(self, c):
        if self.voice is not None:
            self.audio.pause(self.voice, True)
            self.state = MM_STATE_PLAY_PAUSE
        return SUCCESS

    def Resume(self, c):
        if self.voice is not None:
            self.audio.pause(self.voice, False)
            self.state = MM_STATE_PLAY
        return SUCCESS

    def Seek(self, c):
        return EUNSUPPORTED

    def Record(self, c):
        return EUNSUPPORTED

    def GetTotalTime(self, c):
        return EUNSUPPORTED

    def GetState(self, c):
        p = c.arg(1)
        if p:
            self.cpu.w8(p, 0)
        return self.state
