from __future__ import annotations

import unittest

from MayaScope.collectors.evaluation_benchmark import collect_evaluation_performance


class FakeCmds:
    def __init__(self, fail=False):
        self.time = 5.0
        self.fail = fail
        self.pulls = 0

    def currentTime(self, value=None, query=False, edit=False, update=False):
        if query:
            return self.time
        self.time = float(value)

    def playbackOptions(self, query=False, minTime=False, maxTime=False):
        return 1.0 if minTime else 24.0

    def ls(self, geometry=False, type=None, long=False):
        return ["|meshShape"] if geometry else ["|mesh"] if type == "transform" else []

    def dgdirty(self, allPlugs=False):
        pass

    def exactWorldBoundingBox(self, nodes, ignoreInvisible=False):
        self.pulls += 1
        if self.fail:
            raise RuntimeError("evaluation failed")
        return [-1, -1, -1, 1, 1, 1]

    def evaluationManager(self, query=False, mode=False):
        return ["parallel"]


class EvaluationBenchmarkTests(unittest.TestCase):
    def test_collects_samples_and_restores_time(self):
        cmds = FakeCmds()
        result = collect_evaluation_performance(
            sample_count=5, warmup_count=1, cmds_module=cmds
        )
        self.assertEqual(len(result["samples_us"]), 5)
        self.assertEqual(result["geometry_target_count"], 1)
        self.assertEqual(result["evaluation_mode"], "parallel")
        self.assertTrue(result["time_restored"])
        self.assertEqual(cmds.time, 5.0)
        self.assertEqual(cmds.pulls, 7)

    def test_failed_pull_still_restores_original_time(self):
        cmds = FakeCmds(fail=True)
        with self.assertRaisesRegex(RuntimeError, "evaluation failed"):
            collect_evaluation_performance(
                sample_count=3, warmup_count=0, cmds_module=cmds
            )
        self.assertEqual(cmds.time, 5.0)


if __name__ == "__main__":
    unittest.main()
