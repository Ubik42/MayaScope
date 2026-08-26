from __future__ import annotations

import unittest

from MayaScope.analysis.measured_lens import build_measured_root_cause_report
from MayaScope.model import ProfilerCapture, ProfilerCategory, ProfilerEvent, SceneEdge, SceneNode, SceneSnapshot


class MeasuredLensTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SceneSnapshot.build(
            (
                SceneNode("expression", "expr", "expression"),
                SceneNode("matrix", "matrix", "multMatrix"),
                SceneNode("focus", "control", "transform"),
            ),
            (SceneEdge("expression", "matrix"), SceneEdge("matrix", "focus")),
            snapshot_id="scene-a",
        )
        category = (ProfilerCategory(0, "Evaluation"),)
        self.capture = ProfilerCapture(
            events=(
                ProfilerEvent(0, 0, 50, 50, 1, 0, 0, "Evaluation", 1, "Compute", "expr", node_id="expression"),
                ProfilerEvent(1, 5, 20, 20, 1, 0, 0, "Evaluation", 1, "Compute", "matrix", node_id="matrix"),
                ProfilerEvent(2, 0, 100, 100, 1, 0, 0, "Evaluation", 1, "Compute", "control", node_id="focus"),
                ProfilerEvent(3, 0, 10, 10, 2, 1, 0, "Evaluation", 1, "Unknown"),
            ),
            categories=category,
            source_snapshot_id="scene-a",
        )

    def test_observed_duration_reorders_structural_candidates(self):
        report = build_measured_root_cause_report(
            self.snapshot, self.capture, "focus", start_us=0, end_us=100
        )
        self.assertEqual(report.candidates[0].structural.node_id, "expression")
        self.assertEqual(report.candidates[0].observed_inclusive_us, 50)
        self.assertEqual(report.candidates[0].path_inclusive_us, 170)
        self.assertEqual(report.selected_event_count, 4)
        self.assertAlmostEqual(report.measurement_coverage, 0.75)

    def test_range_clips_observed_duration(self):
        report = build_measured_root_cause_report(
            self.snapshot, self.capture, "focus", start_us=20, end_us=40
        )
        expression = next(
            candidate for candidate in report.candidates if candidate.structural.node_id == "expression"
        )
        self.assertEqual(expression.observed_inclusive_us, 20)
        matrix = next(candidate for candidate in report.candidates if candidate.structural.node_id == "matrix")
        self.assertEqual(matrix.observed_inclusive_us, 5)

    def test_capture_snapshot_mismatch_is_rejected(self):
        other = ProfilerCapture(
            events=(), categories=(), source_snapshot_id="different-scene"
        )
        with self.assertRaisesRegex(ValueError, "different SceneSnapshot"):
            build_measured_root_cause_report(self.snapshot, other, "focus")


if __name__ == "__main__":
    unittest.main()
