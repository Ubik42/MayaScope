
# Maya Indie Tools

A collection of Python tools for Autodesk Maya, designed to assist with rigging, scene analysis, and node graph management.

## Tools

### 1. Hierarchy Inspector (`analyze_scene.py`)
A tool to inspect the Maya scene hierarchy with advanced filtering and export capabilities.

**Features:**
- **Tree View:** Visualizes the scene hierarchy.
- **Filtering:** Filter nodes by type (transform, joint, constraints, math nodes, etc.) and search by name.
- **Math Node Logic:** Option to toggle visibility of utility/math nodes.
- **Connection Analysis:** Shows what drives a node (constraints, direct connections) and locked attributes.
- **Markdown Export:** Copy the hierarchy or selected nodes to the clipboard in Markdown format.

### 2. Node Graph Assistant (`node_viewer.py`)
An assistant for Maya's Node Editor to help visualize and manage complex node networks.

**Features:**
- **Graph Operations:** Quickly add/remove inputs and outputs, isolate nodes, and remove specific node types (e.g., `objectSet`).
- **Smart Trace:** Recursively trace and select utility/math/matrix nodes connected to the selection.
- **Mermaid Export:** Generate a Mermaid JS graph diagram of the connected node network, including "Smart Routing" logic to group attributes.
- **Markdown Analysis:** Analyze connection data and export it as a Markdown table.

### 3. Python Analyzer (`py_analyzer.py`)
(Documentation pending - Tool for analyzing Python scripts)

### 4. Set Manager (`set_manager.py`)
(Documentation pending - Tool for managing Maya Sets)

## Installation

1. Clone this repository into your Maya scripts directory or add it to your `PYTHONPATH`.
2. In Maya's Script Editor (Python tab), import and run the desired tool:

```python
# Example for Hierarchy Inspector
import analyze_scene
analyze_scene.show_tool()
```

```python
# Example for Node Viewer
import node_viewer
# (The script is set up to run on import/execution widely used in Maya pipeline)
```

## Requirements
- Autodesk Maya (tested on recent versions)
- PySide6 (included with modern Maya)
