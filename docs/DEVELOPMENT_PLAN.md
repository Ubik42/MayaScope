# MayaScope 开发计划

状态：MayaIndieTool 重命名与重新定位后的基线计划  
日期：2026-08-25  
产品定位：面向 Maya Technical Director 的场景理解、诊断、性能分析和安全操作平台

当前实现进度（持续更新）：SceneSnapshot、基础 Scene Atlas、Issue Evidence、
安全 ChangePlan、Snapshot Store、Scene Delta 与 Structural Root Cause Lens 已落地。
Scene Pulse 现已接入 Maya 2025 Profiler v2 的真实事件、可拖选时间窗和 Atlas 热度；
Root Cause Lens 会把窗口内观察到的包含耗时、事件数与覆盖率叠加到结构证据上，且不把
嵌套 Profiler 耗时冒充优化收益。Scene Clinic 已完成第一阶段规则注册表、逐规则故障隔离、
动态 Rule Array，以及带宿主后置验证和精确 Undo 栈保护的 ChangePlan apply/verify/rollback
闭环，并已实现规则 Profile、Incident 聚类和更完整的 TD 诊断规则。
现已进一步加入 Rig/Animation/Publish Rule Profile、第一类 Reference snapshot/delta、
卸载引用与 failed edit 等六类诊断，并按共享身份、Reference、Namespace 和直接 DG 邻接
生成确定性的 Incident。
严格 JSON 团队配置与版本化 RulePack SDK 现已完成：配置拒绝重复键、未知字段、超限内容
和任何 Python hook，UI 显示配置指纹或整体回退状态；受信 Python 包只能由宿主显式传入。
Incident 级批量 ChangePlan 现可按稳定身份去重、拒绝冲突、在一个 Undo chunk 中执行并
逐项复检源 Finding。Counterfactual Profiler 的配对 AB/BA 实验、bootstrap 区间、
nodeState 安全适配、状态/Undo 恢复、Atlas 差异场和校验档案也已形成完整纵向闭环。

Crash Bisect 纵向闭环现已落地：版本化 Plan/Attempt/Capsule、可取消 ddmin、Snapshot 与
`.ma` 文本候选规划、源 SHA-256 复核、独立工作副本、隐藏串行 mayapy worker、阶段进度、
timeout/crash 结果回收和 Failure Prism 轨迹 UI 均已通过 Maya 2025 验证。安全 `.ma` slicer
能在 Maya 打开前移除 DAG/Reference 候选，并以故障注入证明初始 open timeout 可收敛到单一
候选；`.mb` 仍明确限定为 post-open evaluate/save/reopen isolation。下一步进入 Runner 的
批处理入口、插件/环境清单与可移植 Repro Capsule。Runner 断点恢复已经完成：每次 Probe
之后原子写入带校验 Journal，恢复时把既有 outcome 注入 ddmin cache，保证不重跑已知集合。
JSONL 批处理入口现已支持 `.ma` 的 plan/run、Journal resume 与 Capsule verify，并使用明确的
0/1/2 退出码；每个成功初始化的 Probe 还会记录 Maya/API、Evaluation、单位与 loaded plugin
指纹。下一步集中完成 Maya Module 安装、启动自检、用户级运行日志和故障恢复文档。
用户级 Maya 2025 Module 安装/升级/可恢复卸载、隐藏 Doctor、滚动 JSONL 日志与
`OPERATIONS.md` 现已落地并通过临时目录和真实 Maya 2025 验证；当前用户配置保持未安装。
下一步加入 Shelf/菜单入口、工作区内非阻塞健康状态与版本化发布/演示包。
会话级幂等 Maya 菜单、显式 opt-in Shelf、动态 Host Beacon、确定性 Release Manifest/ZIP
和真实 Maya 2025 Showcase 场景现已落地。Showcase 经 MayaScope 自身采集验证 156 节点、
176 条边、7 个 Clinic 结果与安全 Counterfactual target；发布验证器逐文件校验并拒绝未清单内容。
Release ZIP 干净安装回放现已落地：最终包被解压到隔离目录，通过受管 Module 被真实 Maya 2025
首次加载；子进程不注入开发 `PYTHONPATH` / `MAYA_MODULE_PATH`，并核对实际包来源。回放随后完成
可恢复卸载、备份恢复、最终卸载和临时环境清理。下一项架构优先级是渐进拆分 5500 行
`ui/workspace.py`，先提取 Presentation State 与独立工作区模块，不重写已验证的自绘组件。
Presentation 拆分第一阶段现已完成：新增宿主无关、不可变 `WorkspacePresentationState`，把场景、
诊所、异常/事件选择、根因焦点、Profiler、Runtime、Delta 与反事实证据组织成显式语义转换；三个
QObject Worker 已迁出主窗口模块。兼容属性让现有视觉行为保持不变，`ui/workspace.py` 仍有 5414 行，
下一阶段继续提取 UI Foundation 和独立业务工作区，不能把本阶段描述成重构完毕。

当前宿主策略：展示版只以 Maya 2025 + PySide6 为开发和验收基线。先把一个版本的
视觉完成度、动态交互和可靠性做深，不并行维护 Maya 2024/PySide2；核心数据与算法
仍保持宿主无关，产品成熟后再根据真实需求决定兼容范围。

Maya 与 Atlas 的选择上下文现已双向联动：一个生命周期安全的 SelectionChanged callback
负责宿主观察，工具写回采用精确回声抑制，关闭时移除；长 DAG 路径与唯一节点名在 Clinic
后台预建为不可变稳定 ID 索引。十万节点索引与千次查询均通过明确性能预算。

> T0 市场、社区、算法与视觉方向研究已经完成。产品决策以
> [RESEARCH_TD_PRODUCT.md](RESEARCH_TD_PRODUCT.md) 为准：MayaScope 定位为
> Causal Scene Observatory，由 Scene Atlas、Pulse、Delta、Clinic 四个共享
> 调查上下文的仪器组成；Root Cause Lens、Counterfactual Profiler、
> Crash & Corruption Bisect 是三条招牌工作流。视觉采用 Spectral Causal Atlas，
> 产品形态采用 Maya Probe + 独立 Observatory + Runner/CI。

## 1. 产品判断

MayaScope 不是零散脚本箱，也不是另一个 Node Editor 皮肤。它应该让 TD 看清 Maya 场景内部正在发生什么：DAG、DG、Evaluation Graph、引用、插件、表达式、回调、数据体积、脏传播、性能和结构变化，并把发现的问题转化为可解释、可预览、可批处理的修复计划。

一句话定义：**MayaScope 是 Maya 场景的可交互检查器、分析器和调试器。**

## 2. 明确边界

### 属于 MayaScope

- DAG/DG/Evaluation Graph 的采集、查询、分析和可视化；
- 场景健康检查、规则引擎、结构差异和修复计划；
- 节点、属性、连接、引用、命名空间、Set、Layer、Plugin 与 Callback 诊断；
- Maya 性能采样、热点定位、dirty propagation 和时间轴事件分析；
- 面向 TD 的安全批处理、审计报告、图查询和流水线扩展 API；
- MEL/Python/Maya 节点系统的静态与运行时辅助分析。

### 不属于 MayaScope

- 角色自动绑定、蒙皮权重和动画制作工作流；
- 资产管理系统、农场调度器或完整 DCC Launcher；
- 没有分析模型、证据和回滚方案的“一键清理”；
- 仅把 Maya 命令重新包装成按钮。

绑定与动画能力统一进入 MayaCraft。

## 3. 当前迁移基线

### 原 MayaIndieTool 原型

| 原型 | 处理方向 |
| --- | --- |
| `analyze_scene.py` | 提取 DAG 采集需求，UI 和递归实现重写 |
| `node_viewer.py` | 提取连接采集、图导出和 Node Editor 操作需求 |
| `set_manager.py` | 并入 Scene Collections/Ownership 检查，不保留独立产品定位 |
| `py_analyzer.py` | 与 Maya TD 核心关系弱，调研后决定迁出或转为开发者工具 |
| `AnalyseAdv/` | 作为 MEL 静态分析研究材料，不进入运行时 |
| `mel-outline/` | 可独立发布；与 MayaScope 通过导出格式/API 连接 |

### 从 MayaCraft 迁入的 TD 原型

旧 `ui/td` 与 `core/logic/td` 已移入 `legacy/mayacraft_td/`。这些文件：

- 不进入 MayaScope 运行时；
- 不作为目标架构的模块边界；
- 只用于功能盘点、交互对照和迁移测试；
- 被新实现覆盖后逐项删除，不长期双轨维护。

## 4. 目标架构

```text
MayaScope/
├─ model/             SceneSnapshot、Node、Plug、Edge、Reference、Issue
├─ collectors/        DAG、DG、Evaluation、Plugin、Callback、File 等采集器
├─ query/             图查询、过滤语言、索引与增量查询
├─ analysis/          图算法、性能分析、规则、差异和根因解释
├─ actions/           ChangePlan、preview、apply、verify、rollback
├─ adapters/maya/     Maya API 2.0、cmds、profiler 与 UI 适配
├─ visualization/     图、时间线、热力图、矩阵和详情联动
├─ features/          scene_health、graph_lab、profiler、diff、plugins
├─ ui/                工作区与交互，不包含采集/分析业务实现
├─ protocols/         snapshot/report/query 的版本化格式
├─ tests/             unit、mayapy、scenes、benchmarks
└─ legacy/            迁移材料，不进入运行时
```

### 4.1 统一场景模型

- 采集结果形成不可变或版本化 `SceneSnapshot`，不让 UI 直接遍历 Maya；
- DAG parent/child 与 DG plug connection 分开建模；
- 节点使用 UUID、reference identity 与 path 组合识别，避免单靠名字；
- 支持增量 snapshot，只更新 Maya 事件影响的子图；
- 所有 Issue、图节点和性能样本都能回跳到真实 Maya 对象；
- snapshot 可序列化，用于离线比较、Bug 附件和 CI。

### 4.2 图与根因分析算法

候选能力包括：

- Tarjan/Kosaraju SCC 检测循环依赖和反馈子图；
- topological condensation、关键路径与层级布局；
- fan-in/fan-out、中心性、桥接点和异常子图识别；
- 基于节点类型、属性模式和连接 motif 的网络模式检测；
- 从错误节点向上游进行最小解释路径和影响域追踪；
- graph fingerprint 与结构 diff，区分 rename、rewire、add/remove；
- reference/namespace/instance-aware 的图身份与跨文件边界；
- 大图的分层聚合、按需展开和虚拟化，而不是一次绘制全部节点。

### 4.3 性能与 Evaluation 分析

- 采集 Evaluation Manager、Maya Profiler、DG 计算和时间轴样本；
- 关联节点耗时、调用次数、脏传播来源、缓存命中和线程行为；
- 识别串行化节点、过度 dirty、重复表达式、昂贵 deformer 和 callback 风暴；
- 用 flame/timeline/heatmap/critical-path 多视图解释同一份样本；
- 对比两个场景版本或两个时间区间的性能回归；
- 将“慢”解释成可验证的根因假设，而不是只列耗时排行榜。

### 4.4 Scene Health 与规则引擎

- 规则包含 scope、evidence、severity、cost、safe-fix 和验证函数；
- 支持节点/属性/连接/文件/引用/插件/命名空间/单位/色彩空间等规则；
- 规则可以是声明式查询，也可以是受控 Python 扩展；
- 扫描结果去重、聚类，并显示为何命中、影响范围和修复代价；
- 修复先产生 `ChangePlan`，显示将修改的对象和连接；
- 批量修复进入 Undo Chunk，完成后重新扫描验证；
- 可输出人读报告和机器读 JSON，用于发布门禁。

### 4.5 动态交互与可视化

目标不是“生成 Mermaid 文本”，而是建立联动的分析工作区：

- Graph Canvas：LOD、聚类、稳定布局、框选、路径追踪、上下游透镜；
- Inspector：属性、连接、来源、引用、历史样本和规则证据；
- Timeline：性能样本、callback、dirty/evaluation 事件和选择联动；
- Heatmap：按耗时、内存、连接度、issue 或 dirty 频率着色；
- Diff View：左右场景/版本同步浏览，结构变化动画；
- Query Bar：可保存查询、即时高亮、结果作为后续分析输入；
- Live Mode：监听有限事件并增量更新，带节流、暂停和事件丢失提示；
- 所有视图共享 selection model，Maya 选择与工具选择可双向同步；
- 大场景必须采用后台采集、分批传输和可取消任务，Qt 主线程只渲染。

## 5. 候选产品工作区

```text
MayaScope
├─ Overview          场景规模、健康度、引用、插件和关键风险
├─ Graph Lab         DAG/DG/Evaluation 的查询与交互图
├─ Performance       Timeline、热点、关键路径和回归对比
├─ Scene Health      规则、证据、ChangePlan 和发布门禁
├─ Diff              Snapshot/场景版本的结构与属性差异
├─ Runtime           Callback、scriptJob、expression、plugin 状态
└─ Reports           快照、报告、复现包与 CI 输出
```

## 6. 开发阶段

### T0：迁移与产品研究（已完成，2026-08-25）

- 完成旧代码能力盘点和去留表；
- 调研 Maya DG、Evaluation Manager、Profiler 与 API 能力边界；
- 调研 Node Editor、Bifrost、Houdini Network、Unreal Insights、Nsight 等交互范式；
- 定义首个目标用户场景和三个可量化痛点；
- 确认 Python/Qt 图形方案是否足够，哪些视图需要原生或 WebGPU/Canvas；
- 产出数据规模和性能预算。

完整结论见 `docs/RESEARCH_TD_PRODUCT.md`。下一阶段先做 Forensic Slice，
走通“症状 → 证据 → 假设 → 实验 → Diff → 验证”，不先铺满检查规则或工具页。

### T1：Snapshot 与 Query Kernel

- 实现无 UI 的 SceneSnapshot、DAG/DG collector 和稳定身份；
- 建立图索引、查询 API、序列化和结构 diff；
- 用小/中/大三档场景建立正确性与性能基准；
- 先用文本/JSON 验证模型，不急于做最终画布。

状态：核心纵向闭环已完成。Query Kernel 使用双向整数 CSR、共享快照索引、有界邻域缓存与显式
失效；查询支持 node/edge/depth/deadline/cancel 边界。2026-08-25 本机百万唯一边基准为索引
0.93 s / 32.25 MiB、5,000 节点冷查询 2.09 ms、缓存命中 0.009 ms。预算固定为索引 <5 s、
估算常驻索引 <128 MiB、受限冷查询 <50 ms、缓存查询 <5 ms。

重复捕获已加入精确 payload reconciliation 与 QueryKernel alias。共享拓扑必须同时满足稳定节点顺序
一致且由 collector 复用同一个 edge tuple；不使用概率 fingerprint。百万边未变化快照的双索引 alias
为 8.1 ms、Clinic 预热 0.029 ms；单边 rewire 会拒绝 alias 并完整重建。

### T2：Scene Health

- 规则协议、Issue 证据模型和 ChangePlan；
- 实现一组高价值且可验证的规则；
- 建立扫描、预览、修复、复检闭环；
- 提供 CI/发布门禁的命令行入口。

状态：规则阵列、事件聚类、安全 ChangePlan 与隐藏发布门禁已形成闭环。2026-08-25 新增
Snapshot v3 `SceneSettings` 与配置化 `scene-contract`：Maya 2025 可采集时间单位/精确 fps、
线性/角度单位、上轴、色彩管理、渲染空间、视图变换和 OCIO 路径；Clinic 配置 schema 2 可
声明项目要求并生成中文偏差证据。规则只在团队显式配置时出现，不把单一工作室标准硬编码为
普遍真理。真实隐藏 Audit 已对 pal / m / rad 夹具返回确定性发布门禁，普通测试 130 项全绿。

同日继续完成外部依赖纵向闭环：Snapshot schema 4 建模 Maya 注册路径，`missing-external-files`
与 `nonportable-external-files` 进入发布入口，依赖变化进入 Delta/Atlas，完整记录进入 Audit。
真实 Maya 2025 的 1000 个缺失 UDIM 基准为 0.377 秒（含首尾一致性复核）且无身份/序列标记丢失；普通测试扩展到
134 项。后续需要用已安装的 USD/Arnold/缓存插件场景继续扩大注册类型夹具，不能把核心 file
节点验证夸大成所有第三方插件均已实测。

场景生命周期也已从路径身份中拆出：Snapshot schema 5 记录 modified、文件类型、工作区和时间
范围；发布入口新增 `unsaved-scene-changes`。Audit 接受显式 `--workspace`，否则发现最近
`workspace.mel` 或回退场景目录，不再拿隔离临时 Project 判断路径可移植性。真实 Maya 测试覆盖
保存后 clean、属性修改后 dirty 以及 Audit 打开磁盘场景 modified=false。

分片捕获现已增加首尾 host-context signature：设置、生命周期、plugins-in-use 与刷新后的 Maya
路径注册表必须完全一致，否则拒绝快照。真实测试覆盖 fileTextureName 与 time unit 在捕获中途
变化；这仍不等于捕获了所有任意数值属性变化，后续需要评估 API callback 成本与按高风险属性
抽样复核，不能宣称完整事务隔离。

Audit Regression 已加入 `atomic_subjects`：聚合 UI Issue 不再牺牲依赖级/策略字段级回归精度。
同节点第二条依赖、场景级不同契约偏差都有独立 new/resolved Finding；workspace 与关键场景设置
不一致会拒绝比较。普通 Python 回归扩展到 141 项，真实 collector 10 项全绿。

项目级发布门禁已完成第一条生产纵切：`project_audit` 验证并内嵌多个单场景签名报告，强制统一
Profile、规则配置、Maya 与工作区上下文，确定性汇总严重级、规则和原子 Finding，并对整个包增加
第二层 SHA-256。Spectral UI 的中文“项目发布列车”直接读取真实校验包，以可点击审计舱展示
场景通过/阻断并把双层签名送入问题证据栏。普通 Python 回归扩展到 146 项；两个真实 Maya 2025
发布 Audit 已聚合为 2 场景、2 阻断、4 原子 Finding 的项目证据。

项目门禁现在可从场景清单直接执行：`project_queue` 以签名计划锁定场景/配置内容，严格串行调用
隐藏 Maya，并在每个场景边界原子写入签名断点。安全暂停、异常 `运行中` 恢复、失败重试、已完成
报告复用、源/配置漂移拒绝和最终项目包生成均有自动化覆盖。中文发布列车增加待运行、运行中、
通过、阻断、失败五种真实状态以及“安全暂停/继续队列/打开项目结果”闭环。普通 Python 回归扩展
到 153 项；真实 Maya 2025 已完成 1/2 暂停后恢复，两个场景各运行一次。

批量队列的首个生产缺口已关闭：跨进程内核锁和可读租约保证单一所有者；按卷容量预检在 Maya
启动前 fail closed；Windows Job Object 把子 mayapy 生命周期绑定到父进程，精确身份恢复器只在
PID、启动 ticks、可执行文件和队列归属全匹配时处理遗留孤儿。中文发布列车实时显示容量余量、
后台 PID 和崩溃联动状态。普通 Python 回归扩展到 161 项；真实 Maya 2025 已验证运行态、安全暂停、
并发拒绝与亲自创建的孤儿 mayapy 回收。下一步继续扩大高价值 Scene Clinic 规则覆盖和制作场景校准。

Scene Clinic 已补齐缺失插件根因纵切：Snapshot schema 6 建模 Maya unknown plug-in registry，
节点元数据反查原插件与原始类名；`missing-plugin-requirements` 与 `unknown-nodes` 分别表达根因和
降级结果，并通过稳定身份聚成事件簇。插件登记变化进入 Delta，签名 Audit 保留完整插件/版本/类型，
中文两层“制片信号”阵列提供可点击的“插件幽灵”入口。5000 条登记的普通 Python 性能合同通过；
普通回归 167 项全绿，真实 Maya 2025 collector 11 项全绿。下一步优先做引用解析健康、namespace
归属冲突和缓存类第三方注册路径夹具，不把单一自生成 missing plug-in 夸大成所有商业插件均已验证。

引用解析健康纵切现已完成：Snapshot schema 7 区分实例路径、unresolved path、canonical source、
复制编号和存在状态；同一源文件的 `{1}` 不再污染身份与统计。明确缺失引用和本地节点侵入引用
namespace 分别进入确定性 Clinic 规则，reference inventory 进入签名 Audit，解析字段进入 Delta。
中文“引用轨道”把实例/源文件/缺失/越界压缩成可点击光谱信号，并联动 Evidence Rail 与 Atlas
因果域。普通 Python 173 项、真实 Maya 2025 collector 12 项全绿；5000 reference namespace 性能
合同通过。UNC 可达性仍明确留给有 timeout isolation 的 Runner，不能在 Maya 主线程冒充已验证。

缓存与序列依赖展示纵切现已收口：Snapshot schema 8 对 Maya 注册的 `<UDIM>`、`<UVTILE>`、
`<f>`、hash 与 printf 序列保存有界成员清单；确定性识别已观测编号跨度内部空洞，并将完整性变化
带入 Delta、签名 Audit 与中文“依赖谱系”。算法不依赖安全 Audit 禁用的 UI scriptNode 播放范围，
不推断首尾帧；网络、环境变量、超时和超条目预算保持未知。普通 Python 180 项、真实 Maya 2025
collector 12 项全绿，5,000 条目目录能在 256 条目预算处停止。展示版到此停止扩大规则范围，后续
优先补真实 GUI 短生命周期、安装复演与 Maya 2024 验证。

真实 GUI 生命周期缺口现已关闭：新增独立 Maya GUI 探针，以隔离首选项、隐藏窗口、精确 PID 与
有界超时通过真实 `MayaWindow` 父子关系加载产品入口。首次绘制、重复启动、开发热重载、选择回调、
9 个动态计时器归零、菜单卸载和退出均已在 Maya 2025.3.3 通过；启动前已有 Maya 进程保持原身份。
本轮同时修复开发热重载先覆盖模块全局、导致旧窗口失联的真实泄漏风险。下一步优先做“从发布 zip
解压 → 隔离 Module 安装 → Maya GUI 启动 → 卸载恢复”的干净安装复演。

### T3：Graph Lab

- 分层图、路径追踪、聚类与稳定布局；
- Maya 选择联动、上下游透镜和详情检查器；
- 大图虚拟化、增量更新、取消和进度；
- 支持 DAG、DG 与 Evaluation 视角切换而不混淆语义。

状态：Atlas、Root Cause Lens 与共享 Query Kernel 已联动；Lens 显示实际扫描节点、边、耗时与
截断原因。完整百万节点布局与视图虚拟化仍属于后续工作，不能用百万边查询基准替代渲染验收。

### T4：Performance

- Profiler/Evaluation 数据采集与统一时间模型；
- Timeline、热点、关键路径、dirty 传播与回归比较；
- 建立真实复杂场景基准和分析准确性验证；
- 输出可共享的轻量复现报告。

### T5：Runtime 与开发者能力

- Plugin、callback、scriptJob、expression、unknown node 诊断；
- MEL/Python 源码符号与场景运行对象的关联；
- 可扩展 query/rule/analyzer SDK；
- MEL Outline 独立发布及协议集成。

### T6：制作化

- Maya Module 安装、多版本兼容、崩溃恢复和日志；
- Snapshot/Report 格式版本迁移；
- 文档、样例场景、性能预算和发布检查；
- 真实 TD 使用测试和 API 稳定策略。

## 7. 质量门槛

- 分析必须基于 snapshot/model，不允许 UI 随意重复查询整场景；
- 每个 Issue 必须携带可验证证据和稳定对象身份；
- 修复必须先形成 ChangePlan，并有 Undo 或明确不可逆边界；
- 图算法和 diff 必须有构造图单元测试；
- 采集器必须覆盖 reference、instance、namespace、unknown node 和断连 plug；
- 大场景功能必须有时间、内存和 UI 响应预算；
- Live Mode 不得因 callback 泄漏或事件风暴拖慢 Maya；
- 当前只对 Maya 2025 API 做实际宿主测试；扩展版本支持前必须增加对应宿主夹具；
- legacy 代码不得被新模块反向依赖。

## 8. 第一性成功指标

- TD 能在几分钟内理解陌生场景的结构、风险和主要性能瓶颈；
- 工具能说明“为什么这是问题、影响谁、怎样验证修复”，而不只是列节点；
- 百万级连接或大型制作场景仍可渐进浏览，不冻结 Maya；
- 场景版本差异和性能回归可以被保存、比较并进入 CI；
- 新分析器复用统一模型、查询和可视化，不再复制一套窗口和 `cmds` 遍历。
