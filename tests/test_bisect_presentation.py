from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from MayaScope.presentation.bisect import (
    begin_bisect_prism,
    fail_bisect_prism,
    finish_bisect_prism,
    present_bisect_attempt,
    request_bisect_cancel,
)


def _plan():
    return SimpleNamespace(
        candidates=("rig", "reference", "script"),
        metadata={"isolation_mode": "pre-open-ascii"},
        source_sha256="a" * 64,
    )


def _attempt(**overrides):
    values = {
        "outcome": "fail",
        "stage": "subset",
        "attempt_index": 1,
        "duration_seconds": 2.25,
        "timed_out": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _result(*, complete):
    return SimpleNamespace(
        delta_debug=SimpleNamespace(complete=complete),
        manifest=SimpleNamespace(attempts=(1, 2, 3)),
        manifest_path=Path("D:/probe/repro-capsule.json"),
        manifest_sha256="b" * 64,
    )


class BisectPresentationTests(unittest.TestCase):
    def test_begin_attempt_and_cancel_are_explicit_chinese_states(self):
        state = begin_bisect_prism(_plan())
        self.assertEqual(state.candidate_count, 3)
        self.assertIn("打开前切片", state.mode)
        self.assertEqual(state.outcome, "active")

        state = present_bisect_attempt(
            state,
            SimpleNamespace(candidate_ids=("rig", "script")),
            _attempt(timed_out=True),
        )
        self.assertEqual(state.signal, "复现  ·  2 / 3")
        self.assertIn("探针 02 · 子集 · 2.2 秒 · 超时", state.detail)

        state = request_bisect_cancel(state)
        self.assertFalse(state.cancel_enabled)
        self.assertEqual(state.cancel_text, "已排队停止")
        self.assertIn("安全完成后停止", state.detail)

    def test_finish_and_failure_expose_resume_boundary(self):
        state = finish_bisect_prism(
            begin_bisect_prism(_plan()),
            _result(complete=False),
            ("reference",),
        )
        self.assertEqual(state.signal, "部分收敛  ·  reference")
        self.assertTrue(state.resume_visible)
        self.assertTrue(state.dismiss_visible)
        self.assertFalse(state.cancel_visible)

        failed = fail_bisect_prism(state, "无法读取后台回执" * 20)
        self.assertEqual(failed.signal, "二分已停止")
        self.assertLessEqual(len(failed.detail), 110)
        self.assertEqual(failed.outcome, "unresolved")

        complete = finish_bisect_prism(
            begin_bisect_prism(_plan()),
            _result(complete=True),
            ("rig", "script"),
        )
        self.assertFalse(complete.resume_visible)
        self.assertEqual(complete.outcome, "fail")


if __name__ == "__main__":
    unittest.main()
