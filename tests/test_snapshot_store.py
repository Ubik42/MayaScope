from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.model import SceneEdge, SceneNode, SceneSnapshot
from MayaScope.storage import SnapshotStore, SnapshotStoreError


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "archive"
        self.store = SnapshotStore(self.root)
        self.snapshot = SceneSnapshot.build(
            (SceneNode("a", "角色:控制器", "transform"), SceneNode("b", "driver", "network")),
            (SceneEdge("b", "a", source_plug="driver.out", target_plug="角色:控制器.tx"),),
            snapshot_id="snapshot-test",
            captured_at="2026-08-25T12:00:00+00:00",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_atomic_round_trip_and_listing(self):
        saved = self.store.save(self.snapshot, label="before rig fix")
        self.assertTrue(saved.path.exists())
        self.assertFalse(tuple(self.root.glob("*.tmp")))
        loaded = self.store.load(saved.path.name)
        self.assertEqual(loaded.snapshot, self.snapshot)
        self.assertEqual(loaded.label, "before rig fix")
        self.assertEqual(self.store.list_records()[0].checksum, saved.checksum)

    def test_checksum_detects_payload_tampering(self):
        saved = self.store.save(self.snapshot)
        with gzip.open(str(saved.path), "rb") as stream:
            envelope = json.loads(stream.read().decode("utf-8"))
        envelope["snapshot"]["nodes"][0]["name"] = "tampered"
        with gzip.open(str(saved.path), "wb") as stream:
            stream.write(json.dumps(envelope).encode("utf-8"))
        with self.assertRaisesRegex(SnapshotStoreError, "checksum mismatch"):
            self.store.load(saved.path)

    def test_path_escape_is_rejected(self):
        outside = self.root.parent / "outside.mscope.json.gz"
        with self.assertRaisesRegex(ValueError, "escapes store root"):
            self.store.load(outside)


if __name__ == "__main__":
    unittest.main()
