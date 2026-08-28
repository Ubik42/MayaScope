from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.install_replay import run_install_replay
from MayaScope.release import build_release


class InstallReplayTests(unittest.TestCase):
    def test_release_install_restore_and_final_uninstall_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            maya = root / "maya.exe"
            maya.write_bytes(b"test double")
            receipt = build_release(root / "release-output")
            output = root / "install-replay.json"
            screenshot = root / "first-launch.png"

            def fake_gui_runner(
                maya_executable,
                gui_output,
                screenshot_path,
                **kwargs,
            ):
                self.assertFalse(kwargs["inject_package_parent"])
                self.assertEqual(kwargs["scenario"], "instruments")
                self.assertEqual((kwargs["width"], kwargs["height"]), (800, 900))
                expected = kwargs["expected_package_root"].resolve()
                screenshot_path.write_bytes(b"png evidence")
                payload = {
                    "ok": True,
                    "maya_executable": str(maya_executable),
                    "worker": {"package_root": str(expected), "ok": True},
                }
                gui_output.write_text(json.dumps(payload), encoding="utf-8")
                return payload

            payload = run_install_replay(
                Path(receipt.archive),
                maya,
                output,
                screenshot,
                gui_runner=fake_gui_runner,
                scenario="instruments",
                width=800,
                height=900,
            )

            self.assertTrue(payload["ok"])
            self.assertTrue(all(payload["checks"].values()))
            self.assertFalse(
                payload["isolated_environment"]["development_pythonpath_injected"]
            )
            self.assertTrue(
                payload["isolated_environment"]["temporary_root_cleaned"]
            )
            self.assertEqual(payload["recovered_status"]["state"], "installed")
            self.assertEqual(payload["restore"]["state"], "restored")
            self.assertEqual(payload["final_status"]["state"], "not-installed")
            self.assertTrue(output.is_file())
            self.assertEqual(payload["scenario"], "instruments")
            self.assertEqual(payload["window_size"], [800, 900])


if __name__ == "__main__":
    unittest.main()
