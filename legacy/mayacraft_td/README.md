# MayaCraft TD 迁移快照

本目录保存 2026-08-25 从 MayaCraft 迁出的旧 TD 页面与逻辑，用于 MayaScope 重写期间盘点需求和比对行为。

这些代码仍引用旧的 `MayaCraft.*` 模块，**不会进入 MayaScope 运行时，也不应被新代码导入**。对应能力需要在统一的 SceneSnapshot、Query、Analysis 和 Visualization 架构中重新实现。完成替代后按功能逐项删除本目录文件。

迁入内容：

- `ui/`：旧 Node Viewer、Node Analyser 和扩展页面；
- `core/`：旧属性/连接分析、Node Editor 操作和 Markdown/Mermaid 输出逻辑。
