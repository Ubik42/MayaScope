"""Explicit Maya menu and optional Shelf integration."""

from __future__ import annotations


MENU_NAME = "MayaScopeMainMenu"
SHELF_NAME = "MayaScope"


def _cmds():
    import maya.cmds as cmds  # type: ignore
    return cmds


def install_menu() -> str:
    """Install an idempotent session menu; Maya recreates it next launch on demand."""
    cmds = _cmds()
    if cmds.menu(MENU_NAME, exists=True):
        cmds.deleteUI(MENU_NAME, menu=True)
    menu = cmds.menu(MENU_NAME, label="MayaScope", parent="MayaWindow", tearOff=True)
    cmds.menuItem(
        label="打开因果场景观测台",
        annotation="打开光谱因果场景图谱工作区",
        parent=menu,
        command='from MayaScope import launch; launch.run("workspace")',
        sourceType="python",
    )
    cmds.menuItem(divider=True, parent=menu)
    cmds.menuItem(
        label="层级检查器（旧版）",
        parent=menu,
        command='from MayaScope import launch; launch.run("hierarchy")',
        sourceType="python",
    )
    cmds.menuItem(
        label="节点图助手（旧版）",
        parent=menu,
        command='from MayaScope import launch; launch.run("nodes")',
        sourceType="python",
    )
    cmds.menuItem(
        label="集合管理器（旧版）",
        parent=menu,
        command='from MayaScope import launch; launch.run("sets")',
        sourceType="python",
    )
    cmds.menuItem(divider=True, parent=menu)
    cmds.menuItem(
        label="关闭所有 MayaScope 窗口",
        parent=menu,
        command="from MayaScope import launch; launch.close_all()",
        sourceType="python",
    )
    return str(menu)


def remove_menu() -> bool:
    cmds = _cmds()
    if not cmds.menu(MENU_NAME, exists=True):
        return False
    cmds.deleteUI(MENU_NAME, menu=True)
    return True


def install_shelf(*, persist: bool = False) -> str:
    """Create one launch button; persistence is an explicit opt-in."""
    cmds = _cmds()
    shelf_parent = "ShelfLayout"
    if not cmds.shelfLayout(SHELF_NAME, exists=True):
        shelf = cmds.shelfLayout(SHELF_NAME, parent=shelf_parent)
    else:
        shelf = SHELF_NAME
    button_name = "MayaScopeOpenButton"
    if cmds.shelfButton(button_name, exists=True):
        cmds.deleteUI(button_name, control=True)
    cmds.shelfButton(
        button_name,
        parent=shelf,
        label="MS",
        annotation="MayaScope · 因果场景观测台",
        image1="commandButton.png",
        command='from MayaScope import launch; launch.run("workspace")',
        sourceType="python",
    )
    if persist:
        cmds.saveShelf(SHELF_NAME, SHELF_NAME)
    return button_name
