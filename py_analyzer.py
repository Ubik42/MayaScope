import os
import ast
import sys
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path


# ==========================================
# 核心逻辑：AST 代码解析 (增强版)
# ==========================================
class CodeAnalyzer:
    @staticmethod
    def get_structure(file_path):
        """解析单个文件，返回类、方法、参数和返回值结构"""
        structure = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)

            for node in tree.body:
                # 顶级函数
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = CodeAnalyzer._get_func_signature(node)
                    structure.append({
                        'type': 'function',
                        'name': node.name,
                        'signature': sig,
                        'lineno': node.lineno
                    })
                # 类
                elif isinstance(node, ast.ClassDef):
                    methods = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            m_sig = CodeAnalyzer._get_func_signature(item)
                            methods.append({
                                'name': item.name,
                                'signature': m_sig
                            })

                    structure.append({
                        'type': 'class',
                        'name': node.name,
                        'methods': methods,
                        'lineno': node.lineno
                    })
        except Exception as e:
            structure.append({'type': 'error', 'msg': str(e)})

        return structure

    @staticmethod
    def _format_annotation(node):
        """格式化类型注解 (兼容不同 Python 版本)"""
        if node is None:
            return ""

        # Python 3.9+ 可以直接反解析 AST 为源码字符串
        if sys.version_info >= (3, 9):
            try:
                return ast.unparse(node)
            except (AttributeError, TypeError, ValueError):
                pass

        # Python 3.8 及以下的回退处理 (简化版)
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Constant):
            return str(node.value)
        elif isinstance(node, ast.Attribute):
            return f"{CodeAnalyzer._format_annotation(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            val = CodeAnalyzer._format_annotation(node.value)
            slc = CodeAnalyzer._format_annotation(node.slice)
            return f"{val}[{slc}]"

        return "..."  # 过于复杂的类型在低版本简化显示

    @staticmethod
    def _get_func_signature(node):
        """提取函数签名字符串: (args) -> return"""
        args_strs = []

        # 1. 处理普通参数 (Positional Args)
        # 默认值是从后往前匹配的
        defaults = node.args.defaults
        default_offset = len(node.args.args) - len(defaults)

        for i, arg in enumerate(node.args.args):
            arg_str = arg.arg

            # 类型注解
            if arg.annotation:
                anno = CodeAnalyzer._format_annotation(arg.annotation)
                arg_str += f": {anno}"

            # 默认值
            if i >= default_offset:
                def_val = defaults[i - default_offset]
                # 简单还原默认值的字符串表示
                if sys.version_info >= (3, 9):
                    def_str = ast.unparse(def_val)
                else:
                    # 简易处理
                    if isinstance(def_val, ast.Constant):
                        def_str = repr(def_val.value)
                    elif isinstance(def_val, ast.Name):
                        def_str = def_val.id
                    else:
                        def_str = "..."
                arg_str += f"={def_str}"

            args_strs.append(arg_str)

        # 2. 处理 *args
        if node.args.vararg:
            v_arg = f"*{node.args.vararg.arg}"
            if node.args.vararg.annotation:
                v_arg += f": {CodeAnalyzer._format_annotation(node.args.vararg.annotation)}"
            args_strs.append(v_arg)

        # 3. 处理 Keyword-Only Args (def f(*, a=1))
        for i, kwarg in enumerate(node.args.kwonlyargs):
            k_str = kwarg.arg
            if kwarg.annotation:
                k_str += f": {CodeAnalyzer._format_annotation(kwarg.annotation)}"

            # kw_defaults 可能包含 None (表示该参数没有默认值)
            if i < len(node.args.kw_defaults):
                def_val = node.args.kw_defaults[i]
                if def_val is not None:
                    if sys.version_info >= (3, 9):
                        def_str = ast.unparse(def_val)
                    else:
                        def_str = "..."
                    k_str += f"={def_str}"
            args_strs.append(k_str)

        # 4. 处理 **kwargs
        if node.args.kwarg:
            k_arg = f"**{node.args.kwarg.arg}"
            if node.args.kwarg.annotation:
                k_arg += f": {CodeAnalyzer._format_annotation(node.args.kwarg.annotation)}"
            args_strs.append(k_arg)

        # 5. 处理返回值
        return_anno = ""
        if node.returns:
            return_anno = f" -> {CodeAnalyzer._format_annotation(node.returns)}"

        return f"({', '.join(args_strs)}){return_anno}"


# ==========================================
# GUI 界面应用
# ==========================================
class ProjectAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Python 深度结构分析器 (含参数与返回值)")
        self.root.geometry("800x800")  # 加宽一点以便显示长签名

        # 样式设置
        style = ttk.Style()
        style.configure("Treeview", font=('Consolas', 10), rowheight=24)

        # 图标常量
        self.ICON_PKG = "📦"
        self.ICON_FILE = "🐍"
        self.ICON_DIR = "📁"

        self.project_root = Path(os.path.dirname(os.path.abspath(__file__)))

        self.setup_ui()
        self.load_project_tree()

    def setup_ui(self):
        # 顶部说明
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)
        ttk.Label(top_frame, text=f"扫描路径: {self.project_root}").pack(anchor=tk.W)
        ttk.Label(top_frame, text="提示: 自动解析函数参数及返回值。__init__.py 已被忽略。", foreground="blue").pack(
            anchor=tk.W)

        # 中间树状图
        tree_frame = ttk.Frame(self.root, padding="10")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        # 滚动条
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(tree_frame, selectmode="extended", yscrollcommand=scrollbar.set)
        self.tree.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        # 配置列
        self.tree.heading("#0", text=" 项目文件结构", anchor=tk.W)

        # 底部按钮区
        btn_frame = ttk.Frame(self.root, padding="10")
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="📄 深度解析 (类/方法/参数/返回值)", command=self.analyze_selected).pack(side=tk.LEFT,
                                                                                                           fill=tk.X,
                                                                                                           expand=True,
                                                                                                           padx=5)
        ttk.Button(btn_frame, text="🌳 生成纯文本目录结构", command=self.generate_full_tree_text).pack(side=tk.LEFT,
                                                                                                      fill=tk.X,
                                                                                                      expand=True,
                                                                                                      padx=5)

    def is_package(self, path: Path):
        """判断是否为 Python 包 (含 __init__.py)"""
        return path.is_dir() and (path / "__init__.py").exists()

    def load_project_tree(self):
        """加载文件树"""
        root_node = self.tree.insert("", "end", text=f"{self.ICON_DIR} Root", open=True,
                                     values=[str(self.project_root)])
        self._build_tree_recursive(self.project_root, root_node)

    def _build_tree_recursive(self, current_path: Path, parent_node):
        try:
            items = sorted(list(current_path.iterdir()), key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            return

        for item in items:
            if item.name.startswith('.') or item.name == '__pycache__' or item.name == os.path.basename(__file__):
                continue
            if item.name == '__init__.py': continue  # 忽略 init

            is_pkg = self.is_package(item)
            is_py = item.is_file() and item.suffix == '.py'

            if is_pkg:
                node = self.tree.insert(parent_node, "end", text=f"{self.ICON_PKG} {item.name}", open=True,
                                        values=[str(item)])
                self._build_tree_recursive(item, node)
            elif is_py:
                self.tree.insert(parent_node, "end", text=f"{self.ICON_FILE} {item.name}", values=[str(item)])

    def _get_files_recursively(self, directory: Path):
        found_files = []
        try:
            for item in directory.iterdir():
                if item.name.startswith('.') or item.name == '__pycache__' or item.name == os.path.basename(__file__):
                    continue
                if item.name == '__init__.py': continue

                if item.is_file() and item.suffix == '.py':
                    found_files.append(item)
                elif item.is_dir() and self.is_package(item):
                    found_files.extend(self._get_files_recursively(item))
        except PermissionError:
            pass
        return found_files

    def analyze_selected(self):
        """分析选中的文件"""
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showinfo("提示", "请先选择文件或文件夹！")
            return

        files_to_analyze = set()

        for item_id in selected_items:
            values = self.tree.item(item_id, "values")
            if not values: continue
            path_obj = Path(values[0])

            if path_obj.is_file() and path_obj.suffix == '.py':
                if path_obj.name != '__init__.py':
                    files_to_analyze.add(path_obj)
            elif path_obj.is_dir():
                sub_files = self._get_files_recursively(path_obj)
                for f in sub_files:
                    files_to_analyze.add(f)

        if not files_to_analyze:
            messagebox.showwarning("警告", "未找到有效的 Python 文件 (已忽略 __init__.py)。")
            return

        sorted_files = sorted(list(files_to_analyze))

        report_lines = []
        report_lines.append(f"📊 分析报告: 共 {len(sorted_files)} 个文件")
        report_lines.append("=" * 70)
        report_lines.append("")

        for f in sorted_files:
            try:
                rel_path = f.relative_to(self.project_root)
            except ValueError:
                rel_path = f.name

            report_lines.append(f"📄 文件: {rel_path}")
            report_lines.append("-" * 70)

            structure = CodeAnalyzer.get_structure(f)

            if not structure:
                report_lines.append("   (空或无类/函数定义)")

            for item in structure:
                if item['type'] == 'error':
                    report_lines.append(f"   ❌ 解析错误: {item['msg']}")
                elif item['type'] == 'class':
                    report_lines.append(f"   ⓒ class {item['name']}:")
                    if item['methods']:
                        for m in item['methods']:
                            # 显示方法和完整签名
                            report_lines.append(f"      ⓕ {m['name']}{m['signature']}")
                    else:
                        report_lines.append(f"      (无方法)")
                elif item['type'] == 'function':
                    # 显示顶级函数和完整签名
                    report_lines.append(f"   ⓕ def {item['name']}{item['signature']}")

            report_lines.append("\n")

        self.show_result_window("深度代码分析报告", "\n".join(report_lines))

    def generate_full_tree_text(self):
        lines = [f"📂 Project Root: {self.project_root.name}", "."]
        self._generate_text_tree_recursive(self.project_root, "", lines)
        self.show_result_window("项目目录结构树", "\n".join(lines))

    def _generate_text_tree_recursive(self, directory: Path, prefix: str, lines: list):
        try:
            items = []
            for p in directory.iterdir():
                if p.name.startswith('.') or p.name == '__pycache__' or p.name == os.path.basename(__file__):
                    continue
                if p.name == '__init__.py': continue

                if p.is_file() and p.suffix == '.py':
                    items.append(p)
                elif self.is_package(p):
                    items.append(p)
            items.sort(key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            return

        count = len(items)
        for index, item in enumerate(items):
            is_last = (index == count - 1)
            connector = "└── " if is_last else "├── "

            if item.is_dir():
                lines.append(f"{prefix}{connector}{self.ICON_PKG} {item.name}")
                new_prefix = prefix + ("    " if is_last else "│   ")
                self._generate_text_tree_recursive(item, new_prefix, lines)
            else:
                lines.append(f"{prefix}{connector}{self.ICON_FILE} {item.name}")

    def show_result_window(self, title, content):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("800x600")
        text_area = scrolledtext.ScrolledText(win, font=('Consolas', 10))
        text_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        text_area.insert(tk.END, content)


if __name__ == "__main__":
    root = tk.Tk()
    app = ProjectAnalyzerApp(root)
    root.mainloop()
