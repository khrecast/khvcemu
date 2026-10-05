import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import checksums  # noqa: E402


class ChecksumTests(unittest.TestCase):
    def test_only_installers_are_listed_with_their_real_hash(self):
        with tempfile.TemporaryDirectory() as d:
            for name, data in (("KH-ReCast-Windows-x64.exe", b"abc"), ("KH-ReCast-Linux-x86_64.run", b"xyz" * 500000),
                               ("notes.txt", b"ignore me"), ("SHA256SUMS.txt", b"old")):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(data)
            found = checksums.sums(d)
        self.assertEqual([n for _, n, _ in found], ["KH-ReCast-Linux-x86_64.run", "KH-ReCast-Windows-x64.exe"])
        self.assertEqual(found[1][0], hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(found[0][0], hashlib.sha256(b"xyz" * 500000).hexdigest(), "files bigger than one block")


if __name__ == "__main__":
    unittest.main()
