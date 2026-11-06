"""gamefiles.problems: a complete game folder passes; a wrong or partial one says what is missing."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from khvcemu import gamefiles  # noqa: E402


def make(root, parts):
    path = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")


class GameFilesTests(unittest.TestCase):
    def test_a_complete_folder_has_no_problems(self):
        with tempfile.TemporaryDirectory() as root:
            for parts in gamefiles.REQUIRED:
                make(root, parts)
            self.assertEqual(gamefiles.problems(root), [])

    def test_a_missing_file_is_named(self):
        with tempfile.TemporaryDirectory() as root:
            for parts in gamefiles.REQUIRED[:-1]:
                make(root, parts)
            self.assertEqual(gamefiles.problems(root), ["Missing mod/14957/swv21brew.mod"])

    def test_a_folder_without_mif_and_mod_is_not_the_game_folder(self):
        with tempfile.TemporaryDirectory() as root:
            make(root, ("notes", "a.txt"))
            self.assertIn("not the game folder", gamefiles.problems(root)[0])

    def test_no_folder(self):
        self.assertEqual(gamefiles.problems(""), ["The folder does not exist."])
        self.assertEqual(gamefiles.problems(os.path.join(tempfile.gettempdir(), "no-such-folder-xyz")),
                         ["The folder does not exist."])

    @unittest.skipUnless(os.environ.get("KH_DUMP"), "needs the game files (KH_DUMP)")
    def test_the_real_game_folder_is_complete(self):
        self.assertEqual(gamefiles.problems(os.environ["KH_DUMP"]), [])


if __name__ == "__main__":
    unittest.main()
