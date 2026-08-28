from __future__ import annotations

import unittest

from MayaScope.presentation.regression import (
    RegressionPresentationError,
    present_regression_report,
)


def _performance(*, regressed=True):
    return {
        "comparable": True,
        "regressed": regressed,
        "baseline": {"samples_us": [10000, 10100, 9900], "median_us": 10000},
        "current": {"samples_us": [14000, 14100, 13900], "median_us": 14000},
        "required_delta_us": 2000,
        "delta_us": 4000,
        "slowdown_ratio": 0.4,
    }


def _payload(**regression_overrides):
    regression = {
        "baseline_report_sha256": "a" * 64,
        "new_findings": (),
        "escalated_findings": (),
        "resolved_findings": (),
        "performance": {"comparable": False},
        "gate_failed": False,
    }
    regression.update(regression_overrides)
    return {"report_sha256": "b" * 64, "regression": regression}


class RegressionPresentationTests(unittest.TestCase):
    def test_stable_report_without_performance_is_explained_honestly(self):
        state = present_regression_report(_payload())
        self.assertEqual(state.verdict, "基线保持稳定")
        self.assertIn("无性能配对", state.detail)
        self.assertIn("性能证据不可用", state.evidence_body)
        self.assertFalse(state.performance.comparable)
        self.assertEqual(state.status_text, "回归裂隙  ·  基线保持稳定")

    def test_regression_unifies_strip_evidence_and_deduplicated_highlights(self):
        state = present_regression_report(
            _payload(
                gate_failed=True,
                performance=_performance(),
                new_findings=(
                    {"node_id": "rigRoot"},
                    {"node_id": "<scene>"},
                ),
                escalated_findings=(
                    {"node_id": "rigRoot"},
                    {"node_id": "faceSolver"},
                ),
                resolved_findings=({"node_id": "oldNode"},),
            )
        )
        self.assertEqual(state.verdict, "检测到回归裂隙")
        self.assertEqual(state.active_node_ids, ("rigRoot", "faceSolver"))
        self.assertIn("+4.00 ms", state.detail)
        self.assertIn("求值中位数：10.00 → 14.00 ms", state.evidence_body)
        self.assertTrue(state.performance.regressed)

    def test_incomplete_comparable_payload_is_rejected_before_render(self):
        with self.assertRaisesRegex(RegressionPresentationError, "字段不完整"):
            present_regression_report(
                _payload(
                    performance={
                        "comparable": True,
                        "baseline": {"samples_us": [1, 2, 3]},
                        "current": {"samples_us": [2, 3, 4]},
                    }
                )
            )


if __name__ == "__main__":
    unittest.main()
