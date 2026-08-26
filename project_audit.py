"""Self-contained, signed project-level aggregation for Scene Clinic audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from .audit import _canonical_json, verify_audit_report
from .audit_schema import migrate_audit_payload


PROJECT_AUDIT_SCHEMA_VERSION = 1
PROJECT_AUDIT_FORMAT = "mayascope.project-audit"
SEVERITY_NAMES = ("critical", "error", "warning", "info")


def _sign(payload: Mapping) -> dict:
    envelope = dict(payload)
    envelope.pop("project_sha256", None)
    envelope["project_sha256"] = hashlib.sha256(_canonical_json(envelope)).hexdigest()
    return envelope


def _atomic_project_json(path: Path, payload: Mapping) -> str:
    envelope = _sign(payload)
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    data = json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(destination))
    return envelope["project_sha256"]


def _workspace_root(report: Mapping) -> str:
    lifecycle = (report.get("snapshot") or {}).get("scene_lifecycle") or {}
    return str(lifecycle.get("workspace_root") or "")


def _context(report: Mapping) -> dict:
    maya = report.get("maya") or {}
    return {
        "profile": str(report.get("profile") or ""),
        "config_fingerprint": str(report.get("config_fingerprint") or ""),
        "maya_version": str(maya.get("version") or ""),
        "maya_api": int(maya.get("api") or 0),
        "workspace_root": _workspace_root(report),
    }


def _atomic_count(issue: Mapping) -> int:
    subjects = issue.get("atomic_subjects") or ()
    if subjects:
        return len(subjects)
    node_ids = tuple(dict.fromkeys(issue.get("affected_node_ids") or ()))
    return len(node_ids) if node_ids else 1


def _scene_receipt(report: Mapping) -> dict:
    severities = {name: 0 for name in SEVERITY_NAMES}
    rules = {}
    atomic_findings = 0
    for issue in report.get("issues") or ():
        severity = str(issue.get("severity") or "info").lower()
        severities[severity] = severities.get(severity, 0) + 1
        rule_id = str(issue.get("rule_id") or "unknown")
        rules[rule_id] = rules.get(rule_id, 0) + 1
        atomic_findings += _atomic_count(issue)
    return {
        "source_scene": str(report.get("source_scene") or ""),
        "source_sha256": str(report.get("source_sha256") or ""),
        "report_sha256": str(report.get("report_sha256") or ""),
        "ok": bool(report.get("ok", False)),
        "gate_failed": bool(report.get("gate_failed", False)),
        "audit_exit_code": int(report.get("audit_exit_code", 0)),
        "issue_count": len(report.get("issues") or ()),
        "atomic_finding_count": atomic_findings,
        "severity_counts": severities,
        "rule_counts": dict(sorted(rules.items())),
    }


def _assert_compatible(context: Mapping, candidate: Mapping) -> None:
    labels = {
        "profile": "Clinic 配置档",
        "config_fingerprint": "规则配置指纹",
        "maya_version": "Maya 版本",
        "maya_api": "Maya API",
        "workspace_root": "项目工作区",
    }
    mismatches = [
        labels[key]
        for key in labels
        if candidate.get(key) != context.get(key)
    ]
    if mismatches:
        raise ValueError("项目审计上下文不一致：%s" % "、".join(mismatches))


def build_project_audit(report_paths: Iterable[Path], output: Path | None = None) -> dict:
    paths = tuple(Path(path).expanduser().resolve() for path in report_paths)
    if not paths:
        raise ValueError("至少需要一份带签名的场景审计报告")
    scenes = []
    context = None
    seen_sources = set()
    for path in paths:
        report = verify_audit_report(path)
        raw_report = json.loads(path.read_text(encoding="utf-8"))
        candidate_context = _context(report)
        if context is None:
            context = candidate_context
        else:
            _assert_compatible(context, candidate_context)
        source = str(report.get("source_scene") or "")
        identity = os.path.normcase(os.path.abspath(source)) if source else ""
        if not identity or identity in seen_sources:
            raise ValueError("项目审计包含空场景或重复场景：%s" % (source or "<空>"))
        seen_sources.add(identity)
        scenes.append({"receipt": _scene_receipt(report), "audit": raw_report})
    scenes.sort(key=lambda item: os.path.normcase(item["receipt"]["source_scene"]))

    severity_totals = {name: 0 for name in SEVERITY_NAMES}
    rule_totals = {}
    for item in scenes:
        receipt = item["receipt"]
        for name, count in receipt["severity_counts"].items():
            severity_totals[name] = severity_totals.get(name, 0) + int(count)
        for rule_id, count in receipt["rule_counts"].items():
            rule_totals[rule_id] = rule_totals.get(rule_id, 0) + int(count)
    blocked = sum(
        1 for item in scenes
        if not item["receipt"]["ok"] or item["receipt"]["gate_failed"]
    )
    payload = {
        "format": PROJECT_AUDIT_FORMAT,
        "schema_version": PROJECT_AUDIT_SCHEMA_VERSION,
        "ok": all(item["receipt"]["ok"] for item in scenes),
        "gate_failed": bool(blocked),
        "context": context,
        "summary": {
            "scene_count": len(scenes),
            "passed_scene_count": len(scenes) - blocked,
            "blocked_scene_count": blocked,
            "issue_count": sum(item["receipt"]["issue_count"] for item in scenes),
            "atomic_finding_count": sum(
                item["receipt"]["atomic_finding_count"] for item in scenes
            ),
            "severity_counts": severity_totals,
            "rule_counts": dict(sorted(rule_totals.items())),
        },
        "scenes": scenes,
    }
    signed = _sign(payload)
    if output is not None:
        _atomic_project_json(output, signed)
    return signed


def verify_project_audit(path: Path) -> dict:
    bundle_path = path.expanduser().resolve()
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    if payload.get("format") != PROJECT_AUDIT_FORMAT:
        raise ValueError("不是 MayaScope 项目审计包")
    if payload.get("schema_version") != PROJECT_AUDIT_SCHEMA_VERSION:
        raise ValueError("不支持的项目审计格式版本")
    expected = payload.pop("project_sha256", None)
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("项目审计包缺少有效签名")
    actual = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if actual != expected:
        raise ValueError("项目审计包签名不匹配")
    embedded = payload.get("scenes") or ()
    if not embedded:
        raise ValueError("项目审计包没有场景")
    for item in embedded:
        raw_report = dict(item.get("audit") or {})
        report_checksum = raw_report.pop("report_sha256", None)
        if hashlib.sha256(_canonical_json(raw_report)).hexdigest() != report_checksum:
            raise ValueError("内嵌场景审计签名不匹配")
        report = migrate_audit_payload(raw_report)
        report["report_sha256"] = report_checksum
        if _scene_receipt(report) != item.get("receipt"):
            raise ValueError("场景审计回执与内嵌报告不一致")
    payload["project_sha256"] = expected
    # Rebuild from embedded reports to validate summary, ordering and context.
    migrated_reports = []
    for item in embedded:
        raw = dict(item["audit"])
        checksum = raw.pop("report_sha256")
        migrated = migrate_audit_payload(raw)
        migrated["report_sha256"] = checksum
        migrated_reports.append(migrated)
    context = _context(migrated_reports[0])
    sources = set()
    for report in migrated_reports:
        _assert_compatible(context, _context(report))
        source = os.path.normcase(os.path.abspath(str(report.get("source_scene") or "")))
        if not source or source in sources:
            raise ValueError("项目审计包存在重复场景")
        sources.add(source)
    expected_order = sorted(
        (item["receipt"]["source_scene"] for item in embedded), key=os.path.normcase
    )
    if [item["receipt"]["source_scene"] for item in embedded] != expected_order:
        raise ValueError("项目审计包场景顺序不是确定性的")
    receipts = [item["receipt"] for item in embedded]
    severity_totals = {name: 0 for name in SEVERITY_NAMES}
    rule_totals = {}
    for receipt in receipts:
        for name, count in receipt["severity_counts"].items():
            severity_totals[name] = severity_totals.get(name, 0) + int(count)
        for rule_id, count in receipt["rule_counts"].items():
            rule_totals[rule_id] = rule_totals.get(rule_id, 0) + int(count)
    blocked = sum(1 for receipt in receipts if not receipt["ok"] or receipt["gate_failed"])
    summary = {
        "scene_count": len(receipts),
        "passed_scene_count": len(receipts) - blocked,
        "blocked_scene_count": blocked,
        "issue_count": sum(item["issue_count"] for item in receipts),
        "atomic_finding_count": sum(item["atomic_finding_count"] for item in receipts),
        "severity_counts": severity_totals,
        "rule_counts": dict(sorted(rule_totals.items())),
    }
    if payload.get("context") != context or payload.get("summary") != summary:
        raise ValueError("项目审计包聚合摘要不一致")
    if bool(payload.get("gate_failed")) != bool(blocked):
        raise ValueError("项目审计包门禁状态不一致")
    if bool(payload.get("ok")) != all(item["ok"] for item in receipts):
        raise ValueError("项目审计包执行状态不一致")
    return payload


def _summary(payload: Mapping) -> dict:
    return {
        "ok": bool(payload.get("ok")),
        "gate_failed": bool(payload.get("gate_failed")),
        "project_sha256": payload.get("project_sha256"),
        **dict(payload.get("summary") or {}),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-project-audit")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="汇总带签名的场景审计报告")
    build.add_argument("reports", type=Path, nargs="+")
    build.add_argument("--report", type=Path, required=True)
    build.add_argument("--summary", action="store_true")
    verify = commands.add_parser("verify", help="校验项目审计包")
    verify.add_argument("report", type=Path)
    verify.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            payload = build_project_audit(args.reports, args.report)
        else:
            payload = verify_project_audit(args.report)
        output = _summary(payload) if args.summary else payload
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        if not payload.get("ok", False):
            return 1
        return 2 if payload.get("gate_failed", False) else 0
    except Exception as exc:
        print(json.dumps(
            {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
