from __future__ import annotations

import unittest

from MayaScope.analysis.clinic import (
    ClinicCancelled,
    DEFAULT_PROFILES,
    RuleRegistry,
    RuleSpec,
    profile_map,
)
from MayaScope.analysis.rules import Issue, Severity
from MayaScope.model import SceneNode, SceneSnapshot


class StaticRule:
    def __init__(self, rule_id, issues=(), error=None):
        self.id = rule_id
        self.issues = issues
        self.error = error

    def evaluate(self, snapshot):
        if self.error:
            raise self.error
        return self.issues


class ClinicRegistryTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SceneSnapshot.build((SceneNode("n1", "node", "network"),), ())

    def test_failure_is_isolated_and_run_is_measured(self):
        issue = Issue("ok:1", "ok", "Good", "Evidence", Severity.WARNING, ("n1",), ())
        registry = RuleRegistry(
            (
                RuleSpec(StaticRule("bad", error=RuntimeError("boom")), "Bad", "pipeline", "strong"),
                RuleSpec(StaticRule("ok", (issue,)), "Good", "integrity", "deterministic"),
            )
        )
        report = registry.evaluate(self.snapshot)
        self.assertEqual(report.issues, (issue,))
        self.assertEqual(report.failures[0].rule_id, "bad")
        self.assertEqual(report.runs[0].rule_id, "ok")
        self.assertGreaterEqual(report.duration_ms, 0.0)

    def test_expensive_rules_require_explicit_opt_in(self):
        registry = RuleRegistry((RuleSpec(StaticRule("deep"), "Deep", "performance", "heuristic", cost="expensive"),))
        report = registry.evaluate(self.snapshot)
        self.assertEqual(report.skipped_rule_ids, ("deep",))
        self.assertEqual(len(registry.evaluate(self.snapshot, include_expensive=True).runs), 1)

    def test_cancellation_and_progress_happen_between_rule_boundaries(self):
        registry = RuleRegistry(
            (
                RuleSpec(StaticRule("one"), "One", "integrity", "strong"),
                RuleSpec(StaticRule("two"), "Two", "integrity", "strong"),
            )
        )
        completed = []
        with self.assertRaises(ClinicCancelled):
            registry.evaluate(
                self.snapshot,
                cancelled=lambda: bool(completed),
                progress=lambda done, total, rule_id: completed.append(
                    (done, total, rule_id)
                ),
            )
        self.assertEqual(completed, [(1, 2, "one")])

    def test_contract_rejects_duplicate_ids_and_dangling_evidence(self):
        spec = RuleSpec(StaticRule("same"), "Same", "integrity", "strong")
        with self.assertRaises(ValueError):
            RuleRegistry((spec, spec))
        dangling = Issue("x", "dangling", "Bad", "Bad", Severity.ERROR, ("missing",), ())
        registry = RuleRegistry((RuleSpec(StaticRule("dangling", (dangling,)), "Dangling", "integrity", "strong"),))
        report = registry.evaluate(self.snapshot)
        self.assertFalse(report.issues)
        self.assertIn("missing node", report.failures[0].message)

    def test_default_profiles_are_valid_and_stage_specific(self):
        profiles = profile_map()
        self.assertEqual(set(profiles), {profile.id for profile in DEFAULT_PROFILES})
        self.assertIn("high-fanout", profiles["animation"].rule_ids)
        self.assertIn("namespace-depth", profiles["publish"].rule_ids)
        self.assertNotEqual(profiles["animation"].rule_ids, profiles["publish"].rule_ids)


if __name__ == "__main__":
    unittest.main()
