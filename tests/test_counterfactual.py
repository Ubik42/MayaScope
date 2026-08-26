from __future__ import annotations

import unittest

from MayaScope.analysis.counterfactual import (
    CounterfactualReport,
    ExperimentObservation,
    build_counterfactual_report,
)
from MayaScope.collectors import MayaCounterfactualError, plan_node_state_experiment
from MayaScope.model import SceneNode, SceneSnapshot


def observation(pair, condition, wall, node_time, order=0):
    return ExperimentObservation(
        pair_index=pair,
        condition=condition,
        order_index=order,
        wall_time_us=wall,
        profiler_duration_us=wall - 10,
        mapped_event_count=4,
        capture_id="%s-%s" % (pair, condition),
        node_inclusive_us=(("target", node_time), ("downstream", node_time // 2)),
    )


class CounterfactualTests(unittest.TestCase):
    def test_paired_bootstrap_reports_improvement_and_node_evidence(self):
        measured = []
        for pair, (baseline, variant) in enumerate(((1000, 700), (1050, 710), (980, 690), (1020, 705))):
            order = ("baseline", "variant") if pair % 2 == 0 else ("variant", "baseline")
            values = {"baseline": baseline, "variant": variant}
            node_values = {"baseline": 500, "variant": 180}
            for order_index, condition in enumerate(order):
                measured.append(
                    observation(pair, condition, values[condition], node_values[condition], order_index)
                )
        report = build_counterfactual_report(
            measured,
            target_node_id="target",
            target_name="bend1",
            attribute="nodeState",
            baseline_value=0,
            variant_value=1,
            source_snapshot_id="snapshot-a",
            warmup_count=1,
        )
        self.assertEqual(report.verdict, "improved")
        self.assertGreater(report.benefit_ci_low_us, 0)
        self.assertEqual(report.pair_count, 4)
        self.assertAlmostEqual(report.node_effects[0].observed_delta_us, 320.0)
        self.assertEqual(CounterfactualReport.from_json(report.to_json()), report)

    def test_interval_crossing_zero_is_inconclusive(self):
        report = build_counterfactual_report(
            (
                observation(0, "baseline", 100, 40, 0),
                observation(0, "variant", 110, 30, 1),
                observation(1, "variant", 90, 30, 0),
                observation(1, "baseline", 100, 40, 1),
            ),
            target_node_id="target",
            target_name="bend1",
            attribute="nodeState",
            baseline_value=0,
            variant_value=1,
        )
        self.assertEqual(report.verdict, "inconclusive")
        self.assertLessEqual(report.benefit_ci_low_us, 0)
        self.assertGreaterEqual(report.benefit_ci_high_us, 0)

    def test_unpaired_or_duplicate_observations_fail_loudly(self):
        baseline = observation(0, "baseline", 100, 40)
        with self.assertRaisesRegex(ValueError, "requires baseline and variant"):
            build_counterfactual_report(
                (baseline,),
                target_node_id="target",
                target_name="bend1",
                attribute="nodeState",
                baseline_value=0,
                variant_value=1,
            )
        with self.assertRaisesRegex(ValueError, "Duplicate baseline"):
            build_counterfactual_report(
                (baseline, baseline),
                target_node_id="target",
                target_name="bend1",
                attribute="nodeState",
                baseline_value=0,
                variant_value=1,
            )

    def test_planning_refuses_referenced_nodes_before_maya_mutation(self):
        snapshot = SceneSnapshot.build(
            (SceneNode("ref-id", "asset:bend", "nonLinear", referenced=True),),
            (),
        )
        with self.assertRaisesRegex(MayaCounterfactualError, "Referenced nodes"):
            plan_node_state_experiment(snapshot, "ref-id")


if __name__ == "__main__":
    unittest.main()
