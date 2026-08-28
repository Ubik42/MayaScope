from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import unittest

from MayaScope.analysis.clinic import ClinicReport, RuleRun
from MayaScope.analysis.counterfactual import (
    ExperimentObservation,
    build_counterfactual_report,
)
from MayaScope.analysis.incidents import Incident
from MayaScope.analysis.rules import Evidence, Issue, Severity
from MayaScope.analysis.runtime import RuntimeReport
from MayaScope.application import (
    AtlasClearIntent,
    AtlasCounterfactualIntent,
    AtlasDeltaIntent,
    AtlasHighlightIntent,
    AtlasLensIntent,
    AtlasPulseIntent,
    AtlasSceneIntent,
    AtlasSelectionIntent,
    InvestigationCoordinator,
    InvestigationStateError,
    InvestigationTransition,
    resolve_host_selection,
)
from MayaScope.model import (
    ProfilerCapture,
    ProfilerCategory,
    ProfilerEvent,
    RuntimeSnapshot,
    SceneEdge,
    SceneNode,
    SceneSnapshot,
)
from MayaScope.presentation import WorkspacePresentationState
from MayaScope.ui.investigation_renderer import render_atlas_transition


class InvestigationCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = InvestigationCoordinator()
        self.snapshot = SceneSnapshot.build(
            (
                SceneNode("a", "驱动_A", "network", dag_paths=("|角色|驱动_A",)),
                SceneNode("b", "中间_B", "network"),
                SceneNode("c", "结果_C", "network"),
            ),
            (
                SceneEdge("a", "b", source_plug="out", target_plug="in"),
                SceneEdge("b", "c", source_plug="out", target_plug="in"),
            ),
            snapshot_id="scene-current",
            metadata={"selection": ("|角色|驱动_A",)},
        )
        self.issue = Issue(
            id="issue:b",
            rule_id="test-rule",
            title="中间节点异常",
            description="用于验证调查协调器。",
            severity=Severity.WARNING,
            affected_node_ids=("b",),
            evidence=(Evidence("节点", "中间_B"),),
        )
        self.report = ClinicReport(
            self.snapshot.snapshot_id,
            (self.issue,),
            (RuleRun("test-rule", 0.2, 1),),
            (),
            (),
        )
        self.incident = Incident(
            "incident:b",
            "中间节点事件",
            Severity.WARNING,
            (self.issue.id,),
            ("b",),
            (Evidence("聚类", "1 项关联发现"),),
        )

    def _accepted(self):
        return self.coordinator.accept_scene(
            WorkspacePresentationState(),
            self.snapshot,
            self.report,
            (self.incident,),
        )

    def _capture(self, *, source_snapshot_id=None, node_id="b", duration_us=100):
        return ProfilerCapture(
            events=(
                ProfilerEvent(
                    0,
                    0,
                    duration_us,
                    duration_us,
                    0,
                    0,
                    0,
                    "DG",
                    0,
                    "中间_B",
                    node_id=node_id,
                ),
            ),
            categories=(ProfilerCategory(0, "DG"),),
            source_snapshot_id=(
                self.snapshot.snapshot_id
                if source_snapshot_id is None
                else source_snapshot_id
            ),
        )

    def _counterfactual_run(self, *, state_restored=True, source_snapshot_id=None):
        source_id = (
            self.snapshot.snapshot_id
            if source_snapshot_id is None
            else source_snapshot_id
        )
        observations = (
            ExperimentObservation(0, "baseline", 0, 120, 100, 1),
            ExperimentObservation(0, "variant", 1, 90, 80, 1),
            ExperimentObservation(1, "variant", 0, 92, 82, 1),
            ExperimentObservation(1, "baseline", 1, 124, 104, 1),
        )
        report = build_counterfactual_report(
            observations,
            target_node_id="b",
            target_name="中间_B",
            attribute="nodeState",
            baseline_value=0,
            variant_value=1,
            source_snapshot_id=source_id,
            bootstrap_iterations=100,
            metadata={
                "state_restored": state_restored,
                "undo_head_preserved": True,
            },
        )
        captures = tuple(
            self._capture(source_snapshot_id=source_id) for _index in range(2)
        )
        return SimpleNamespace(
            report=report,
            baseline_captures=captures,
            variant_captures=captures,
        )

    def test_accept_scene_validates_generation_and_emits_scene_intent(self):
        transition = self._accepted()
        self.assertIs(transition.state.snapshot, self.snapshot)
        self.assertEqual(transition.state.issues, (self.issue,))
        self.assertEqual(transition.state.incidents, (self.incident,))
        intent = transition.atlas_intents[0]
        self.assertIsInstance(intent, AtlasSceneIntent)
        self.assertEqual(intent.priority_node_ids, ("a",))
        with self.assertRaises(TypeError):
            transition.identity_index["new"] = "a"

    def test_accept_scene_computes_delta_in_the_same_generation_transition(self):
        before = SceneSnapshot.build(
            self.snapshot.nodes[:2],
            (SceneEdge("a", "b"),),
            snapshot_id="scene-before",
        )
        transition = self.coordinator.accept_scene(
            WorkspacePresentationState(snapshot=before),
            self.snapshot,
            self.report,
            (self.incident,),
            previous_snapshot=before,
        )
        self.assertIsNotNone(transition.state.delta)
        self.assertIs(transition.state.delta_before, before)
        self.assertEqual(
            {change.node_id for change in transition.state.delta.node_changes},
            {"c"},
        )

    def test_stale_clinic_result_is_rejected_before_it_reaches_the_view(self):
        stale = ClinicReport("scene-old", (), (), (), ())
        with self.assertRaisesRegex(InvestigationStateError, "旧快照"):
            self.coordinator.accept_scene(
                WorkspacePresentationState(), self.snapshot, stale, ()
            )
        current = self._accepted().state
        with self.assertRaisesRegex(InvestigationStateError, "旧快照"):
            self.coordinator.accept_clinic(current, stale, ())

    def test_issue_and_incident_selection_clear_lens_and_emit_highlight(self):
        state = self._accepted().state.update(
            focus_node_id="c",
            lens_report=object(),
        )
        selected = self.coordinator.select_issue(state, self.issue)
        self.assertIs(selected.state.selected_issue, self.issue)
        self.assertIsNone(selected.state.focus_node_id)
        self.assertIsInstance(selected.atlas_intents[0], AtlasClearIntent)
        self.assertEqual(selected.atlas_intents[1], AtlasHighlightIntent(("b",)))
        clustered = self.coordinator.select_incident(state, self.incident)
        self.assertIs(clustered.state.selected_incident, self.incident)
        self.assertEqual(clustered.atlas_intents[1], AtlasHighlightIntent(("b",)))

    def test_stale_issue_and_incident_selection_are_rejected(self):
        state = self._accepted().state
        stale_issue = Issue(
            "issue:old",
            "test-rule",
            "旧诊断",
            "不属于当前代。",
            Severity.INFO,
            (),
            (),
        )
        stale_incident = Incident(
            "incident:old", "旧事件", Severity.INFO, (), (), ()
        )
        with self.assertRaisesRegex(InvestigationStateError, "不属于当前快照"):
            self.coordinator.select_issue(state, stale_issue)
        with self.assertRaisesRegex(InvestigationStateError, "不属于当前快照"):
            self.coordinator.select_incident(state, stale_incident)

    def test_focus_and_candidate_form_one_validated_lens_generation(self):
        state = self._accepted().state
        focused = self.coordinator.focus(
            state,
            "c",
            direction="upstream",
            max_depth=4,
        )
        self.assertEqual(focused.state.focus_node_id, "c")
        self.assertIsInstance(focused.atlas_intents[0], AtlasLensIntent)
        self.assertTrue(focused.state.lens_report.candidates)
        candidate = focused.state.lens_report.candidates[0]
        selected = self.coordinator.select_candidate(focused.state, candidate)
        self.assertEqual(selected.state.selected_candidate.node_id, candidate.node_id)
        self.assertEqual(selected.atlas_intents[0].candidate.node_id, candidate.node_id)

    def test_close_lens_restores_profiler_or_counterfactual_overlay(self):
        capture = ProfilerCapture(
            events=(
                ProfilerEvent(
                    0, 0, 100, 100, 0, 0, 0, "DG", 0, "中间_B", node_id="b"
                ),
            ),
            categories=(ProfilerCategory(0, "DG"),),
            source_snapshot_id=self.snapshot.snapshot_id,
        )
        state = self._accepted().state.present_profiler(capture).focus("b")
        restored = self.coordinator.close_lens(state)
        self.assertIsNone(restored.state.focus_node_id)
        self.assertIsInstance(restored.atlas_intents[0], AtlasPulseIntent)
        self.assertEqual(restored.atlas_intents[0].stats[0].node_id, "b")
        report = SimpleNamespace(target_node_id="b")
        counterfactual = state.present_counterfactual(SimpleNamespace(report=report))
        restored = self.coordinator.close_lens(counterfactual)
        self.assertIsInstance(restored.atlas_intents[0], AtlasCounterfactualIntent)
        self.assertIs(restored.atlas_intents[0].report, report)

    def test_profiler_is_accepted_as_one_validated_generation(self):
        state = self._accepted().state
        capture = self._capture()
        transition = self.coordinator.accept_profiler(state, capture)
        self.assertIs(transition.state.profiler_capture, capture)
        self.assertEqual(transition.state.pulse_range, (0, 100))
        self.assertIsInstance(transition.atlas_intents[0], AtlasPulseIntent)
        self.assertEqual(transition.atlas_intents[0].stats[0].node_id, "b")
        with self.assertRaisesRegex(InvestigationStateError, "不属于当前快照"):
            self.coordinator.accept_profiler(state, self._capture(source_snapshot_id="old"))
        with self.assertRaisesRegex(InvestigationStateError, "快照之外"):
            self.coordinator.accept_profiler(state, self._capture(node_id="missing"))

    def test_pulse_range_is_normalized_and_bounds_checked(self):
        profiled = self.coordinator.accept_profiler(
            self._accepted().state,
            self._capture(),
        ).state
        transition = self.coordinator.set_pulse_range(profiled, 80, 20)
        self.assertEqual(transition.state.pulse_range, (20, 80))
        self.assertIsInstance(transition.atlas_intents[0], AtlasPulseIntent)
        with self.assertRaisesRegex(InvestigationStateError, "越界"):
            self.coordinator.set_pulse_range(profiled, -1, 101)

    def test_runtime_inventory_and_report_share_one_identity_boundary(self):
        state = self._accepted().state
        runtime = RuntimeSnapshot(
            source_snapshot_id=self.snapshot.snapshot_id,
            script_jobs=(),
            expressions=(),
            plugins=(),
            node_callbacks=(),
            script_jobs_available=True,
            batch_mode=False,
            maya_version="2025",
            runtime_id="runtime-current",
        )
        report = RuntimeReport("runtime-current", (self.issue,), ("只读清点",))
        transition = self.coordinator.accept_runtime(state, runtime, report)
        self.assertIs(transition.state.runtime_snapshot, runtime)
        self.assertIsInstance(transition.atlas_intents[0], AtlasHighlightIntent)
        self.assertEqual(transition.atlas_intents[0].node_ids, ("b",))
        with self.assertRaisesRegex(InvestigationStateError, "身份不一致"):
            self.coordinator.accept_runtime(
                state,
                runtime,
                RuntimeReport("runtime-old", (), ()),
            )
        stale = RuntimeSnapshot(
            source_snapshot_id="scene-old",
            script_jobs=(),
            expressions=(),
            plugins=(),
            node_callbacks=(),
            script_jobs_available=False,
            batch_mode=True,
            maya_version="2025",
        )
        with self.assertRaisesRegex(InvestigationStateError, "不属于当前快照"):
            self.coordinator.accept_runtime(
                state,
                stale,
                RuntimeReport(stale.runtime_id, (), ()),
            )

    def test_counterfactual_requires_restoration_and_exact_scene_generation(self):
        state = self._accepted().state
        run = self._counterfactual_run()
        transition = self.coordinator.accept_counterfactual(state, run, "receipt")
        self.assertIs(transition.state.counterfactual_run, run)
        self.assertEqual(transition.state.counterfactual_record, "receipt")
        self.assertIsInstance(
            transition.atlas_intents[0], AtlasCounterfactualIntent
        )
        with self.assertRaisesRegex(InvestigationStateError, "状态已经恢复"):
            self.coordinator.accept_counterfactual(
                state,
                self._counterfactual_run(state_restored=False),
            )
        with self.assertRaisesRegex(InvestigationStateError, "不属于当前快照"):
            self.coordinator.accept_counterfactual(
                state,
                self._counterfactual_run(source_snapshot_id="scene-old"),
            )

    def test_dismissing_counterfactual_restores_profiler_overlay(self):
        state = self.coordinator.accept_profiler(
            self._accepted().state,
            self._capture(),
        ).state
        counterfactual = self.coordinator.accept_counterfactual(
            state,
            self._counterfactual_run(),
        ).state
        transition = self.coordinator.dismiss_counterfactual(counterfactual)
        self.assertIsNone(transition.state.counterfactual_run)
        self.assertIsInstance(transition.atlas_intents[0], AtlasPulseIntent)

    def test_dismissing_profiler_clears_derived_lens_and_restores_delta(self):
        before = SceneSnapshot.build(
            self.snapshot.nodes[:2],
            (SceneEdge("a", "b"),),
            snapshot_id="scene-before",
        )
        state = self.coordinator.accept_scene(
            WorkspacePresentationState(snapshot=before),
            self.snapshot,
            self.report,
            (self.incident,),
            previous_snapshot=before,
        ).state
        state = self.coordinator.accept_profiler(state, self._capture()).state
        state = self.coordinator.focus(
            state,
            "b",
            direction="upstream",
            max_depth=4,
        ).state
        transition = self.coordinator.dismiss_profiler(state)
        self.assertIsNone(transition.state.profiler_capture)
        self.assertEqual(transition.state.pulse_range, (0, 0))
        self.assertIsNone(transition.state.lens_report)
        self.assertIsInstance(transition.atlas_intents[0], AtlasDeltaIntent)
        self.assertIs(transition.atlas_intents[0].delta, state.delta)

    def test_dismissing_runtime_restores_profiler_instead_of_leaving_highlight(self):
        state = self.coordinator.accept_profiler(
            self._accepted().state,
            self._capture(),
        ).state
        runtime = RuntimeSnapshot(
            source_snapshot_id=self.snapshot.snapshot_id,
            script_jobs=(),
            expressions=(),
            plugins=(),
            node_callbacks=(),
            script_jobs_available=True,
            batch_mode=False,
            maya_version="2025",
        )
        state = self.coordinator.accept_runtime(
            state,
            runtime,
            RuntimeReport(runtime.runtime_id, (self.issue,), ()),
        ).state
        transition = self.coordinator.dismiss_runtime(state)
        self.assertIsNone(transition.state.runtime_snapshot)
        self.assertIsNone(transition.state.runtime_report)
        self.assertIsInstance(transition.atlas_intents[0], AtlasPulseIntent)

    def test_dismissing_profiler_keeps_valid_runtime_highlight(self):
        state = self.coordinator.accept_profiler(
            self._accepted().state,
            self._capture(),
        ).state
        runtime = RuntimeSnapshot(
            source_snapshot_id=self.snapshot.snapshot_id,
            script_jobs=(),
            expressions=(),
            plugins=(),
            node_callbacks=(),
            script_jobs_available=True,
            batch_mode=False,
            maya_version="2025",
        )
        state = self.coordinator.accept_runtime(
            state,
            runtime,
            RuntimeReport(runtime.runtime_id, (self.issue,), ()),
        ).state
        transition = self.coordinator.dismiss_profiler(state)
        self.assertIs(transition.state.runtime_snapshot, runtime)
        self.assertIsInstance(transition.atlas_intents[0], AtlasHighlightIntent)
        self.assertEqual(transition.atlas_intents[0].node_ids, ("b",))

    def test_exact_identity_mapping_refuses_ambiguous_short_names(self):
        ambiguous = SceneSnapshot.build(
            (
                SceneNode("left", "ctrl", "transform", dag_paths=("|左|ctrl",)),
                SceneNode("right", "ctrl", "transform", dag_paths=("|右|ctrl",)),
            ),
            (),
        )
        self.assertEqual(resolve_host_selection(ambiguous, ("ctrl",)), ())
        self.assertEqual(resolve_host_selection(ambiguous, ("|右|ctrl",)), ("right",))

    def test_host_selection_is_one_coherent_selection_and_lens_decision(self):
        state = self._accepted().state
        single = self.coordinator.host_selection(
            state,
            ("结果_C",),
            direction="upstream",
            max_depth=4,
            center=True,
        )
        self.assertEqual(single.outcome, "single")
        self.assertEqual(single.node_ids, ("c",))
        self.assertEqual(single.transition.state.focus_node_id, "c")
        self.assertEqual(
            single.transition.atlas_intents[0],
            AtlasSelectionIntent(("c",), True),
        )
        self.assertIsInstance(single.transition.atlas_intents[1], AtlasLensIntent)

        multiple = self.coordinator.host_selection(
            single.transition.state,
            ("驱动_A", "中间_B"),
            direction="upstream",
            max_depth=4,
            center=False,
        )
        self.assertEqual(multiple.outcome, "multiple")
        self.assertIsNone(multiple.transition.state.focus_node_id)
        self.assertIsInstance(multiple.transition.atlas_intents[-1], AtlasHighlightIntent)

    def test_empty_and_unmapped_host_selection_have_distinct_safe_outcomes(self):
        state = self._accepted().state.focus("b")
        empty = self.coordinator.host_selection(
            state,
            (),
            direction="upstream",
            max_depth=4,
            center=False,
        )
        self.assertEqual(empty.outcome, "empty")
        self.assertIsNone(empty.transition.state.focus_node_id)
        self.assertEqual(
            empty.transition.atlas_intents[-1], AtlasSelectionIntent((), False)
        )
        unmapped = self.coordinator.host_selection(
            state,
            ("不存在的节点",),
            direction="upstream",
            max_depth=4,
            center=False,
        )
        self.assertEqual(unmapped.outcome, "unmapped")
        self.assertIs(unmapped.transition.state, state)
        self.assertEqual(unmapped.transition.atlas_intents, ())

    def test_application_coordinator_has_no_maya_qt_or_view_dependency(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "application"
            / "investigation.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "maya.cmds",
            "maya.api",
            "qt_compat",
            "..ui",
            "QWidget",
            "collectors",
        ):
            self.assertNotIn(forbidden, source)

    def test_qt_adapter_dispatches_typed_intents_without_business_decisions(self):
        class AtlasProbe:
            def __init__(self):
                self.calls = []

            def set_snapshot(self, snapshot, issues, priority_node_ids=()):
                self.calls.append(("scene", snapshot, issues, priority_node_ids))

            def highlight(self, node_ids):
                self.calls.append(("highlight", node_ids))

            def show_lens(self, report, candidate=None):
                self.calls.append(("lens", report, candidate))

            def select_node_ids(self, node_ids, center=False):
                self.calls.append(("selection", node_ids, center))

            def show_pulse(self, stats):
                self.calls.append(("pulse", stats))

            def show_counterfactual(self, report):
                self.calls.append(("counterfactual", report))

            def show_delta(self, delta):
                self.calls.append(("delta", delta))

            def clear_lens(self):
                self.calls.append(("clear",))

        lens = SimpleNamespace(name="lens")
        candidate = SimpleNamespace(name="candidate")
        counterfactual = SimpleNamespace(name="counterfactual")
        delta = SimpleNamespace(name="delta")
        intents = (
            AtlasSceneIntent(self.snapshot, (self.issue,), ("a",)),
            AtlasHighlightIntent(("b",)),
            AtlasLensIntent(lens, candidate),
            AtlasSelectionIntent(("c",), True),
            AtlasPulseIntent(()),
            AtlasCounterfactualIntent(counterfactual),
            AtlasDeltaIntent(delta),
            AtlasClearIntent(),
        )
        probe = AtlasProbe()
        render_atlas_transition(
            probe,
            InvestigationTransition(self._accepted().state, intents),
        )
        self.assertEqual(
            [call[0] for call in probe.calls],
            [
                "scene",
                "highlight",
                "lens",
                "selection",
                "pulse",
                "counterfactual",
                "delta",
                "clear",
            ],
        )


if __name__ == "__main__":
    unittest.main()
