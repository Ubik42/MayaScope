# MayaScope Codex `/goal` — 持续快速开发

下列提示词挂载整个 MayaScope v1 产品开发。单个纵向切片只是里程碑，不能作为 `/goal` 的完成条件。

```text
/goal 持续快速开发 D:\3D\_tools\MayaScope，直到达到可供 Maya TD 日常生产使用的 v1 产品标准；不得把单个纵向切片、一次测试通过或一轮对话视为整个目标完成。以 PRODUCT.md、docs/RESEARCH_TD_PRODUCT.md、docs/DEVELOPMENT_PLAN.md 和已确定的 Causal Scene Observatory 定位为产品约束，持续推进 Scene Atlas、Root Cause Lens、Scene Pulse、Scene Delta、Scene Clinic、Counterfactual Profiler、Crash/Corruption Bisect、批处理 Runner、快照持久化与对比、可扩展诊断规则和安全 ChangePlan 系统。每轮优先选择价值最高且能够真实运行、演示、测试的纵向闭环，直接阅读现有代码并实现，不做只有界面的占位功能，不进行无边界推倒重写；保留并适配用户已有修改，逐步隔离 legacy。架构上保持普通 Python 核心与 Maya/Qt 宿主适配层分离，使用稳定节点身份、显式数据契约、可取消或分片的大场景任务、结构化错误与日志；所有场景修改必须先预览，提交时重新验证身份和引用状态，处于明确 Undo/事务边界，并在执行后重新采集验证。当前展示版只以 Maya 2025 + PySide6 为宿主与 UI 验收基线，不为同步兼容 Maya 2024/PySide2 分散开发；持续运行普通 Python 单元测试、Maya 2025 mayapy/离屏 GUI 宿主测试和明确的大场景性能基准。视觉和交互是核心产品能力：坚持现代、炫酷、鲜明、动态、具有独立辨识度的 Spectral Causal Atlas 方向，给予实现充分创作自由，避免旧式标签页、按钮堆叠及沉闷同质化 Dashboard，同时保证状态反馈、渐进披露、键盘操作和高 DPI 可用性。每个里程碑完成后更新文档和下一优先级并继续开发；只有当 v1 核心调查闭环全部可用、Maya 2025 验证完成、性能与安全门槛通过、安装/启动/故障恢复文档齐备且不存在阻断生产使用的问题时，才可将整个 /goal 标记为 complete；暂不可用的外部条件应记录缺口并继续完成其他不受阻部分，不得因此提前结束目标。
```

## 持续执行约束

- 每一轮开始先定义一个用户可以亲手验证的调查任务，再落核心、宿主边界和界面。
- Maya API 与 Qt 只能出现在适配层；算法、证据规则和 ChangePlan 必须能用普通 Python 测试。
- 诊断结果必须包含节点身份、因果关系和证据，不接受只有红黄绿分数的黑盒健康度。
- 场景修改默认只预览；执行前复核对象与引用状态，执行时进入一个 Undo chunk，执行后重新采集验证。
- 可视化追求鲜明、动态和工具独有的仪器感。规则是质量护栏，不是把设计收敛成同一种克制 Dashboard。
- 性能优化以可重跑基准为依据；大场景必须支持折叠、筛选、增量和取消，不能冻结 Maya 主线程。

## 整体完成条件

只有同时满足以下条件，才允许结束 `/goal`：

1. v1 核心调查闭环全部真实可用，不存在只有界面的占位模块。
2. Maya 2025 的 mayapy 和离屏/真实 GUI 验证完成。
3. 大场景性能、安全修改和故障恢复门槛通过。
4. 安装、启动、诊断、恢复和扩展规则文档齐备。
5. 不存在阻断 Maya TD 日常生产使用的问题。

## 第一里程碑验收（已完成）

1. Maya 场景可采集为可序列化且经过一致性校验的 `SceneSnapshot`。
2. Scene Atlas 可呈现 DG/DAG 拓扑并支持缩放、拖动、搜索和证据高亮。
3. 至少检测 unknown 节点、DG 环、高扇出与跨引用连接。
4. unknown 节点可以生成保护引用节点的 ChangePlan，并完成预览、Undo 与重新扫描。
5. 普通 Python、Maya 2025 mayapy 和 PySide6 界面烟雾测试通过。
6. 10,000 节点图算法基准不使用递归且不退化为平方复杂度。

## 第二里程碑验收（已完成：Structural Root Cause Lens）

1. Maya 当前选择或 Atlas 节点可以成为调查焦点。
2. Upstream 与 Impact 模式提供有深度上限的最短因果路径。
3. 候选包含 DG 距离、分支、节点类型、Issue 和 Reference 边界的透明评分构成。
4. Atlas 对候选、焦点和真实 Plug 路径采用不同形状/标签/颜色状态并提供动态路径。
5. 明确声明 Structural Signal 不是 Profiler 测量值或根因概率。
6. 10,000 节点 Lens 性能契约、PySide6 和 960px 紧凑布局验证通过。

## 第三里程碑验收（已完成：Snapshot Store + Scene Delta）

1. 快照使用 gzip、SHA-256 校验和与同目录原子替换持久化，失败不留下半文件。
2. Store 拒绝目录逃逸并在载荷被修改时明确报错。
3. Scene Delta 按稳定 UUID 区分 add/remove/rename/modify、连接增删和 rewire。
4. 连续 Capture 可立即显示 Delta Field；历史 Archive 可以与当前场景只读比较。
5. Atlas 对新增、修改和 rewire 使用不同视觉状态，删除对象保留在 Evidence 摘要中。
6. 普通 Python、Maya 2025 mayapy 与离屏 PySide6 验证通过。

## 第四里程碑验收（已完成：Scene Pulse + Measured Root Cause Lens）

1. Maya 2025 Profiler v2 输出被解析为可序列化、绑定 SceneSnapshot 的事件模型。
2. Profiler 会话拒绝覆盖外部采样，并在操作成功、失败或导出异常后恢复采样状态。
3. Trace Horizon 以类别轨道呈现真实事件，支持拖选时间窗和双击复位。
4. 时间窗内的映射事件形成 Atlas 节点热度，并把实测包含耗时融合进 Root Cause 候选排序。
5. UI 明确展示映射覆盖率、事件数与结构评分，并声明嵌套包含耗时不是优化收益预测。
6. 普通 Python 与 Maya 2025 mayapy 全部 30 项测试通过；离屏窗口使用真实采集完成渲染验收。

下一里程碑进入 Scene Clinic：先建立可扩展的规则注册表、严重度/置信度契约与安全修复工作台，再接 Counterfactual Profiler。

## 第五里程碑进度（进行中：Scene Clinic）

已完成：

1. 规则注册表声明 category、confidence、scan cost、default state 与 repair kind。
2. 每条规则独立计时和隔离失败；错误规则不会中断扫描，也不会被当作 clean。
3. Maya 工作区提供动态 Rule Array，可在冻结快照上切换规则并重新运行。
4. Issue 卡展示规则契约，并继续联动 Atlas、Evidence 与 ChangePlan。
5. ChangePlan 现会在同一 Undo chunk 内验证宿主后置条件，失败自动回滚。
6. Apply 后重新采集验证原 Incident；只有 Undo 栈顶精确匹配时才允许回滚。
7. 普通 Python 与 Maya 2025 mayapy 全部 35 项测试通过，1480px 与 960px 离屏布局验收通过。
8. All/Rig/Animation/Publish Profile 已绑定不同规则集合，并在 Maya 2025 实测切换扫描结果。
9. Finding 按共享节点、Reference、Namespace 与直接 DG 邻接聚合为带 linkage evidence 的 Incident。
10. 新增孤立 utility 和过深 namespace 规则；两者保持诊断优先，不做无法证明安全的自动删除。
11. 10,000 节点 / 1,000 Finding 聚类性能契约通过；普通 Python 与 Maya 2025 全部 40 项测试通过。
12. 严格团队 JSON 支持白名单阈值、全局禁用、声明式节点类型策略和自定义 Profile。
13. JSON 拒绝重复键、未知字段、错误类型、超限内容与 Python hook，并生成稳定 SHA-256 指纹。
14. Python RulePack 采用版本化显式信任边界，不做模块发现，不修改全局默认 Registry。
15. Rule Array 支持大量团队规则的滚动阵列，并显示团队规则指纹或配置已回退。
16. Maya 2025 已验证有效团队配置、自定义规则、Profile 差异和缺失配置整体回退；普通 Python 与 mayapy 全部 45 项测试通过。
17. SceneSnapshot schema v2 将文件引用建模为第一类记录，覆盖路径、namespace、父引用、加载/预览状态、成员稳定身份与 failed edits，并兼容迁移 schema v1。
18. 新增卸载引用、failed edits、深层嵌套引用、未保存场景、runtime script 和 detached animCurve 六类诊断，Rig/Animation/Publish Profile 已接入对应信号。
19. Scene Delta 会独立呈现 Reference add/remove/modify 及字段级证据；Incident 可生成去重、冲突检查、单 Undo 边界的批量 ChangePlan，并在重采集后验证全部源 Finding。
20. 普通 Python 与 Maya 2025 mayapy 全部 51 项测试通过；真实文件引用加载/卸载采集通过，1480px 与 960px 离屏布局再次验收，Standalone 空字体库的文字方框问题已由显式字体宿主适配解决。

Scene Clinic 的 Reference/Animation/Publish 首批规则与批量计划纵向闭环已完成。下一里程碑进入 Counterfactual Profiler：先建立无破坏的实验模型、基线/变体测量和收益置信区间，再把验证后的实验意图接回 Atlas。整个 `/goal` 继续保持 active。

## 第六里程碑进度（已完成：Counterfactual Profiler）

1. 实验统计核心与 Maya/Qt 完全隔离，采用成对 AB/BA 采样、完整操作 wall-clock、p95、CV 噪声与确定性 paired bootstrap 95% 区间。
2. 结论只分 `IMPROVED / INCONCLUSIVE / REGRESSED`；置信区间跨零时不会把平均值包装成确定收益。
3. Maya 2025 nodeState adapter 在采样前复核稳定 UUID、引用状态、Plug 可写性与 baseline；Undo 记录在实验期间无 flush 暂停。
4. 成功、采样异常和用户取消均验证原始 nodeState、Profiler sampling 与 Undo head 完整复原。
5. Counterfactual Spectrum 用配对双柱、动态扫描线、结果区间和 Atlas 绿/橙差异场显示实验，Root Cause Lens 与 Scene Clinic 上下文继续保留。
6. 报告包含版本化 JSON 契约，自动写入 gzip + SHA-256 + 原子替换的实验档案，并拒绝篡改和目录逃逸。
7. 200 对样本、4,000 次 bootstrap 在普通 Python 中约 0.13 秒；60 项普通 Python 与 Maya 2025 全套测试通过。
8. 真实 Maya nonLinear 节点和 1480×900 / 960×720 离屏窗口完成宿主、恢复与视觉验收；一次实测均值为正但区间跨零，UI 正确呈现 `INCONCLUSIVE`。

下一里程碑进入 Crash & Corruption Bisect 和后台 Runner：先实现隔离工作副本、进程结果契约与 delta-debugging 核心，绝不在用户唯一源文件上做删除实验。整个 `/goal` 继续保持 active。

## 第七里程碑进度（进行中：Crash Bisect / Runner）

已完成：

1. BisectCandidate、BisectPlan、ProbeAttempt 与 ReproCapsuleManifest 均为版本化、可校验的数据契约。
2. 经典 ddmin 支持 subset/complement、交互故障、`PASS/FAIL/UNRESOLVED`、结果缓存、Probe 预算、取消与完整决策 trace。
3. SceneSnapshot 可生成本地顶层 DAG 和 Reference 候选，并把稳定节点成员、Maya path、Reference node 与 source hash 固化到 Plan。
4. IsolatedMayaProbe 每次运行前重新验证源 SHA-256，只复制到独立 attempt；子进程只接受 attempt root 内的输入、输出、结果和进度路径。
5. 隐藏 Maya 2025 worker 已实测完成 open → 排除候选 → evaluate → save → reopen；源 `.ma` 内容与哈希不变，副本过滤正确。
6. timeout、非零退出、worker 配置错误和最后阶段有明确分类；stdout/stderr 尾部、crash artifact 与全部 Attempt 进入原子 Repro Capsule。
7. 安全 Maya ASCII slicer 在 Maya 启动前解析语句、节点 ownership、DAG 子树与 Reference；动态 `parent`、歧义路径、非 UTF-8 或 `.mb` 会 fail closed。
8. 初始 open 故障注入已真实运行：完整集合 timeout、good 子集 PASS、poison 子集 timeout，ddmin 用三个严格串行的隐藏 Maya 2025 进程收敛到单个 `poison_GRP`，源哈希不变，Capsule 校验通过。
9. Spectral Failure Prism 已接入非阻塞 QThread 调度：动态显示 PASS/FAIL/UNRESOLVED、阶段、候选数与收缩路径；取消在当前 Probe 后生效，窗口关闭会等待子进程回收，避免销毁运行中的线程。
10. `.ma` 采用 pre-open isolation；`.mb` 明确限定为 post-open evaluate/save/reopen，不夸大初始打开崩溃能力。
11. 每个 Probe 完成后原子写入带 SHA-256 的 Bisect Journal；恢复会校验并重放已有 outcome，测试证明完整恢复新增 Maya Probe 数为 0，Failure Prism 可直接 `RESUME BISECT`。
12. `python -m MayaScope.runner` 已提供 JSONL `run/resume/verify`、0/1/2 退出码、原子 Plan 输出与 `.mb` fail-closed 边界，可直接接 CI 或农场调度。
13. Probe 会把 Maya 2025 版本/API、操作系统、Evaluation 模式、线性/角度/时间单位与 loaded plugin 清单写入证据；真实隐藏 Runner 已验证该环境指纹。
14. 普通 Python 与 Maya 2025 全套 80 项测试通过；1480×900 与 960×760 离屏 Failure Prism 完成视觉验收。

第七里程碑的 Crash Bisect / Runner 首个生产级纵向闭环已经完成。整个 `/goal` 仍保持 active；下一里程碑进入 Maya Module 安装、启动自检、用户级日志、恢复手册与交付封装。

## 第八里程碑进度（进行中：安装、自检与运维交付）

已完成：

1. 用户级 Maya 2025 Module 安装器支持 status/install/update；原子写入且只覆盖带 MayaScope ownership marker 的 `.mod`，拒绝外来同名文件。
2. uninstall 不删除 Module，而是保留 UTC 时间戳备份，可手工恢复；所有安装生命周期已在临时 Maya 目录测试，不擅自改动当前用户配置。
3. 只读 Doctor 使用隐藏离屏 mayapy 验证真实宿主；本机结果为 Maya 2025、API 20250303、PySide 6.5.3、MayaScope 3.0.0-dev，当前 Module 状态仍为 not-installed。
4. UI 与 Runner 共用 2 MiB × 5 文件的滚动 JSONL 日志，记录 plan/attempt/stage/outcome/duration/Capsule hash，不默认写完整节点清单。
5. `docs/OPERATIONS.md` 已覆盖安装、升级、可恢复卸载、Journal 续跑、Capsule 校验、后台进程、日志和 fail-closed 排障顺序。
6. 普通 Python 与 Maya 2025 全套 80 项测试通过，Failure Prism 宽/窄屏在最终字体与按钮修正后再次验收。

尚未完成：一键 Shelf/菜单入口、启动时非阻塞健康状态展示、版本化发布清单与最终演示场景打包。因此第八里程碑和整个 `/goal` 继续保持 active。

后续完成：

7. 第一次打开 Workspace 会安装幂等、会话级 MayaScope 主菜单；Shelf 安装必须显式调用，`persist=False` 不写 Preferences，`persist=True` 才保存。
8. 顶栏 Host Beacon 使用真实 Maya/API/PySide/Runner/Module 状态，宽屏动态呈现、窄屏结构性收起，点击后把完整只读证据送入 Evidence Rail。
9. Release builder 以固定 ZIP metadata 和排序输入生成确定性包，Manifest 覆盖每个文件的 size + SHA-256，并拒绝重复、逃逸、哈希漂移、缺失及未清单 payload。
10. 隐藏 Maya 2025 生成真实 Showcase：156 节点、176 条边、loaded/unloaded Reference、72 路 fan-out、Namespace、孤立曲线/Utility、惰性 Script node 与 `showcase_bend`。
11. MayaScope 自身重采集确认六类预期规则全部命中，另检出 DG cycle，共 7 个 Clinic 结果；Counterfactual 规划通过。
12. 普通 Python 和 Maya 2025 测试扩展到 92 项；Host Beacon + Failure Prism 的 1480×900 / 960×760 最终截图通过。

第八里程碑现已完成。整个 `/goal` 仍保持 active；下一阶段做 v1 完成度审计，优先处理真实生产阻断项、性能/大场景增量采集和未覆盖的恢复边界，而不是继续堆展示功能。

## 第九里程碑进度（进行中：大场景响应与 CI 门禁）

1. Maya 场景采集改为 QTimer 驱动的分片会话，按节点、DG、DAG、身份复核和 finalize 分阶段推进；可取消且保留上一快照。
2. 节点新增/删除、连接变化与结束身份复核构成双层 mutation guard；采集中场景变化会拒绝混合快照。
3. Clinic 在不可变快照上通过独立 QThread 按规则运行，支持逐规则进度和安全取消；关闭窗口会等待线程退出，不悬挂 Qt 对象。
4. 2,550 节点真实 Maya 基准完成 107 个 capture slice，总计约 187 ms，最大单片约 3.27 ms；Qt heartbeat 最大间隔约 3.94 ms。
5. 隐藏 Maya 2025 Scene Clinic Audit 已提供 CI / publish gate：禁用 script node 执行、锁定源 SHA、记录规则耗时与配置指纹，并用 0/1/2 区分通过、门禁命中和不可采信失败。
6. Audit artifact 原子落盘并带 SHA-256；独立 `--verify-report` 会拒绝篡改，worker 退出码与报告状态不一致同样 fail closed。
7. 真实 Showcase 审计稳定得到 7 个结果；Maya 内置配置 script 节点被降噪，仅保留用户 payload 命中。
8. 10,000 节点、19,982 条边的合成快照在 Maya 2025 离屏 UI 中应用 Atlas 用时约 15.84 ms；渲染保持 240 个高信号节点和 462 条可见边，不随完整场景规模无限增长。

下一步继续 v1 完成度审计，重点验证 Atlas 大快照应用成本、完整 Maya 2025 回归和最终发布包一致性。整个 `/goal` 继续保持 active。

## 第十里程碑进度（完成：跨版本回归门禁与 Regression Rift）

1. Scene Clinic 回归不比较易抖动的聚合 Issue id，而是拆成 `rule_id + stable node id` 原子 Finding，分别记录新增、加重和解决。
2. 性能证据使用隐藏 Maya 2025 的相邻时间交替 evaluation；dirty 全场景后 demand-pull 几何输出，不依赖无头 viewport refresh，并在任何成功/异常路径恢复原时间。
3. 性能退化必须同时越过配置比例、绝对微秒值和三倍双方 MAD 噪声带；嵌套 Profiler 事件不被错误相加。
4. 任意签名 Audit 报告都能作为基线；比较要求 profile、Clinic 配置指纹、Maya 版本和 Evaluation Mode 一致，否则 fail closed。
5. `absolute` 与 `regression` gate mode 分离：前者检查当前绝对质量，后者只阻断相对基线新增/加重或真实变慢；报告分别记录 worker 与最终 audit 退出码。
6. 真实 Showcase 以 7 个样本完成基线和二次比较：绝对门禁返回 2，回归门禁返回 0；3 个几何输出被实际拉取，原时间恢复。
7. Workspace 新增 Regression Rift：紫/青双样本轨迹、动态扫描线、BASELINE HOLDS / RIFT DETECTED 状态、结构变化计数和 Evidence Rail 解释均来自签名报告。
8. Regression Rift 的 1480×900 与 960×760 离屏 Maya 2025 截图通过；窄屏隐藏入口但保留已打开的证据带，不压缩主操作。
9. 普通 Python 与真实 Maya 2025 测试扩展到 100 项并全部通过。

整个 `/goal` 继续保持 active。下一阶段优先审计百万连接目标下的查询/布局虚拟化证据、Snapshot/Report schema migration，以及 Runtime callback/scriptJob 诊断缺口。

## 第十一里程碑进度（完成：Snapshot / Audit Schema Migration）

1. 新增宿主无关的 `MigrationRegistry`，只允许注册 `N → N+1`，在深复制数据上逐级运行；拒绝未来版本、缺失步骤、重复注册、跳级和不推进版本。
2. SceneSnapshot v1→v2 正式进入迁移链，补齐 references/metadata 后再走当前模型验证，不再依赖 from_dict 中的隐式兼容分支。
3. Scene Clinic Audit 升级到 schema 2，v1→v2 会补齐 gate mode、absolute gate、最终 audit exit code 与 performance 边界。
4. 签名报告严格先验证原始 schema 内容的 SHA-256，再迁移内存副本；读取不会改写历史 artifact。
5. 发布目录中的真实 schema-1 `clinic-audit.json` 验证并迁移成功；新的 Maya worker 原生输出 schema 2。
6. 普通 Python 与真实 Maya 2025 测试扩展到 103 项并全部通过。

整个 `/goal` 继续保持 active；下一阶段转向 Runtime Observatory：callback、scriptJob、expression、插件依赖和运行时副作用清单，以及百万连接查询预算。

## 第十二里程碑进度（完成：Runtime Observatory）

1. 新增独立不可变 RuntimeSnapshot，覆盖 expression、interactive scriptJob、loaded plugin 与 node-scoped callback footprint，并与 SceneSnapshot id 绑定。
2. Runtime collector 以 7 ms 时间片扫描；node add/remove mutation guards、scene identity 和 expression/plugin/job 双端复核防止混合运行时快照，可取消且立即清理 callbacks。
3. expression 记录稳定节点身份、alwaysEvaluate、unit conversion、源码长度/短预览/SHA-256；不会擅自执行、mute 或删除。
4. scriptJob 在交互式 Maya 中解析 trigger/lifetime/hash；standalone 明确记录 unavailable，不冒充 0 jobs。
5. callback 使用 Maya 公开的 `MMessage.nodeCallbacks` 节点级 opaque ID 数量；API 不提供全局 owner/function 清单，因此 Runtime Finding 明确禁止虚假归因。
6. plugin inventory 记录 path/vendor/version/API/autoload/unloadOk/注册节点和命令；Runtime Observatory 不自动 unload。
7. 隐藏 Audit 合并 Runtime Finding 和完整 RuntimeSnapshot；独立 fixture 在禁用 scriptNode 执行时稳定检出 `runtime-script-nodes` 与 `runtime-expressions`，签名报告验证通过。
8. Workspace 新增 Runtime Constellation：expression、job、plugin、callback 四条动态轨道，Finding/limitations 进入 Evidence Rail，可归属节点反向点亮 Atlas。
9. 真实 Maya 2025 宽/窄屏验证得到 1 expression、2 plugins、1 callback node、2 runtime signals；窄屏折叠入口但保留已打开的星座。
10. 普通 Python 与真实 Maya 2025 测试扩展到 108 项并全部通过，包括取消、场景突变和 callback cleanup。

整个 `/goal` 继续保持 active；下一阶段建立百万连接 Query Kernel 的内存/时间预算、邻域查询缓存与增量失效证据。

## 第十三里程碑进度（完成：Million-edge Query Kernel）

1. GraphIndex 从字符串 set/dict 邻接重写为双向整数 CSR；节点 identity 只存一次，百万边常驻索引估算 32.25 MiB。
2. 独立 Plug 连接按节点对压缩邻接，但完整 SceneEdge 证据仍可按路径恢复；Root Cause Lens 不丢失并行连接。
3. Query Kernel 在 SceneSnapshot 层共享索引并使用对象身份隔离同名快照；支持单快照族与全局显式失效。
4. 邻域 BFS 支持深度、节点数、扫描边数、deadline 与即时取消，返回 elapsed、scanned edges 和明确 truncation reason。
5. 查询结果采用不可变 Mapping 与有界 LRU；重复 Lens 查询直接命中，快照缓存最多保留两个索引。
6. Clinic Worker 在独立 QThread 预热索引；UI 线程第一次选择节点不再承担大图构建。
7. Root Cause Lens Ribbon 与状态栏显示 `N / E / ms`，安全截断不再伪装为完整调查范围。
8. 确定性 100,000 / 1,000,000 唯一边基准四项预算全部通过：百万边索引 0.93 s、32.25 MiB，冷查询 2.09 ms、缓存查询 0.009 ms。
9. 新增并行边、严格 edge budget、即时取消、缓存命中、同 id 快照隔离与族失效回归；普通 Python 111 项全部通过。

整个 `/goal` 继续保持 active；下一阶段进入百万规模 Atlas 布局/视图虚拟化与增量 SceneSnapshot 更新，查询吞吐不能替代可视化响应验收。

## 第十四里程碑进度（完成：Atlas Semantic Window）

1. 确认旧 Atlas 的 240 节点策略只是一次性截断；折叠节点后来成为 Lens/Delta/Runtime 目标时无法显示。
2. Atlas 改为 240 槽语义渲染窗口：焦点、候选路径、Issue、Profiler、Delta 与 Runtime 节点可按业务优先级动态换入。
3. 当前窗口边由共享 `dg + dag` CSR 索引局部抽取，不再为每次物化遍历完整 SceneSnapshot.edges。
4. 全关系索引与稳定高流量排名在 Clinic QThread 预热；UI 线程只实例化固定数量 QGraphicsItem。
5. 换窗采用增量图元复用：保留仍可见节点，只替换真正进出窗口的节点并重建局部边。
6. 100,000 节点 / 1,000,000 唯一边 Maya 2025 离屏基准：后台索引+排名 2.83 s、前台应用 63.5 ms、折叠焦点换入 32.8 ms，三项预算全部通过。
7. 独立视觉证据确认原本折叠的 `node_099999` 被物化为调查焦点；完整 Workspace 宽/窄屏 Lens 遥测保持正确。
8. 普通 Python 与隐藏 Maya 2025 回归均为 111 项全绿。

整个 `/goal` 继续保持 active；下一阶段进入增量 SceneSnapshot / graph invalidation，减少重复捕获中未变化对象与索引的重建成本。

## 第十五里程碑进度（完成：Incremental Snapshot Reconciliation）

1. MayaSceneCaptureSession 接受 previous Snapshot，在 seal 前按稳定 ID 复用完全相同的 SceneNode 与 SceneReference。
2. 只有节点 ID 顺序和完整 edge tuple 严格一致才共享旧连接对象；不使用存在碰撞风险的 topology hash。
3. QueryKernel alias 还会复核共享 edge tuple 与节点顺序；复制出的等值 tuple 会 fail closed。
4. 新 Snapshot 继续拥有独立 capture id、时间、selection/plugins metadata；属性变化与 Reference Delta 不会被吞掉。
5. Scene Delta 对 collector 共享的 edge/reference tuple 使用 O(1) 快路径；rewire 仍产生完整结构证据。
6. Workspace 在后台 Clinic 前完成 CSR alias，两个索引随后直接命中；`CSR REUSED` 在普通状态与自动 Lens 状态中持续可见。
7. 真实 Maya 2025 的 801 节点 / 758 边场景：未变化捕获复用全部节点和边，双索引 alias 0.061 ms，Clinic 预热 0.008 ms；属性变化保持拓扑，rewire 强制重建。
8. 100,000 节点 / 1,000,000 边模型证据：双索引 alias 8.1 ms，Clinic 预热 0.029 ms；单边 rewire alias=0、双索引重建约 1.86 s。
9. 普通 Python 与隐藏 Maya 2025 测试扩展到 113 项；完整 Workspace 截图同时证明新 Snapshot、空结构 Delta、Lens 追踪和 CSR REUSED 状态。

整个 `/goal` 继续保持 active；下一阶段审计长期 Maya 会话中的 Snapshot/Atlas/Runtime 缓存生命周期、内存回收和取消压力，避免持续使用后的隐性驻留增长。

## 第十六里程碑进度（完成：Evidence Lifecycle & Session Cleanup）

1. 新 Snapshot 应用会统一清除上一快照的 RuntimeSnapshot/Report、Regression Rift、Counterfactual、Profiler、Lens 与旧 Delta。
2. Runtime focus 在展示前复核 `source_snapshot_id`；跨快照 inventory 会被拒绝并要求重新捕获。
3. Runtime、Regression 与 Counterfactual 子控件新增 clear contract；隐藏控件不再暗中持有旧性能样本或 experiment observations。
4. Runtime dismiss 释放 inventory，而不只是隐藏条带；Regression/Counterfactual dismiss 同样清空内部 payload。
5. Workspace 真正关闭时停止 capture/runtime/全部视觉 timer，清空 QGraphicsScene 和快照引用，并使全局 QueryKernel 失效。
6. 隐藏 Maya 2025 生命周期 smoke 证明：新捕获清除旧 Runtime/Regression/Counterfactual，关闭前 2 个索引、关闭后 0 个，动画 timer 全停。
7. 100 次连续未变化 Snapshot alias 回归证明缓存始终只有最新快照的两个逻辑索引，估算常驻字节不增长。
8. 普通 Python 测试扩展到 114 项并全部通过。

整个 `/goal` 继续保持 active；下一阶段进行 v1 生产完成度缺口审计，优先补主线程阻塞、错误恢复、真实场景契约或用户可观察性缺口，不继续添加无验证的展示面板。

## 第十七里程碑进度（完成：中文展示界面与可取消索引构建）

1. 展示版明确以国内企业面试官为目标观众，MayaScope 的窗口标题、导航、按钮、状态、提示、对话框、诊断结论与 Maya 菜单统一采用简体中文。
2. Maya、API、DG/DAG、CSR、Profiler、Plug、scriptJob、FK/IK、节点类型与稳定协议 ID 等行业术语按必要性保留，不再用大段英文全大写制造“技术感”。
3. Scene Clinic 的默认规则、制作阶段 Profile、Issue 描述、Evidence 标签、事件聚类与 Runtime Finding 均重写为自然中文；JSON 字段、规则 ID 和内部算法枚举保持稳定，避免破坏历史快照与自动化接口。
4. Root Cause Lens 的结构评分因素、候选理由、路径边界与测量免责声明全部中文化；ChangePlan 的预览、执行回执、回滚与后置验证也完成中文闭环。
5. 字体策略优先加载 Microsoft YaHei UI / Microsoft YaHei / DengXian，并保留 Segoe UI 回退；宽屏 1480×900 与窄屏 960×760 均完成 Maya 2025 + PySide6 离屏视觉验收。
6. 新增中文界面回归门禁，禁止旧版 `SCENE ATLAS`、`ROOT CAUSE LENS`、`CAPTURE SCENE`、`FAILURE PRISM` 等展示标题回流。
7. Query Kernel 的 CSR 构建与稳定排名新增细粒度取消检查；Clinic 在图索引阶段收到取消后不会污染共享缓存，也不会误报失败。
8. 普通测试扩展到 117 项并全部通过；Maya 2025 离屏宿主成功捕获中文宽/窄屏证据，窗口、Profile、状态与诊断内容均通过实机读取。

整个 `/goal` 继续保持 active；下一阶段优先审计诊断广度与生产级恢复路径，并用真实复杂场景校准规则阈值、Profiler 解释力和错误信息，而不是重新扩张语言或版本矩阵。

## 第十八里程碑进度（完成：Maya / Atlas 双向选择上下文）

1. 新增宿主独立的 `MayaSelectionBridge`，只拥有一个 Maya `SelectionChanged` callback；启动、停止和析构均幂等，callback 异常不会泄漏到 Maya 事件循环。
2. Maya → Atlas 采用 45 ms 去抖；长 DAG 路径与唯一节点名映射到当前 Snapshot 的稳定 ID，重名短名称明确拒绝猜测。
3. Atlas → Maya 自动写回选择，并用 expected-selection contract 精确抑制自己的回声；下一次艺术家选择仍能正常抵达，不使用容易吞事件的全局布尔锁。
4. 顶部新增高辨识度 **MAYA · 联动** 动态按钮，联动时短暂光谱闪烁；支持显式暂停，窄屏按现有层级折叠，全部状态和错误均为中文。
5. 身份索引由 Clinic 后台线程构建并可取消，以不可变 Mapping 交回 UI；选择事件不再扫描整场景。
6. 100,000 节点 / 200,000 身份基准：后台构建 0.128 秒、峰值 11.0 MiB；1000 次查询总计 0.392 ms，三项预算全部通过。
7. Maya 2025 + PySide6 离屏实机证明 Maya 选择 `driver_00` 后 Atlas 自动聚焦；Atlas 选择 `matrix_driver_03` 后 Maya 返回同名选择；关闭后 bridge active=false。
8. 普通与真实 Maya 测试扩展到 126 项并全部通过，覆盖歧义身份、取消、写回抑制、下一事件存活、启动回滚和 callback 清理。

整个 `/goal` 继续保持 active；下一阶段继续审计 Scene Clinic 规则覆盖与真实制作场景校准，优先补能解释发布失败、求值退化或引用污染的高价值证据链。

## 第十九里程碑进度（完成：场景制片契约）

1. SceneSnapshot 升级到 schema 3，新增不可变 `SceneSettings`；v1→v2→v3 逐级迁移，不改写旧 artifact。
2. Maya 2025 collector 以容错边界采集时间单位、精确 fps、线性/角度单位、上轴、色彩管理状态、渲染空间、视图变换和 OCIO 配置路径。
3. Clinic 配置升级到 schema 2，schema 1 保持内存兼容；团队可声明允许帧率、单位/上轴、色彩策略及必要/禁用插件，未知字段和自相矛盾策略 fail closed。
4. `scene-contract` 只有在团队显式配置后才注册，并自动加入全量信号与发布入口；默认不假设 24fps、cm、Y-up 或 ACEScg 对所有项目都正确。
5. 偏差聚合为一条中文场景级 Finding，每一项都展示“要求 / 当前”；没有受影响节点时保持空身份集合，不伪造节点证据。
6. Clinic 顶部新增光谱“制片信号”带，动态显示帧率、尺度、上轴和色彩管理，悬停展开渲染空间、视图变换与 OCIO 路径；窄屏按层级收起。
7. Scene Delta 把设置变化作为第一类差异，Audit 报告携带完整 `scene_settings` 与 `plugins_in_use`，发布 CI 可直接复核。
8. 普通 Python 130 项测试全绿；真实 Maya 2025 的 6 项 collector 测试全绿。隐藏发布审计对 pal / m / rad 夹具产生一条确定性门禁、0 条规则失败；1480×930 离屏中文视觉验收通过。

整个 `/goal` 继续保持 active；下一阶段优先补“外部文件与路径依赖健康”——纹理、缓存、Alembic/USD、音频、代理与工作区相对路径的存在性、可移植性和发布风险证据链。

## 第二十里程碑进度（完成：外部文件依赖健康）

1. SceneSnapshot 升级到 schema 4，以稳定 owner UUID + plug 身份建模 `ExternalDependency`；v3→v4 迁移补空清单，旧快照继续逐级读取。
2. Maya collector 读取 `filePathEditor` 注册表而不是遍历所有字符串属性；Reference 单独建模并去重，插件注册的路径类型可自然进入。
3. 每项依赖保留语义类型、原始/解析路径、Maya 存在状态、路径形态、工作区归属及 `<UDIM>`、`<uvtile>`、`<f>`、`####`、`%04d` 序列 token。
4. 采集器不递归目录、不展开序列、不打开依赖文件，因此不会为“检查缺失文件”在 Maya 主线程扫描海量磁盘或主动触碰网络共享。
5. 新增确定性的“外部文件依赖缺失”和高置信“外部依赖不可移植”规则，自动进入全量信号和发布入口；路径样例、类型分布与检查来源均为中文证据。
6. 制片信号带新增依赖总数/缺失数，缺失时切换橙色风险态；Delta 把依赖新增、移除、换路径和状态变化作为第一类差异，并将 owner 节点点亮为琥珀色。
7. 隐藏 Audit 输出完整依赖清单。真实缺失 UDIM 夹具稳定得到 `exists=false`、`sequence_pattern=<UDIM>`、一条发布 ERROR、0 条规则失败和退出码 2。
8. 1000 个缺失 UDIM 的真实 Maya 2025 完整捕获耗时 0.377 秒（含首尾路径表 refresh 与一致性复核），1000 个稳定 ID 与 token 全部保留；普通 Python 134 项、真实 collector 7 项全绿，1480×930 中文风险态视觉验收通过。

整个 `/goal` 继续保持 active；下一阶段优先审计“发布前未知修改与脏场景状态”以及场景保存/打开生命周期，确保自动化门禁能区分磁盘文件、内存未保存变化与打开后脚本副作用。

## 第二十一里程碑进度（完成：场景内存生命周期与工作区语义）

1. SceneSnapshot 升级到 schema 5，新增 `SceneLifecycle`，保存 modified、文件类型、实际工作区、当前时间、播放范围与动画范围；v4→v5 迁移保持旧 artifact 可读。
2. 新增确定性 `unsaved-scene-changes`：只在 Maya 明确返回 modified=true 时产生中文 Finding，不把未知状态误判为干净或脏。
3. 制片信号带在内存脏时切换橙色边界并显示“未保存”，状态栏同步提示；正常保存后自动恢复，风险态不是固定装饰。
4. Scene Delta 将 modified、工作区、文件类型与时间范围变化作为生命周期差异，Evidence Rail 展示具体中文字段。
5. 隐藏 Audit 输出完整 `scene_lifecycle`，可观察打开后插件/callback 导致的意外脏场景；磁盘源 SHA 复核继续独立存在。
6. Audit 新增显式 `--workspace`，严格验证目录并传入 worker；未提供时向上发现最近 `workspace.mel`，最后回退场景目录并记录来源。
7. 修复了隔离 `MAYA_APP_DIR` 默认 Project 可能导致“工作区之外”误报的生产边界；真实报告证明 explicit workspace 生效且已保存场景 modified=false。
8. 普通 Python 138 项测试全绿；真实 Maya 2025 collector 8 项全绿，覆盖保存/修改状态和播放范围。中文离屏风险态继续通过。

整个 `/goal` 继续保持 active；下一阶段优先做 Snapshot 捕获的一致性强化：除拓扑外，验证外部路径、场景设置和生命周期在分片采集期间没有漂移，避免把跨时刻状态封进同一快照。

## 第二十二里程碑进度（完成：分片快照宿主上下文一致性）

1. 采集首尾建立宿主上下文签名，覆盖 SceneSettings、SceneLifecycle、plugins-in-use 与 Maya 注册外部路径表。
2. 路径表在首尾显式 `filePathEditor(refresh=True)`，能发现采集中途修改 fileTextureName，而不是依赖可能滞后的编辑器缓存。
3. 任一上下文变化与现有节点/连接 mutation 一样 fail closed：移除 owned callbacks、拒绝混合 Snapshot、要求稳定后重试。
4. 签名不打开依赖内容、不展开 UDIM、不递归目录；1000 个依赖的双端 refresh + 全捕获仍为 0.377 秒，低于 3 秒预算。
5. 真实 Maya 2025 回归分别证明捕获中途修改外部路径和 time unit 都会触发 `SceneChangedDuringCapture`。
6. 能力边界保持诚实：任意已存在节点的所有普通数值属性尚未做全量首尾复核；当前保证拓扑、身份、高风险宿主设置与外部依赖的一致性。

整个 `/goal` 继续保持 active；下一阶段审计 Scene Clinic 的 Issue 稳定性与跨快照身份：场景级 Finding、外部依赖换路径及同一节点多条依赖不应在回归比较中互相覆盖。

## 第二十三里程碑进度（完成：回归 Finding 原子主体）

1. Issue 新增不可变 `atomic_subjects`，每项包含稳定 subject id 与可选 owner node UUID；空 id、重复 id 和悬空 owner 均 fail closed。
2. 外部依赖聚合卡按 dependency id 输出原子主体；1000 条缺失路径仍是一张可读卡，但 Regression 能逐条判断新增/解决。
3. 场景制片契约按 time/linear/angular/axis/color/render-space/plugin 等字段输出主体，不再把不同策略偏差都压成 `<scene>`。
4. Audit 报告序列化原子主体；旧规则继续按 node UUID 拆分，旧场景级报告按 Issue id 安全回退。
5. 回归测试证明同一节点新增第二条缺失路径产生独立 new Finding，帧率偏差切换为上轴偏差产生 resolved + new。
6. Regression 现在比较显式 workspace root 与关键 SceneSettings；项目根、fps、单位、上轴、色彩管理或渲染空间不一致时拒绝伪比较。
7. Snapshot delta 新增外部依赖数量统计；原有节点/Reference/Performance 比较保持兼容。
8. 普通 Python 141 项全绿，真实 Maya 2025 collector 10 项全绿；签名 Audit 已实测输出 dependency atomic subject 与 owner UUID。

整个 `/goal` 继续保持 active；下一阶段优先审计批量发布报告的可读性与聚合：把大量文件/场景 Audit 结果汇总为中文项目级门禁，而不是要求 TD 手工打开每个 JSON。

## 第二十四里程碑进度（完成：项目级批量发布指挥台）

1. 新增独立 `project_audit` 契约与命令行；场景 Audit 仍由隐藏 Maya 串行执行，聚合阶段不启动 Maya、不影响前台会话。
2. 聚合前逐份验证场景 SHA-256，并强制统一 Profile、Clinic 配置指纹、Maya 版本/API 与工作区；重复场景和混用上下文 fail closed。
3. 项目包内嵌原始签名报告与派生回执，按规范化场景路径确定性排序，再增加 `project_sha256` 第二层签名。
4. 独立 verifier 会重算双层签名、回执、上下文、场景顺序、严重级/规则汇总与门禁状态；不能靠篡改 summary 伪造通过。
5. 汇总同时保留 UI Issue 数与 atomic Finding 数；一张依赖聚合卡中的多条路径、场景契约中的多项偏差不会在项目统计中塌缩。
6. 顶栏新增中文 **项目门禁**；动态“项目发布列车”把真实场景绘制为可点击审计舱，并在问题证据栏展示场景/项目双签名与严重级统计。
7. 真实 Maya 2025 串行审计两个故意违规夹具，聚合结果为 2 个场景、2 个阻断、2 条 Issue、4 个原子 Finding；项目包验证通过。
8. 普通 Python 146 项全绿（17 项仅 Maya 环境跳过）；新增项目聚合、篡改、上下文、重复场景、退出码和 PySide6 中文 UI 回归。

整个 `/goal` 继续保持 active；下一阶段优先补项目门禁的“串行队列编排与进度恢复”：从场景清单在后台逐个 Audit、记录未完成/失败原因，并允许断点续跑，而不是只消费预先生成的报告。

## 第二十五里程碑进度（完成：可恢复的串行发布队列）

1. 新增签名 `project-audit-plan`：锁定每个场景路径/SHA、Clinic 配置内容、工作区、Profile、门槛、mayapy 与超时，重复场景和计划篡改 fail closed。
2. 新增签名 `project-audit-journal`：任务具有待运行、运行中、通过、阻断、失败状态，每个状态边界原子落盘并刷新 SHA-256。
3. 队列严格一次启动一个隐藏 Maya；不会与 Workspace 当前捕获、Clinic、Runtime 或故障二分并发争用，前台 Qt 由独立 QThread 保持响应。
4. “安全暂停”只在当前场景结束后生效；异常留下的运行中任务恢复为待运行并增加 recovery count，已完成签名报告不会重复执行。
5. 失败场景保留结构化错误与 attempts，下次执行可重试；源场景或 Clinic 配置内容漂移会拒绝运行，不在旧批准计划上偷换输入。
6. 全部场景可信后自动生成双重签名项目包；CLI 延续 0/1/2 语义，并提供 create/run/verify 三个中文工作流入口。
7. 中文发布列车新增五态光谱舱、断点签名、完成进度和“安全暂停 / 继续队列 / 打开项目结果”动作；关闭 MayaScope 会排队暂停并等待线程安全退出。
8. 真实 Maya 2025 对两个夹具完成“运行 1 个后暂停 → 恢复第 2 个”：两项 attempts 均为 1，最终 2 个阻断、4 个原子 Finding；普通 Python 153 项全绿（17 项仅 Maya 环境跳过）。

整个 `/goal` 继续保持 active；下一阶段优先做 v1 生产缺口审计，检查批量队列的并发锁、跨进程所有权、磁盘容量与孤儿 mayapy 恢复边界，同时继续扩展 Scene Clinic 的真实制作规则覆盖。

## 第二十六里程碑进度（完成：批量队列生产防护）

1. journal 同名 `.lock` 使用 Windows/Unix 内核锁，进程内注册表同时阻止同一 Python 进程重复取得所有权；JSON 只作可读租约证据。
2. 租约持续记录 PID、主机、计划/断点归属、心跳、当前场景与后台 Maya 精确身份；释放后保留签名和 `已释放` 状态供排障。
3. 第二个真实 Python 进程持锁时竞争者被拒绝并返回持有者 PID；释放后重新取得成功，不会并发启动 Maya。
4. 计划新增签名容量预算，启动前按磁盘卷聚合 journal、报告和隐藏 Maya 临时目录需求；不足时写入结构化预检证据且不启动 Maya。
5. Windows 子 mayapy 进入 `KILL_ON_JOB_CLOSE` Job Object，父进程崩溃时由内核回收；回调自身异常也不能绕过 Job handle 清理。
6. 遗留孤儿恢复同时核验 mayapy 文件名、规范化可执行路径、PID、启动 ticks、计划签名和 journal 路径；PID 复用或队列不匹配一律拒绝终止。
7. 中文项目发布列车实时显示容量余量、后台 Maya PID 与“崩溃联动开启/降级”，容量失败和所有权冲突都有明确中文保护态。
8. Maya 2025 + PySide6 离屏实机完成真实运行态截图和场景边界安全暂停；独立实证回收了测试脚本亲自创建的 mayapy 孤儿。普通 Python 161 项全绿（17 项仅 Maya 环境跳过）。

整个 `/goal` 继续保持 active；下一阶段回到 Scene Clinic 的制作价值，优先扩展引用、缓存、unknown node/plugin、命名空间与发布性能的高价值规则，并用真实复杂场景校准误报和耗时预算。

## 第二十七里程碑进度（完成：插件幽灵因果诊断）

1. SceneSnapshot 升级到 schema 6，新增不可变 `UnknownPlugin`；v5→v6 迁移补空登记，旧快照继续逐级读取。
2. Maya 2025 collector 只读采集 `unknownPlugin` 的名称、版本、注册节点/数据类型，并从 `unknownNode` 反查原插件和原始类名；不加载或搜索插件。
3. 首尾 host-context signature 纳入 unknown plug-in registry，采集期间登记漂移会与插件/设置/路径漂移一样 fail closed。
4. 新增确定性 `missing-plugin-requirements` 根因规则；每个插件具有稳定 atomic subject，并关联已降级 unknown 节点。
5. `unknown-nodes` 增加来源插件、原始类与节点级 atomic subject；本地删除仍必须经过预览 ChangePlan，引用节点继续受保护。
6. Scene Delta 把插件登记新增、消失、版本、节点类型和数据类型变化作为一等差异；签名 Audit 输出完整登记。
7. 中文制片信号带改为两层光谱阵列，可点击“插件幽灵”定位规则；真实节点在 Atlas 中橙色聚焦，右侧展示只读因果证据和安全边界。
8. 自生成 `unknown-plugin-probe.ma`、素材清单、真实 Maya 2025 Audit、离屏截图和结构化交互回执均已落盘。普通 Python 167 项全绿（18 项仅宿主环境跳过），真实 collector 11 项全绿；5000 条登记性能合同通过。

整个 `/goal` 继续保持 active；下一阶段优先完成引用解析健康与 namespace 归属冲突，把 missing/unresolved reference、复制编号、引用 namespace 与本地 namespace 污染组织成可解释的发布证据链，并补缓存类第三方路径夹具。

## 第二十八里程碑进度（完成：引用轨道与 namespace 归属）

1. SceneSnapshot 升级到 schema 7；`SceneReference` 新增 canonical path、复制编号和三态存在性，v6→v7 迁移从历史 resolved path 安全补全。
2. Maya 2025 实机证明第二个同源引用返回 `{1}`，`withoutCopyNumber` 回到同一源文件；源删除后 reference node 仍存在且 loaded=false。
3. Collector 对非 UNC 路径使用 Maya `file -q -exists`，同一 canonical path 只查询一次；UNC 保留未知，避免主线程网络阻塞。
4. 新增 `missing-reference-files`：多个引用实例按 canonical source 合并 atomic finding，明确缺失时 ERROR。
5. 新增 `reference-namespace-intrusion`：用 namespace 前缀集合线性扫描本地节点，精确定位侵入引用归属域的稳定身份，不进行自动移动或改名。
6. Scene Delta 记录 resolved/unresolved/canonical path、copy number 和 exists 变化；签名 Audit 输出完整 `reference_inventory`。
7. 中文制片信号阵列新增全宽“引用轨道”，实时显示实例、源文件、缺失和越界；点击联动最高风险规则、Evidence Rail 和 Atlas 关联节点。
8. 自生成失败夹具、素材哈希、真实 Audit、离屏截图与结构化回执均已落盘。普通 Python 173 项全绿（19 项仅宿主环境跳过），真实 collector 12 项全绿；5000 namespace 性能合同通过。

整个 `/goal` 继续保持 active；下一阶段优先补缓存与代理类第三方路径的真实注册夹具，并审计 Scene Clinic 对 unknown node、missing plugin、missing reference 与外部依赖之间的跨域事件聚类和发布报告可读性。

## 第二十九里程碑进度（完成：依赖谱系展示版）

1. SceneSnapshot 升级到 schema 8，外部依赖新增序列类型、成员/跨度/缺口计数、样例与扫描完整性边界。
2. 支持 UDIM、UVTILE、`<f>`、hash 和 printf 模式；UDIM 只统计成员，不把 tile 间隔误报为帧缺口。
3. 帧序列只判断已观测最小/最大编号之间的内部空洞，不依赖安全 Audit 禁用的 Maya UI scriptNode。
4. 本地目录扫描具有 10,000 条目与 50 ms 双预算；网络、环境变量和超预算目录保持未知。
5. 新增 `external-sequence-gaps`，以 atomic dependency 身份保存确定缺口并进入 Delta 与签名 Audit。
6. 中文“依赖谱系”全宽动态信号显示依赖、序列、缺文件和缺帧，点击联动规则、Evidence Rail 与 Atlas。
7. Maya 2025 自生成夹具证明 UDIM 1001/1002 有效，帧序列 0001/0003 明确缺少 0002。
8. 普通 Python 180 项、真实 collector 12 项全绿；截图、回执、签名报告与可复现素材已落盘。

按用户要求，本轮转为展示版收口，不继续扩大复杂功能。下一优先级是发布包、GitHub 中文首页与
真实宿主 GUI 生命周期证据；整个 v1 `/goal` 仍保持 active。

## 第三十里程碑进度（完成：真实 Maya GUI 生命周期）

1. 新增 `gui_lifecycle` 独立启动器：隔离 `MAYA_APP_DIR`、隐藏 GUI、记录既有 Maya PID，并精确持有测试进程身份。
2. Maya 内 worker 通过真实 `launch.run("workspace")` 加载产品，确认父窗口为 `MayaWindow` 并保存真实绘制截图。
3. 重复启动验证旧窗口隐藏且始终只有一个可见工作区。
4. 修复开发热重载先覆盖 `_WINDOW`、可能遗留旧窗口/回调的问题；真实热重载验证通过。
5. 关闭阶段验证 9 个活动计时器归零、选择回调移除、可见工作区归零和菜单卸载。
6. Maya 2025.3.3 测试 PID 34284 在 13.092 秒内自行退出，未触发超时回收。
7. 启动前既有 Maya PID 32232 在测试结束后身份完全一致，未被附着、驱动或关闭。
8. 结构化回执、Maya 日志和真实中文宿主截图已落盘；普通启动顺序回归同步加入测试。

整个 `/goal` 继续保持 active；下一阶段优先完成发布 zip 的隔离安装、首次启动和可恢复卸载复演。

## 第三十一里程碑进度（完成：Release ZIP 干净安装回放）

1. 新增 `install_replay` 命令，把最终 Release ZIP 而不是源码目录作为唯一安装输入。
2. 回放先验证 manifest、成员集合、大小和逐文件 SHA-256，再解压到独立临时 release 目录。
3. 安装器由解压副本运行，生成的 `MayaScope.mod` 明确指向临时 release；安装后重新查询状态。
4. 真实 Maya GUI 启动前清空开发 `PYTHONPATH` 与 `MAYA_MODULE_PATH`，只允许 Maya Module 发现包。
5. Maya 内 worker 记录实际 `MayaScope.__file__` 所在包目录并与预期解压目录比较，杜绝源码假通过。
6. 同一次回放验证首次绘制、重复启动、热重载、选择回调、计时器、菜单和宿主退出。
7. 退出后执行可恢复卸载、恢复备份、重新识别和最终卸载；整个临时 Maya 配置与解压目录被清理。
8. 候选包真实 Maya 2025 PID 50220 在 18.292 秒内自行退出，全部检查通过；新增普通回归覆盖隔离安装状态机。

整个 `/goal` 继续保持 active；下一阶段优先渐进拆分 `ui/workspace.py` 的 Presentation State、
后台任务编排和业务工作区，不一次性重写已经通过真实 Maya 验证的 QPainter/QGraphicsView 组件。

## 第三十二里程碑进度（完成：Presentation State 第一阶段）

1. 新增宿主无关、不可变 `WorkspacePresentationState`，普通 Python 不导入 Maya 或 PySide。
2. 新场景代会原子清除旧 Lens、Profiler、Runtime、Delta 与反事实证据，不再依赖一串松散赋值维持一致性。
3. Finding / Incident 选择互斥、节点焦点、Lens、Clinic、Profiler、Runtime 和 Delta 均有显式语义转换。
4. 主窗口保留临时兼容属性，但所有原字段已映射到唯一 `_presentation`，后续可分区迁移而不大爆炸重写。
5. Clinic、Crash Bisect 和项目队列 Worker 已移到 `ui/workers.py`，不再与视觉类混在同一巨型模块。
6. `ui/workspace.py` 从 5542 行降到 5414 行；文档明确这只是第一阶段，不把分文件冒充职责已经完全分离。
7. 新增 4 项状态转换测试，普通 Python 总计 187 项通过（19 项宿主限定跳过）。
8. 真实 Maya 2025 PID 53308 在 19.116 秒内通过首次启动、重复启动、热重载和关闭；10 个计时器归零。

整个 `/goal` 继续保持 active；下一阶段提取 UI Foundation（字体、色彩、Qt 枚举、确认对话框），
再优先拆出 Scene Atlas 视图与控制器，同时保持真实中文视觉和生命周期证据不变。

## 第三十三里程碑进度（完成：UI Foundation 与 Scene Atlas View 边界）

1. 新增 `ui/foundation.py`，集中管理光谱色板、Qt5/6 枚举解析、中文“执行/取消”确认框和离屏中文字体装载。
2. 新增 `ui/atlas.py`；节点图元、连接图元、环形布局、240 节点语义窗口、搜索、Lens、Delta、Pulse 与反事实光谱覆盖整体迁出主窗口。
3. Atlas 只依赖不可变 Model、Analysis 和 PySide，不导入 Maya Collector、Callback、QThread 或主窗口；Maya 双向选择编排仍由 Workspace 持有。
4. 外部选择使用抑制边界写入图谱，不会回声成一次新的用户激活；Atlas 动效只拥有自己的 QTimer，可独立启停并随窗口关闭清理。
5. 新增 9 项 Foundation/Atlas 回归，覆盖稳定色板、Qt 枚举、节点与边物化、异常节点预算优先、选择不回声、定时器和源码依赖边界。
6. `ui/workspace.py` 从 5414 行降到 4835 行；这只代表 View 和基础层完成迁移，Atlas 控制器及其他业务面仍在主窗口。
7. 普通 Python 总计 196 项通过（19 项宿主限定跳过）。
8. 真实 Maya 2025 PID 35408 在 19.815 秒内通过首次启动、重复启动、热重载、中文绘制和关闭；9 个活动定时器归零。

整个 `/goal` 继续保持 active；下一阶段优先建立 Atlas/Application Coordinator，把捕获、选择、
Clinic、Lens 与视觉渲染之间的控制流从主窗口迁出，再拆 Clinic View；不重写已经验证的光谱视觉。

## 第三十四里程碑进度（完成：Investigation Coordinator）

1. 新增宿主无关 `application.InvestigationCoordinator`；不导入 Maya、PySide、QWidget 或主窗口。
2. Scene/Clinic 异步结果进入状态前核对快照代次、Issue/Incident 唯一身份和受影响节点；旧结果直接拒绝，不再覆盖新场景。
3. 新场景接收在一次 Transition 中生成 Presentation State、Scene Delta、稳定宿主身份索引和 Atlas Scene Intent。
4. Maya 单选、多选、清空与无法映射成为四种显式决策；重名短名称继续拒绝猜测，单选的选择与 Lens 属于同一代。
5. 结构/实测 Lens 在 Coordinator 中计算；旧 Issue、Incident 和 Candidate 均无法进入当前调查代。
6. 关闭 Lens 会按状态恢复 Counterfactual、Profiler 或普通 Atlas 覆盖，不由 QWidget 重复猜测优先级。
7. 新增 `ui/investigation_renderer.py`，只负责将类型化 Intent 分派到真实生产 Atlas，不包含业务判断。
8. 新增 12 项协调器/渲染契约，普通 Python 总计 208 项通过（19 项宿主限定跳过）。
9. 真实 Maya 2025 PID 49348 在 20.530 秒内通过首次启动、重复启动、热重载、选择回调、中文绘制与关闭；10 个活动定时器归零。

整个 `/goal` 继续保持 active；下一阶段拆分 Scene Clinic View 与中文 Evidence Presenter，使规则阵列、
Issue/Incident 卡和证据文案不再定义在主窗口，同时保持 Coordinator 与 ChangePlan 安全边界不变。

## 第三十五里程碑进度（完成：Scene Clinic Rail 与 Evidence Presenter）

1. 新增宿主无关 `presentation.ClinicEvidencePresenter`，统一等待、空规则、故障隔离、正常结果、Issue 与 Incident 的中文证据状态。
2. `EvidencePanelState` 把标题、正文、操作文案和可执行状态冻结为一个结果，并拒绝空白用户文案。
3. 新增 `ui.SceneClinicView`，独立拥有 Issue/Incident 卡片、滚动区、证据正文、ChangePlan 入口和回滚入口。
4. Workspace 不再直接创建、销毁或持有 `issue_heading`、`evidence`、`plan_button` 与 Issue 卡片列表。
5. 事件簇引用不存在的 Issue 时明确拒绝渲染，不会静默漏掉诊断；旧 `_populate_issues` 不再越过 Coordinator 手动修改选择状态。
6. 原有 18px Rail 留白、紧凑宽度、规则阵列、光谱动效、中文对象名和 QSS 选择器全部保留，并补充中文可访问名称。
7. 新增 7 项 Presenter/View 契约，普通 Python 总计 215 项通过（19 项宿主限定跳过）。
8. 真实 Maya 2025 PID 39012 在 20.824 秒内通过首次启动、重复启动、热重载、选择回调、中文绘制与关闭；9 个活动计时器归零。
9. `ui/workspace.py` 降至 4679 行；`ui/clinic.py` 279 行，`presentation/evidence.py` 140 行。

整个 `/goal` 继续保持 active；下一阶段把已作为 Scene Clinic Rail 子控件运行的 Rule Array / Spectrum
定义迁入 `ui/clinic.py`，再扩展 Coordinator 的 Profiler、Runtime 与 Counterfactual 代次边界。

## 第三十六里程碑进度（完成：完整 Scene Clinic 与调查证据边界）

1. `ClinicRuleArray` 与 `ClinicSpectrum` 从主窗口机械迁入 `ui/clinic.py`，原有中文层级、四通道光谱、配置指纹、制片信号和动态绘制保持不变。
2. `SceneClinicView` 现在自行构造并持有规则阵列，Workspace 只装配完整诊所视图；测试仍可通过显式注入替身隔离业务。
3. 规则阵列和光谱新增中文可访问名称；真实 Maya 截图确认迁移未造成布局、色彩和动态层级回归。
4. `InvestigationCoordinator.accept_profiler` 核对快照代次与事件节点身份，并原子生成完整时间窗和 Atlas Pulse 意图。
5. 时间窗选择统一验证、排序和越界拒绝；QWidget 不再直接决定 Pulse 覆盖层状态。
6. Runtime 清单与报告必须共享精确身份，诊断身份不可重复、受影响节点必须属于当前快照，才允许驱动 Atlas 高亮。
7. Counterfactual 只接收真实版本化报告、完整成对采样和同代 Profiler Capture，并强制验证 `state_restored` 与 `undo_head_preserved` 回执。
8. 关闭反事实结果按当前调查状态恢复 Lens、Profiler 或普通 Atlas，不由按钮槽函数重复猜测覆盖优先级。
9. 普通 Python 221 项通过（19 项宿主限定跳过）；真实 Maya 2025 PID 56008 在 18.713 秒内完成首次启动、重复启动、热重载、中文绘制和关闭，9 个活动计时器归零。
10. 最终 Release ZIP 共 106 个清单成员，SHA-256 为 `12dc6817eb9d1f84a29f1583b6eecb4f9d3246f60dab2ba5110e8f78c2e3dfa4`；干净安装 PID 25748 只从临时 Module 导入，18.623 秒后自行退出并完成恢复/最终卸载。
11. `ui/workspace.py` 从 4679 行降至 4269 行；`ui/clinic.py` 为 715 行。这里完成的是 Clinic View 和三类证据接收边界，采集会话与其他业务工作区仍在主窗口。

整个 `/goal` 继续保持 active；下一阶段优先把 Profiler 与 Runtime 的采集/关闭用例从 QWidget 移入应用层，
再拆出相应生产视图，持续使用真实 Maya 截图做视觉回归，不扩大展示版功能面。

## 第三十七里程碑进度（完成：Profiler / Runtime 仪器视图与可恢复关闭）

1. `PulseHorizon` 原样迁入 `ui/profiler.py`，真实事件轨道、2500 事件绘制预算、时间窗拖选和动态地平线不再定义在主窗口。
2. `RuntimeConstellationCanvas/Strip` 迁入 `ui/runtime.py`，表达式、scriptJob、插件、回调四轨星图保持生产 QPainter 视觉和独立 QTimer 所有权。
3. Profiler 新增中文“清除采样”动作与暖橙警示态；工具提示明确它只清理调查证据，不修改 Maya 场景。
4. `InvestigationCoordinator.dismiss_profiler` 同步失效 Profiler、实测 Lens 与 Counterfactual；仍有效的 Runtime 或 Delta 自动恢复到 Atlas。
5. `dismiss_runtime` 不再由 QWidget 直接清状态；关闭后按 Lens、Counterfactual、Profiler、Runtime、Delta 的有效证据优先级恢复覆盖，修复残留高亮或错误清空。
6. 新增类型化 `AtlasDeltaIntent`，Qt renderer 只负责把确定的应用意图分派给生产 Atlas。
7. 真实截图发现性能统计与时间窗在窄宽重叠；时间窗改为绘图区右上角半透明仪器徽标，并补 800px 按钮几何测试。
8. GUI 生命周期探针新增可选 `instruments` 场景与宽高参数：在自己拥有的 Maya 中真实执行 DG/视口 Profiler、Runtime 清点、截图和清除采样恢复，不影响默认干净安装路径。
9. 普通 Python 229 项通过（19 项宿主限定跳过）；Maya 2025 mayapy 的 Profiler/Runtime 5 项集成测试通过。
10. 1480 × 900 真机 PID 44988 采集 584 个事件并在 22.440 秒内退出；800 × 900 真机 PID 15124 采集 865 个事件并在 22.984 秒内退出。两者均证明 Runtime 保留、派生证据失效、清除按钮复位、modified 状态不变和 9 个计时器归零。
11. `ui/workspace.py` 从 4269 行降至 3937 行；`ui/profiler.py` 254 行，`ui/runtime.py` 155 行。采集会话仍在 Workspace，本阶段不把 View 拆分冒充完整控制器迁移。

整个 `/goal` 继续保持 active；下一阶段优先把 Runtime 分片采集、取消、控件锁定与关闭等待组织成
可测试的 Application 会话控制器，再评估 Lens Ribbon 或 Project Gate 的下一次低风险视图拆分。

## 第三十八里程碑进度（完成：Runtime 分片会话控制器与真实取消闭环）

1. 新增宿主无关 `application.RuntimeCaptureController`；Maya Collector、分析器和异常类型均从装配根注入，不导入 PySide、Maya 或 UI。
2. 控制器独占采集会话、源快照身份、取消请求和分片预算，输出 `started/progress/cancelling/cancelled/stale/failed/completed` 七类不可变语义事件。
3. 场景代次在下一分片前变化会立即取消并释放守卫；Runtime 身份不一致时不进入分析器，分析异常也保证回到空闲态。
4. 取消请求幂等；完成前明确取消的部分结果绝不会覆盖上次有效 Runtime 证据，宿主关闭通过同步 `abort` 清理。
5. Workspace 只负责将语义事件渲染为自然中文状态和动态控件锁定，不再直接持有或推进 `MayaRuntimeCaptureSession`。
6. 真机探针暴露并修复一个异步竞争：Clinic/二分/项目队列的延迟完成回调不得在 Runtime 活跃时重新启用入口；Runtime 也不再与项目队列并发启动。
7. 新增 `runtime-cancel` GUI 场景：真实启动 Runtime、冻结“正在取消…”状态截图、推进下一安全分片，再验证五组控件恢复、旧证据保留和 Maya modified 状态不变。
8. 普通 Python 238 项通过（19 项宿主限定跳过）；Maya 2025 mayapy 的 Collector/Controller 11 项定向测试通过。
9. 源码真机 PID 58316 在 19.715 秒内完成取消、恢复、重复启动、热重载和关闭；真实中文 1480 × 900 截图显示工具栏取消态与底部安全分片提示。
10. 候选 ZIP 的隔离 Module 回放 PID 8176 在 22.884 秒内自行退出；包来源核对、取消恢复、备份恢复、最终卸载和临时目录清理全部通过。
11. `application/runtime_capture.py` 为 217 行；它完成的是 Runtime 会话编排边界，Runtime 生产视图仍由 `ui/runtime.py` 独立拥有，Qt 定时调度仍留在宿主装配层。

整个 `/goal` 继续保持 active；下一阶段优先拆分 Lens Ribbon 或 Project Gate 的生产视图与应用状态，
同时保持当前发布面收口，不为展示版继续扩大长周期功能范围。

## 第三十九里程碑进度（完成：Project Gate 状态边界与三镜头发布列车）

1. 新增宿主无关 `presentation.project_gate`，把项目报告、断点队列和所有权故障归一化为不可变 `ProjectGateViewState`，不导入 Maya、PySide 或 UI。
2. Presentation 层严格验证项目/场景 SHA-256、摘要数量、门禁结论、队列状态、尝试次数和容量预检；证据矛盾时拒绝猜测或渲染。
3. `ProjectGateCanvas/Strip` 迁入 `ui/project_gate.py`，独立拥有发布列车动画、场景命中测试、工具提示、reduced-motion 和中文可访问名称。
4. 清空、报告、队列与故障现在统一应用完整视图状态；旧失败色和安全暂停动作不会泄漏到下一份项目证据。
5. `examples/generate/project_gate_fixture.py` 生成三个轻量 Maya ASCII 2025 场景、三份签名 Scene Clinic 回执和一个二次签名项目包，并立即调用生产 verifier 复核。
6. 演示素材固定覆盖镜头 010 干净基线、镜头 020 缓存缺失阻断、镜头 030 插件登记警告；输出 manifest 保存实际场景校验值、回执路径、项目签名和预期 2/1 结论。
7. GUI 生命周期新增 `project-gate` 场景：在真实 Maya 内现场生成、验证并显示签名包，聚焦唯一阻断镜头，确认场景 modified 状态不变。
8. 1480 × 900 真机 PID 54180 在 22.334 秒内通过；800 × 900 真机 PID 31572 在 22.229 秒内通过。两次均完成重复启动、热重载、菜单卸载和 9 个活动计时器归零。
9. 第一次真机运行前已有 Maya PID 58104，测试结束后身份保持一致；探针没有附着、驱动或关闭用户宿主。
10. 普通 Python 246 项通过（19 项宿主限定跳过）；新增 Presentation、View 边界、生成素材和签名聚合回归。
11. 真实截图暴露的临时绝对路径与完整 64 位签名拥挤已修正为短场景名和签名摘要；窄停靠仍清楚显示绿/橙/绿三节列车与阻断证据。
12. `ui/workspace.py` 从 3965 行降至 3639 行；`ui/project_gate.py` 278 行，`presentation/project_gate.py` 263 行。这里完成的是项目门禁视图与呈现边界，队列执行器仍保留独立签名状态机和 Worker。

整个 `/goal` 继续保持 active；下一阶段优先拆分 Root Cause Lens 的控制条与候选视图，或补齐黄金调查路径的连续截图/教程证据；以当前完成审计中暴露的最高风险项为准。

## 第四十里程碑进度（完成：Root Cause Lens 因果走廊与真实绑定驱动夹具）

1. 新增宿主无关 `presentation.lens`，把结构/实测报告转换为不可变中文卡片、摘要、状态与候选证据，不导入 Maya、PySide、Collector 或 Workspace。
2. Presenter 会拒绝陈旧焦点、重复或外部候选、路径方向不一致、Plug 路径漂移，以及实测/结构候选代次不一致；不会为了画界面猜测缺失证据。
3. `LensControlBar`、`LensCandidateCard` 与 `LensRibbon` 迁入 `ui/lens.py`，独立拥有方向、深度、中文动作、键盘激活、可访问名称和紧凑模式。
4. Scene Clinic 进入 Lens 时收起普通规则阵列，把右侧空间完整让给因果路径、Plug 证据和评分因素；关闭后恢复原问题视图。
5. Atlas 将候选按真实 DG 距离动态排成水平因果走廊；fan-out 同距离候选自动进入分层车道，选定路径以动态虚线强调，关闭 Lens 后恢复原节点位置。
6. `examples/generate/lens_chain_scene.py` 在 Maya 2025 中生成并保存 `heroRoot → globalMatrix → spaceDecompose → faceDriver → heroFace_CTRL`，同时让 `faceDriver` 驱动第二控制器形成真实分支证据。
7. GUI 生命周期新增 `lens` 场景，核对四个候选身份、方向、焦点、控制条、证据带和 Maya modified 状态，并继续完成重复启动、热重载、回调/计时器释放和菜单卸载。
8. 1480 × 900 真机 PID 48016 与 800 × 900 真机 PID 29880 均通过；启动前已有 Maya PID 58104 在每轮结束后保持同一身份。
9. 新增宽窄真实截图、黄金路径教程、生成素材说明和干净安装场景入口；界面用户可见文案保持简体中文，节点名按 Maya 制作规范使用短英文。
10. 普通 Python 256 项通过（19 项宿主限定跳过），同一套 256 项在 Maya 2025 `mayapy` 全部通过；新增 Presenter、View、动态布局恢复与真实宿主回归。`ui/workspace.py` 从 3639 行降至 3415 行。
11. 候选 ZIP 的隔离 Module 回放 PID 39572 只从临时解压包导入并完成同一 `lens` 场景；随后验证可恢复卸载、备份恢复、最终卸载和临时目录清理，用户 Maya PID 58104 保持原身份。

整个 `/goal` 继续保持 active；下一阶段优先把 Runtime/Profiler 采集编排进一步移出 Workspace，或对
Atlas 大图增量布局和渲染预算做下一条真实制作纵切；不继续扩张展示版功能面。

## 第四十一里程碑进度（完成：Scene Capture 会话控制器与动态安全边界）

1. 新增宿主无关 `application.scene_capture`，以不可变事件统一场景捕获的启动、进度、取消、代次漂移、失败、复用和完成，不导入 Maya、Qt、Collector 或 UI。
2. 控制器独占采集会话、上次快照身份、分片预算与必需后置验证；取消幂等，必需验证期间拒绝取消，任何终态都确定性释放会话。
3. 场景代次在分片前变化、结果身份错配、旧快照漂移和 Collector 异常都不会提交半成品；显式 `abort` 供关闭路径同步清理。
4. Workspace 不再手动持有 `_capture_session` / `_capture_previous_snapshot`，捕获、队列、Runtime、诊所和性能入口由同一语义状态锁定与恢复。
5. 新增独立 `SceneCaptureStrip`：七阶段光谱扫描、动态探针、橙色取消态、中文安全边界、reduced-motion 与 800px 紧凑模式；平时自动隐藏，不占用调查空间。
6. GUI 生命周期新增 `capture-cancel`：真实 Maya 中保留旧快照、发起并冻结取消态、推进下一安全分片，再验证部分快照未提交、旧对象保留、四组入口恢复和 modified 状态不变。
7. 1480 × 900 真机 PID 54944 与 800 × 900 真机 PID 38488 均通过；两轮结束后启动前已有 Maya PID 58104 保持同一身份。
8. 新增控制器、视图、中文界面和真实生命周期回归；普通 Python 267 项通过（19 项宿主限定跳过），同一套 267 项在 Maya 2025 `mayapy` 全部通过。
9. `application/scene_capture.py` 257 行，`ui/capture.py` 186 行，`ui/workspace.py` 3441 行；这一阶段只收拢捕获编排和状态呈现，不重写已验证的 Collector。
10. 候选 ZIP 的隔离 Module 回放 PID 47012 只从临时解压包加载，完成同一 `capture-cancel` 场景、可恢复卸载、备份恢复、最终卸载和临时目录清理；回放启动时没有可附着的既有 Maya。

整个 `/goal` 继续保持 active；下一阶段优先用真实大场景测量 Atlas 增量布局与绘制预算，再决定布局内核或视口虚拟化的最小纵向切片，不扩大展示版功能面。
