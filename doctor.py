"""Read-only hidden Maya 2025 host self-check."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .deployment import inspect_module, package_root


def locate_mayapy(value=None) -> Path:
    candidates = (
        Path(value).expanduser() if value else None,
        Path(os.environ["MAYASCOPE_MAYAPY"]).expanduser()
        if os.environ.get("MAYASCOPE_MAYAPY") else None,
        Path(r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"),
    )
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("Maya 2025 mayapy.exe not found")


def run_host_check(mayapy=None, timeout: float = 30.0):
    executable = locate_mayapy(mayapy)
    parent = package_root().parent
    code = (
        "import json,sys;"
        "sys.path.insert(0,%r);"
        "import maya.standalone;maya.standalone.initialize(name='python');"
        "import maya.cmds as c;import PySide6;import MayaScope;"
        "print(json.dumps({'ok':True,'maya':c.about(version=True),"
        "'api':c.about(apiVersion=True),'pyside':PySide6.__version__,"
        "'mayascope':MayaScope.__version__},sort_keys=True))"
    ) % str(parent)
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(parent), existing) if value
    )
    completed = subprocess.run(
        (str(executable), "-c", code),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "host check failed")[-2000:])
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if payload.get("ok") is True:
            return payload
    raise RuntimeError("Maya host check returned no machine-readable result")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-doctor")
    parser.add_argument("--mayapy")
    parser.add_argument("--module-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    report = {"module": inspect_module(args.module_dir).__dict__}
    try:
        report["host"] = run_host_check(args.mayapy, args.timeout)
        report["ok"] = True
        code = 0
    except Exception as exc:
        report["host"] = {"ok": False, "detail": str(exc)}
        report["ok"] = False
        code = 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
