"""Generate a deterministic dense Maya ASCII scene for Atlas scale replay."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_scene(output: Path, *, node_count: int = 1200, fanout: int = 4) -> Dict[str, object]:
    """Write a redistributable high-coupling fixture without requiring Maya."""
    output = Path(output).expanduser().resolve()
    if node_count < 300:
        raise ValueError("Atlas scale fixture requires at least 300 nodes")
    if fanout <= 0 or fanout >= node_count:
        raise ValueError("fanout must be between 1 and node_count - 1")
    lines = [
        "//Maya ASCII 2025 scene",
        'requires maya "2025";',
        'currentUnit -l centimeter -a degree -t film;',
        'fileInfo "application" "MayaScope Atlas Scale Fixture";',
        'fileInfo "license" "CC0-1.0 / deterministic self-generated fixture";',
    ]
    names = tuple("atlasProbe_%05d" % index for index in range(node_count))
    for name in names:
        lines.extend(
            (
                'createNode network -n "%s";' % name,
                '    addAttr -ci true -sn "ao" -ln "atlasOut" -at "double";',
                '    addAttr -ci true -sn "ai" -ln "atlasIn" -at "double" -m;',
            )
        )
    for source, source_name in enumerate(names):
        for offset in range(1, fanout + 1):
            target = (source + offset) % node_count
            lines.append(
                'connectAttr "%s.atlasOut" "%s.atlasIn[%d]";'
                % (source_name, names[target], offset - 1)
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(output)
    return {
        "format": "mayascope.atlas-scale-fixture",
        "schema_version": 1,
        "scene": str(output),
        "sha256": _sha256(output),
        "nodes": node_count,
        "connections": node_count * fanout,
        "fanout": fanout,
        "source": "MayaScope deterministic generator",
        "license": "CC0-1.0",
        "expected": {
            "atlas_node_budget": 240,
            "atlas_edge_budget": 960,
            "folded_focus": names[-1],
        },
    }


__all__ = ["build_scene"]
