from __future__ import annotations

import unittest
from pathlib import Path
import sys
import tempfile

from MayaScope.analysis.ddmin import FAIL, PASS, UNRESOLVED, minimize_failing_set
from MayaScope.model import (
    BisectCandidate,
    BisectPlan,
    ProbeAttempt,
    ReproCapsuleManifest,
    SceneEdge,
    SceneNode,
    SceneReference,
    SceneSnapshot,
)
from MayaScope.runner import (
    BisectSession,
    build_post_open_bisect_plan,
    load_bisect_journal,
    load_repro_capsule,
)


class BisectTests(unittest.TestCase):
    def test_ddmin_finds_interacting_minimal_failure_with_trace(self):
        def oracle(candidate_ids):
            values = set(candidate_ids)
            return FAIL if {"bad-a", "bad-b"}.issubset(values) else PASS

        result = minimize_failing_set(
            ("noise-1", "bad-a", "noise-2", "bad-b", "noise-3"), oracle
        )
        self.assertTrue(result.complete)
        self.assertEqual(set(result.minimal_candidate_ids), {"bad-a", "bad-b"})
        self.assertEqual(result.reason, "1-minimal failing set")
        self.assertTrue(any(step.purpose == "complement" for step in result.steps))
        self.assertLess(result.probe_count, 20)

    def test_unresolved_is_not_treated_as_pass_or_fail(self):
        def oracle(candidate_ids):
            values = set(candidate_ids)
            if "unstable" in values and "bad" not in values:
                return UNRESOLVED
            return FAIL if "bad" in values else PASS

        result = minimize_failing_set(("noise", "unstable", "bad"), oracle)
        self.assertEqual(result.minimal_candidate_ids, ("bad",))
        self.assertTrue(any(step.outcome == UNRESOLVED for step in result.steps))

    def test_known_outcomes_are_replayed_without_calling_oracle(self):
        called = []

        def oracle(values):
            called.append(values)
            return FAIL if "poison" in values else PASS

        result = minimize_failing_set(
            ("good", "poison"),
            oracle,
            known_outcomes={
                frozenset(("good", "poison")): FAIL,
                frozenset(("good",)): PASS,
                frozenset(("poison",)): FAIL,
            },
        )
        self.assertEqual(result.minimal_candidate_ids, ("poison",))
        self.assertEqual(called, [])
        self.assertEqual(result.probe_count, 0)
        self.assertGreaterEqual(result.cache_hits, 3)

    def test_nonfailing_source_and_cancel_are_explicit_incomplete_results(self):
        clean = minimize_failing_set(("a", "b"), lambda _values: PASS)
        self.assertFalse(clean.complete)
        self.assertIn("not fail", clean.reason)

        seen = []

        def cancel_after_two():
            return len(seen) >= 2

        cancelled = minimize_failing_set(
            ("a", "b", "c", "d"),
            lambda _values: seen.append(1) or FAIL,
            cancelled=cancel_after_two,
        )
        self.assertFalse(cancelled.complete)
        self.assertEqual(cancelled.reason, "cancelled")

    def test_plan_attempt_and_capsule_round_trip(self):
        plan = BisectPlan(
            source_scene="D:/shots/broken.ma",
            source_sha256="a" * 64,
            candidates=(
                BisectCandidate("ref-hero", "heroRN", "reference", ("uuid-a",)),
                BisectCandidate("dag-props", "props_GRP", "top-level-dag", ("uuid-b",)),
            ),
            maya_executable="C:/Program Files/Autodesk/Maya2025/bin/mayapy.exe",
            plan_id="bisect-test",
            created_at="2026-08-25T00:00:00+00:00",
        )
        attempt = ProbeAttempt(
            0,
            ("ref-hero", "dag-props"),
            "fail",
            "open",
            3.2,
            exit_code=-1,
            stderr_tail="access violation",
            crash_artifacts=("mayaCrashLog.txt",),
            started_at="2026-08-25T00:01:00+00:00",
        )
        capsule = ReproCapsuleManifest(
            plan,
            (attempt,),
            ("ref-hero",),
            True,
            "1-minimal failing set",
            environment={"maya_version": "2025"},
            capsule_id="capsule-test",
            created_at="2026-08-25T00:02:00+00:00",
        )
        self.assertEqual(BisectPlan.from_json(plan.to_json()), plan)
        self.assertEqual(ReproCapsuleManifest.from_json(capsule.to_json()), capsule)

    def test_scene_snapshot_builds_post_open_dag_and_reference_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "shot.ma"
            scene.write_text("// scene", encoding="utf-8")
            nodes = (
                SceneNode("root", "asset_GRP", "transform", ("|asset_GRP",), True),
                SceneNode("child", "assetMesh", "mesh", ("|asset_GRP|assetMesh",), True),
                SceneNode("camera", "persp", "transform", ("|persp",), True),
                SceneNode("ref-node", "hero:root", "transform", ("|hero:root",), True, True),
            )
            snapshot = SceneSnapshot.build(
                nodes,
                (SceneEdge("root", "child", relation="dag"),),
                (SceneReference("heroRN", "hero.ma", node_ids=("ref-node",)),),
                source_scene=str(scene),
                snapshot_id="snapshot-bisect",
            )
            plan = build_post_open_bisect_plan(snapshot, sys.executable)
            by_kind = {candidate.kind: candidate for candidate in plan.candidates}
            self.assertEqual(by_kind["top-level-dag"].stable_node_ids, ("root", "child"))
            self.assertEqual(by_kind["top-level-dag"].metadata["maya_names"], ("|asset_GRP",))
            self.assertEqual(by_kind["reference"].metadata["reference_node"], "heroRN")
            self.assertNotIn("camera", {node_id for item in plan.candidates for node_id in item.stable_node_ids})
            self.assertIn("post-open", plan.metadata["capability"])

    def test_bisect_session_persists_capsule_from_probe_trace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = BisectPlan(
                source_scene=str(root / "source.ma"),
                source_sha256="b" * 64,
                candidates=tuple(
                    BisectCandidate(value, value, "top-level-dag")
                    for value in ("noise", "bad-a", "bad-b")
                ),
                maya_executable=sys.executable,
                plan_id="session-test",
            )

            class FakeProbe:
                def __init__(self):
                    self.root = root / "attempts"

                def run(self, candidate_ids, attempt_index):
                    outcome = FAIL if {"bad-a", "bad-b"}.issubset(candidate_ids) else PASS
                    return ProbeAttempt(
                        attempt_index,
                        tuple(candidate_ids),
                        outcome,
                        "exit",
                        0.01,
                        exit_code=20 if outcome == FAIL else 0,
                    )

            session = BisectSession(plan, probe=FakeProbe())
            result = session.run()
            self.assertTrue(result.manifest.complete)
            self.assertEqual(set(result.manifest.minimal_candidate_ids), {"bad-a", "bad-b"})
            self.assertTrue(result.manifest_path.is_file())
            self.assertEqual(len(result.manifest_sha256), 64)
            self.assertEqual(len(result.manifest.attempts), result.delta_debug.probe_count)
            self.assertEqual(load_repro_capsule(result.manifest_path), result.manifest)
            journal_path = root / "attempts" / "bisect-journal.json"
            journal = load_bisect_journal(journal_path)
            self.assertEqual(journal.status, "finalized")
            self.assertEqual(journal.attempts, result.manifest.attempts)

            class NoNewProbe:
                def __init__(self, probe_root):
                    self.root = probe_root

                def run(self, _candidate_ids, _attempt_index):
                    raise AssertionError("resume reran an already known candidate set")

            resumed = BisectSession.resume(
                journal_path,
                probe=NoNewProbe(root / "attempts"),
                validate_source=False,
            ).run()
            self.assertEqual(resumed.delta_debug.probe_count, 0)
            self.assertGreater(resumed.delta_debug.cache_hits, 0)
            self.assertEqual(
                resumed.manifest.minimal_candidate_ids,
                result.manifest.minimal_candidate_ids,
            )


if __name__ == "__main__":
    unittest.main()
