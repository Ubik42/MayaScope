from __future__ import annotations

import os
import subprocess
import sys
import unittest

from MayaScope.process_guard import (
    ChildJobGuard,
    ProcessIdentity,
    get_process_identity,
    terminate_exact_process,
)


class ProcessGuardTests(unittest.TestCase):
    def _sleeping_child(self):
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_process_identity_detects_pid_reuse_before_termination(self):
        child = self._sleeping_child()
        try:
            identity = get_process_identity(child.pid)
            self.assertIsNotNone(identity)
            wrong = ProcessIdentity(
                identity.pid, identity.executable, identity.started_ticks + 1
            )
            with self.assertRaisesRegex(RuntimeError, "PID.*复用"):
                terminate_exact_process(wrong)
            self.assertIsNone(child.poll())
            self.assertTrue(terminate_exact_process(identity))
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object contract")
    def test_windows_job_handle_close_reaps_child(self):
        child = self._sleeping_child()
        guard = ChildJobGuard(child)
        try:
            self.assertTrue(guard.assigned)
            guard.close()
            child.wait(timeout=5)
            self.assertIsNotNone(child.returncode)
        finally:
            guard.close()
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
