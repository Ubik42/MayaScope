"""No-UI mayapy worker. It must only receive paths inside an owned attempt."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Mapping


def _atomic_json(path: Path, payload: Mapping) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _owned(path: str, root: Path) -> Path:
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Runner path escapes attempt root: %s" % candidate) from exc
    return candidate


def _stage(progress_path: Path, stage: str, detail: str = "") -> None:
    _atomic_json(
        progress_path,
        {"stage": stage, "detail": detail, "updated_at": time.time()},
    )


def _exclude_candidates(cmds, request: Mapping) -> None:
    enabled = set(request.get("enabled_candidate_ids", ()))
    for candidate in request.get("candidates", ()):
        if candidate.get("id") in enabled:
            continue
        kind = candidate.get("kind")
        metadata = candidate.get("metadata", {})
        if kind == "top-level-dag":
            names = tuple(metadata.get("maya_names", ()))
            existing = [name for name in names if cmds.objExists(name)]
            if existing:
                cmds.delete(existing)
        elif kind == "reference":
            reference_node = str(metadata.get("reference_node", ""))
            if reference_node and cmds.objExists(reference_node):
                cmds.file(unloadReference=reference_node)
        else:
            raise ValueError("Unsupported Runner candidate kind: %s" % kind)


def _maya_environment(cmds) -> Mapping:
    """Small reproducibility fingerprint; never loads additional plugins."""
    def safe(call, fallback=None):
        try:
            value = call()
            return fallback if value is None else value
        except Exception:
            return fallback

    return {
        "maya_version": str(safe(lambda: cmds.about(version=True), "unknown")),
        "maya_api_version": int(safe(lambda: cmds.about(apiVersion=True), 0)),
        "os": str(safe(lambda: cmds.about(operatingSystem=True), "unknown")),
        "evaluation_mode": tuple(safe(lambda: cmds.evaluationManager(query=True, mode=True), ())),
        "linear_unit": str(safe(lambda: cmds.currentUnit(query=True, linear=True), "unknown")),
        "angular_unit": str(safe(lambda: cmds.currentUnit(query=True, angle=True), "unknown")),
        "time_unit": str(safe(lambda: cmds.currentUnit(query=True, time=True), "unknown")),
        "loaded_plugins": tuple(sorted(safe(lambda: cmds.pluginInfo(query=True, listPlugins=True), ()))),
    }


def main(request_file: str) -> int:
    request_path = Path(request_file).resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    attempt_root = Path(request["attempt_root"]).resolve()
    request_path.relative_to(attempt_root)
    input_copy = _owned(request["input_copy"], attempt_root)
    output_copy = _owned(request["output_copy"], attempt_root)
    result_path = _owned(request["result_path"], attempt_root)
    progress_path = _owned(request["progress_path"], attempt_root)
    if _sha256(input_copy) != request["input_sha256"]:
        raise ValueError("Worker input checksum does not match the Probe request")

    stage = "prepare"
    environment = {}
    try:
        _stage(progress_path, stage, "initializing Maya standalone")
        import maya.standalone
        maya.standalone.initialize(name="python")
        import maya.cmds as cmds
        environment = _maya_environment(cmds)

        stage = "open"
        _stage(progress_path, stage, input_copy.name)
        cmds.file(
            str(input_copy),
            open=True,
            force=True,
            prompt=False,
            ignoreVersion=True,
            executeScriptNodes=False,
        )
        _exclude_candidates(cmds, request)

        if "evaluate" in request.get("stages", ()):
            stage = "evaluate"
            _stage(progress_path, stage, "dirty + refresh")
            cmds.dgdirty(allPlugs=True)
            cmds.refresh(force=True)

        if "save" in request.get("stages", ()):
            stage = "save"
            _stage(progress_path, stage, output_copy.name)
            cmds.file(rename=str(output_copy))
            file_type = "mayaAscii" if output_copy.suffix.lower() == ".ma" else "mayaBinary"
            cmds.file(save=True, force=True, type=file_type)

        if "reopen" in request.get("stages", ()):
            stage = "reopen"
            _stage(progress_path, stage, output_copy.name)
            cmds.file(
                str(output_copy),
                open=True,
                force=True,
                prompt=False,
                ignoreVersion=True,
                executeScriptNodes=False,
            )

        stage = "exit"
        _stage(progress_path, stage, "probe passed")
        _atomic_json(
            result_path,
            {
                "outcome": "pass",
                "stage": stage,
                "message": "all requested stages passed",
                "environment": environment,
            },
        )
        return 0
    except (ValueError, KeyError) as exc:
        _atomic_json(
            result_path,
            {
                "outcome": "unresolved",
                "stage": stage,
                "message": str(exc),
                "environment": environment,
            },
        )
        return 2
    except Exception as exc:
        _atomic_json(
            result_path,
            {
                "outcome": "fail",
                "stage": stage,
                "message": "%s\n%s" % (exc, traceback.format_exc()),
                "environment": environment,
            },
        )
        return 20


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: mayapy -m MayaScope.runner.worker REQUEST.json", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
