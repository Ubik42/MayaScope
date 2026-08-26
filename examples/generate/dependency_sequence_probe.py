"""Regenerate the self-authored Maya 2025 dependency sequence fixture."""

from __future__ import annotations

from pathlib import Path

import maya.standalone


ROOT = Path(__file__).resolve().parents[2]
SCENE = ROOT / "examples" / "dependency-sequence-probe.ma"
ASSETS = ROOT / "examples" / "assets"

maya.standalone.initialize(name="python")
from maya import cmds

cmds.workspace(str(ROOT), openWorkspace=True)
cmds.file(new=True, force=True)
cmds.playbackOptions(minTime=1, maxTime=3, animationStartTime=1, animationEndTime=3)

plate = cmds.shadingNode("file", asTexture=True, name="plateSequence")
cmds.setAttr(plate + ".useFrameExtension", True)
cmds.setAttr(
    plate + ".fileTextureName",
    str(ASSETS / "mayascope_plate.0001.exr").replace("\\", "/"),
    type="string",
)

udim = cmds.shadingNode("file", asTexture=True, name="heroUdim")
cmds.setAttr(udim + ".uvTilingMode", 3)
cmds.setAttr(
    udim + ".fileTextureName",
    "examples/assets/mayascope_hero.<UDIM>.exr",
    type="string",
)

cmds.file(rename=str(SCENE))
cmds.file(save=True, force=True, type="mayaAscii")
maya.standalone.uninitialize()
