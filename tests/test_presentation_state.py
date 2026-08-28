from __future__ import annotations

from types import SimpleNamespace
import unittest

from MayaScope.presentation import WorkspacePresentationState


class WorkspacePresentationStateTests(unittest.TestCase):
    def test_new_scene_invalidates_all_evidence_from_previous_generation(self):
        old = WorkspacePresentationState(
            snapshot="old",
            issues=("old-issue",),
            selected_issue="old-issue",
            focus_node_id="old-node",
            profiler_capture="profile",
            counterfactual_run="experiment",
            runtime_snapshot="runtime",
            delta="delta",
        )
        current = old.present_scene(
            "new", ("new-issue",), "new-report", ("new-incident",)
        )
        self.assertEqual(current.snapshot, "new")
        self.assertEqual(current.issues, ("new-issue",))
        self.assertIsNone(current.focus_node_id)
        self.assertIsNone(current.profiler_capture)
        self.assertIsNone(current.counterfactual_run)
        self.assertIsNone(current.runtime_snapshot)
        self.assertIsNone(current.delta)

    def test_selection_and_lens_transitions_keep_mutual_exclusion(self):
        state = WorkspacePresentationState().select_issue("finding")
        self.assertEqual(state.selected_issue, "finding")
        state = state.select_incident("incident")
        self.assertIsNone(state.selected_issue)
        self.assertEqual(state.selected_incident, "incident")
        state = state.focus("node-a").present_lens("lens", "measured")
        self.assertIsNone(state.selected_incident)
        self.assertEqual(state.focus_node_id, "node-a")
        self.assertEqual(state.lens_report, "lens")
        self.assertEqual(state.measured_report, "measured")
        self.assertIsNone(state.clear_lens().focus_node_id)

    def test_clinic_profiler_runtime_and_delta_have_explicit_transitions(self):
        report = SimpleNamespace(issues=("a", "b"))
        capture = SimpleNamespace(duration_us=4200)
        state = WorkspacePresentationState(snapshot="scene")
        state = state.present_clinic(report, ("incident",))
        state = state.present_profiler(capture)
        state = state.present_runtime("runtime", "runtime-report")
        state = state.present_delta("delta", "before")
        self.assertEqual(state.issues, ("a", "b"))
        self.assertEqual(state.pulse_range, (0, 4200))
        self.assertEqual(
            state.as_debug_mapping(),
            {
                "has_snapshot": True,
                "issue_count": 2,
                "incident_count": 1,
                "focus_node_id": "",
                "has_profiler": True,
                "has_runtime": True,
                "has_delta": True,
            },
        )

    def test_unknown_state_field_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "未知呈现状态字段"):
            WorkspacePresentationState().update(snaphsot="typo")


if __name__ == "__main__":
    unittest.main()
