import unittest
from pathlib import Path

from MayaScope.analysis.clinic import DEFAULT_PROFILES, DEFAULT_REGISTRY


class ChineseInterfaceTests(unittest.TestCase):
    def test_default_clinic_content_is_written_for_chinese_reviewers(self):
        for text in [
            *(profile.title for profile in DEFAULT_PROFILES),
            *(profile.description for profile in DEFAULT_PROFILES),
            *(spec.title for spec in DEFAULT_REGISTRY.specs),
        ]:
            self.assertRegex(text, r"[\u4e00-\u9fff]")

    def test_workspace_has_no_legacy_english_display_headings(self):
        ui_root = Path(__file__).resolve().parents[1] / "ui"
        source = "\n".join(
            (ui_root / name).read_text(encoding="utf-8")
            for name in (
                "workspace.py",
                "clinic.py",
                "profiler.py",
                "runtime.py",
                "project_gate.py",
                "lens.py",
                "capture.py",
            )
        )
        required = (
            "场景图谱  /  实时取证",
            "场景诊所  /  规则阵列",
            "◉  根因透镜",
            "✦  运行时星图",
            "//  故障棱镜",
            "问题证据",
            "MAYA · 联动",
            "项目门禁",
            "追踪地平线  /  性能采样",
            "依赖谱系 ·",
        )
        for text in required:
            self.assertIn(text, source)
        forbidden = (
            "SCENE ATLAS  /  LIVE FORENSICS",
            "SCENE CLINIC  /  RULE ARRAY",
            "ROOT CAUSE LENS",
            "CAPTURE SCENE",
            "PREVIEW CHANGEPLAN",
            "FAILURE PRISM",
            "PROBE IDLE",
            "PROFILER",
        )
        for text in forbidden:
            self.assertNotIn(text, source)


if __name__ == "__main__":
    unittest.main()
