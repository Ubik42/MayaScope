# MayaScope TD 产品研究与方向决策

状态：T0 产品研究结论  
日期：2026-08-25  
范围：Maya 场景理解、性能、运行时、引用、验证、差异、调试与安全操作  
产品定义：**Maya 的场景黑匣子、因果调查台和可交互地图**

## 0. 最终判断

MayaScope 不应该成为另一个 Scene Cleaner、Profiler 外壳、Node Editor 皮肤或发布检查列表。它应成为 **Causal Scene Observatory（场景因果观测台）**：记录 Maya 场景的结构、时间、事件和变化，让 TD 从一个症状出发，建立证据链、定位根因、设计实验、预览修复并验证结果。

它必须同时解决五类问题：

1. **What exists**：场景中到底有什么，来自哪里，如何分层、引用和实例化；
2. **What depends on what**：DAG、DG、Evaluation、文件、插件、运行时之间的真实依赖；
3. **What happened**：某一帧、某次打开、某次选择、某段回放或某次发布发生了什么；
4. **Why it happened**：哪个节点、Plug、Callback、引用编辑或结构变化构成最小解释路径；
5. **What will happen if changed**：修复的影响范围、风险、性能收益、验证方法和回滚边界。

一句话定位：

> MayaScope 把 Maya 场景转换成可以记录、查询、比较、解释和安全试验的因果模型。

## 1. 为什么现有工具没有解决完整问题

### 1.1 Maya 官方能力很深，但彼此割裂

Maya 已经提供大量底层诊断能力：

- Evaluation Toolkit 可以切换 DG/Serial/Parallel/GPU Override，运行 EM Validation、Computed Nodes Trace、Profiler、Analytics 和 Scene Lint；[Evaluation Toolkit](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Customizing/files/GUID-E22B253D-914B-4056-93F5-755702A6C998.htm)
- Profiler 能记录 CPU、Thread、Category 事件，并允许脚本和插件通过 API 写入自定义 profiling event；[Maya Profiler](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Customizing/files/GUID-66E4D9A3-2050-4CDF-B6A4-8C5645BFFBB8.htm) · [profiler command](https://help.autodesk.com/cloudhelp/ENU/MayaCRE-Tech-Docs/Commands/profiler.html)
- `dbpeek`、`dbtrace`、`dgeval` 和 Evaluation Manager 查询可暴露 Evaluation Graph、调度类型、缺失依赖和 dirty/evaluation 行为；[evaluationManager](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Commands/evaluationManager.html) · [dgeval](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Commands/dgeval.html)
- Node Editor 提供上下游遍历、Watchpoint、DOT/Graphviz 导出、遍历深度和自定义布局接口；[nodeEditor command](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Commands/nodeEditor.html)
- `MDGMessage` 等 API 可以监听节点、连接和时间变化，但 Callback 生命周期处理错误会导致致命问题；[MDGMessage](https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/cpp_ref/class_m_d_g_message.html)
- 引用系统允许查询和处理 reference edits，但 unloaded reference 会丢失一部分详细归属信息，某些编辑也不可撤销；[referenceEdit](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Commands/referenceEdit.html)

真正缺失的是统一调查模型：Profiler 的时间块、Node Editor 的局部连接、Outliner 的层级、Reference Editor 的文件、Scene Lint 的规则和 Script Editor 的日志彼此不知道对方。TD 只能手工在多个窗口间拼接因果关系。

### 1.2 其他顶级工具证明了正确交互范式

| 参考 | 最值得学习 | MayaScope 应进一步推进 |
|---|---|---|
| Houdini Network + Performance Monitor | 性能数据直接着色到节点网络；参数级依赖；跨 Network 跳转 | 把 DAG、DG、Evaluation、文件和事件作为不同 Lens，而不是混成一张图 |
| Unreal Insights | 统一 Trace、Frame、CPU/GPU Track、Timer、Counter、Callers/Callees；选中时间区间后其他视图联动 | 让时间区间和 SceneSnapshot/节点子图双向联动 |
| Unreal Reference Viewer | Referencer/Dependency 两侧结构、深度/宽度限制、Overflow Node、Size Map | 增加 reference edit、namespace、插件和实际 DG 影响解释 |
| NVIDIA Nsight Systems | 系统级统一时间线、线程/GPU/资源相关性、低开销 Capture | 建立 Maya 主线程、Evaluation task、Callback、Python/MEL、Viewport 和插件事件的同一时钟 |
| Neo4j Bloom | Perspective 决定节点类别、关系、样式和查询；通过语义视角探索大图 | 把 TD 常用调查意图做成 Scene Perspective，而不是要求所有人先写图查询 |
| Pyblish / AYON | collect → validate → extract → integrate；validator 可修复、可重跑 | 将发布检查升级为 evidence → ChangePlan → apply → verify，并与场景因果模型共享数据 |

证据来源：[Houdini Dependencies](https://www.sidefx.com/docs/houdini/network/dependencies.html) · [Houdini Performance Monitor](https://www.sidefx.com/docs/houdini/ref/panes/perfmon) · [Unreal Insights](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-insights-in-unreal-engine) · [Unreal Reference Viewer](https://dev.epicgames.com/documentation/unreal-engine/reference-viewer-in-unreal-engine?lang=en-US) · [Nsight Systems](https://developer.nvidia.com/nsight-systems) · [Neo4j Bloom Perspectives](https://neo4j.com/docs/aura/explore/explore-perspectives/perspectives/) · [AYON Publisher](https://help.ayon.app/articles/1075843-creator-publisher)

## 2. 社区暴露的真正工作痛点

### 2.1 “慢”通常只能靠猜

社区中最常见的性能排查流程仍然是：切 Parallel、开 GPU Override、关 Smooth Preview、删除一半对象、重开场景，再重复。一个 2026 年获得大量反馈的 Scene Doctor 工具之所以受欢迎，是因为它把真实 playback FPS、viewport-spin FPS、表达式、重模型、引用和缓存检查放到一个入口，并解释为什么和修复后的变化。[Scene Doctor 讨论](https://www.reddit.com/r/Maya/comments/1u01w0r/got_tired_of_guessing_why_my_scenes_lag_so_i/)

这说明基础体检有市场，但 MayaScope 面向 TD 时不能止步于 19 条规则。它必须回答：

- 慢发生在哪个时间区间和线程；
- 哪个 Evaluation cluster、serial island 或 dirty frontier 导致；
- 哪些节点只是耗时高，哪些节点是真正限制总体吞吐的关键路径；
- 禁用或替换某个节点能带来多大可重复收益；
- 结论在另一帧、另一 Maya 版本或另一场景版本是否仍成立。

Tech-Artists 的讨论反复提到表达式被视为 untrusted、海量 cluster/connection 造成串行瓶颈、循环依赖导致 evaluate cluster，以及 Profiler 信息过碎难以阅读。[复杂 Rig 性能](https://www.tech-artists.org/t/speed-of-complex-character-rigs/2472) · [Deformer Evaluation](https://www.tech-artists.org/t/deactivating-deformer-evaluation/11786) · [循环依赖案例](https://www.tech-artists.org/t/maya-controller-follow-mesh-without-circular-dependencies/10290)

### 2.2 “坏场景”通常只能靠破坏性二分

场景打不开或崩溃时，社区建议常常是另存 `.ma`、删除未知节点、导入新场景，或者删除一半对象后重开，直到找到罪魁祸首。有案例最终通过反复删除定位到三个普通几何体之一。[Maya 崩溃排查讨论](https://www.reddit.com/r/Maya/comments/1g9jedn)

这暴露了一个强烈的产品机会：**Crash/Corruption Bisect**。MayaScope 应在隔离进程中自动进行场景子集、Reference、Plugin、Node Type 或 Deformer 链的二分实验，保存每次启动、打开、求值和退出结果，最终输出最小可疑集合。危险场景不能要求用户在唯一工作文件上手工删东西。

### 2.3 Reference 与 Namespace 是文件、身份和编辑历史问题

用户经常把 Namespace 当作“讨厌的前缀”而删除，但社区 TD 指出 referenced rig 包含大量隐藏 DG 节点，直接剥离 namespace 或复制 skeleton 会破坏更新关系、制造命名冲突或留下不可维护副本。[Referenced Namespace 讨论](https://www.reddit.com/r/Maya/comments/ihfo3b) · [导出去 Namespace 的争议](https://www.reddit.com/r/Maya/comments/1bskz9z)

MayaScope 不能只列 Namespace。它需要显示：

- 文件引用树、实例、加载状态与文件版本；
- Reference Edit 的目标、来源、成功/失败、所属层级与潜在漂移；
- Namespace 内本地节点、跨 Reference 连接和命名冲突风险；
- 导入、复制、扁平化或重新指向 Reference 将改变哪些身份和连接；
- SceneSnapshot 中的稳定身份不能只依赖短名或 DAG path。

### 2.4 Scene Health 往往变成公司内部的规则列表

Pyblish/AYON 已经证明 validator、repair 和重跑发布流程很有用；社区也认为每个工作室都有自己的 sanity checks，并倾向建立模块化规则系统。[Pyblish](https://learn.pyblish.com/) · [AYON Maya Validation](https://help.ayon.app/articles/6811988-working-with-maya-in-ayon) · [Sanity Check 讨论](https://www.reddit.com/r/Maya/comments/15p8i0r)

但普通 validator 往往只有 pass/fail 和一个 repair 函数。MayaScope 的规则必须输出：

- 命中的对象与原始证据；
- 规则为何重要、误报条件和扫描成本；
- 问题的共同根因和重复项聚类；
- 修复前后结构差异；
- 是否可撤销、是否会修改 Reference、是否需隔离进程；
- 复检结果与可保存的执行凭证。

### 2.5 安全也是 TD 场景诊断的一部分

Autodesk Security Tools 会检查 scene file、userSetup 和已知恶意脚本，并支持主动加载扫描和批处理；它说明 Maya 文件本身可能携带执行逻辑。[Autodesk Maya Security Tool](https://www.autodesk.com/support/technical/article/caas/tsarticles/ts/263G8wMqYtim0ZoGaCx8az.html)

MayaScope 不应自称杀毒软件，但应建立 **Execution Surface Inventory**：scriptNode、expression、scriptJob、Callback、unknown plugin/node、userSetup 影响、自动加载插件和文件打开时执行路径。对未知场景提供 Safe Intake Mode，先做静态/隔离扫描，再决定是否在主 Maya 会话打开。

## 3. 产品结构：一个调查循环，四个核心仪器

传统产品容易分成 Overview、Graph、Profiler、Health、Diff 五六个标签页。MayaScope 应围绕同一个调查循环组织：

```text
Symptom
  ↓
Capture / Snapshot
  ↓
Scope & Evidence
  ↓
Cause Hypothesis
  ↓
Experiment / ChangePlan
  ↓
Verify & Compare
  ↺
```

四个核心仪器共享 SceneSnapshot、Selection、Time Range、Query 和 Evidence Trail。

### 3.1 Scene Atlas：多尺度场景地图

不是一次画出所有节点，而是按语义、LOD 和调查 Perspective 渐进显影。

核心能力：

- 同一 SceneSnapshot 上切换 DAG、DG、Evaluation、Reference、Plugin/Runtime、Ownership 等 Lens；
- 默认按 Reference、Namespace、Asset、Node Type、Evaluation Cluster 或用户规则聚合；
- Semantic Zoom：远景看模块和边界，中景看节点与主要边，近景才展开 Plug；
- 查询结果不是另一张表，而是地图中的高亮、隔离区、路径和可保存 Scope；
- 上下游 Lens、最短解释路径、影响域、跨边界连接和循环成分；
- 选择 Maya 对象可在 Atlas 定位，Atlas 选择也能回到 Maya、Node Editor 或 Reference Editor；
- 不同 Lens 不混淆：DAG parenting、DG plug connection、Evaluation dependency、file composition 使用不同边语法。

参考 Unreal Reference Viewer 的深度/宽度限制、Overflow Node 和 inactive chain：被过滤的中间节点仍需以压缩节点保留，不能让依赖链看起来凭空断裂。[Unreal Reference Viewer](https://dev.epicgames.com/documentation/unreal-engine/reference-viewer-in-unreal-engine?lang=en-US)

### 3.2 Pulse：时间与因果追踪器

Maya Profiler 提供原始事件，但 Pulse 负责把“时间”重新连接到“场景结构”。

核心能力：

- 录制 frame、thread、category、evaluation task、callback、Python/MEL、viewport、file I/O 和自定义事件；
- 顶部 Frame Horizon 显示 FPS、frame time、峰值和状态变化；
- 选中一个时间区间，Atlas 只显示此区间实际参与或被 dirty 的子图；
- 选中一个节点、Reference 或插件，时间线突出其事件、caller/callee 和历史基线；
- Critical Path、Serial Island、Wait/Idle、重复计算和 Dirty Storm 可视化；
- 两次 Capture 进行对齐比较，按 frame、操作标记或事件锚点对齐；
- 统计噪声、热身帧、缓存状态和播放模式被记录为实验条件。

Unreal Insights 的关键优点是选择时间区间后 Timer、Counter、Caller/Callee 自动聚合；Nsight 的优点是把不同资源层放在同一时钟。MayaScope 应把这种联动推进到 Maya 场景节点层。[Unreal Insights Overview](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-insights-overview?application_version=4.27) · [Nsight Systems](https://developer.nvidia.com/nsight-systems)

### 3.3 Delta：场景结构与行为差异

Maya 文件 diff 不能退化成文本行 diff。Delta 比较的是经过身份解析的场景模型：

- add/remove/rename/reparent/rewire/property/reference edit/plugin/runtime state；
- rename 与 delete+add 的候选匹配，并显示置信度；
- Reference 更新导致的局部变化与用户本地编辑分开；
- Scene Health、节点规模、内存、Evaluation scheduling 和性能样本差异；
- 图布局保持稳定，未变化区域固定，变化边和节点以 morph/flow 表示；
- 可从“性能回归 8ms”回溯到新增节点、连接或 Reference 版本变化；
- Diff 结果可导出为人读报告和机器读协议，进入 CI。

OpenUSD 的 composed scenegraph、LayerStack、Reference、Override 和 Instancing 提供了更成熟的场景组合心智模型；MayaScope 的 Snapshot 协议应该为 Maya Reference 和未来 USD Stage 保留组合来源字段。[OpenUSD Introduction](https://openusd.org/release/intro.html) · [USD Instancing](https://openusd.org/23.05/api/_usd__page__scenegraph_instancing.html)

### 3.4 Clinic：证据驱动的场景健康与修复

Clinic 不以大号“健康分”作为主界面。它把 Issue 组织成可调查的 Incident：

- 按共同根因、Reference、插件、发布目标和影响范围聚类；
- Issue 绑定 Evidence、Scope、Severity、Confidence、Scan Cost、Safe Fix 和 Verify；
- 点击 Issue 后 Atlas/Pulse/Delta 自动切换到相关证据；
- 修复形成 ChangePlan，逐项显示对象、属性、连接、文件边界和预期收益；
- 支持 apply、verify、rollback；不可撤销或危险操作必须走隔离副本；
- 规则 Profile 可按 Modeling、Rig、Animation、Lighting、Publish、Security 切换；
- 规则 SDK 兼容命令行、mayapy、CI 和团队配置。

## 4. 三条真正有辨识度的招牌工作流

### 4.1 Root Cause Lens：从症状自动构建最小证据路径

用户可从任何症状开始：一个慢帧、一个坏节点、一个 failed reference edit、一条日志错误、一个发布 Issue 或一个 Maya 选择。

系统随后：

1. 创建 Investigation Session，冻结相关 Snapshot 和环境条件；
2. 收集相关时间事件、上下游子图、Reference/Plugin 来源和近期变化；
3. 用 SCC、dominators、critical path、fan-in/out 和边界信息生成候选根因；
4. 以“最小解释路径”而非整张大图呈现；
5. 允许用户锁定、排除或提升某条假设；
6. 建议可验证实验，例如 mute 一个 deformer、停用一类 callback、切换 evaluation mode 或卸载一个 reference；
7. 保存实验结果并重新排序假设。

这里的“智能”首先来自正确模型和实验闭环，不依赖 LLM。LLM 后期可以把 Evidence Trail 转成解释或查询，但不得编造缺失证据。

### 4.2 Counterfactual Profiler：不只告诉哪里慢，而是验证改哪里有用

传统 Profiler 按耗时排名，但耗时最高的节点不一定是限制最终帧时间的节点。Coz 的 causal profiling 研究指出，普通 profiler 告诉程序在哪里花时间，却不一定告诉优化哪里会改善总体性能；其方法通过 virtual speedup 实验估算真正收益。[Coz 论文](https://arxiv.org/abs/1608.03676)

MayaScope 不直接复制 Coz，而是采用适合 Maya 的安全实验：

- Node/Module mute 或 `nodeState` 实验；
- 替换为 passthrough/cache/proxy 的临时实验；
- Reference load/unload、viewport visibility、evaluation mode 的控制变量实验；
- 对关键节点或子图做 synthetic delay / skip 候选，仅在可证明安全的 adapter 中启用；
- 多次运行、热身、固定时间区间，报告均值、分位数和噪声；
- 输出“若处理此子图，预计帧时间改善范围”，并明确实验条件。

这是 MayaScope 最有“底层味道”的能力之一，也比一个耗时排行榜更有价值。

### 4.3 Crash & Corruption Bisect：隔离进程中的自动二分调查

对打不开、随机崩溃或保存后损坏的场景：

1. 主工具生成只读调查计划和工作副本；
2. mayapy/Maya 子进程以 Safe Intake Profile 启动；
3. 按 Reference、顶层 DAG、Node Type、Plugin、Deformer 或最近变化做层级二分；
4. 每轮记录启动、打开、求值、保存、重开、退出码、stderr、crash log 和时长；
5. 用 delta debugging 思路缩小到最小失败集合；
6. 生成可共享 Repro Capsule，包含 SceneSnapshot、环境、插件清单、最小对象集合和实验记录；
7. 永不在用户唯一原文件上运行删除实验。

这条工作流直接替代社区中的“删除一半，保存，重开，再猜”。

## 5. 算法与数据结构方向

### 5.1 图分析不是装饰性 Node Canvas

| 算法/结构 | MayaScope 用途 | 备注 |
|---|---|---|
| Tarjan/Kosaraju SCC | DG/Evaluation 循环、反馈子图、循环压缩 | Tarjan 在线性 `O(V+E)` 时间完成；[原论文](https://www.ime.usp.br/~coelho/mac0323-2019/aulas/aula21/Tarjan-1972.pdf) |
| Condensation DAG | 把循环成分压成可分析 DAG | critical path 和层级布局的基础 |
| Dominator/Post-dominator | 找“所有影响路径必经”的控制点或切断点 | 适合关键依赖、污染传播与最小干预候选 |
| Topological/critical path | Evaluation 关键链、发布步骤和文件加载依赖 | 必须区分 wall time、CPU time 和并行调度 |
| Reachability + bidirectional BFS | 上下游、最短解释路径、影响域 | 使用 CSR/CSC 或压缩邻接结构 |
| Betweenness/bridge/articulation 候选 | 高风险桥接节点与跨资产连接 | 大图使用近似算法，不默认全量中心性 |
| Graph fingerprint / motif | 结构版本识别、重复网络、异常模式 | fingerprint 不能替代稳定身份 |
| Tree/graph edit matching | rename/rewire 与结构 diff | 采用分层候选、语义特征和置信度，避免全图精确同构 |
| Delta debugging | 崩溃/损坏最小失败集合 | 每次实验必须隔离、可复现、记录条件 |
| Change-point/outlier detection | 性能回归、callback storm、异常帧 | 先提供统计证据，不自动归因 |

### 5.2 大图数据模型

百万级 connection 不能为每个节点和边保留沉重 Python/Qt 对象。

建议基线：

- Node、Plug、Edge 使用连续整数 ID；名称、路径、类型和文件路径字典编码；
- DAG、DG、Evaluation、Reference 等关系分别存储，使用类型化 edge table；
- 上下游访问维护 CSR/CSC 类压缩邻接索引；
- UI 只拿当前 Scope 的 view model，不直接持有全图对象；
- Snapshot 不可变，Live Event 先进入 append-only delta log，再周期性合并；
- Issue、Profiler Event 和 ChangeSet 只引用稳定 ID，不复制对象；
- 磁盘格式需要 schema version、Maya/version/plugin/environment metadata；
- Arrow/SQLite/自定义二进制格式先通过真实基准比较，不在研究阶段拍脑袋锁定。

### 5.3 大图布局与动态稳定性

普通 force-directed layout 在大图上既慢又不稳定，每次刷新节点乱飞会摧毁 TD 的空间记忆。

采用分层策略：

1. 先按 Reference/Namespace/Asset/Node Type/Evaluation Cluster 聚合；
2. 远景使用 quotient graph；
3. 展开时只细化局部，并固定未变化区域；
4. DAG/Evaluation 优先 layered layout；局部关系调查可用 constrained force layout；
5. 动态更新采用 mental-map preserving layout，新增节点从父 cluster 或连接方向长出；
6. 边采用 bundling/聚合和按需显示，默认不画百万根线；
7. 只渲染可视区域和当前 LOD。

多层级 force-directed 研究已证明对十万级图比朴素方法更可行；动态多层图研究也专门处理在线增删节点的稳定布局。[Multilevel Graph Drawing](https://jgaa.info/index.php/jgaa/article/view/paper70) · [Dynamic Multilevel Graph Visualization](https://arxiv.org/abs/0712.1549)

## 6. 双进程产品形态

MayaScope 不应把全部计算和可视化塞进 Maya 主进程。

### 6.1 Probe：Maya 内嵌探针

- 轻量 WorkspaceControl；
- 当前 Scene 状态、Capture、Issue 数量、性能 HUD 和快速 Scope；
- Maya selection、Node Editor、Reference Editor 双向跳转；
- 受控 Callback、Profiler 和增量 Snapshot 采集；
- ChangePlan 的 Maya adapter、Undo、apply 和 verify；
- 主线程只做必要采集与应用，不承担全图布局和重分析。

### 6.2 Observatory：独立调查工作站

- 打开 Snapshot、Capture、Diff 和 Repro Capsule；
- 大图 Atlas、Pulse 时间线、Delta、Clinic 和 Investigation Notebook；
- Maya 崩溃后仍能查看最后一次捕获；
- 可同时比较多个场景、Maya 版本、机器或提交版本；
- 运行图算法、布局、统计和报告导出；
- 可以连接 Live Probe，但断开后仍可离线工作。

### 6.3 Runner：隔离与 CI 执行器

- mayapy/Maya batch 子进程；
- Safe Intake、Health Scan、Profiler Benchmark、Crash Bisect、Snapshot Diff；
- 明确超时、退出码、crash artifact 和临时目录；
- CI 返回机器可读结果，不依赖 GUI；
- 所有危险操作使用工作副本，保持源文件只读。

这三个表面共享 protocol，不共享 UI 状态。Probe 的轻量、Observatory 的视觉深度和 Runner 的可靠隔离组成完整产品。

## 7. 视觉与动态交互方向

### 7.1 物理使用场景

TD 在暗光制作环境中同时使用 Maya 和第二块显示器，正在接手一个陌生、卡顿或即将发布的场景。界面需要在长时间阅读中保持冷静，但在捕获、传播、回归和危险边界出现时产生足够强的视觉信号。

### 7.2 三条候选路线

| 路线 | 空间结构 | 气质 | 判断 |
|---|---|---|---|
| A. Spectral Causal Atlas | 全画布拓扑地图 + 底部 Trace Horizon + 可移动 Investigation Lens | 科学成像、地图学、因果传播；变化像天气系统在地图上显影 | **采用** |
| B. Black Box Flight Recorder | 多轨时间线占据中心，图和证据作为选中事件的展开面板 | 飞行记录器、事件回放、故障复盘 | 性能调查极强，但场景结构与 Diff 被降为次级 |
| C. Forensic Evidence Desk | Incident/假设/证据列为主，Atlas 和 Timeline 是证据附件 | 调查台、可审计、适合团队协作 | 太接近工单系统，不够突出 Maya 图与时间的技术优势 |

最终选择 **Spectral Causal Atlas（光谱因果地图）**，并吸收 B 的 Trace Horizon 与 C 的 Evidence Trail。

### 7.3 视觉路线卡

- **产品类型**：editor + monitor + investigation hybrid。
- **核心用户**：高频使用的 Maya TD；最高频动作是从一个症状缩小 Scope 并验证根因。
- **主要对象**：SceneSnapshot、Scope、Node/Plug/Edge、Time Range、Issue、Hypothesis、ChangePlan。
- **主工作区**：没有固定 Dashboard 首页；打开场景后直接进入 Atlas，当前 Scene 状态沿画布边缘形成 Context Frame。
- **标志性结构**：中央无边界 Atlas；底部可拉高的 Trace Horizon；查询和 Lens 形成可移动工具；Inspector 只在选择对象时从画布内展开，不长期挤占三分之一宽度。
- **信息密度**：远景中等、聚焦调查时高；Semantic Zoom 而不是把所有文字永久缩小。
- **与 MayaCraft 的差异**：MayaCraft 以角色 Viewport 为舞台、围绕身体和运动；MayaScope 以拓扑地图和时间地层为舞台、围绕证据与因果。两者不能复用同一三栏壳层。

### 7.4 视觉语言

- **基础表面**：冷钛蓝灰和接近黑色的墨色，不用纯黑；地图区域有极弱的等值线/空间分区，但不使用装饰网格。
- **主信号色**：电紫用于当前 Scope 与查询；灼橙用于回归、异常和跨边界变化；酸性黄绿用于 Live Capture/已验证路径；冰蓝用于只读结构。
- **颜色策略**：Full Palette，但每种颜色绑定固定数据角色。Node Type 不无限随机着色，使用形状、纹理和小面积标记共同编码。
- **节点**：远景是密度岛和边界轮廓，中景是紧凑 glyph，近景才成为带 Plug 的精确节点；不使用大圆角卡片。
- **边**：静态关系低对比，当前路径增强；Evaluation/dirty 传播使用短暂方向脉冲；跨 Reference 边穿过明显边界门。
- **时间**：Trace Horizon 像地层剖面，与 Atlas 的当前时间切片垂直联动。
- **文字**：清晰无衬线承担界面，等宽字体只用于路径、节点名、Plug、UUID、时间和日志。
- **数字**：持续时间、连接数、内存、样本和置信度固定小数规则，变化时短暂翻页/高亮，不做娱乐性滚动数字。

### 7.5 动态交互语法

- **Capture**：Atlas 边缘出现一次扫描波前，已采集 cluster 逐步清晰；扫描速度代表进度，不播放循环动画。
- **Semantic Zoom**：cluster 平滑分裂成子 cluster，再分裂成节点；标签密度离散切换，避免缩放时所有文字连续变形。
- **Trace**：选中慢帧后，实际 Evaluation 路径按时间顺序短暂点亮，随后停留为静态关键路径。
- **Dirty Storm**：传播频率转为局部闪烁/等值热区；reduced-motion 下改用纹理密度和数字。
- **Diff Morph**：保留节点位置；新增从来源边界长出，删除收缩为残影，rewire 显示旧/新边短暂分叉。
- **Hypothesis**：系统推荐的候选路径使用虚线和置信区间；完成实验后才变为实线证据。
- **ChangePlan**：影响域先在 Atlas 上扩散预览，用户确认后进入逐项执行；验证通过后路径由橙转为黄绿。
- **Lens**：按住快捷键出现径向 Lens Wheel，选择 Upstream、Downstream、Critical、Dirty、Reference、Runtime 等视角；松手后直接作用于当前 Scope。

动效必须允许中断、快进和关闭。常规控件反馈 100–200ms；图布局和 Diff morph 允许 250–500ms，但用户操作不等待动画结束。

## 8. Scene Query 与 Investigation Notebook

### 8.1 Query 不应要求所有 TD 学一种新语言

提供三层入口：

1. Natural Filter：`referenced skinClusters slower than 1ms`、`unknown nodes under selected asset`；
2. Visual Query Builder：类型、关系、方向、深度、属性、时间和聚合条件；
3. Text DSL：供高级 TD、自动化和 CI 使用。

自然语言只负责生成可见、可编辑的结构化查询，不直接执行隐藏逻辑。用户始终能看到转换后的 Query Plan、预计 Scope 和扫描成本。

Query 结果可命名为 Scope，并作为 Health、Profiler、Diff 或 ChangePlan 的输入。Neo4j Bloom 的 Perspective 证明同一图需要面向任务的类别、关系和样式集合，而不是只有一个万能图。[Neo4j Bloom](https://neo4j.com/docs/bloom-user-guide/current/)

### 8.2 Investigation Notebook 不是普通日志

每次调查自动记录：

- 起始症状、场景版本、Maya/OS/插件环境；
- 使用过的 Snapshot、Query、Scope、Time Range；
- 查看过的 Evidence 和被排除的假设；
- 运行过的实验、条件、测量与结果；
- ChangePlan、执行步骤、复检与回滚；
- 最终结论和 Repro Capsule。

Notebook 的每一项都可回到 Atlas/Pulse/Delta 的精确状态。这样 TD 的经验不再停留在聊天消息和记忆中。

## 9. 现有代码去留

| 现有部分 | 决定 | 处理方式 |
|---|---|---|
| `analyze_scene.py` | 保留需求，重写 | 提取 DAG/驱动/锁定属性采集需求；递归 UI 遍历替换为 Snapshot collector |
| `node_viewer.py` | 保留 Maya Node Editor adapter 思路，图模型重写 | Node Editor 变为一个跳转目标，不是 MayaScope 主画布 |
| `set_manager.py` | 并入 Ownership/Collection Lens | 不保留独立 Set Manager 产品页；Set 是一种关系和规则范围 |
| `py_analyzer.py` | 迁出主运行时 | Python 静态分析作为 Developer/Runtime source adapter，成熟后再接入 |
| `AnalyseAdv/` | 只作 MEL 研究夹具 | 不进入产品；可为 MEL symbol/source mapping 提供测试材料 |
| `mel-outline/` | 独立维护 | 通过 symbol/query protocol 与 Runtime Lens 联动，不塞进 Maya UI |
| `legacy/mayacraft_td` | 迁移参考后删除 | 不允许新架构依赖 legacy UI 或逻辑 |
| 当前全部 UI | 原型冻结，整体重做 | 需求可保留，空间结构和视觉语言不继承 |

## 10. 技术架构与风险

```text
Maya Probe
  collectors / callbacks / profiler / changes
                 │ versioned protocol
                 ▼
Snapshot & Event Store ── Query / Graph / Diff / Rules / Statistics
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
Observatory UI          Runner / CI
Atlas + Pulse + Delta   mayapy isolation
Clinic + Notebook       bisect / benchmark
```

### 10.1 UI/渲染技术必须先做基准切片

不可在研究阶段假定普通 `QTreeWidget`、`QGraphicsScene` 或嵌入网页能扛住目标规模。T1 前做四组技术试验：

1. 10k / 100k / 1M node-edge 的数据传输与内存；
2. QGraphicsView、Qt Quick/Scene Graph、自定义 GPU renderer 的平移、缩放、拾取和增量更新；
3. Timeline 对 100k / 1M event 的虚拟化；
4. Maya 内 Probe 与独立 Observatory 的协议延迟、断线恢复和版本兼容。

选择标准：不是初始 demo 最快，而是文本清晰度、HiDPI、拾取、稳定布局、离线打包、Maya 2024/2025 兼容和长期维护的综合结果。

### 10.2 Callback 与 Live Mode 风险

- 所有 Callback 必须集中注册、弱引用、可枚举、可暂停并确保卸载时移除；
- 事件风暴合并和节流，不能每个 `attributeChanged` 都重画全图；
- 明确区分“观察导致的性能成本”和场景本身成本；
- Capture 显示 dropped/coalesced event，不制造虚假完整性；
- Live Mode 默认限制 Scope，完整 Snapshot 明确由用户触发；
- Maya 正在 file I/O、undo/redo 或 shutdown 时采用专门状态机。

## 11. 开发优先级

### Phase A：Forensic Slice，证明因果调查闭环

选择一个真实的慢 Rig/坏场景，完成：

1. SceneSnapshot：DAG、DG、Reference、Plugin、基础 Evaluation metadata；
2. Scene Atlas：聚合、Semantic Zoom、上下游与循环；
3. Pulse：导入 Maya Profiler，选择区间联动 Atlas；
4. Root Cause Lens：从慢帧生成关键子图和候选原因；
5. 一个安全实验，例如 mute expression/deformer 后重复 benchmark；
6. before/after Delta 与 Evidence Trail；
7. Probe + Observatory 最小双进程链路。

成功标准：TD 能从“这段回放慢”走到一个可重复验证的根因，不打开五个 Maya 窗口，也不手工删除场景内容。

### Phase B：Scene Health 与 ChangePlan

- Rule/Issue/Evidence/ChangePlan/Verify 协议；
- Reference、Namespace、Unknown Node、Plugin、Callback、Expression 高价值规则；
- 批量修复预览、Undo 与隔离副本；
- 命令行和 CI 结果；
- Investigation Notebook 和报告。

### Phase C：Performance Observatory

- 完整 Trace Horizon、thread/category/evaluation tracks；
- Critical Path、Serial Island、Dirty Storm、Callback Storm；
- 多 Capture 统计比较与回归门槛；
- Counterfactual Profiler 的安全实验集；
- Maya 2024/2025/不同机器基准归一化策略。

### Phase D：Delta 与 Crash Lab

- 稳定身份、结构匹配、Reference-aware Diff；
- 性能回归关联结构变化；
- mayapy/Maya 子进程隔离、Crash & Corruption Bisect；
- Repro Capsule 和自动最小化；
- 保存/重开验证和 crash artifact 收集。

### Phase E：Runtime 与 Pipeline SDK

- scriptNode、scriptJob、Callback、expression、plugin execution inventory；
- MEL/Python symbol 与运行对象关联；
- MEL Outline protocol；
- 自定义 Collector、Lens、Rule、Analyzer、Experiment SDK；
- USD Stage、OpenUSD composition 与外部 DCC snapshot adapter。

## 12. 明确不做什么

- 不用一个“Scene Health 83 分”掩盖复杂问题；任何摘要都必须能展开到证据。
- 不把 DAG、DG、Evaluation 和 Reference 粗暴画成同一种边。
- 不默认画全场景所有节点；大图的价值来自 Scope、聚合和路径，而不是视觉噪声。
- 不在 Maya 主线程做全图算法、布局或危险二分实验。
- 不提供没有 ChangePlan、影响预览、Undo/隔离和复检的一键清理。
- 不承诺识别所有崩溃根因；工具输出候选、实验和置信度，并保留未知状态。
- 不把 LLM 解释当作证据；模型只能操作结构化查询或总结已采集事实。
- 不变成完整 Asset Manager、Farm、Launcher 或项目管理系统。
- 不复制 MayaCraft 的角色中心舞台、霓虹骨架和 Motion 交互。

## 13. 产品成功指标

### 调查效率

- 对标准测试场景，TD 在 5 分钟内从症状形成可验证的 Top-3 根因假设；
- 高频调查不需要同时打开 Evaluation Toolkit、Profiler、Node Editor、Reference Editor 和 Script Editor；
- Evidence Trail 可以被另一名 TD复现，不依赖口头说明。

### 分析质量

- 每个自动结论带来源、Scope、条件、置信度和反证入口；
- 性能建议通过重复实验报告收益区间，而非只按耗时排序；
- Scene Diff 能区分 rename、rewire、reference update 和 local edit 的主要案例；
- Crash Bisect 永不修改原文件，并能输出最小可疑集合与完整实验记录。

### 规模与响应

- 10 万节点/100 万连接 Snapshot 有明确采集、内存和磁盘预算；
- Atlas 常规平移/缩放目标 60 Hz，重图最低 30 Hz；
- 首个可操作概貌优先出现，完整分析渐进完成；
- 长任务可取消，Maya 主线程保持响应，Live Probe 清楚报告自身开销。

### 生产可靠性

- Snapshot、Capture、Issue、ChangePlan 和 Report 均有版本化 schema；
- Maya 2024/2025 通过真实 GUI/mayapy 场景验证；
- Callback 零泄漏，工具卸载后不留 scriptJob 或未知状态；
- 所有写操作具备 Undo、工作副本或明确不可逆边界。

## 14. 下一轮应做什么

本轮已经确定 MayaScope 的产品方向。下一轮应该进入 **Forensic Slice 交互与技术验证**，而不是继续扩充检查规则：

1. 选一个慢 Rig、一个 Reference 污染场景和一个 crash/corruption 夹具；
2. 定义 SceneSnapshot v0、稳定身份、typed edge 和 Profiler event schema；
3. 制作三张高保真关键界面：Scene Atlas、Pulse/Root Cause Lens、Crash Bisect；
4. 实现 10k/100k/1M 图渲染基准，决定 Observatory renderer；
5. 验证 Maya Probe 到独立 Observatory 的最小协议；
6. 走通一次“症状 → 证据 → 假设 → 实验 → Diff → 验证”英雄流程。

后续所有功能都应回答一个问题：它是否让 TD 更快、更可靠地建立和验证因果解释。如果只是多一个列表、按钮或统计数字，默认不进入主产品。
