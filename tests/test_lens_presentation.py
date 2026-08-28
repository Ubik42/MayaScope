from __future__ import annotations

from pathlib import Path
import unittest

from MayaScope.analysis.lens import RootCauseCandidate, build_root_cause_report
from MayaScope.analysis.measured_lens import build_measured_root_cause_report
from MayaScope.model import (
    ProfilerCapture,
    ProfilerCategory,
    ProfilerEvent,
    SceneEdge,
    SceneNode,
    SceneSnapshot,
)
from MayaScope.presentation import (
    LensPresentationError,
    present_lens_candidate,
    present_lens_result,
)


class LensPresentationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SceneSnapshot.build(
            (
                SceneNode("matrix", "角色总控矩阵", "multMatrix"),
                SceneNode("decompose", "空间分解", "decomposeMatrix"),
                SceneNode("driver", "共享表情驱动", "multiplyDivide"),
                SceneNode("focus", "主角面部控制器", "transform"),
                SceneNode("secondary", "次级面部控制器", "transform"),
            ),
            (
                SceneEdge("matrix", "decompose", source_plug="matrixSum", target_plug="inputMatrix"),
                SceneEdge("decompose", "driver", source_plug="outputTranslateX", target_plug="input1X"),
                SceneEdge("driver", "focus", source_plug="outputX", target_plug="translateX"),
                SceneEdge("driver", "secondary", source_plug="outputX", target_plug="translateX"),
            ),
            snapshot_id="lens-scene",
            metadata={"capture_reuse": {"topology_unchanged": True}},
        )
        self.report = build_root_cause_report(self.snapshot, "focus", max_depth=4)

    def test_structural_result_is_chinese_and_exposes_query_telemetry(self):
        state = present_lens_result(self.report, self.snapshot)
        self.assertEqual(len(state.cards), 3)
        self.assertIn("结构推断", state.summary)
        self.assertIn("节点 /", state.summary)
        self.assertIn("CSR 已复用", state.status)
        self.assertEqual(state.cards[0].rank, 1)
        self.assertFalse(state.cards[0].measured)

    def test_candidate_evidence_preserves_path_and_exact_plugs(self):
        candidate = next(item for item in self.report.candidates if item.node_id == "matrix")
        evidence = present_lens_candidate(candidate, self.report, self.snapshot)
        self.assertEqual(evidence.heading, "角色总控矩阵")
        self.assertIn("角色总控矩阵  →  空间分解", evidence.body)
        self.assertIn("matrixSum  →  inputMatrix", evidence.body)
        self.assertIn("该分数不是概率", evidence.body)

    def test_profiler_measurement_is_labelled_as_observation_not_savings(self):
        capture = ProfilerCapture(
            events=(
                ProfilerEvent(0, 0, 2200, 2200, 1, 0, 0, "DG", 1, "Compute", "共享表情驱动", node_id="driver"),
                ProfilerEvent(1, 0, 4000, 4000, 1, 0, 0, "DG", 1, "Compute", "主角面部控制器", node_id="focus"),
            ),
            categories=(ProfilerCategory(0, "DG"),),
            source_snapshot_id="lens-scene",
        )
        measured = build_measured_root_cause_report(
            self.snapshot, capture, "focus", start_us=0, end_us=4000
        )
        state = present_lens_result(measured.structural, self.snapshot, measured)
        self.assertTrue(any(card.measured for card in state.cards))
        self.assertIn("实测覆盖", state.summary)
        evidence = present_lens_candidate(
            measured.candidates[0].structural,
            measured.structural,
            self.snapshot,
            measured,
        )
        self.assertIn("观测证据，不代表预计优化收益", evidence.body)

    def test_stale_report_and_foreign_candidate_fail_closed(self):
        other = SceneSnapshot.build((SceneNode("other", "别的场景", "transform"),), ())
        with self.assertRaisesRegex(LensPresentationError, "焦点不属于当前快照"):
            present_lens_result(self.report, other)
        foreign = RootCauseCandidate(
            node_id="secondary",
            distance=1,
            structural_score=1.0,
            path_node_ids=("focus", "secondary"),
            path_links=(),
            evidence=(),
            reasons=("伪造候选",),
        )
        with self.assertRaisesRegex(LensPresentationError, "不属于当前透镜结果"):
            present_lens_candidate(foreign, self.report, self.snapshot)

    def test_presenter_has_no_qt_maya_collector_or_view_dependency(self):
        source = (
            Path(__file__).resolve().parents[1] / "presentation" / "lens.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in ("pyside", "qtwidgets", "maya.cmds", "collectors", "ui."):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
