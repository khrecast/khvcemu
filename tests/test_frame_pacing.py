"""frame_locked_clock: in real time the clock the game sees is held still during each callback, so its frame
timer (re-armed at the end of every frame) gives max(40 ms, the host's time per frame) instead of adding the frame
time to the delay. See the comment in Emulator.__init__."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu import runtime  # noqa: E402
from khvcemu.runtime import Emulator  # noqa: E402


class FakeTime:
    """Stands in for time.monotonic inside khvcemu.runtime, so a test can move the clock by hand."""
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now


def stub(realtime=True, locked=True):
    """An Emulator without the CPU and game files: just what clock_ms and the guest-entry helpers use."""
    emu = Emulator.__new__(Emulator)
    emu.realtime = realtime
    emu.frame_locked_clock = locked
    emu._frozen_ms = None
    emu._guest_depth = 0
    emu._virtual_ms = 0.0
    emu._t0 = 100.0
    return emu


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTime()
        self.saved = runtime.time
        runtime.time = self.fake
        self.addCleanup(setattr, runtime, "time", self.saved)

    def test_the_clock_runs_in_real_time_between_callbacks(self):
        emu = stub()
        self.fake.now = 100.5
        self.assertEqual(emu.clock_ms(), 500)

    def test_the_clock_is_held_during_a_callback_and_runs_on_after_it(self):
        emu = stub()
        self.fake.now = 100.5
        emu._enter_guest()
        self.fake.now = 100.533                       # the callback took 33 ms
        self.assertEqual(emu.clock_ms(), 500, "the game sees no time pass inside its callback")
        emu._leave_guest()
        self.assertAlmostEqual(emu.clock_ms(), 533, delta=1, msg="and the clock has not lost the time")

    def test_a_timer_set_inside_a_callback_is_due_exactly_that_long_after_its_start(self):
        emu = stub()
        emu.timers, emu._timer_seq = [], 0
        self.fake.now = 100.5
        emu._enter_guest()
        self.fake.now = 100.533
        emu.set_timer(40, 1, 0)                       # what the game does at the end of its frame
        emu._leave_guest()
        self.assertAlmostEqual(emu.next_due(), 540, delta=1, msg="a 40 ms frame period, not 33 + 40")

    def test_nested_callbacks_freeze_and_release_once(self):
        emu = stub()
        self.fake.now = 100.5
        emu._enter_guest()
        self.fake.now = 100.51
        emu._enter_guest()
        self.fake.now = 100.52
        emu._leave_guest()
        self.assertEqual(emu.clock_ms(), 500, "still inside the outer callback")
        emu._leave_guest()
        self.assertAlmostEqual(emu.clock_ms(), 520, delta=1)      # (floating point: 519.99 may truncate to 519)

    def test_without_the_option_the_clock_keeps_running(self):
        emu = stub(locked=False)
        self.fake.now = 100.5
        emu._enter_guest()
        self.fake.now = 100.533
        self.assertAlmostEqual(emu.clock_ms(), 533, delta=1)
        emu._leave_guest()

    def test_the_virtual_clock_is_left_alone(self):
        emu = stub(realtime=False)
        emu._virtual_ms = 1234.0
        emu._enter_guest()
        emu.advance(5)
        self.assertEqual(emu.clock_ms(), 1239, "headless runs already hold time still: the host moves it")
        emu._leave_guest()


@unittest.skipUnless(os.environ.get("KH_DUMP"), "needs the game files (KH_DUMP)")
class RealTimeFramesTests(unittest.TestCase):
    def test_the_title_screen_runs_at_the_games_own_rate(self):
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        emu = Emulator(os.environ["KH_DUMP"], tempfile.mkdtemp(), realtime=True, audio=False, log=lambda s: None,
                       frame_locked_clock=True)
        stamps = []
        emu.frame_listeners.append(lambda f: stamps.append(emu.clock_ms()))
        emu.start()
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 14:
            emu.run_due()
            due = emu.next_due()
            wait = 0.002 if due is None else (due - emu.clock_ms()) / 1000
            if wait > 0.001:
                time.sleep(min(wait, 0.005))
        steady = [b - a for a, b in zip(stamps, stamps[1:]) if a > 8000]
        self.assertGreater(len(steady), 50)
        median = sorted(steady)[len(steady) // 2]
        self.assertLessEqual(abs(median - 40), 3, f"the median frame interval was {median} ms, not 40")


if __name__ == "__main__":
    unittest.main()
