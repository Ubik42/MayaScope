# -*- coding: utf-8 -*-
import maya.cmds as cmds


def get_scene_nodes_info():
    """
    获取场景中所有节点的信息 (不局限于 C++ 节点)。
    包含: Name, Node Type, Belong to Sets.

    Returns:
        list of dict: [{'name': 'pSphere1', 'type': 'transform', 'sets': ['set1']}, ...]
    """
    data_list = []

    # --- 1. 性能优化：预先构建 "节点 -> 集合列表" 的映射字典 ---
    # 避免在后续循环中对成千上万个节点逐个调用 cmds.listSets (这会导致极严重的卡顿)
    node_to_sets_map = {}

    # 获取场景中所有的 Set (包括 objectSet, shadingEngine 等)
    all_sets = cmds.ls(type="objectSet") or []

    for set_node in all_sets:
        # 获取集合成员
        # query=True 返回成员列表
        members = cmds.sets(set_node, query=True) or []

        for member in members:
            # 处理组件 (Component) 情况
            # 例如集合中包含 "pSphere1.vtx[0:10]"，我们需要将其归纳为 "pSphere1"
            # Maya 节点名中不会有点号 (Namespaces用冒号)，只有组件有点号
            node_name = member.split(".")[0]

            if node_name not in node_to_sets_map:
                node_to_sets_map[node_name] = []

            # 记录该节点属于当前 set_node
            # 避免重复 (例如多个点都在同一个集里)
            if set_node not in node_to_sets_map[node_name]:
                node_to_sets_map[node_name].append(set_node)

    # --- 2. 获取场景所有节点 ---
    # dependencyNodes=True: 获取所有节点 (包括 DAG, Shader, Utility 等)
    # 如果只想看大纲视图里的物体，可以将 dependencyNodes=True 改为 dag=True
    all_nodes = cmds.ls(dependencyNodes=True) or []

    # (可选) 排除列表：过滤掉 Maya 默认生成的且不可删除的节点，减少干扰
    # default_nodes = set(["time1", "sequenceManager1", "hardwareRenderingGlobals", "renderPartition", "renderGlobalsList1"])

    for node in all_nodes:
        # if node in default_nodes: continue # 启用此行可过滤默认节点

        # 即使节点不在任何 Set 里，也能快速查到 []
        belong_sets = node_to_sets_map.get(node, [])
        belong_sets.sort()  # 排序集合名，美观

        data_list.append(
            {"name": node, "type": cmds.nodeType(node), "sets": belong_sets}
        )

    # --- 3. 排序 ---
    # 优先按类型排序，其次按名字排序 (符合 Notion 数据库常见视图)
    data_list.sort(key=lambda x: (x["type"], x["name"]))

    return data_list
