# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.mel as mel
from MayaScope.qt_compat import QtWidgets, QtCore, QtGui
import hashlib
import colorsys
from collections import deque


def get_maya_window():
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == "MayaWindow":
            return widget
    return None


class NodeEditorAssistant(QtWidgets.QDialog):
    MATH_NODE_TYPES = {
        'multMatrix', 'inverseMatrix', 'blendMatrix', 'composeMatrix',
        'decomposeMatrix', 'pickMatrix', 'aimMatrix', 'wtAddMatrix',
        'holdMatrix', 'passMatrix', 'fourByFourMatrix', 'transposeMatrix',
        'addMatrix',
        'plusMinusAverage', 'multiplyDivide', 'multDoubleLinear', 'reverse',
        'distanceBetween', 'vectorProduct', 'angleBetween',
        'clamp', 'setRange', 'remapValue', 'ramp',
        'blendColors', 'blendTwoAttr', 'blendWeighted', 'condition', 'choice',
        'quatToEuler', 'eulerToQuat', 'axisAngleToQuat', 'rotationToDirection',
        'unitConversion'
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Node Graph Assistant 2025 (Router Logic)")
        self.resize(900, 850)
        self.setWindowFlags(QtCore.Qt.Window)

        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: #cccccc; }
            QPushButton { 
                background-color: #5285a6; color: white; border-radius: 4px; padding: 8px; font-size: 13px;
            }
            QPushButton:hover { background-color: #639ubc; }
            QPushButton:pressed { background-color: #406882; }
            QTextEdit { 
                background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; border: 1px solid #3e3e3e; font-size: 12px; white-space: pre;
            }
            QGroupBox { border: 1px solid #444; margin-top: 6px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
            QCheckBox { spacing: 8px; }
        """)

        self.init_ui()

    def init_ui(self):
        main = QtWidgets.QVBoxLayout(self)
        main.setSpacing(15)

        # 1. Graph Operations
        grp_op = QtWidgets.QGroupBox("Graph Operations")
        lyt_op = QtWidgets.QVBoxLayout(grp_op)

        btn_iso = QtWidgets.QPushButton("Isolate Selected (Reset)")
        btn_iso.clicked.connect(self.on_isolate_clicked)
        btn_iso.setStyleSheet("background-color: #d65d5d; font-weight: bold;")

        lyt_add = QtWidgets.QHBoxLayout()
        btn_add_in = QtWidgets.QPushButton("Add Inputs (<)")
        btn_add_in.clicked.connect(lambda: self.on_expand_graph(True, False))
        btn_add_out = QtWidgets.QPushButton("Add Outputs (>)")
        btn_add_out.clicked.connect(lambda: self.on_expand_graph(False, True))
        lyt_add.addWidget(btn_add_in)
        lyt_add.addWidget(btn_add_out)

        lyt_rem = QtWidgets.QHBoxLayout()
        btn_rem_in = QtWidgets.QPushButton("Remove Inputs (<)")
        btn_rem_in.clicked.connect(lambda: self.on_reduce_graph(True, False))
        btn_rem_out = QtWidgets.QPushButton("Remove Outputs (>)")
        btn_rem_out.clicked.connect(lambda: self.on_reduce_graph(False, True))
        lyt_rem.addWidget(btn_rem_in)
        lyt_rem.addWidget(btn_rem_out)

        btn_cls = QtWidgets.QPushButton("Remove All 'objectSet' Nodes")
        btn_cls.clicked.connect(self.on_remove_object_sets)
        btn_cls.setStyleSheet("background-color: #7d5e28;")

        lyt_op.addWidget(btn_iso)
        lyt_op.addLayout(lyt_add)
        lyt_op.addLayout(lyt_rem)
        lyt_op.addWidget(btn_cls)
        main.addWidget(grp_op)

        # 2. Analysis
        grp_an = QtWidgets.QGroupBox("Analysis")
        lyt_an = QtWidgets.QVBoxLayout(grp_an)

        self.chk_smart_trace = QtWidgets.QCheckBox("🌀 Smart Trace: Recursively Include Math/Matrix Network")
        self.chk_smart_trace.setChecked(True)
        self.chk_smart_trace.setStyleSheet("color: #4db8ff; font-weight: bold;")

        btn_md = QtWidgets.QPushButton("Analyze to Markdown")
        btn_md.clicked.connect(self.on_analyze_clicked)

        lyt_mm = QtWidgets.QHBoxLayout()
        self.chk_in = QtWidgets.QCheckBox("Inputs")
        self.chk_in.setChecked(False)
        self.chk_out = QtWidgets.QCheckBox("Outputs")
        self.chk_out.setChecked(True)
        btn_mm = QtWidgets.QPushButton("Mermaid Graph")
        btn_mm.clicked.connect(self.on_mermaid_clicked)

        lyt_mm.addWidget(self.chk_in)
        lyt_mm.addWidget(self.chk_out)
        lyt_mm.addWidget(btn_mm)

        lyt_an.addWidget(self.chk_smart_trace)
        lyt_an.addWidget(btn_md)
        lyt_an.addLayout(lyt_mm)
        main.addWidget(grp_an)

        # 3. Output
        grp_out = QtWidgets.QGroupBox("Output")
        lyt_out = QtWidgets.QVBoxLayout(grp_out)
        self.text_edit = QtWidgets.QTextEdit()
        self.btn_copy = QtWidgets.QPushButton("Copy to Clipboard")
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        lyt_out.addWidget(self.text_edit)
        lyt_out.addWidget(self.btn_copy)
        main.addWidget(grp_out)

    # --- Smart Trace Logic ---
    def get_expanded_selection(self, initial_selection):
        if not self.chk_smart_trace.isChecked():
            return cmds.ls(initial_selection, long=True) or []

        nodes_to_process = list(cmds.ls(initial_selection, long=True) or [])
        final_nodes = set(nodes_to_process)
        visited = set(nodes_to_process)
        queue = deque(nodes_to_process)

        while queue:
            current_node = queue.popleft()
            connections = cmds.listConnections(current_node, source=True, destination=True) or []

            for conn in connections:
                matches = cmds.ls(conn, long=True) or []
                full_conn = matches[0] if matches else conn

                if full_conn in visited:
                    continue

                node_type = cmds.nodeType(full_conn)
                if node_type in self.MATH_NODE_TYPES:
                    visited.add(full_conn)
                    final_nodes.add(full_conn)
                    queue.append(full_conn)

        return list(final_nodes)

    # =========================================================================
    # Mermaid Logic (Router Node Implementation)
    # =========================================================================
    def on_mermaid_clicked(self):
        raw_sel = cmds.ls(sl=1)
        if not raw_sel: return

        nodes_to_analyze = self.get_expanded_selection(raw_sel)

        # 1. 样式定义
        self.mm_lines = ["graph LR"]
        self.mm_lines.append("    classDef transform fill:#333,stroke:#fff,stroke-width:2px,color:#fff;")
        self.mm_lines.append("    classDef joint fill:#2b6a99,stroke:#fff,stroke-width:2px,color:#fff;")
        self.mm_lines.append("    classDef matrix fill:#483C6C,stroke:#a6a,stroke-width:1px,color:#fff;")
        self.mm_lines.append("    classDef math fill:#2D5A4C,stroke:#4ea,stroke-width:1px,color:#fff;")
        self.mm_lines.append("    classDef constraint fill:#8B4513,stroke:#fa0,stroke-width:1px,color:#fff;")
        # 【新增】路由节点样式：圆角矩形，深灰背景，浅字，像一个接线端子
        self.mm_lines.append(
            "    classDef router fill:#222,stroke:#666,stroke-width:1px,color:#ccc,rx:5,ry:5,font-size:9pt;")

        self.mm_nodes = set()
        self.dynamic_classes = set()

        # 临时存储所有原始连线数据
        raw_edges = []

        show_in = self.chk_in.isChecked()
        show_out = self.chk_out.isChecked()

        # 2. 收集数据 (Nodes & Raw Edges)
        for node in nodes_to_analyze:
            self.mm_add_node(node)
            nid = self.mm_id(node)

            # Input Connections
            if show_in:
                ins = self.get_connections(node, source=True, destination=False)
                for x in ins:
                    oid = self.mm_id(x['other_node_full'])
                    self.mm_add_node(x['other_node_full'])
                    raw_edges.append({
                        'src_id': oid, 'dst_id': nid,
                        'src_attr': x['other_attr'], 'dst_attr': x['my_attr']
                    })

            # Output Connections
            if show_out:
                outs = self.get_connections(node, source=False, destination=True)
                for x in outs:
                    oid = self.mm_id(x['other_node_full'])
                    self.mm_add_node(x['other_node_full'])
                    raw_edges.append({
                        'src_id': nid, 'dst_id': oid,
                        'src_attr': x['my_attr'], 'dst_attr': x['other_attr']
                    })

        # --- 3. 智能路由分组 ---

        # 分组 Key: (SourceNodeID, SourceAttr, DestAttr)
        # 只有当源属性和目标属性都完全一致，但连接了不同的目标节点时，才合并。
        # 这样就能生成 "output -> inputValue" 这样的中间节点。
        router_groups = {}

        for edge in raw_edges:
            key = (edge['src_id'], edge['src_attr'], edge['dst_attr'])
            if key not in router_groups: router_groups[key] = []
            router_groups[key].append(edge['dst_id'])

        processed_lines = set()

        for (src_id, src_attr, dst_attr), targets in router_groups.items():
            targets = list(set(targets))  # 去重目标节点

            if len(targets) > 1:
                # === Case A: 需要路由节点 (1对多) ===
                # 生成唯一的 Router ID
                router_hash = hashlib.md5(f"{src_id}{src_attr}{dst_attr}".encode()).hexdigest()[:6]
                router_id = f"r_{router_hash}"

                # 标签: "output → inputValue"
                router_label = f"{src_attr} → {dst_attr}".replace('"', "'")

                # 定义 Router 节点
                self.mm_lines.append(f'    {router_id}(["{router_label}"]):::router')

                # 1. 源 -> Router (实线，无标签)
                line1 = f'    {src_id} --- {router_id}'
                if line1 not in processed_lines:
                    self.mm_lines.append(line1)
                    processed_lines.add(line1)

                # 2. Router -> 多个目标 (带箭头，无标签)
                for dst_id in targets:
                    line2 = f'    {router_id} --> {dst_id}'
                    if line2 not in processed_lines:
                        self.mm_lines.append(line2)
                        processed_lines.add(line2)

            else:
                # === Case B: 不需要路由 (1对1) ===
                # 这里我们还是要做一下常规合并 (Attribute Bundling)
                # 即 A -> B 有多条不同属性的连线
                # 但由于我们上面的循环是按属性拆开的，这里直接画线
                # 为了美观，我们先把单线存起来，最后再按 (Src, Dst) 合并一次标签
                # (这部分逻辑稍微复杂点，为了简单且符合当前需求，直接画单线)

                dst_id = targets[0]
                # 检查是否还有其他属性也连向这个 dst_id，如果有，合并显示
                # 为了简单起见，这里直接画出带标签的线
                label = f"{src_attr} → {dst_attr}".replace('"', "'")
                line = f'    {src_id} -- "{label}" --> {dst_id}'

                # 优化：稍后会有去重，但为了防止同一对节点出现多条线，
                # 最好还是在这里做个简单的收集。
                # 鉴于上面的 router 逻辑已经很强了，这里直接输出即可。
                if line not in processed_lines:
                    self.mm_lines.append(line)
                    processed_lines.add(line)

        self.text_edit.setText("\n".join(self.mm_lines))
        self.btn_copy.setEnabled(True)

    def mm_id(self, name):
        return "n" + hashlib.md5(name.encode()).hexdigest()[:6]

    def mm_add_node(self, fullname):
        nid = self.mm_id(fullname)
        if nid not in self.mm_nodes:
            short = fullname.split("|")[-1]
            try:
                typ = cmds.nodeType(fullname)
            except (RuntimeError, TypeError):
                typ = "unknown"

            style_class = "transform"
            if typ == 'joint':
                style_class = "joint"
            elif typ in self.MATH_NODE_TYPES:
                if 'Matrix' in typ:
                    style_class = "matrix"
                else:
                    style_class = "math"
            elif 'Constraint' in typ:
                style_class = "constraint"
            elif typ == 'transform':
                style_class = "transform"
            else:
                style_class = self.get_random_color_class(typ)

            self.mm_lines.append(f'    {nid}["{short}<br><small>({typ})</small>"]:::{style_class}')
            self.mm_nodes.add(nid)

    def get_random_color_class(self, node_type):
        class_name = f"type_{node_type}"
        if class_name not in self.dynamic_classes:
            hash_val = int(hashlib.md5(node_type.encode()).hexdigest(), 16)
            hue = hash_val % 360
            r, g, b = colorsys.hls_to_rgb(hue / 360.0, 0.4, 0.6)
            hex_color = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
            self.mm_lines.append(f"    classDef {class_name} fill:{hex_color},stroke:#fff,color:#fff;")
            self.dynamic_classes.add(class_name)
        return class_name

    # --- Helpers (Unchanged) ---
    def get_connections(self, node, source=True, destination=True):
        conns = cmds.listConnections(node, s=source, d=destination, plugs=True, connections=True) or []
        results = []
        for i in range(0, len(conns), 2):
            my_plug_str = conns[i]
            other_plug_str = conns[i + 1]
            _, _, my_attr = my_plug_str.partition('.')
            other_node_part, _, other_attr = other_plug_str.partition('.')
            full_other_node = other_node_part
            if cmds.objExists(other_node_part):
                ls_res = cmds.ls(other_node_part, long=True)
                if ls_res: full_other_node = ls_res[0]
            if cmds.nodeType(full_other_node) == 'objectSet':
                continue
            short_other_node = full_other_node.split('|')[-1]
            results.append({
                'my_attr': my_attr,
                'other_node': short_other_node,
                'other_node_full': full_other_node,
                'other_attr': other_attr
            })
        return results

    # --- Analysis Logic (Unchanged) ---
    def on_analyze_clicked(self):
        sel = cmds.ls(sl=1, long=True)
        if not sel:
            self.text_edit.setText("Select nodes.")
            return
        nodes = self.get_expanded_selection(sel)
        nodes.sort()
        md = ["# Node Connections", ""]
        if self.chk_smart_trace.isChecked(): md.append("> 🌀 Smart Trace Active\n")
        for node in nodes:
            typ = cmds.nodeType(node)
            short = node.split('|')[-1]
            md.append(f"### `{short}` ({typ})")
            ins = self.get_connections(node, source=True, destination=False)
            outs = self.get_connections(node, source=False, destination=True)
            ins.sort(key=lambda x: x['my_attr'])
            outs.sort(key=lambda x: x['my_attr'])
            if not ins and not outs:
                md.append("> *No connections.*\n")
                continue
            md.append("| Dir | My Attr | Connected Node | Other Attr |")
            md.append("|:---:|:---|:---|:---|")
            for x in ins: md.append(f"| ← | `{x['my_attr']}` | `{x['other_node']}` | `{x['other_attr']}` |")
            for x in outs: md.append(f"| → | `{x['my_attr']}` | `{x['other_node']}` | `{x['other_attr']}` |")
            md.append("")
        self.text_edit.setText("\n".join(md))
        self.btn_copy.setEnabled(True)

    # --- Graph Boilerplate (Unchanged) ---
    def get_ne(self):
        pnls = cmds.getPanel(scriptType='nodeEditorPanel')
        if not pnls: return None
        for p in pnls:
            if cmds.control(p, ex=1) and cmds.control(p, q=1, vis=1): return p
        return pnls[0] if pnls else None

    def on_expand_graph(self, up, down):
        sel = cmds.ls(sl=1);
        pnl = self.get_ne()
        if sel and pnl:
            try:
                cmds.nodeEditor(pnl + "NodeEditorEd", e=1, addNode=cmds.listConnections(sel, s=up, d=down) or [],
                                layout=1)
            except (RuntimeError, TypeError):
                pass

    def on_reduce_graph(self, up, down):
        sel = cmds.ls(sl=1);
        pnl = self.get_ne()
        if sel and pnl:
            rem = cmds.listConnections(sel, s=up, d=down) or []
            rem = [n for n in rem if n not in sel]
            if rem: cmds.nodeEditor(pnl + "NodeEditorEd", e=1, removeNode=rem)

    def on_remove_object_sets(self):
        pnl = self.get_ne()
        if pnl:
            try:
                cmds.nodeEditor(pnl + "NodeEditorEd", e=1, removeNode=cmds.ls(type='objectSet') or [])
            except (RuntimeError, TypeError):
                pass

    def on_isolate_clicked(self):
        sel = cmds.ls(sl=1);
        pnl = self.get_ne()
        if sel and pnl:
            ed = pnl + "NodeEditorEd"
            try:
                cmds.nodeEditor(ed, e=1, rootNode="", addNode=sel)
                shapes = cmds.listRelatives(sel, shapes=1, f=1) or []
                hide = [s for s in shapes if s not in cmds.ls(sel, l=1)]
                if hide: cmds.nodeEditor(ed, e=1, removeNode=hide)
                cmds.nodeEditor(ed, e=1, layout=1, frameAll=1)
            except (RuntimeError, TypeError):
                pass

    def copy_to_clipboard(self):
        cb = QtWidgets.QApplication.clipboard()
        cb.setText(self.text_edit.toPlainText())
        cmds.inViewMessage(amg='<span style=\"color: #00FF00;\">Copied!</span>', pos='midCenter', fade=True)


my_node_assistant_ui = None


def close_tool():
    global my_node_assistant_ui
    if my_node_assistant_ui is None:
        return
    try:
        my_node_assistant_ui.close()
        my_node_assistant_ui.deleteLater()
    except RuntimeError:
        pass
    finally:
        my_node_assistant_ui = None


def show_tool():
    global my_node_assistant_ui
    close_tool()
    my_node_assistant_ui = NodeEditorAssistant(get_maya_window())
    my_node_assistant_ui.show()
    return my_node_assistant_ui


if __name__ == "__main__":
    show_tool()
