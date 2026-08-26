from __future__ import annotations

import unittest

from MayaScope.analysis.pulse import ProfilerParseError, node_stats, parse_maya_profiler_output
from MayaScope.model import ProfilerCapture, SceneNode, SceneSnapshot


FIXTURE = """#File Version, # of events, # of CPUs
2\t3\t8
Main\tEvaluation\t
Main thread\tGraph evaluation\t
#Comment mapping---------
@0 = Compute
@1 = nodeA
@2 = Dirty
@3 = nodeB
#Comment mapping---------
#Event time, Comment, Extra comment, Category id, Duration, Thread Duration, Thread id, Cpu id, Color id
100\t@0\t@1\t1\t10\t12\t7\t2\t4
110\t@0\t@1\t1\t20\t22\t7\t2\t4
105\t@2\t@3\t0\t5\t6\t8\t3\t2
#Begin comment description mapping---------
0 = Calling compute
2 = Dirty propagation
#Begin comment description mapping---------
"""


class ProfilerPulseTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SceneSnapshot.build(
            (SceneNode("uuid-a", "nodeA", "network"), SceneNode("uuid-b", "nodeB", "network")),
            (),
            snapshot_id="scene-capture",
            maya_version="2025",
        )

    def test_parser_preserves_tracks_and_maps_stable_node_ids(self):
        capture = parse_maya_profiler_output(FIXTURE, self.snapshot)
        self.assertEqual(capture.source_snapshot_id, "scene-capture")
        self.assertEqual(capture.metadata["cpu_count"], 8)
        self.assertEqual(capture.duration_us, 30)
        self.assertEqual(capture.events[0].start_us, 0)
        self.assertEqual(capture.events[0].category_name, "Evaluation")
        self.assertEqual(capture.events[0].node_id, "uuid-a")
        self.assertEqual(capture.events[2].node_id, "uuid-b")
        self.assertEqual(capture.events[0].description, "Calling compute")
        self.assertEqual(ProfilerCapture.from_json(capture.to_json()), capture)

    def test_time_range_aggregates_clipped_inclusive_duration(self):
        capture = parse_maya_profiler_output(FIXTURE, self.snapshot)
        stats = node_stats(capture, start_us=5, end_us=25)
        self.assertEqual(stats[0].node_id, "uuid-a")
        self.assertEqual(stats[0].inclusive_duration_us, 20)
        self.assertEqual(stats[0].event_count, 2)
        self.assertEqual(stats[1].inclusive_duration_us, 5)
        self.assertAlmostEqual(stats[0].capture_share, 0.8)

    def test_malformed_event_count_fails_loudly(self):
        malformed = FIXTURE.replace("2\t3\t8", "2\t4\t8")
        with self.assertRaisesRegex(ProfilerParseError, "event count mismatch"):
            parse_maya_profiler_output(malformed, self.snapshot)


if __name__ == "__main__":
    unittest.main()
