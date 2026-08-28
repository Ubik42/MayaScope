# MayaScope 架构与渐进拆分合同

MayaScope 采用“宿主无关调查内核 + 薄 Maya 边界 + 状态驱动 PySide 视图”的目标架构。当前实现已经
拥有较清晰的 Model、Analysis、Collector、Action、Runner 和 Storage，但历史快速开发让
历史版本的 `ui/workspace.py` 同时承担视图、呈现状态、后台任务和业务编排。当前已经抽出
Presentation State、核心 Investigation Coordinator、后台 Worker、UI Foundation、Scene Atlas View、
Scene Clinic 完整视图与 Evidence Presenter，
但主窗口仍承担 Runtime、Profiler、项目门禁等工作区的装配和控制器逻辑。本文件记录当前真实边界
与渐进迁移顺序；它不是已经完成重构的声明。

## 依赖方向

```text
model / analysis
    纯数据、图算法、规则、Delta、根因与性能解释
                    ↑
presentation
    宿主无关的用户可见调查状态与语义转换
                    ↑
application / actions / runner
    用例、ChangePlan、后台审计、取消与恢复
                    ↑
collectors / Maya adapters
    Maya 场景采集、选择、Profiler、Runtime 与安全写操作
                    ↑
ui
    PySide6 控件、QPainter、QGraphicsView、动效、焦点和中文反馈
                    ↑
launch / maya_integration
    MayaWindow、菜单、单实例、热重载与关闭生命周期
```

底层不得反向导入 PySide 视图。纯算法和 Presentation State 必须能在普通 Python 中测试；Maya
对象、Qt Widget、QThread、Callback 和 Timer 不能进入可序列化业务模型。

## Presentation State 第一阶段

`presentation.WorkspacePresentationState` 是不可变的用户可见调查状态，集中保存：

- 当前 SceneSnapshot、ClinicReport、Finding 和 Incident；
- 当前异常、事件簇、焦点节点、Root Cause Lens 与候选；
- 当前 Profiler、反事实实验、Delta 和 Runtime 证据；
- 当前性能时间窗。

它不保存：

- QThread、Worker、QTimer 和取消令牌；
- Maya callback、选择桥或窗口实例；
- 捕获会话、临时路径和进程句柄；
- 控件展开、Hover、动画 phase 等局部绘制状态。

这些对象具有独立生命周期，混入不可变呈现状态会制造无法复制、无法比较也无法安全销毁的假状态。

### 语义转换

Presentation State 不要求视图逐字段猜测失效关系，而是提供语义转换：

| 转换 | 保证 |
| --- | --- |
| `present_scene` | 新快照一次替换场景、诊所与事件，并清除上一代 Lens、Profiler、Runtime、Delta 和实验 |
| `present_clinic` | 同一场景替换规则结果，清除旧异常选择与根因候选 |
| `select_issue` / `select_incident` | Finding 与 Incident 选择互斥 |
| `focus` / `present_lens` / `clear_lens` | 节点焦点和根因证据形成明确生命周期 |
| `present_profiler` | Profiler 与完整采样时间窗同时进入状态 |
| `present_runtime` / `present_delta` | 运行时证据和版本差异显式归属当前调查代 |
| `dismiss_profiler` | 清除采样、实测 Lens 与反事实派生结果，恢复仍有效的 Runtime 或 Delta 覆盖 |
| `dismiss_runtime` | 关闭运行时清单并按 Lens、反事实、Profiler、Delta 优先级恢复 Atlas |

`MayaScopeWorkspace` 暂时保留 `_snapshot`、`_issues` 等兼容属性，它们全部映射到唯一
`_presentation`，保证可以小步迁移现有 5000 多行视图代码。新增代码应直接使用语义转换，不再添加
新的平行状态字段。兼容属性将在各工作区拆分完成后删除。

## Investigation Coordinator

`application.InvestigationCoordinator` 是不导入 Maya、PySide 或 QWidget 的应用编排层，当前负责：

- 接收 Scene/Clinic 异步结果前验证 `snapshot_id`、Issue、Incident 与节点身份，拒绝旧场景结果；
- 在同一场景代中原子生成 Presentation State、Scene Delta 和宿主选择身份索引；
- 把 Maya 单选、多选、清空与无法映射区分为明确决策，歧义短名称不猜测；
- 统一计算结构/实测 Root Cause Lens，并拒绝旧候选进入新 Lens；
- 接收 Profiler、Runtime 与 Counterfactual 前验证场景代次、节点/报告身份、时间范围和恢复回执；
- 输出 `AtlasSceneIntent`、`AtlasHighlightIntent`、`AtlasLensIntent` 等类型化渲染意图。

`ui/investigation_renderer.py` 只把这些意图分派给真实 `SpectralAtlasView`。它不决定规则、身份、
Lens 方向或状态失效关系。这样普通 Python 能证明业务转换，PySide 测试只需要证明意图正确落到
生产 Atlas，而不需要复制一套界面。

## Scene Clinic Rail 与 Evidence Presenter

`presentation.ClinicEvidencePresenter` 不导入 Maya、PySide 或 QWidget，负责把 Clinic 的等待、
未启用规则、规则失败隔离、正常结果、Issue 与 Incident 转成完整 `EvidencePanelState`。标题、正文、
操作文案与是否可执行属于同一个不可变结果，避免视图先换标题、后换正文时短暂显示错误组合。

`ui.clinic.SceneClinicView` 拥有 Rule Array、Spectrum、Issue/Incident 卡片、滚动区、证据正文、变更计划入口和回滚入口。
卡片的创建、销毁与信号转发不再由主窗口处理；事件簇若引用不存在的 Issue 会直接拒绝渲染，不能
静默漏掉证据。Rule Array / Spectrum 已从 `workspace.py` 原样机械迁入该模块，保持已验证的规则光谱、
配置指纹、制片信号和动效不变；构造器仍允许注入替身，普通 Python/Qt 测试无需创建主窗口。

## Qt Worker 边界

Clinic、Crash Bisect 与项目审计队列的 QObject Worker 已移到 `ui/workers.py`。Worker 只负责：

1. 在拥有它的 QThread 中执行一个有界 Application Job；
2. 通过 Signal 发布进度、完成、取消或失败；
3. 不直接读取或修改 QWidget；
4. 不拥有主窗口生命周期。

主窗口仍负责创建 QThread、连接信号、请求取消，并在关闭时等待安全边界。未来会继续把重复的
“创建线程—连接—退出—deleteLater”提取为受测试的任务协调器，但不能为了统一接口削弱项目队列和
故障二分各自的安全退出语义。

## 当前 PySide 视图结构

MayaScope 使用原生 Maya 2025 + PySide6，不使用 WebView 或 Electron：

- `ui/foundation.py` 统一提供光谱颜色、Qt5/6 枚举解析、中文确认框与离屏中文字体装载；
- `ui/atlas.py` 使用 `QGraphicsView/QGraphicsScene` 管理可交互节点、连接、语义渲染窗口、
  Lens/Delta/Pulse/反事实覆盖和选择回声抑制；它不导入 Maya Collector 或主窗口；
- `ui/profiler.py` 独立拥有真实事件地平线、时间窗拖选、采样/反事实/清除动作和自己的动效计时器；
- `ui/runtime.py` 独立拥有表达式、scriptJob、插件与回调四轨动态星图；
- Failure Prism 已迁入 `ui/bisect.py`，中文结果映射位于宿主无关 `presentation/bisect.py`；
- 回归裂隙已迁入 `ui/regression.py`，性能与 Finding 的中文解释由
  `presentation/regression.py` 一次生成；项目门禁已位于独立视图模块；
- Counterfactual Spectrum 已迁入 `ui/counterfactual.py`；宿主无关
  `presentation/counterfactual.py` 在状态切换前验证完整连续的 AB/BA 配对，并统一生成条带、
  证据正文和状态栏文案；
- QTimer 只驱动绘制 phase、去抖和分片捕获；
- 耗时纯数据分析使用 QThread Worker；
- Maya 场景 API 与 QWidget 更新留在对应的安全线程边界；
- 视觉仍保持“取证、拓扑、光谱、风险、精密仪器”，不与 MayaCraft 共享完整皮肤。

## 后续拆分顺序

1. 将剩余批处理/故障编排逐步迁入显式 Application 用例；
2. 继续拆分 Delta 等遗留表面；Lens、Project Gate、Bisect、Regression、Counterfactual 已完成独立边界；
3. 将当前主窗口内的完整 QSS 提取为可版本化主题表面，并保留真实截图差异验收；
4. 逐步移除 `_presentation_field` 兼容属性，让视图通过显式 render/state transition 工作；
5. 为每个工作区保留普通 Python 状态测试、离屏中文视觉测试与真实 Maya 生命周期测试。

每一步必须保持真实入口、截图、选择联动、取消、热重载和关闭清理通过。禁止一次性搬动全部类、
重新实现已经验证的 QPainter/QGraphicsView，或用“代码分文件了”冒充职责已经分离。

## 当前验证证据

- 普通 Python：291 项通过，19 项仅宿主环境测试按预期跳过；
- Presentation State：新场景代际失效、选择互斥、Lens、Profiler、Runtime、Delta 与字段拼写保护；
- UI Foundation：稳定命名色板、Qt6 分组枚举和拼写拒绝；
- Scene Atlas：节点/边物化、240 节点预算、异常节点优先、选择不回声和动效定时器边界；
- Investigation Coordinator：旧 Clinic/Issue/Incident/Candidate 拒绝、同代 Delta、单选/多选/清空、
  歧义身份、Profiler 时间窗、Runtime 身份、反事实恢复回执和确定性的覆盖恢复优先级；
- Profiler/Runtime View：中文清除动作、窄宽按钮几何、计时器归属、真实报告形状和源码依赖边界；
- Clinic/Evidence：等待、空规则、故障隔离、Issue/Incident、ChangePlan 状态、卡片生命周期、紧凑宽度
  与中文源码扫描均有独立契约；
- Failure Prism：开始、探针、取消、完成、部分收敛与失败由纯 Presenter 转换；独立 View 保留原有
  动态钻石轨迹、中文控制和 reduced-motion 计时器边界；
- Regression Rift：稳定、门禁失败、无性能配对和残缺配对证据均有纯 Presenter 契约；条带、Atlas
  高亮、证据正文与状态栏消费同一个不可变状态；
- Counterfactual Spectrum：完整配对、证据不足、中文归档与恢复回执均有纯 Presenter 契约；
  独立 View 保留双柱光谱、扫描线与 reduced-motion 计时器边界；
- 真实 Maya 2025 仪器宽屏：PID 44988，584 个 Profiler 事件，22.440 秒自行退出；
- 真实 Maya 2025 仪器窄屏：800 × 900，PID 15124，865 个 Profiler 事件，22.984 秒自行退出；
- 干净 Release 安装：PID 25748 只从临时 Module 导入，18.623 秒自行退出并完成最终卸载；
- 生命周期：首次启动、重复启动、开发热重载、唯一可见工作区、选择回调和菜单卸载通过；
- 清理：9 个活动计时器归零，残留可见工作区为 0。

`ui/workspace.py` 当前 2853 行；独立 `ui/profiler.py` 为 254 行，`ui/runtime.py` 为 155 行，
`ui/clinic.py` 为 715 行，宿主无关
`presentation/evidence.py` 为 140 行，`ui/bisect.py` 为 222 行，`presentation/bisect.py` 为 119 行，
`ui/regression.py` 为 149 行，`presentation/regression.py` 为 144 行，`ui/counterfactual.py` 为
135 行，`presentation/counterfactual.py` 为 153 行。
主窗口已不再直接拥有 `issue_heading`、`evidence`、`plan_button`、Issue 卡片列表、Clinic、Profiler、
Runtime、Failure Prism、Regression Rift 或 Counterfactual Spectrum View 定义；其他业务工作区仍待迁移。该证据
不能被解释成整个主窗口已经完成拆分。
