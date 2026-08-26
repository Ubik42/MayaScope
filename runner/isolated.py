"""Launch one no-window mayapy probe against an isolated scene copy."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Iterable, Mapping, Tuple

from ..model import BisectPlan, ProbeAttempt
from .maya_ascii import slice_maya_ascii


class RunnerError(RuntimeError):
    pass


def sha256_file(path: os.PathLike | str, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def _tail(value: str, limit: int = 16_000) -> str:
    return value[-limit:]


class IsolatedMayaProbe:
    """Create an owned attempt directory and run Maya only against its copy."""

    def __init__(self, plan: BisectPlan, root: os.PathLike | str | None = None):
        self.plan = plan
        if root is None:
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            root = base / "MayaScope" / "runner" / plan.plan_id
        self.root = Path(root).expanduser().resolve()

    def _validate_source(self) -> Path:
        source = Path(self.plan.source_scene).expanduser().resolve()
        executable = Path(self.plan.maya_executable).expanduser().resolve()
        if not source.is_file():
            raise RunnerError("Bisect source scene does not exist: %s" % source)
        if not executable.is_file():
            raise RunnerError("Configured mayapy executable does not exist: %s" % executable)
        actual = sha256_file(source)
        if actual != self.plan.source_sha256:
            raise RunnerError(
                "Source scene checksum changed after Bisect preview; refusing to run"
            )
        return source

    def run(self, candidate_ids: Iterable[str], attempt_index: int) -> ProbeAttempt:
        source = self._validate_source()
        enabled = tuple(candidate_ids)
        known = {candidate.id for candidate in self.plan.candidates}
        if len(enabled) != len(set(enabled)) or not set(enabled).issubset(known):
            raise RunnerError("Probe candidate set contains duplicate or unknown ids")
        if attempt_index < 0:
            raise ValueError("Probe attempt index cannot be negative")

        attempt_root = self.root / ("attempt-%04d" % attempt_index)
        if attempt_root.exists():
            raise RunnerError("Probe attempt directory already exists: %s" % attempt_root)
        attempt_root.mkdir(parents=True)
        source_copy = attempt_root / ("source-copy" + source.suffix.lower())
        output_copy = attempt_root / ("output" + source.suffix.lower())
        shutil.copy2(str(source), str(source_copy))
        copied_checksum = sha256_file(source_copy)
        if copied_checksum != self.plan.source_sha256:
            raise RunnerError("Isolated scene copy failed checksum verification")
        input_copy = source_copy
        if self.plan.metadata.get("isolation_mode") == "pre-open-ascii":
            if source.suffix.lower() != ".ma":
                raise RunnerError("Pre-open ASCII isolation requires a .ma source scene")
            excluded = [
                candidate for candidate in self.plan.candidates if candidate.id not in enabled
            ]
            removed_roots = tuple(
                name
                for candidate in excluded
                for name in candidate.metadata.get("pre_open_roots", ())
            )
            removed_reference_paths = tuple(
                path
                for candidate in excluded
                for path in candidate.metadata.get("pre_open_reference_paths", ())
            )
            input_copy = attempt_root / "probe-input.ma"
            slice_maya_ascii(
                source_copy,
                input_copy,
                removed_roots=removed_roots,
                removed_reference_paths=removed_reference_paths,
            )
        input_checksum = sha256_file(input_copy)

        request_path = attempt_root / "request.json"
        result_path = attempt_root / "result.json"
        progress_path = attempt_root / "progress.json"
        candidates = []
        for candidate in self.plan.candidates:
            candidates.append(
                {
                    "id": candidate.id,
                    "label": candidate.label,
                    "kind": candidate.kind,
                    "metadata": dict(candidate.metadata),
                }
            )
        _atomic_json(
            request_path,
            {
                "schema_version": 1,
                "plan_id": self.plan.plan_id,
                "attempt_index": attempt_index,
                "attempt_root": str(attempt_root),
                "input_copy": str(input_copy),
                "output_copy": str(output_copy),
                "result_path": str(result_path),
                "progress_path": str(progress_path),
                "source_sha256": self.plan.source_sha256,
                "input_sha256": input_checksum,
                "enabled_candidate_ids": enabled,
                "candidates": candidates,
                "stages": self.plan.stages,
            },
        )
        environment = os.environ.copy()
        package_parent = str(Path(__file__).resolve().parents[2])
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (package_parent, existing_pythonpath) if value
        )
        environment["MAYA_APP_DIR"] = str(attempt_root / "maya_app")
        environment["QT_QPA_PLATFORM"] = "offscreen"
        command = (
            str(Path(self.plan.maya_executable).resolve()),
            "-m",
            "MayaScope.runner.worker",
            str(request_path),
        )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        started = time.perf_counter()
        timed_out = False
        exit_code = None
        stdout = ""
        stderr = ""
        try:
            completed = subprocess.run(
                command,
                cwd=str(attempt_root),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.plan.timeout_seconds,
                creationflags=creation_flags,
                shell=False,
            )
            exit_code = completed.returncode
            stdout, stderr = completed.stdout or "", completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        duration = time.perf_counter() - started

        result = {}
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                result = {}
        progress = {}
        if progress_path.is_file():
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
            except Exception:
                progress = {}
        stage = str(result.get("stage") or progress.get("stage") or "prepare")
        if stage not in {"prepare", "open", "evaluate", "save", "reopen", "exit"}:
            stage = "prepare"
        if timed_out:
            outcome = "fail"
        elif result.get("outcome") in {"pass", "fail", "unresolved"}:
            outcome = str(result["outcome"])
        elif exit_code == 0:
            outcome = "unresolved"
        elif exit_code == 2:
            outcome = "unresolved"
        else:
            outcome = "fail"
        artifacts = tuple(
            str(path.relative_to(attempt_root))
            for pattern in ("**/mayaCrash*", "**/*.dmp", "**/*.crash")
            for path in attempt_root.glob(pattern)
            if path.is_file()
        )
        return ProbeAttempt(
            attempt_index=attempt_index,
            candidate_ids=enabled,
            outcome=outcome,
            stage=stage,
            duration_seconds=duration,
            exit_code=exit_code,
            timed_out=timed_out,
            work_copy=str(input_copy),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr or str(result.get("message", ""))),
            crash_artifacts=tuple(sorted(set(artifacts))),
            environment=result.get("environment", {}),
        )
