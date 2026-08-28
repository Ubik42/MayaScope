"""Build a deterministic Maya 2025 DG chain for Root Cause Lens demos."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_scene(cmds_module=None, save_to=None) -> dict:
    """Create one fan-out rigging graph and optionally save it as Maya ASCII."""
    if cmds_module is None:
        from maya import cmds as cmds_module

    cmds = cmds_module
    cmds.file(new=True, force=True)
    root = cmds.createNode("transform", name="heroRoot")
    matrix = cmds.createNode("multMatrix", name="globalMatrix")
    decompose = cmds.createNode("decomposeMatrix", name="spaceDecompose")
    driver = cmds.createNode("multiplyDivide", name="faceDriver")
    focus = cmds.createNode("transform", name="heroFace_CTRL")
    secondary = cmds.createNode("transform", name="secondaryFace_CTRL")
    cmds.connectAttr(root + ".worldMatrix[0]", matrix + ".matrixIn[0]", force=True)
    cmds.connectAttr(matrix + ".matrixSum", decompose + ".inputMatrix", force=True)
    cmds.connectAttr(decompose + ".outputTranslateX", driver + ".input1X", force=True)
    cmds.setAttr(driver + ".input2X", 1.25)
    cmds.connectAttr(driver + ".outputX", focus + ".translateX", force=True)
    cmds.connectAttr(driver + ".outputX", secondary + ".translateX", force=True)
    cmds.select(focus, replace=True)
    output = ""
    if save_to:
        path = Path(save_to).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        cmds.file(rename=str(path))
        cmds.file(save=True, type="mayaAscii", force=True)
        output = str(path)
    return {
        "root": root,
        "matrix": matrix,
        "decompose": decompose,
        "driver": driver,
        "focus": focus,
        "secondary": secondary,
        "saved_scene": output,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-lens-chain-scene")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    result = build_scene(save_to=args.output)
    print("已生成根因透镜场景：%s" % result["saved_scene"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_scene"]
