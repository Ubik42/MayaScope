"""Tests for package behavior that does not require Maya."""

from __future__ import annotations

import unittest

import MayaScope
from MayaScope import launch


class LaunchTests(unittest.TestCase):
    def test_entry_point_imports_without_maya(self) -> None:
        self.assertEqual(launch.available_tools(), ("workspace", "hierarchy", "nodes", "sets"))

    def test_unknown_tool_fails_before_importing_maya(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown MayaScope"):
            launch.run("missing")

    def test_version_is_exposed(self) -> None:
        self.assertRegex(MayaScope.__version__, r"^\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
