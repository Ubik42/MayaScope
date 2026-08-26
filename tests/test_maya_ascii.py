from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from MayaScope.runner.maya_ascii import (
    MayaAsciiSafetyError,
    parse_maya_ascii_text,
    slice_maya_ascii,
)
from MayaScope.runner import build_pre_open_ascii_bisect_plan


FIXTURE = r'''//Maya ASCII 2025 scene
requires maya "2025";
file -r -ns "hero" -rfn "heroRN" "D:/assets/hero.ma";
createNode transform -n "keep_GRP";
	rename -uid "KEEP-UUID";
	setAttr ".notes" -type "string" "keep; semicolon";
createNode mesh -n "keepShape" -p "keep_GRP";
	rename -uid "KEEP-SHAPE";
createNode transform -n "remove_GRP";
	rename -uid "REMOVE-UUID";
	setAttr ".tx" 4;
createNode mesh -n "removeShape" -p "remove_GRP";
	rename -uid "REMOVE-SHAPE";
	setAttr ".io" yes;
	unknownPluginCommand "remove-owned payload";
createNode multiplyDivide -n "driver";
	rename -uid "DRIVER-UUID";
connectAttr "driver.outputX" "remove_GRP.tx";
connectAttr "driver.outputY" "keep_GRP.ty";
setAttr "hero:ctrl.tx" 2;
// End of fixture
'''


class MayaAsciiTests(unittest.TestCase):
    def test_parser_preserves_multiline_blocks_strings_and_reference_metadata(self):
        document = parse_maya_ascii_text(FIXTURE)
        self.assertEqual(len(document.nodes), 5)
        self.assertEqual(document.nodes[1].full_path, "|keep_GRP|keepShape")
        self.assertEqual(document.references[0].namespace, "hero")
        self.assertEqual(document.references[0].reference_node, "heroRN")
        notes = next(item for item in document.statements if "keep; semicolon" in item.text)
        self.assertEqual(notes.command, "setAttr")
        self.assertEqual(notes.owner, "|keep_GRP")

    def test_slice_removes_complete_dag_block_connections_and_reference_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ma"
            output = Path(folder) / "slice.ma"
            source.write_text(FIXTURE, encoding="utf-8")
            original = source.read_bytes()
            report = slice_maya_ascii(
                source,
                output,
                removed_roots=("remove_GRP",),
                removed_reference_paths=("D:/assets/hero.ma",),
            )
            sliced = output.read_text(encoding="utf-8")
            self.assertTrue(sliced.startswith("//Maya ASCII"))
            self.assertEqual(source.read_bytes(), original)
            self.assertIn("keep_GRP", sliced)
            self.assertIn("driver.outputY", sliced)
            self.assertNotIn("remove_GRP", sliced)
            self.assertNotIn("REMOVE-SHAPE", sliced)
            self.assertNotIn("unknownPluginCommand", sliced)
            self.assertNotIn("driver.outputX", sliced)
            self.assertNotIn("D:/assets/hero.ma", sliced)
            self.assertNotIn("hero:ctrl", sliced)
            self.assertEqual(
                set(report.removed_node_paths),
                {"|remove_GRP", "|remove_GRP|removeShape"},
            )
            self.assertGreater(report.removed_statement_count, 4)
            self.assertEqual(
                len(parse_maya_ascii_text(sliced).nodes),
                3,
            )

    def test_ambiguous_roots_and_dynamic_parent_commands_fail_closed(self):
        ambiguous = (
            'createNode transform -n "a";\n'
            'createNode transform -n "b";\n'
            'createNode transform -n "child" -p "a";\n'
            'createNode transform -n "child" -p "b";\n'
        )
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ma"
            output = Path(folder) / "slice.ma"
            source.write_text(ambiguous, encoding="utf-8")
            with self.assertRaisesRegex(MayaAsciiSafetyError, "resolves to 2"):
                slice_maya_ascii(source, output, removed_roots=("child",))
        with self.assertRaisesRegex(MayaAsciiSafetyError, "parent commands"):
            parse_maya_ascii_text(
                'createNode transform -n "a"; parent "a" "b";'
            )

    def test_pre_open_plan_is_built_without_importing_maya(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.ma"
            source.write_text(FIXTURE, encoding="utf-8")
            plan = build_pre_open_ascii_bisect_plan(str(source), sys.executable)
            labels = {candidate.label for candidate in plan.candidates}
            self.assertIn("keep_GRP", labels)
            self.assertIn("remove_GRP", labels)
            self.assertIn("heroRN", labels)
            self.assertEqual(plan.metadata["isolation_mode"], "pre-open-ascii")
            self.assertEqual(plan.metadata["source_node_count"], 5)


if __name__ == "__main__":
    unittest.main()
