# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.mel as mel


def get_filtered_attributes(connected_only, has_value):
    """
    获取当前选中节点过滤后的属性

    Args:
        connected_only (bool): 是否只显示有连接的属性
        has_value (bool): 是否只显示非默认值的属性 (即被修改过的值)

    Returns:
        dict: {
            'node': 'pSphere1',
            'type': 'transform',
            'attributes': [
                {'name': 'translateX', 'value': 10.0, 'connection': '', 'is_connected': False, 'is_non_default': True},
                ...
            ]
        }
    """
    sel = cmds.ls(sl=True)
    if not sel:
        return {}

    node = sel[0]
    node_type = cmds.nodeType(node)

    # 获取属性列表
    # keyable=True 通常是我们关心的“输入”引脚
    # 如果想看所有属性，可以去掉 keyable=True，但列表会非常长
    attrs = cmds.listAttr(node, keyable=True) or []

    # 如果列表太少，尝试获取 extra attributes
    if not attrs:
        attrs = cmds.listAttr(node, userDefined=True) or []

    result_attrs = []

    for attr in sorted(attrs):
        full_attr = f"{node}.{attr}"

        # 1. 检查连接状态
        connections = cmds.listConnections(
            full_attr, source=True, destination=True, plugs=True
        )
        is_connected = bool(connections)
        connection_str = connections[0] if is_connected else ""

        # 2. 检查数值
        try:
            val = cmds.getAttr(full_attr)
            # 格式化数值，保留2位小数显示
            if isinstance(val, float):
                val_display = round(val, 3)
            else:
                val_display = val
        except Exception:
            val_display = "<Data>"  # 某些复杂属性无法直接 getAttr

        # 3. 检查是否为默认值 (用于 "仅显示有值/非默认值" 功能)
        is_non_default = False
        try:
            # listDefault 返回一个列表，通常只有一个值
            default_val = cmds.attributeQuery(attr, node=node, listDefault=True)
            if default_val:
                # 简单比较：注意浮点数精度
                # 如果是列表(比如 vector default)，比较稍微复杂，这里做简化处理
                if isinstance(val, (int, float)) and isinstance(
                    default_val[0], (int, float)
                ):
                    if abs(val - default_val[0]) > 0.0001:
                        is_non_default = True
                elif val != default_val[0]:
                    is_non_default = True
        except Exception:
            pass  # 某些动态属性查询不到默认值

        # --- 核心过滤逻辑 ---

        # 过滤器 A: 仅显示连接
        if connected_only and not is_connected:
            continue

        # 过滤器 B: 仅显示非默认值 (忽略已连接的，因为已连接肯定重要)
        # 逻辑：如果没有连接，且又是默认值，且用户勾选了"仅显示有值"，则跳过
        if has_value and not is_connected and not is_non_default:
            continue

        result_attrs.append(
            {
                "name": attr,
                "value": val_display,
                "connection": connection_str,
                "is_connected": is_connected,
                "is_non_default": is_non_default,
            }
        )

    return {"node": node, "type": node_type, "attributes": result_attrs}


def add_nodes_to_editor(node_type):
    """
    将符合类型的节点加入当前活动的 Node Editor
    """
    # 1. 查找符合类型的节点
    nodes = cmds.ls(type=node_type)
    if not nodes:
        print(f"场景中未找到类型为 '{node_type}' 的节点。")
        return 0

    # 2. 查找当前的 Node Editor 面板
    # Maya 获取当前获得焦点的 Panel 有点 tricky，我们需要遍历查找类型
    target_panel = None

    # 尝试获取当前有焦点的面板
    current_panel = cmds.getPanel(withFocus=True)
    if current_panel and "nodeEditorPanel" in current_panel:
        target_panel = current_panel

    # 如果当前没有焦点，或者焦点不是 Node Editor，尝试找第一个可见的 Node Editor
    if not target_panel:
        all_panels = cmds.getPanel(scriptType="nodeEditorPanel")
        if all_panels:
            # 通常 visible panel 更有意义
            for p in all_panels:
                if cmds.nodeEditor(p, query=True, control=True):  # 检查控件是否存在
                    target_panel = p
                    break

    if not target_panel:
        print("未找到打开的 Node Editor 面板，请先打开一个。")
        # 也可以选择强制打开一个: mel.eval('NodeEditorWindow;')
        return 0

    # 3. 将节点添加到该编辑器
    # nodeEditor 命令使用的是 editor 名称，通常是 panel name + "NodeEditorEd"
    # 但直接传 panel name 给 nodeEditor 命令通常也行，或者获取其 editor
    editor_name = cmds.nodeEditor(target_panel, query=True, editor=True)

    # addNode 参数添加节点，layout=True 让 Maya 自动排版一下新加的节点
    cmds.nodeEditor(editor_name, edit=True, addNode=nodes)

    # 可选：让节点在视图中显示
    cmds.nodeEditor(editor_name, edit=True, frameAll=True)

    return len(nodes)
