"""Generate three signed Scene Clinic receipts and one verified project bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from MayaScope.audit import _atomic_json
from MayaScope.project_audit import build_project_audit, verify_project_audit


SCENES = (
    ("镜头010_干净基线.ma", False, ()),
    (
        "镜头020_缓存缺失.ma",
        True,
        (
            {
                "id": "missing-cache:shot020",
                "rule_id": "missing-external-files",
                "title": "发布缓存文件缺失",
                "description": "镜头引用的 Alembic 缓存不存在，发布必须阻断。",
                "severity": "error",
                "affected_node_ids": ["cacheNode_shot020"],
                "atomic_subjects": [
                    {"id": "D:/项目/cache/shot020/hero.abc", "node_id": "cacheNode_shot020"}
                ],
            },
        ),
    ),
    (
        "镜头030_插件登记漂移.ma",
        False,
        (
            {
                "id": "plugin-drift:shot030",
                "rule_id": "unknown-plugin-registry",
                "title": "插件登记与农场基线不同",
                "description": "场景仍可打开，但需要 TD 在提交农场前确认插件版本。",
                "severity": "warning",
                "affected_node_ids": [],
                "atomic_subjects": [{"id": "studioDeformer:4.7", "node_id": ""}],
            },
        ),
    ),
)


def _scene_text(name: str) -> str:
    node = Path(name).stem.replace("-", "_")
    return (
        "// MayaScope 自生成项目门禁演示场景\n"
        "// Maya ASCII 2025 scene\n"
        "requires maya \"2025\";\n"
        "currentUnit -l centimeter -a degree -t film;\n"
        'createNode transform -n "%s";\n' % node
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture(output: Path) -> dict:
    root = output.expanduser().resolve()
    scene_root = root / "scenes"
    report_root = root / "reports"
    scene_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    reports = []
    materials = []
    for index, (name, gate_failed, issues) in enumerate(SCENES, 1):
        scene = scene_root / name
        scene.write_text(_scene_text(name), encoding="utf-8", newline="\n")
        report = report_root / ("scene-%02d.audit.json" % index)
        _atomic_json(
            report,
            {
                "format": "mayascope.clinic-audit",
                "schema_version": 2,
                "ok": True,
                "gate_failed": gate_failed,
                "audit_exit_code": 2 if gate_failed else 0,
                "source_scene": str(scene),
                "source_sha256": _sha256(scene),
                "profile": "publish",
                "config_fingerprint": "mayascope-project-gate-showcase-v1",
                "maya": {"version": "2025", "api": 20250303},
                "snapshot": {"scene_lifecycle": {"workspace_root": str(root)}},
                "issues": list(issues),
            },
        )
        reports.append(report)
        materials.append(
            {
                "scene": str(scene),
                "scene_sha256": _sha256(scene),
                "report": str(report),
                "expected": "阻断" if gate_failed else "通过",
            }
        )
    bundle = root / "project-audit-showcase.json"
    built = build_project_audit(reports, bundle)
    verified = verify_project_audit(bundle)
    manifest = root / "fixture-manifest.json"
    _atomic_json(
        manifest,
        {
            "format": "mayascope.project-gate-fixture",
            "schema_version": 1,
            "source": "MayaScope 确定性自生成",
            "license": "项目内部开发、测试与作品展示",
            "maya": "2025",
            "generator": "examples/generate/project_gate_fixture.py",
            "project_bundle": str(bundle),
            "project_sha256": verified["project_sha256"],
            "materials": materials,
            "expected": {
                "scene_count": 3,
                "passed_scene_count": 2,
                "blocked_scene_count": 1,
                "atomic_finding_count": 2,
            },
        },
    )
    return {
        "bundle": str(bundle),
        "manifest": str(manifest),
        "project_sha256": built["project_sha256"],
        "summary": built["summary"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-project-gate-fixture")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_fixture(args.output)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
