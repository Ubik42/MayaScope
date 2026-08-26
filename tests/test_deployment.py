from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.deployment import install_module, inspect_module, uninstall_module
from MayaScope.install import main


class DeploymentTests(unittest.TestCase):
    def test_install_status_update_and_recoverable_uninstall(self):
        with tempfile.TemporaryDirectory() as folder:
            module_dir = Path(folder) / "2025" / "modules"
            self.assertEqual(inspect_module(module_dir).state, "not-installed")
            installed = install_module(module_dir)
            target = Path(installed.module_file)
            self.assertEqual(inspect_module(module_dir).state, "installed")
            self.assertIn("+ MayaScope 3.0.0", target.read_text(encoding="utf-8"))
            self.assertIn("PYTHONPATH +:= .", target.read_text(encoding="utf-8"))

            target.write_text(target.read_text() + "# stale\n", encoding="utf-8")
            self.assertEqual(inspect_module(module_dir).state, "update-available")
            install_module(module_dir)
            self.assertEqual(inspect_module(module_dir).state, "installed")

            removed = uninstall_module(module_dir)
            self.assertEqual(removed.state, "uninstalled")
            self.assertFalse(target.exists())
            self.assertTrue(Path(removed.backup_file).is_file())

    def test_foreign_module_is_never_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            module_dir = Path(folder)
            target = module_dir / "MayaScope.mod"
            target.write_text("+ SomeoneElse 1.0 C:/foreign\n", encoding="utf-8")
            original = target.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "not managed"):
                install_module(module_dir)
            with self.assertRaisesRegex(RuntimeError, "not managed"):
                uninstall_module(module_dir)
            self.assertEqual(target.read_bytes(), original)

    def test_cli_error_is_valid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            module_dir = Path(folder)
            (module_dir / "MayaScope.mod").write_text("foreign", encoding="utf-8")
            from contextlib import redirect_stdout
            from io import StringIO

            stream = StringIO()
            with redirect_stdout(stream):
                code = main(["install", "--module-dir", str(module_dir)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stream.getvalue())["state"], "error")


if __name__ == "__main__":
    unittest.main()
