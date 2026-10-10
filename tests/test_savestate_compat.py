"""A save state made on a computer with numpy 2 loads where numpy 1 is installed (the phone), and a state that cannot be
read is reported as an error instead of ending the game."""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from khvcemu.savestate import _CompatUnpickler  # noqa: E402


def global_ref(module: str, name: str) -> bytes:
    """A pickle that only looks up module.name (protocol 0 GLOBAL opcode)."""
    return b"c" + module.encode() + b"\n" + name.encode() + b"\n."


class NumpyNamesTests(unittest.TestCase):
    def test_a_missing_numpy_core_module_is_tried_under_its_numpy_1_name(self):
        with self.assertRaises(ModuleNotFoundError) as caught:
            _CompatUnpickler(io.BytesIO(global_ref("numpy._core.no_such_module", "thing"))).load()
        self.assertIn("numpy.core.no_such_module", str(caught.exception))       # the fallback name was the one tried

    def test_other_missing_modules_still_fail_under_their_own_name(self):
        with self.assertRaises(ModuleNotFoundError) as caught:
            _CompatUnpickler(io.BytesIO(global_ref("no_such_package.x", "thing"))).load()
        self.assertIn("no_such_package", str(caught.exception))

    def test_an_array_round_trips(self):
        import pickle
        arr = np.arange(12, dtype=np.uint16).reshape(3, 4)
        back = _CompatUnpickler(io.BytesIO(pickle.dumps(arr))).load()
        self.assertTrue((back == arr).all())

    def test_the_old_package_name_is_still_mapped(self):
        cls = _CompatUnpickler(io.BytesIO(global_ref("khemu.savestate", "StateError"))).load()
        self.assertEqual(cls.__module__, "khvcemu.savestate")


@unittest.skipUnless(os.environ.get("KH_DUMP"), "needs the game files (KH_DUMP)")
class UnreadableStateTests(unittest.TestCase):
    def test_a_state_that_cannot_be_decoded_is_a_state_error_and_changes_nothing(self):
        import tempfile
        from unittest import mock

        from khvcemu import savestate
        from khvcemu.runtime import Emulator
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        emu = Emulator(os.environ["KH_DUMP"], tempfile.mkdtemp(), realtime=False, audio=False, log=lambda s: None)
        emu.start()
        for _ in range(300):
            emu.advance(10)
            emu.run_due()
        path = os.path.join(tempfile.mkdtemp(), "s.khs")
        emu.save_state(path)
        clock = emu.clock_ms()

        class Broken(savestate._Unpickler):
            def load(self):
                raise ModuleNotFoundError("No module named 'somewhere_else'")

        with mock.patch.object(savestate, "_Unpickler", Broken):
            with self.assertRaises(savestate.StateError) as caught:
                emu.load_state(path)
        self.assertIn("cannot be read here", str(caught.exception))
        self.assertEqual(emu.clock_ms(), clock, "nothing was changed")
        emu.advance(100)                                   # and the game still runs
        emu.run_due()


if __name__ == "__main__":
    unittest.main()
