from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

from MayaScope.model import BisectCandidate, BisectPlan, ReproCapsuleManifest
from MayaScope.runner.cli import main
from MayaScope.runner.session import _write_checked_envelope


class RunnerCliTests(unittest.TestCase):
    def test_plan_only_emits_json_lines_and_writes_plan(self):
        fixture = '''//Maya ASCII 2025 scene
requires maya "2025";
createNode transform -n "hero_GRP";
createNode mesh -n "heroShape" -p "hero_GRP";
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = root / "shot.ma"
            output = root / "plan.json"
            scene.write_text(fixture, encoding="utf-8")
            stream = StringIO()
            with redirect_stdout(stream):
                code = main(
                    [
                        "run",
                        str(scene),
                        "--mayapy",
                        sys.executable,
                        "--plan-only",
                        "--plan-output",
                        str(output),
                    ]
                )
            events = [json.loads(line) for line in stream.getvalue().splitlines()]
            self.assertEqual(code, 0)
            self.assertEqual([item["event"] for item in events], ["plan", "plan-written"])
            self.assertEqual(BisectPlan.from_json(output.read_text()).metadata["isolation_mode"], "pre-open-ascii")

    def test_verify_rejects_tamper_and_reports_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capsule_path = root / "repro-capsule.json"
            plan = BisectPlan(
                source_scene=str(root / "shot.ma"),
                source_sha256="a" * 64,
                candidates=(BisectCandidate("hero", "hero_GRP", "top-level-dag"),),
                maya_executable=sys.executable,
            )
            manifest = ReproCapsuleManifest(
                plan,
                (),
                ("hero",),
                True,
                "fixture",
                environment={"maya": {"maya_version": "2025"}},
            )
            _write_checked_envelope(
                capsule_path,
                {
                    "format": "mayascope.repro-capsule",
                    "store_schema": 1,
                    "manifest": manifest.to_dict(),
                },
            )
            stream = StringIO()
            with redirect_stdout(stream):
                code = main(["verify", str(capsule_path)])
            event = json.loads(stream.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(event["event"], "verified")
            self.assertEqual(event["maya"]["maya_version"], "2025")

            capsule_path.write_text(capsule_path.read_text() + " ", encoding="utf-8")
            # Whitespace is outside canonical content and remains valid JSON; mutate data instead.
            payload = json.loads(capsule_path.read_text())
            payload["manifest"]["reason"] = "tampered"
            capsule_path.write_text(json.dumps(payload), encoding="utf-8")
            stream = StringIO()
            with redirect_stdout(stream):
                code = main(["verify", str(capsule_path)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stream.getvalue())["event"], "error")


if __name__ == "__main__":
    unittest.main()
