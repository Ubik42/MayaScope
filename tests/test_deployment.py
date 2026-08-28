from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.deployment import (
    install_module,
    inspect_module,
    restore_module,
    uninstall_module,
)
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
            idempotent = install_module(module_dir)
            self.assertEqual(idempotent.backup_file, "")

            stale = target.read_text() + "# stale\n"
            target.write_text(stale, encoding="utf-8")
            self.assertEqual(inspect_module(module_dir).state, "update-available")
            upgraded = install_module(module_dir)
            self.assertEqual(inspect_module(module_dir).state, "installed")
            self.assertTrue(Path(upgraded.backup_file).is_file())
            self.assertEqual(Path(upgraded.backup_file).read_text(), stale)

            removed = uninstall_module(module_dir)
            self.assertEqual(removed.state, "uninstalled")
            self.assertFalse(target.exists())
            self.assertTrue(Path(removed.backup_file).is_file())

            restored = restore_module(Path(removed.backup_file), module_dir)
            self.assertEqual(restored.state, "restored")
            self.assertTrue(target.is_file())
            self.assertTrue(Path(removed.backup_file).is_file())
            self.assertEqual(inspect_module(module_dir).state, "installed")

            rolled_back = restore_module(Path(upgraded.backup_file), module_dir)
            self.assertTrue(Path(rolled_back.rollback_file).is_file())
            self.assertTrue(Path(upgraded.backup_file).is_file())
            self.assertEqual(target.read_text(), stale)
            restore_module(Path(removed.backup_file), module_dir)
            self.assertEqual(inspect_module(module_dir).state, "installed")

    def test_restore_refuses_foreign_or_out_of_directory_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            module_dir = root / "modules"
            module_dir.mkdir()
            foreign = module_dir / "MayaScope.mod.uninstalled-foreign.bak"
            foreign.write_text("+ SomeoneElse 1.0 C:/foreign\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "not managed"):
                restore_module(foreign, module_dir)

            outside = root / "MayaScope.mod.uninstalled-outside.bak"
            outside.write_text(
                "# MAYASCOPE-MANAGED-MODULE schema=1\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "target module directory"):
                restore_module(outside, module_dir)

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
