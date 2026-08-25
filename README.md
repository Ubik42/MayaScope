# Maya Indie Tools

一组面向 Autodesk Maya 技术美术与绑定工作的独立小工具。仓库重点解决三类问题：复杂场景和节点网络难以阅读、Maya Set 管理操作分散，以及大型 MEL / Python 代码缺少便于沟通的结构化输出。

这些工具彼此独立，可以按需复制到 Maya 脚本目录运行；仓库同时包含一个实验性的 VS Code MEL 导航扩展。

## 工具一览

| 工具 | 入口 | 用途 |
| --- | --- | --- |
| Hierarchy Inspector | `analyze_scene.py` | 检查场景层级、驱动关系与锁定属性，并导出 Markdown |
| Node Graph Assistant | `node_viewer.py` | 整理 Maya Node Editor、追踪连接并导出 Markdown / Mermaid |
| Set Manager Pro | `set_manager.py` | 创建、检查和整理 Maya Object Set |
| Python Project Analyzer | `py_analyzer.py` | 静态分析 Python 项目结构，生成类、函数与目录报告 |
| Advanced Skeleton Parser | `AnalyseAdv/` | 从大型 MEL 文件提取全局过程并按人工分类重排 |
| MEL Outline | `mel-outline/` | 为 VS Code 提供 MEL 符号、折叠、定义与引用导航 |

## Maya 场景与节点工具

### Hierarchy Inspector

`analyze_scene.py` 将 Maya 场景整理成可筛选的树形结构：

- 按名称搜索，按 transform、joint、constraint、utility/math 等类型筛选；
- 显示节点类型、锁定属性和上游驱动信息；
- 可切换 utility / math 节点的显示；
- 展开、折叠和刷新场景树；
- 将全部可见节点或当前选择复制成 Markdown，便于问题记录和技术沟通。

在 Maya Script Editor 的 Python 标签页运行：

```python
import analyze_scene
analyze_scene.show_tool()
```

### Node Graph Assistant

`node_viewer.py` 直接操作当前 Maya Node Editor：

- 将选中节点设为当前图的起点；
- 添加或移除输入、输出节点；
- 从图中清理 `objectSet` 节点；
- 递归追踪 utility、math 与 matrix 连接；
- 将连接关系输出为 Markdown 表格或 Mermaid 图；
- 复制分析结果到系统剪贴板。

运行：

```python
exec(open(r"D:\path\to\MayaIndieTool\node_viewer.py", encoding="utf-8").read())
```

### Set Manager Pro

`set_manager.py` 提供 Maya Set 的集中管理界面：

- 创建单个 Set，或按所选对象类型批量创建；
- 将对象加入、移出指定 Set；
- 随 Maya 当前选择实时显示对象所属 Set；
- 使用 Maya Set 的颜色信息辅助辨认。

运行：

```python
exec(open(r"D:\path\to\MayaIndieTool\set_manager.py", encoding="utf-8").read())
```

## 代码分析与 MEL 导航

### Python Project Analyzer

`py_analyzer.py` 是一个基于 Tkinter 与 Python AST 的独立桌面工具，不依赖 Maya。它可以选择文件或目录，递归识别 Python 包，列出类、方法、顶层函数及其签名，并生成项目目录树。

```powershell
python py_analyzer.py
```

### Advanced Skeleton Parser

`AnalyseAdv/categorize_mel.py` 面向体量较大的 MEL 单文件：

1. 读取人工维护的过程分类表；
2. 解析源文件中的 `global proc`，避开块注释等干扰；
3. 按分类重新组织过程，并加入 `#region` / `#endregion`；
4. 将未命中的过程统一保留在 `Uncategorized` 区域。

仓库中保留了原始输入、分类表、过程清单和重排后的 MEL，便于核对处理结果。

### MEL Outline（实验性）

`mel-outline/` 是一个独立的 VS Code 扩展工程，当前代码提供：

- MEL 文档符号与 Outline；
- `#region` 折叠；
- `global proc` 的定义跳转与引用查找；
- CodeLens 引用入口；
- 导出全局过程列表命令。

开发运行方式见 [`mel-outline/README.md`](mel-outline/README.md)。该扩展目前是源码级实验项目，仓库没有提供已打包的 VSIX。

## 环境与安装

- Maya 工具：Autodesk Maya 2025 或其他内置 PySide6 的较新版本；
- Python Project Analyzer：Python 3，Tkinter；
- MEL Outline：VS Code 1.106+，Node.js 与 npm。

最简单的 Maya 安装方式，是将仓库加入 `MAYA_SCRIPT_PATH` / `PYTHONPATH`，或将需要的单文件复制到 Maya 用户脚本目录。工具直接调用 `maya.cmds` 和当前 Maya UI，不应在普通 Python 解释器中运行。

## 仓库结构

```text
analyze_scene.py        场景层级检查与 Markdown 导出
node_viewer.py          Node Editor 辅助与连接图导出
set_manager.py          Object Set 管理
py_analyzer.py          独立 Python 项目结构分析器
AnalyseAdv/             Advanced Skeleton MEL 分类与重排
mel-outline/            VS Code MEL 导航扩展工程
```

## 当前边界

- 仓库由多个独立工具组成，目前没有统一安装器或总入口；
- Maya 工具依赖宿主场景与 Node Editor 状态，执行前应保存场景；
- MEL Outline 尚未发布到 VS Code Marketplace，也未提供预编译安装包；
- `AnalyseAdv/` 中的 Advanced Skeleton 源文件用于代码研究与重排验证，使用时仍需遵守原工具的授权条件。
