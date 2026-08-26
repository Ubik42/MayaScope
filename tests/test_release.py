from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from MayaScope.release import build_release, verify_release


class ReleaseTests(unittest.TestCase):
    def test_release_is_deterministic_manifested_and_excludes_dev_trees(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            showcase = output / "showcase.ma"
            showcase.write_text("//Maya ASCII 2025 scene\n", encoding="utf-8")
            first = build_release(output, showcase_files=(showcase,))
            first_hash = first.archive_sha256
            second = build_release(output, showcase_files=(showcase,))
            self.assertEqual(second.archive_sha256, first_hash)
            manifest = verify_release(Path(second.archive))
            self.assertEqual(manifest["target"]["maya"], "2025")
            names = {item["path"] for item in manifest["files"]}
            self.assertIn("MayaScope/launch.py", names)
            self.assertIn("MayaScope/docs/OPERATIONS.md", names)
            self.assertIn("showcase/showcase.ma", names)
            self.assertFalse(any("/tests/" in name for name in names))
            self.assertFalse(any("/legacy/" in name for name in names))

    def test_unmanifested_archive_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = build_release(Path(folder))
            with zipfile.ZipFile(receipt.archive, "a") as archive:
                archive.writestr("surprise.txt", "not in manifest")
            with self.assertRaisesRegex(ValueError, "unmanifested"):
                verify_release(Path(receipt.archive))


if __name__ == "__main__":
    unittest.main()
