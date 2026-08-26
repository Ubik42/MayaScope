from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.analysis.counterfactual import ExperimentObservation, build_counterfactual_report
from MayaScope.storage import ExperimentStore, ExperimentStoreError


class ExperimentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "experiments"
        self.store = ExperimentStore(self.root)
        observations = (
            ExperimentObservation(0, "baseline", 0, 1000, 900, 3),
            ExperimentObservation(0, "variant", 1, 700, 620, 2),
            ExperimentObservation(1, "variant", 0, 720, 640, 2),
            ExperimentObservation(1, "baseline", 1, 980, 880, 3),
        )
        self.report = build_counterfactual_report(
            observations,
            target_node_id="node-id",
            target_name="角色:deformer",
            attribute="nodeState",
            baseline_value=0,
            variant_value=1,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_atomic_round_trip_and_listing(self):
        saved = self.store.save(self.report)
        self.assertTrue(saved.path.exists())
        self.assertFalse(tuple(self.root.glob("*.tmp")))
        loaded = self.store.load(saved.path.name)
        self.assertEqual(loaded.report, self.report)
        self.assertEqual(self.store.list_records()[0].checksum, saved.checksum)

    def test_checksum_detects_tampering(self):
        saved = self.store.save(self.report)
        with gzip.open(str(saved.path), "rb") as stream:
            envelope = json.loads(stream.read().decode("utf-8"))
        envelope["report"]["benefit_mean_us"] = 999999
        with gzip.open(str(saved.path), "wb") as stream:
            stream.write(json.dumps(envelope).encode("utf-8"))
        with self.assertRaisesRegex(ExperimentStoreError, "checksum mismatch"):
            self.store.load(saved.path)

    def test_path_escape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "escapes store root"):
            self.store.load(self.root.parent / "outside.msexperiment.json.gz")


if __name__ == "__main__":
    unittest.main()
