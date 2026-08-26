"""Hidden mayapy worker for read-only Scene Clinic publish gates."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

from .audit_schema import AUDIT_SCHEMA_VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def _owned(path: str, root: Path) -> Path:
    candidate = Path(path).resolve()
    candidate.relative_to(root)
    return candidate


def _workspace_for_scene(scene: Path, requested: str):
    if requested:
        return Path(requested).resolve(), "explicit"
    for candidate in (scene.parent,) + tuple(scene.parents):
        if (candidate / "workspace.mel").is_file():
            return candidate, "discovered"
    return scene.parent, "scene-directory"


def main(request_file: str) -> int:
    request_path = Path(request_file).resolve()
    root = request_path.parent
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result_path = _owned(request["result_path"], root)
    scene = Path(request["scene"]).resolve()
    stage = "prepare"
    try:
        if not scene.is_file() or _sha256(scene) != request["source_sha256"]:
            raise ValueError("Scene is missing or changed after audit request creation")
        import maya.standalone  # type: ignore
        maya.standalone.initialize(name="python")
        import maya.cmds as cmds  # type: ignore

        workspace, workspace_source = _workspace_for_scene(
            scene, str(request.get("workspace", ""))
        )
        if not workspace.is_dir():
            raise ValueError("Audit workspace does not exist: %s" % workspace)
        cmds.workspace(str(workspace), openWorkspace=True)
        stage = "open"
        cmds.file(
            str(scene),
            open=True,
            force=True,
            prompt=False,
            ignoreVersion=True,
            executeScriptNodes=False,
        )
        stage = "capture"
        from MayaScope.analysis.clinic import profile_map
        from MayaScope.analysis.config import load_environment_from_env
        from MayaScope.collectors import capture_scene

        environment = load_environment_from_env()
        profiles = profile_map(environment.profiles, environment.registry)
        profile_id = str(request["profile"])
        if profile_id not in profiles:
            raise ValueError("Unknown Clinic profile: %s" % profile_id)
        profile = profiles[profile_id]
        snapshot = capture_scene()
        stage = "analyze"
        report = environment.registry.evaluate(
            snapshot,
            enabled_rule_ids=profile.rule_ids,
            include_expensive=profile.include_expensive,
        )
        stage = "runtime"
        from MayaScope.analysis.runtime import analyze_runtime
        from MayaScope.collectors import capture_runtime

        runtime_started = time.perf_counter()
        runtime_snapshot = capture_runtime(snapshot)
        runtime_report = analyze_runtime(runtime_snapshot, snapshot)
        runtime_capture_ms = (time.perf_counter() - runtime_started) * 1000.0
        performance = None
        performance_samples = int(request.get("performance_samples", 0))
        if performance_samples:
            stage = "performance"
            from MayaScope.collectors import collect_evaluation_performance

            performance = collect_evaluation_performance(
                sample_count=performance_samples,
                warmup_count=int(request.get("performance_warmups", 2)),
                cmds_module=cmds,
            )
        if _sha256(scene) != request["source_sha256"]:
            raise RuntimeError("Source scene changed during read-only audit")
        threshold = int(request["severity_threshold"])
        issues = [
            {
                "id": issue.id,
                "rule_id": issue.rule_id,
                "title": issue.title,
                "description": issue.description,
                "severity": issue.severity.name.lower(),
                "severity_value": int(issue.severity),
                "affected_node_ids": issue.affected_node_ids,
                "evidence": [
                    {"label": item.label, "value": item.value}
                    for item in issue.evidence
                ],
                "suggested_action": issue.suggested_action,
                "atomic_subjects": [
                    {"id": subject, "node_id": node_id}
                    for subject, node_id in issue.atomic_subjects
                ],
            }
            for issue in tuple(report.issues) + tuple(runtime_report.issues)
        ]
        gate_failed = any(item["severity_value"] >= threshold for item in issues)
        payload = {
            "format": "mayascope.clinic-audit",
            "schema_version": AUDIT_SCHEMA_VERSION,
            "ok": not report.failures,
            "gate_failed": gate_failed,
            "stage": "done",
            "source_scene": str(scene),
            "source_sha256": request["source_sha256"],
            "profile": profile.id,
            "profile_title": profile.title,
            "config_source": environment.source,
            "config_fingerprint": environment.fingerprint,
            "workspace_source": workspace_source,
            "maya": {
                "version": str(cmds.about(version=True)),
                "api": int(cmds.about(apiVersion=True)),
            },
            "snapshot": {
                "id": snapshot.snapshot_id,
                "nodes": len(snapshot.nodes),
                "edges": len(snapshot.edges),
                "references": len(snapshot.references),
                "reference_inventory": [
                    {
                        "reference_node": item.reference_node,
                        "resolved_path": item.resolved_path,
                        "unresolved_path": item.unresolved_path,
                        "canonical_path": item.canonical_path,
                        "copy_number": item.copy_number,
                        "exists": item.exists,
                        "namespace": item.namespace,
                        "parent_reference_node": item.parent_reference_node,
                        "loaded": item.loaded,
                        "preview_only": item.preview_only,
                        "node_ids": item.node_ids,
                        "failed_edit_count": item.failed_edit_count,
                        "failed_edit_scan_complete": item.failed_edit_scan_complete,
                    }
                    for item in snapshot.references
                ],
                "unknown_plugins": [
                    {
                        "name": item.name,
                        "version": item.version,
                        "node_types": item.node_types,
                        "data_types": item.data_types,
                    }
                    for item in snapshot.unknown_plugins
                ],
                "scene_settings": snapshot.to_dict()["scene_settings"],
                "scene_lifecycle": snapshot.to_dict()["scene_lifecycle"],
                "plugins_in_use": snapshot.metadata.get("plugins_in_use", ()),
                "external_dependencies": [
                    {
                        "id": item.id,
                        "node_id": item.node_id,
                        "kind": item.kind,
                        "attribute": item.attribute,
                        "raw_path": item.raw_path,
                        "resolved_path": item.resolved_path,
                        "exists": item.exists,
                        "path_kind": item.path_kind,
                        "inside_workspace": item.inside_workspace,
                        "sequence_pattern": item.sequence_pattern,
                        "sequence_kind": item.sequence_kind,
                        "sequence_member_count": item.sequence_member_count,
                        "sequence_expected_count": item.sequence_expected_count,
                        "sequence_missing_count": item.sequence_missing_count,
                        "sequence_missing_samples": item.sequence_missing_samples,
                        "sequence_scan_complete": item.sequence_scan_complete,
                        "sequence_scan_reason": item.sequence_scan_reason,
                    }
                    for item in snapshot.external_dependencies
                ],
            },
            "performance": performance,
            "runtime": runtime_snapshot.to_dict(),
            "runtime_capture_ms": runtime_capture_ms,
            "runtime_limitations": runtime_report.limitations,
            "runtime_issue_count": len(runtime_report.issues),
            "issues": issues,
            "rule_runs": [
                {
                    "rule_id": item.rule_id,
                    "duration_ms": item.duration_ms,
                    "issue_count": item.issue_count,
                }
                for item in report.runs
            ],
            "rule_failures": [
                {"rule_id": item.rule_id, "message": item.message}
                for item in report.failures
            ],
            "skipped_rule_ids": report.skipped_rule_ids,
        }
        _atomic_json(result_path, payload)
        return 1 if report.failures else 2 if gate_failed else 0
    except Exception as exc:
        _atomic_json(
            result_path,
            {
                "format": "mayascope.clinic-audit",
                "schema_version": AUDIT_SCHEMA_VERSION,
                "ok": False,
                "gate_failed": False,
                "stage": stage,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc()[-8000:],
            },
        )
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: mayapy -m MayaScope.audit_worker REQUEST.json")
    raise SystemExit(main(sys.argv[1]))
