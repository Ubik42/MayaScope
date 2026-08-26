# -*- coding: utf-8 -*-
import maya.cmds as cmds
import hashlib
import colorsys


class NodeAnalyserLogic(object):
    # 绿色：数学/逻辑节点类型集合
    MATH_NODE_TYPES = {
        "multMatrix",
        "inverseMatrix",
        "blendMatrix",
        "composeMatrix",
        "decomposeMatrix",
        "pickMatrix",
        "aimMatrix",
        "wtAddMatrix",
        "holdMatrix",
        "passMatrix",
        "fourByFourMatrix",
        "transposeMatrix",
        "addMatrix",
        "plusMinusAverage",
        "multiplyDivide",
        "multDoubleLinear",
        "reverse",
        "distanceBetween",
        "vectorProduct",
        "angleBetween",
        "clamp",
        "setRange",
        "remapValue",
        "ramp",
        "blendColors",
        "blendTwoAttr",
        "blendWeighted",
        "condition",
        "choice",
        "quatToEuler",
        "eulerToQuat",
        "axisAngleToQuat",
        "rotationToDirection",
        "unitConversion",
    }

    def __init__(self):
        self.dynamic_classes = set()

    # =========================================================================
    # 1. 智能追踪 (Smart Trace)
    # =========================================================================
    def get_expanded_selection(self, initial_selection, smart_trace=True):
        """
        获取扩展的选择集。
        """
        valid_initial = [
            n
            for n in (cmds.ls(initial_selection, long=True) or [])
            if cmds.nodeType(n) != "objectSet"
        ]

        if not smart_trace:
            return valid_initial

        nodes_to_process = list(valid_initial)
        final_nodes = set(nodes_to_process)
        visited = set(nodes_to_process)
        queue = list(nodes_to_process)

        while queue:
            current_node = queue.pop(0)
            connections = (
                cmds.listConnections(current_node, source=True, destination=True) or []
            )

            for conn in connections:
                try:
                    full_conn = cmds.ls(conn, long=True)[0]
                except Exception:
                    full_conn = conn

                if full_conn in visited:
                    continue

                try:
                    node_type = cmds.nodeType(full_conn)
                except Exception:
                    continue

                # 追踪数学节点
                if node_type in self.MATH_NODE_TYPES:
                    visited.add(full_conn)
                    final_nodes.add(full_conn)
                    queue.append(full_conn)

        return list(final_nodes)

    # =========================================================================
    # 2. Mermaid 代码生成
    # =========================================================================
    def generate_mermaid(self, nodes, show_in=True, show_out=True):
        """
        生成 Mermaid 代码。
        改进点：
        1. 使用 'basis' 曲线，实现平滑流畅的连线（Notion 风格）。
        2. 修正配色：Transform(黄), Constraint(红), Joint(蓝), Math(绿)。
        """
        self.dynamic_classes = set()  # 重置动态样式

        # [Config]
        # themeVariables: 调整基础颜色适应暗色背景
        # curve: basis (平滑曲线) 或 monotoneX (水平优先平滑)。basis 最接近 Notion 默认的优雅感。
        lines = [
            "%%{init: {'theme': 'base', 'themeVariables': { 'darkMode': true, 'primaryColor': '#333', 'lineColor': '#ccc', 'mainBkg': '#1e1e1e'}, 'flowchart': {'curve': 'basis', 'nodeSpacing': 40, 'rankSpacing': 60}}}%%",
            "graph LR",
        ]

        # [Styles] 配色方案
        # Transform: 黄色
        lines.append(
            "    classDef transform fill:#F1C40F,stroke:#D4AC0D,stroke-width:2px,color:#222;"
        )
        # Joint: 蓝色
        lines.append(
            "    classDef joint fill:#3498DB,stroke:#2980B9,stroke-width:2px,color:#fff;"
        )
        # Constraint: 红色
        lines.append(
            "    classDef constraint fill:#E74C3C,stroke:#C0392B,stroke-width:2px,color:#fff;"
        )
        # Math/Matrix: 绿色
        lines.append(
            "    classDef math fill:#2ECC71,stroke:#27AE60,stroke-width:1px,color:#fff;"
        )
        lines.append(
            "    classDef matrix fill:#2ECC71,stroke:#27AE60,stroke-width:1px,color:#fff;"
        )

        # Controller (Smart Detect): 橙色/金色
        lines.append(
            "    classDef controller fill:#E67E22,stroke:#D35400,stroke-width:2px,color:#fff;"
        )

        # Router (路由点): 深灰
        lines.append(
            "    classDef router fill:#333,stroke:#666,stroke-width:1px,color:#aaa,rx:2,ry:2,font-size:8pt;"
        )

        mm_nodes_added = set()
        all_raw_edges = []
        edge_counter = 0

        # --- Helper: 节点添加与样式分配 ---
        def add_node_def(fullname):
            nid = self._mm_id(fullname)
            if nid not in mm_nodes_added:
                short = fullname.split("|")[-1]
                typ = self._get_smart_type(fullname)

                # 样式分配
                style_class = "transform"  # 默认黄

                if typ == "joint":
                    style_class = "joint"  # 蓝
                elif "Constraint" in typ:
                    style_class = "constraint"  # 红
                elif typ == "controller":
                    style_class = "controller"  # 橙
                elif typ in self.MATH_NODE_TYPES:
                    if "Matrix" in typ:
                        style_class = "matrix"  # 绿
                    else:
                        style_class = "math"  # 绿
                elif typ == "transform":
                    style_class = "transform"  # 黄
                else:
                    style_class = self._get_random_color_class(typ, lines)

                safe_short = short.replace('"', "'")
                # 颜色为浅色(Transform)时，文字可能需要深色，但这里统一CSS处理了
                lines.append(
                    f'    {nid}["{safe_short}<br><small>({typ})</small>"]:::{style_class}'
                )
                mm_nodes_added.add(nid)
            return nid

        # --- 收集节点和边 ---
        for node in nodes:
            nid = add_node_def(node)

            if show_in:
                ins = self._get_connections(node, source=True, destination=False)
                for x in ins:
                    oid = add_node_def(x["other_node_full"])
                    all_raw_edges.append(
                        {
                            "idx": edge_counter,
                            "src_id": oid,
                            "dst_id": nid,
                            "src_attr": x["other_attr"],
                            "dst_attr": x["my_attr"],
                        }
                    )
                    edge_counter += 1

            if show_out:
                outs = self._get_connections(node, source=False, destination=True)
                for x in outs:
                    oid = add_node_def(x["other_node_full"])
                    all_raw_edges.append(
                        {
                            "idx": edge_counter,
                            "src_id": nid,
                            "dst_id": oid,
                            "src_attr": x["my_attr"],
                            "dst_attr": x["other_attr"],
                        }
                    )
                    edge_counter += 1

        # --- 连线聚合 (Router & Bundling) ---
        processed_indices = set()
        final_edge_lines = set()

        # 1. 路由聚合 (Router)
        router_map = {}
        for edge in all_raw_edges:
            key = (edge["src_id"], edge["src_attr"], edge["dst_attr"])
            if key not in router_map:
                router_map[key] = []
            router_map[key].append(edge)

        for (src_id, src_attr, dst_attr), edges in router_map.items():
            unique_targets = set(e["dst_id"] for e in edges)

            if len(unique_targets) > 1:
                router_hash = hashlib.md5(
                    f"{src_id}{src_attr}{dst_attr}".encode()
                ).hexdigest()[:6]
                router_id = f"r_{router_hash}"
                router_label = f"{src_attr} → {dst_attr}".replace('"', "'")

                lines.append(f'    {router_id}(["{router_label}"]):::router')
                # 路由连接使用实线
                final_edge_lines.add(f"    {src_id} --- {router_id}")
                for dst_id in unique_targets:
                    final_edge_lines.add(f"    {router_id} --> {dst_id}")

                for e in edges:
                    processed_indices.add(e["idx"])

        # 2. 直连聚合 (Direct Bundling)
        direct_map = {}
        for edge in all_raw_edges:
            if edge["idx"] in processed_indices:
                continue
            key = (edge["src_id"], edge["dst_id"])
            if key not in direct_map:
                direct_map[key] = []
            direct_map[key].append(edge)

        for (src_id, dst_id), edges in direct_map.items():
            attr_pairs = {}
            for e in edges:
                if e["src_attr"] not in attr_pairs:
                    attr_pairs[e["src_attr"]] = []
                if e["dst_attr"] not in attr_pairs[e["src_attr"]]:
                    attr_pairs[e["src_attr"]].append(e["dst_attr"])

            label_parts = []
            for s, d_list in attr_pairs.items():
                d_str = ", ".join(d_list)
                label_parts.append(f"{s} → {d_str}")

            final_label = "<br>".join(label_parts).replace('"', "'")
            # 标准连线
            final_edge_lines.add(f'    {src_id} -- "{final_label}" --> {dst_id}')

        lines.extend(sorted(list(final_edge_lines)))

        return "\n".join(lines)

    # =========================================================================
    # 4. Markdown 生成
    # =========================================================================
    def generate_markdown(self, nodes, is_smart_active=True):
        nodes = sorted(list(nodes))
        md = ["# Node Connections", ""]
        if is_smart_active:
            md.append("> 🌀 Smart Trace Active\n")

        for node in nodes:
            typ = self._get_smart_type(node)
            short = node.split("|")[-1]
            md.append(f"### `{short}` ({typ})")

            ins = self._get_connections(node, source=True, destination=False)
            outs = self._get_connections(node, source=False, destination=True)
            ins.sort(key=lambda x: x["my_attr"])
            outs.sort(key=lambda x: x["my_attr"])

            if not ins and not outs:
                md.append("> *No connections.*\n")
                continue

            md.append("| Dir | My Attr | Connected Node | Other Attr |")
            md.append("|:---:|:---|:---|:---|")
            for x in ins:
                md.append(
                    f"| ← | `{x['my_attr']}` | `{x['other_node']}` | `{x['other_attr']}` |"
                )
            for x in outs:
                md.append(
                    f"| → | `{x['my_attr']}` | `{x['other_node']}` | `{x['other_attr']}` |"
                )
            md.append("")
        return "\n".join(md)

    # =========================================================================
    # Helpers
    # =========================================================================
    def _mm_id(self, name):
        return "n" + hashlib.md5(name.encode()).hexdigest()[:6]

    def _get_smart_type(self, fullname):
        try:
            base_type = cmds.nodeType(fullname)
            if base_type == "transform":
                shapes = cmds.listRelatives(fullname, shapes=True)
                if shapes:
                    return "controller"
            return base_type
        except Exception:
            return "unknown"

    def _get_connections(self, node, source=True, destination=True):
        """
        获取连接详情，并过滤自连接。
        """
        conns = (
            cmds.listConnections(
                node, s=source, d=destination, plugs=True, connections=True
            )
            or []
        )
        results = []
        for i in range(0, len(conns), 2):
            my_plug_str = conns[i]
            other_plug_str = conns[i + 1]
            _, _, my_attr = my_plug_str.partition(".")
            other_node_part, _, other_attr = other_plug_str.partition(".")

            full_other_node = other_node_part
            if cmds.objExists(other_node_part):
                ls_res = cmds.ls(other_node_part, long=True)
                if ls_res:
                    full_other_node = ls_res[0]

            # --- 自环过滤 (Self-Constraint Fix) ---
            # 1. 检查全路径是否相同
            if full_other_node == node:
                continue
            # 2. 检查短名是否相同 (防御性)
            if full_other_node.split("|")[-1] == node.split("|")[-1]:
                continue
            # ------------------------------------

            try:
                if cmds.nodeType(full_other_node) == "objectSet":
                    continue
            except Exception:
                pass

            short_other_node = full_other_node.split("|")[-1]
            results.append(
                {
                    "my_attr": my_attr,
                    "other_node": short_other_node,
                    "other_node_full": full_other_node,
                    "other_attr": other_attr,
                }
            )
        return results

    def _get_random_color_class(self, node_type, lines_list):
        class_name = f"type_{node_type}"
        if class_name not in self.dynamic_classes:
            hash_val = int(hashlib.md5(node_type.encode()).hexdigest(), 16)
            hue = hash_val % 360
            # 随机色使用稍微中性的亮度，避免看不清文字
            r, g, b = colorsys.hls_to_rgb(hue / 360.0, 0.4, 0.5)
            hex_color = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
            lines_list.append(
                f"    classDef {class_name} fill:{hex_color},stroke:#fff,color:#fff;"
            )
            self.dynamic_classes.add(class_name)
        return class_name

    # =========================================================================
    # 5. External Web Rendering
    # =========================================================================
    def generate_mermaid_html(self, mermaid_text):
        """
        Generate the HTML content for the Mermaid diagram.
        """
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mermaid Graph Viewer</title>
    <style>
        body {{ background-color: #1e1e1e; margin: 0; padding: 20px; color: #d4d4d4; font-family: sans-serif; }}
        .mermaid {{ background-color: transparent; }}
    </style>
</head>
<body>
    <h2>Mermaid Graph Viewer</h2>
    <div class="mermaid">
{mermaid_text}
    </div>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'base',
            themeVariables: {{
                darkMode: true,
                primaryColor: '#333',
                lineColor: '#aaa',
                mainBkg: '#1e1e1e',
                fontFamily: 'Segoe UI'
            }}
        }});
    </script>
</body>
</html>
"""
        return html_content
