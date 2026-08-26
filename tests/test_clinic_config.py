from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.analysis.clinic import RuleProfile, RuleSpec
from MayaScope.analysis.config import (
    CONFIG_ENV_VAR,
    ClinicConfigError,
    build_environment,
    load_clinic_config,
    load_environment_from_env,
)
from MayaScope.analysis.rules import Issue, Severity
from MayaScope.analysis.sdk import RulePack, extend_environment
from MayaScope.model import SceneNode, SceneSnapshot


class TrustedRule:
    id = "trusted-pack-rule"

    def evaluate(self, snapshot):
        return (
            Issue("trusted:1", self.id, "Trusted", "Trusted host extension", Severity.INFO, (snapshot.nodes[0].id,), ()),
        )


class ClinicConfigTests(unittest.TestCase):
    def valid_payload(self):
        return {
            "schema_version": 1,
            "thresholds": {"high-fanout": 96, "namespace-depth": 4},
            "disabled_rules": ["orphan-utilities"],
            "custom_rules": [
                {
                    "id": "studio-no-script",
                    "kind": "forbidden_node_types",
                    "title": "Script nodes forbidden",
                    "node_types": ["script"],
                    "severity": "ERROR",
                    "category": "pipeline",
                    "confidence": "deterministic",
                }
            ],
            "profiles": [
                {
                    "id": "studio-publish",
                    "title": "Studio Publish",
                    "description": "Studio publish policy.",
                    "rule_ids": ["unknown-nodes", "namespace-depth", "studio-no-script"],
                }
            ],
        }

    def test_declarative_config_builds_rules_profiles_and_fingerprint(self):
        environment = build_environment(self.valid_payload(), source="test")
        specs = {spec.id: spec for spec in environment.registry.specs}
        self.assertEqual(specs["high-fanout"].rule.threshold, 96)
        self.assertFalse(specs["orphan-utilities"].default_enabled)
        self.assertIn("studio-no-script", specs)
        self.assertIn("studio-publish", {profile.id for profile in environment.profiles})
        self.assertEqual(len(environment.fingerprint), 64)

        snapshot = SceneSnapshot.build((SceneNode("s", "payloadScript", "script"),), ())
        report = environment.registry.evaluate(snapshot, enabled_rule_ids=("studio-no-script",))
        self.assertEqual(report.issues[0].severity, Severity.ERROR)

    def test_file_and_environment_loading_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clinic.json"
            path.write_text(json.dumps(self.valid_payload()), encoding="utf-8")
            direct = load_clinic_config(path)
            through_env = load_environment_from_env({CONFIG_ENV_VAR: str(path)})
            self.assertEqual(direct.fingerprint, through_env.fingerprint)
            self.assertEqual(load_environment_from_env({}).source, "built-in")

    def test_duplicate_keys_unknown_fields_and_python_hooks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ClinicConfigError, "Duplicate"):
                load_clinic_config(path)
        for payload in (
            {"schema_version": 1, "module": "evil.module"},
            {"schema_version": 1, "custom_rules": [{"id": "x-rule", "kind": "python", "title": "X", "node_types": ["x"]}]},
            {"schema_version": 1, "thresholds": {"high-fanout": True}},
        ):
            with self.assertRaises(ClinicConfigError):
                build_environment(payload)

    def test_trusted_rule_pack_requires_explicit_object_and_extends_all(self):
        base = load_environment_from_env({})
        spec = RuleSpec(TrustedRule(), "Trusted pack", "pipeline", "strong")
        profile = RuleProfile("trusted-profile", "Trusted", "Explicit trusted pack.", (spec.id,))
        extended = extend_environment(base, RulePack("studio-pack", (spec,), (profile,)))
        self.assertIn(spec.id, {item.id for item in extended.registry.specs})
        all_profile = next(item for item in extended.profiles if item.id == "all")
        self.assertIn(spec.id, all_profile.rule_ids)
        self.assertIn("trusted:studio-pack", extended.source)


if __name__ == "__main__":
    unittest.main()
