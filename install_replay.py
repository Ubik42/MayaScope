"""Replay a MayaScope release ZIP through install, first launch and removal."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable
import zipfile

from .gui_lifecycle import _atomic_json, run_gui_lifecycle
from .release import verify_release


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _installer_environment(extraction_root: Path) -> dict:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(extraction_root)
    environment.pop("MAYA_MODULE_PATH", None)
    return environment


def _run_installer(
    extraction_root: Path,
    module_dir: Path,
    action: str,
    working_directory: Path,
) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "MayaScope.install",
            action,
            "--module-dir",
            str(module_dir),
        ],
        cwd=str(working_directory),
        env=_installer_environment(extraction_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30.0,
        check=False,
    )
    lines = tuple(line for line in result.stdout.splitlines() if line.strip())
    try:
        payload = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("安装器没有返回有效 JSON：%s" % result.stdout[-1000:]) from exc
    if result.returncode != 0:
        raise RuntimeError(
            "安装器 %s 失败（%s）：%s"
            % (action, result.returncode, payload.get("detail") or result.stderr[-1000:])
        )
    return payload


def run_install_replay(
    archive: Path,
    maya_executable: Path,
    output: Path,
    screenshot: Path,
    *,
    timeout: float = 90.0,
    gui_runner: Callable = run_gui_lifecycle,
    scenario: str = "default",
    width: int = 1480,
    height: int = 900,
) -> dict:
    archive = archive.expanduser().resolve()
    maya = maya_executable.expanduser().resolve()
    output = output.expanduser().resolve()
    screenshot = screenshot.expanduser().resolve()
    if not archive.is_file():
        raise ValueError("发布包不存在：%s" % archive)
    if not maya.is_file() or maya.name.casefold() != "maya.exe":
        raise ValueError("必须提供真实 Maya GUI 可执行文件 maya.exe")
    manifest = verify_release(archive)
    gui_output = output.with_name(output.stem + "-gui.json")
    temporary_root = ""

    with tempfile.TemporaryDirectory(prefix="mayascope-install-replay-") as folder:
        root = Path(folder).resolve()
        temporary_root = str(root)
        extraction_root = root / "release"
        extraction_root.mkdir()
        with zipfile.ZipFile(archive, "r") as release_zip:
            release_zip.extractall(extraction_root)
        package_root = extraction_root / "MayaScope"
        if not (package_root / "__init__.py").is_file():
            raise ValueError("发布包缺少 MayaScope/__init__.py")

        sandbox = root / "runner"
        sandbox.mkdir()
        maya_app = root / "maya-app"
        module_dir = maya_app / "2025" / "modules"
        installed = _run_installer(extraction_root, module_dir, "install", sandbox)
        status_after_install = _run_installer(
            extraction_root, module_dir, "status", sandbox
        )
        module_file = Path(installed["module_file"])
        module_content = module_file.read_text(encoding="utf-8")
        module_points_to_release = package_root.as_posix() in module_content

        gui = gui_runner(
            maya,
            gui_output,
            screenshot,
            timeout=timeout,
            maya_app_dir=maya_app,
            inject_package_parent=False,
            expected_package_root=package_root,
            working_directory=sandbox,
            scenario=scenario,
            width=width,
            height=height,
        )

        removed = _run_installer(extraction_root, module_dir, "uninstall", sandbox)
        backup = Path(removed.get("backup_file", ""))
        target = Path(removed["module_file"])
        backup_created = backup.is_file() and not target.exists()
        if not backup_created:
            raise RuntimeError("卸载没有留下可恢复的 Module 备份")
        os.replace(str(backup), str(target))
        recovered = _run_installer(extraction_root, module_dir, "status", sandbox)
        removed_final = _run_installer(
            extraction_root, module_dir, "uninstall", sandbox
        )
        final_status = _run_installer(extraction_root, module_dir, "status", sandbox)

        checks = {
            "发布包清单通过": True,
            "Module 指向解压副本": module_points_to_release,
            "安装状态正确": status_after_install.get("state") == "installed",
            "真实 Maya 首次启动通过": bool(gui.get("ok")),
            "卸载保留可恢复备份": backup_created,
            "备份恢复后可识别": recovered.get("state") == "installed",
            "最终卸载无活动 Module": final_status.get("state") == "not-installed",
        }
        payload = {
            "format": "mayascope.install-replay",
            "schema_version": 1,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "ok": all(checks.values()),
            "checks": checks,
            "release": {
                "archive": str(archive),
                "sha256": _sha256(archive),
                "version": manifest["version"],
                "file_count": len(manifest["files"]),
            },
            "isolated_environment": {
                "temporary_root": temporary_root,
                "package_root": str(package_root),
                "maya_app_dir": str(maya_app),
                "module_file": str(module_file),
                "development_pythonpath_injected": False,
                "module_content": module_content,
            },
            "install": installed,
            "status_after_install": status_after_install,
            "gui_lifecycle": gui,
            "gui_receipt": str(gui_output),
            "screenshot": str(screenshot),
            "scenario": scenario,
            "window_size": [int(width), int(height)],
            "uninstall": removed,
            "recovered_status": recovered,
            "final_uninstall": removed_final,
            "final_status": final_status,
        }

    payload["isolated_environment"]["temporary_root_cleaned"] = not Path(
        temporary_root
    ).exists()
    payload["checks"]["临时安装环境已清理"] = payload["isolated_environment"][
        "temporary_root_cleaned"
    ]
    payload["ok"] = all(payload["checks"].values())
    _atomic_json(output, payload)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-install-replay")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--maya", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--scenario",
        choices=("default", "instruments", "runtime-cancel", "capture-cancel", "project-gate", "lens", "atlas-scale"),
        default="default",
    )
    parser.add_argument("--width", type=int, default=1480)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        payload = run_install_replay(
            args.archive,
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
