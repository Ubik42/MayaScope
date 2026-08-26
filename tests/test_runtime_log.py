from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.runtime_log import close_logger, get_logger


class RuntimeLogTests(unittest.TestCase):
    def test_jsonl_event_has_stable_machine_readable_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            logger = get_logger(root)
            logger.info(
                "probe passed",
                extra={"event": "bisect.probe", "context": {"attempt": 3}},
            )
            for handler in logger.handlers:
                handler.flush()
            lines = (root / "mayascope.jsonl").read_text(encoding="utf-8").splitlines()
            payload = json.loads(lines[-1])
            self.assertEqual(payload["event"], "bisect.probe")
            self.assertEqual(payload["context"]["attempt"], 3)
            self.assertEqual(payload["message"], "probe passed")
            self.assertIn("timestamp", payload)
            close_logger(logger)


if __name__ == "__main__":
    unittest.main()
