from __future__ import annotations

import unittest

from MayaScope.analysis.config import ClinicConfigError, build_environment
from MayaScope.analysis.delta import compare_snapshots
from MayaScope.analysis.rules import Severity
from MayaScope.model import SceneSettings, SceneSnapshot


class SceneContractTests(unittest.TestCase):
    def payload(self):
        return {
            "schema_version": 2,
            "scene_contract": {
                "allowed_time_units": ["film", "23.976fps"],
                "required_linear_unit": "cm",
                "required_angular_unit": "deg",
                "required_up_axis": "y",
                "required_color_management": True,
                "allowed_rendering_spaces": ["ACEScg"],
                "required_plugins": ["studioRig.py"],
                "forbidden_plugins": ["legacySolver.mll"],
                "severity": "ERROR",
            },
        }

    def test_typed_scene_settings_round_trip_and_delta(self):
        settings = SceneSettings(
            time_unit="film",
            frames_per_second=24.0,
            linear_unit="cm",
            angular_unit="deg",
            up_axis="y",
            color_management_enabled=True,
            rendering_space="ACEScg",
            view_transform="ACES 1.0 SDR-video",
            color_config_path="D:/studio/config.ocio",
        )
        snapshot = SceneSnapshot.build((), (), scene_settings=settings)
        restored = SceneSnapshot.from_json(snapshot.to_json())
        self.assertEqual(restored.scene_settings, settings)

        changed = SceneSnapshot.build((), (), scene_settings=SceneSettings(time_unit="pal"))
        delta = compare_snapshots(snapshot, changed)
        self.assertIn("time_unit", delta.setting_changes)
        self.assertGreater(delta.summary()["scene_settings_modified"], 0)
        self.assertFalse(delta.is_empty)

    def test_contract_is_in_publish_profile_and_emits_chinese_evidence(self):
        environment = build_environment(self.payload(), source="test")
        specs = {spec.id: spec for spec in environment.registry.specs}
        publish = next(profile for profile in environment.profiles if profile.id == "publish")
        self.assertIn("scene-contract", publish.rule_ids)

        snapshot = SceneSnapshot.build(
            (),
            (),
            scene_settings=SceneSettings(
                time_unit="pal",
                frames_per_second=25.0,
                linear_unit="m",
                angular_unit="rad",
                up_axis="z",
                color_management_enabled=False,
                rendering_space="scene-linear Rec.709-sRGB",
            ),
            metadata={"plugins_in_use": ("legacySolver.mll",)},
        )
        report = environment.registry.evaluate(snapshot, enabled_rule_ids=("scene-contract",))
        self.assertEqual(len(report.issues), 1)
        issue = report.issues[0]
        self.assertEqual(issue.title, "场景制片规范不一致")
        self.assertEqual(issue.severity, Severity.ERROR)
        labels = {evidence.label for evidence in issue.evidence}
        self.assertIn("时间单位 / 帧率", labels)
        self.assertIn("色彩管理", labels)
        self.assertIn("缺失必要插件", labels)
        self.assertIn("禁用插件命中", labels)
        self.assertEqual(issue.affected_node_ids, ())
        self.assertIs(specs["scene-contract"].rule.contract.required_color_management, True)

    def test_matching_contract_is_clean_and_invalid_policy_fails_closed(self):
        environment = build_environment(self.payload())
        snapshot = SceneSnapshot.build(
            (),
            (),
            scene_settings=SceneSettings(
                time_unit="film",
                frames_per_second=24.0,
                linear_unit="cm",
                angular_unit="deg",
                up_axis="y",
                color_management_enabled=True,
                rendering_space="ACEScg",
            ),
            metadata={"plugins_in_use": ("studioRig.py",)},
        )
        report = environment.registry.evaluate(snapshot, enabled_rule_ids=("scene-contract",))
        self.assertEqual(report.issues, ())

        invalid = self.payload()
        invalid["scene_contract"]["required_up_axis"] = "x"
        with self.assertRaises(ClinicConfigError):
            build_environment(invalid)

        contradictory = self.payload()
        contradictory["scene_contract"]["forbidden_plugins"] = ["studioRig.py"]
        with self.assertRaises(ClinicConfigError):
            build_environment(contradictory)


if __name__ == "__main__":
    unittest.main()
