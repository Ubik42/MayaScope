from __future__ import annotations

import unittest

from MayaScope.qt_compat import QtCore, QtGui
from MayaScope.ui.foundation import COLORS, PALETTE_HEX, qt_enum


class UiFoundationTests(unittest.TestCase):
    def test_palette_keeps_named_qcolors_and_stable_hex_contract(self):
        self.assertEqual(set(COLORS), set(PALETTE_HEX))
        for name, value in PALETTE_HEX.items():
            self.assertEqual(COLORS[name].name().upper(), value)

    def test_qt_enum_resolves_qt6_grouped_values(self):
        self.assertEqual(qt_enum(QtCore.Qt, "AlignCenter"), QtCore.Qt.AlignCenter)
        self.assertEqual(qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"), QtCore.Qt.ScrollBarAlwaysOff)

    def test_qt_enum_prefers_direct_values_and_rejects_typos(self):
        sentinel = object()

        class Direct:
            Example = sentinel

        self.assertIs(qt_enum(Direct, "Example"), sentinel)
        with self.assertRaisesRegex(AttributeError, "NotARealQtEnum"):
            qt_enum(QtCore.Qt, "NotARealQtEnum")

    def test_palette_values_are_valid_and_opaque(self):
        for color in COLORS.values():
            self.assertIsInstance(color, QtGui.QColor)
            self.assertTrue(color.isValid())
            self.assertEqual(color.alpha(), 255)


if __name__ == "__main__":
    unittest.main()
