"""Build a real Maya 2025 showcase scene for MayaScope demonstrations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output: Path) -> Path:
    import maya.standalone  # type: ignore
    try:
        maya.standalone.initialize(name="python")
    except RuntimeError:
        # Reuse an already initialized Maya host when called interactively.
        pass
    import maya.cmds as cmds  # type: ignore

    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    reference_scene = output / "mayascope_showcase_prop.ma"
    main_scene = output / "mayascope_showcase.ma"

    cmds.file(new=True, force=True)
    prop_root = cmds.createNode("transform", name="REF_PROP_GRP")
    prop_mesh = cmds.polyCube(name="diagnostic_prop_GEO", width=2.5, height=1.0, depth=1.5)[0]
    cmds.parent(prop_mesh, prop_root)
    cmds.file(rename=str(reference_scene))
    cmds.file(save=True, type="mayaAscii", force=True)

    cmds.file(new=True, force=True)
    hero = cmds.createNode("transform", name="HERO_RIG_GRP")
    sim = cmds.createNode("transform", name="CROWD_SIM_GRP")
    lighting = cmds.createNode("transform", name="LIGHTING_GRP")
    poison = cmds.createNode("transform", name="poison_GRP")

    mesh = cmds.polyPlane(name="hero_deform_GEO", subdivisionsX=32, subdivisionsY=32)[0]
    cmds.parent(mesh, hero)
    created = cmds.nonLinear(mesh, type="bend", name="showcase_bend")
    bend = next(node for node in created if cmds.nodeType(node) == "nonLinear")
    cmds.setAttr(bend + ".curvature", 0.8)

    driver = cmds.createNode("multiplyDivide", name="spectral_fanout_driver")
    cmds.setAttr(driver + ".input1X", 2.0)
    cmds.setAttr(driver + ".input2X", 1.5)
    for index in range(72):
        probe = cmds.createNode("transform", name="fanout_probe_%02d" % index, parent=sim)
        cmds.connectAttr(driver + ".outputX", probe + ".translateX")
    cmds.connectAttr(driver + ".outputX", bend + ".curvature", force=True)

    cmds.createNode("plusMinusAverage", name="orphan_math_residue")
    cmds.createNode("animCurveTL", name="orphan_translate_curve")
    cmds.scriptNode(
        name="publish_runtime_payload",
        scriptType=1,
        beforeScript="// MayaScope showcase: intentionally inert runtime script node",
        sourceType="mel",
    )
    payload = cmds.createNode("network", name="legacy_payload_marker")
    cmds.addAttr(poison, longName="legacyPayload", attributeType="message")
    cmds.connectAttr(payload + ".message", poison + ".legacyPayload")
    cmds.createNode("pointLight", name="showcase_keyLightShape", parent=lighting)

    cmds.namespace(add="show")
    cmds.namespace(add="show:seq")
    cmds.namespace(add="show:seq:shot")
    cmds.namespace(add="show:seq:shot:asset")
    cmds.createNode("transform", name="show:seq:shot:asset:deep_namespace_GRP")

    cmds.file(
        str(reference_scene),
        reference=True,
        namespace="prop",
        referenceNode="propRN",
    )
    cmds.file(
        str(reference_scene),
        reference=True,
        namespace="setdress",
        referenceNode="setdressRN",
    )
    cmds.file(unloadReference="setdressRN")
    cmds.select(bend, replace=True)
    cmds.file(rename=str(main_scene))
    cmds.file(save=True, type="mayaAscii", force=True)

    metadata = {
        "format": "mayascope.showcase",
        "schema_version": 1,
        "maya_version": str(cmds.about(version=True)),
        "scene": main_scene.name,
        "scene_sha256": _sha256(main_scene),
        "reference": reference_scene.name,
        "reference_sha256": _sha256(reference_scene),
        "focus_node": bend,
        "expected_signals": [
            "high-fanout",
            "orphan-utilities",
            "orphan-animation-curves",
            "runtime-script-nodes",
            "namespace-depth",
            "unloaded-references",
        ],
        "workflows": [
            "Capture Scene and inspect Scene Clinic incidents",
            "Focus showcase_bend and run Root Cause Lens",
            "Profile Frame, then drag a Trace Horizon range",
            "Run TEST FOCUS for a state-restored counterfactual",
            "Archive, modify a probe, recapture, and inspect Delta Field",
            "Use a disposable copy for Failure Prism demonstrations",
        ],
    }
    metadata_path = output / "mayascope_showcase.json"
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(metadata_path)
    return metadata_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    metadata = build(args.output)
    print(str(metadata))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
