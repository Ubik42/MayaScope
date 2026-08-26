from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from MayaScope.host_health import collect_host_health
from MayaScope import maya_integration


class HostIntegrationTests(unittest.TestCase):
    def test_fast_health_report_covers_showcase_boundary(self):
        class FakeCmds:
            @staticmethod
            def about(version=False, apiVersion=False):
                return "2025" if version else 20250303

            @staticmethod
            def evaluationManager(query=False, mode=False):
                return ["parallel"]

        with tempfile.TemporaryDirectory() as folder:
            bin_dir = Path(folder) / "bin"
            bin_dir.mkdir()
            maya = bin_dir / "maya.exe"
            mayapy = bin_dir / "mayapy.exe"
            maya.write_bytes(b"")
            mayapy.write_bytes(b"")
            health = collect_host_health(FakeCmds(), str(maya), pyside_version="6.5.3")
        self.assertTrue(health.ready, health)
        self.assertEqual(health.maya_api, "20250303")
        self.assertEqual(health.evaluation_mode, ("parallel",))
        self.assertEqual(Path(health.mayapy_path).name, "mayapy.exe")

    def test_menu_and_shelf_are_idempotent_and_shelf_persistence_is_opt_in(self):
        class FakeCmds:
            def __init__(self):
                self.menus = set()
                self.shelves = set()
                self.buttons = set()
                self.saved = []
                self.items = []

            def menu(self, name, exists=False, **kwargs):
                if exists:
                    return name in self.menus
                self.menus.add(name)
                return name

            def menuItem(self, **kwargs):
                self.items.append(kwargs)
                return "item-%s" % len(self.items)

            def shelfLayout(self, name, exists=False, **kwargs):
                if exists:
                    return name in self.shelves
                self.shelves.add(name)
                return name

            def shelfButton(self, name, exists=False, **kwargs):
                if exists:
                    return name in self.buttons
                self.buttons.add(name)
                return name

            def deleteUI(self, name, **kwargs):
                self.menus.discard(name)
                self.buttons.discard(name)

            def saveShelf(self, name, path):
                self.saved.append((name, path))

        fake = FakeCmds()
        with mock.patch("MayaScope.maya_integration._cmds", return_value=fake):
            maya_integration.install_menu()
            maya_integration.install_menu()
            maya_integration.install_shelf()
            self.assertEqual(fake.saved, [])
            maya_integration.install_shelf(persist=True)
            self.assertEqual(fake.saved, [("MayaScope", "MayaScope")])
            self.assertTrue(maya_integration.remove_menu())
            self.assertFalse(maya_integration.remove_menu())
        labels = [item.get("label") for item in fake.items if item.get("label")]
        self.assertIn("打开因果场景观测台", labels)


if __name__ == "__main__":
    unittest.main()
