"""Launch and verify one isolated, hidden Maya GUI owned by MayaScope."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from .process_guard import get_process_identity, terminate_exact_process


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def maya_process_ids() -> tuple[int, ...]:
    if os.name != "nt":
        return ()
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq maya.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    pids = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) >= 2 and row[0].casefold() == "maya.exe":
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return tuple(sorted(set(pids)))


def run_gui_lifecycle(
    maya_executable: Path,
    output: Path,
    screenshot: Path,
    *,
    timeout: float = 90.0,
    maya_app_dir: Path | None = None,
    inject_package_parent: bool = True,
    expected_package_root: Path | None = None,
    working_directory: Path | None = None,
    scenario: str = "default",
    width: int = 1480,
    height: int = 900,
) -> dict:
    maya = maya_executable.expanduser().resolve()
    if not maya.is_file() or maya.name.casefold() != "maya.exe":
        raise ValueError("必须提供真实 Maya GUI 可执行文件 maya.exe")
    output = output.expanduser().resolve()
    screenshot = screenshot.expanduser().resolve()
    if scenario not in {"default", "instruments"}:
        raise ValueError("不支持的 Maya GUI 验收场景：%s" % scenario)
    width, height = int(width), int(height)
    if width < 800 or height < 560:
        raise ValueError("MayaScope GUI 验收尺寸不得小于 800 × 560")
    preexisting_ids = maya_process_ids()
    preexisting = {
        pid: identity
        for pid in preexisting_ids
        if (identity := get_process_identity(pid)) is not None
    }
    started = time.perf_counter()
    timed_out = False
    terminated_after_timeout = False

    with tempfile.TemporaryDirectory(prefix="mayascope-gui-lifecycle-") as folder:
        root = Path(folder)
        worker_receipt = root / "worker.json"
        mel_script = root / "launch_probe.mel"
        log_path = output.with_name("mayascope-gui-lifecycle-maya.log")
        mel_script.write_text(
            'python("from MayaScope.gui_lifecycle_worker import schedule; schedule()");\n',
            encoding="utf-8",
        )
        environment = os.environ.copy()
        if inject_package_parent:
            package_parent = str(Path(__file__).resolve().parent.parent)
            environment["PYTHONPATH"] = package_parent + os.pathsep + environment.get(
                "PYTHONPATH", ""
            )
        else:
            # A clean-install replay must prove Maya discovered the package from
            # its .mod file, not from this development checkout.
            environment.pop("PYTHONPATH", None)
            environment.pop("MAYA_MODULE_PATH", None)
        environment["MAYA_APP_DIR"] = str(
            (maya_app_dir or (root / "maya-app")).expanduser().resolve()
        )
        environment["MAYA_DISABLE_CIP"] = "1"
        environment["MAYA_DISABLE_CER"] = "1"
        environment["MAYASCOPE_GUI_LIFECYCLE_WORKER"] = str(worker_receipt)
        environment["MAYASCOPE_GUI_LIFECYCLE_SCREENSHOT"] = str(screenshot)
        environment["MAYASCOPE_GUI_LIFECYCLE_SCENARIO"] = scenario
        environment["MAYASCOPE_GUI_LIFECYCLE_WIDTH"] = str(width)
        environment["MAYASCOPE_GUI_LIFECYCLE_HEIGHT"] = str(height)
        if expected_package_root is not None:
            environment["MAYASCOPE_EXPECTED_PACKAGE_ROOT"] = str(
                expected_package_root.expanduser().resolve()
            )

        startup = None
        creation_flags = 0
        if os.name == "nt":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            [
                str(maya), "-hideConsole", "-noAutoloadPlugins",
                "-script", str(mel_script), "-log", str(log_path),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(working_directory.expanduser().resolve()) if working_directory else None,
            startupinfo=startup,
            creationflags=creation_flags,
        )
        identity = get_process_identity(process.pid)
        deadline = time.monotonic() + max(10.0, float(timeout))
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            timed_out = True
            if identity is None:
                identity = get_process_identity(process.pid)
            if identity is not None:
                terminated_after_timeout = terminate_exact_process(identity, timeout=8.0)
            process.wait(timeout=10.0)
        exit_code = process.returncode
        worker = (
            json.loads(worker_receipt.read_text(encoding="utf-8"))
            if worker_receipt.is_file()
            else {"ok": False, "error": "Maya GUI 未生成 worker 回执"}
        )

    preserved = {
        str(pid): get_process_identity(pid) == before
        for pid, before in preexisting.items()
    }
    owned_ended = get_process_identity(process.pid) is None
    payload = {
        "format": "mayascope.gui-lifecycle",
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "ok": bool(
            worker.get("ok")
            and not timed_out
            and owned_ended
            and all(preserved.values())
        ),
        "maya_executable": str(maya),
        "owned_pid": process.pid,
        "owned_identity": identity.to_dict() if identity else None,
        "owned_process_ended": owned_ended,
        "preexisting_maya_pids": list(preexisting_ids),
        "preexisting_processes_preserved": preserved,
        "timed_out": timed_out,
        "terminated_after_timeout": terminated_after_timeout,
        "exit_code": exit_code,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "maya_log": str(log_path),
        "screenshot": str(screenshot),
        "scenario": scenario,
        "window_size": [width, height],
        "worker": worker,
    }
    _atomic_json(output, payload)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-gui-lifecycle")
    parser.add_argument("--maya", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--scenario",
        choices=("default", "instruments"),
        default="default",
        help="可选真实交互场景；instruments 会采集 Profiler 与 Runtime 证据",
    )
    parser.add_argument("--width", type=int, default=1480)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        payload = run_gui_lifecycle(
            args.maya,
            args.output,
            args.screenshot,
            timeout=args.timeout,
            scenario=args.scenario,
            width=args.width,
            height=args.height,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
