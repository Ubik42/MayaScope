from __future__ import annotations

from dataclasses import replace
import unittest

from MayaScope.analysis.counterfactual import (
    ExperimentObservation,
    build_counterfactual_report,
)
from MayaScope.presentation.counterfactual import (
    CounterfactualPresentationError,
    present_counterfactual_report,
)


def _observation(pair, condition, wall, node_time, order):
    return ExperimentObservation(
        pair_index=pair,
        condition=condition,
        order_index=order,
        wall_time_us=wall,
        profiler_duration_us=wall - 10,
        mapped_event_count=3,
        capture_id="%s-%s" % (pair, condition),
        node_inclusive_us=(("target", node_time),),
    )


def _report():
    return build_counterfactual_report(
        (
            _observation(0, "baseline", 1000, 500, 0),
            _observation(0, "variant", 700, 190, 1),
            _observation(1, "variant", 680, 180, 0),
            _observation(1, "baseline", 1020, 510, 1),
        ),
        target_node_id="target",
        target_name="角色绑定求解器",
        attribute="nodeState",
        baseline_value=0,
        variant_value=1,
        warmup_count=2,
    )


class CounterfactualPresentationTests(unittest.TestCase):
    def test_report_unifies_spectrum_evidence_status_and_archive_receipt(self):
        state = present_counterfactual_report(
            _report(),
            node_names={"target": "面部求解器"},
            archive_path="D:/evidence/experiment.json",
            archive_checksum="a" * 64,
        )
        self.assertEqual(state.target, "角色绑定求解器")
        self.assertEqual(state.verdict, "improved")
        self.assertEqual(len(state.pairs), 2)
        self.assertIn("改善", state.metric)
        self.assertIn("2 组配对", state.design)
        self.assertIn("面部求解器", state.body)
        self.assertIn("experiment.json", state.body)
        self.assertIn("状态与 Undo 已恢复", state.status_text)

    def test_inconclusive_verdict_is_explained_in_chinese(self):
        state = present_counterfactual_report(replace(_report(), verdict="inconclusive"))
        self.assertIn("证据不足", state.metric)
        self.assertIn("结论 证据不足", state.body)

    def test_incomplete_pair_is_rejected_before_any_view_transition(self):
        malformed = replace(_report(), observations=(_report().observations[0],))
        with self.assertRaisesRegex(CounterfactualPresentationError, "缺少 baseline 或 variant"):
            present_counterfactual_report(malformed)


if __name__ == "__main__":
    unittest.main()
