# MayaScope 架构与渐进拆分合同

MayaScope 采用“宿主无关调查内核 + 薄 Maya 边界 + 状态驱动 PySide 视图”的目标架构。当前实现已经
拥有较清晰的 Model、Analysis、Collector、Action、Runner 和 Storage，但历史快速开发让
历史版本的 `ui/workspace.py` 同时承担视图、呈现状态、后台任务和业务编排。当前已经抽出
Presentation State、后台 Worker、UI Foundation 与 Scene Atlas View，但主窗口仍承担多个业务工作区
的装配和控制器逻辑。本文件记录当前真实边界与渐进迁移顺序；它不是已经完成重构的声明。

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

`MayaScopeWorkspace` 暂时保留 `_snapshot`、`_issues` 等兼容属性，它们全部映射到唯一
`_presentation`，保证可以小步迁移现有 5000 多行视图代码。新增代码应直接使用语义转换，不再添加
新的平行状态字段。兼容属性将在各工作区拆分完成后删除。

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
- 性能、Runtime、回归、项目门禁和 Failure Prism 使用 QWidget + QPainter；
- QTimer 只驱动绘制 phase、去抖和分片捕获；
- 耗时纯数据分析使用 QThread Worker；
- Maya 场景 API 与 QWidget 更新留在对应的安全线程边界；
- 视觉仍保持“取证、拓扑、光谱、风险、精密仪器”，不与 MayaCraft 共享完整皮肤。

## 后续拆分顺序

1. 继续把 Atlas 控制器从主窗口迁到显式 Coordinator；当前只完成 View 边界；
2. 按 Clinic、Lens、Profiler、Runtime、Project Gate、Regression、Bisect 拆分视图模块；
3. 建立 Application Coordinator，统一捕获、诊所、性能和项目任务的状态机；
4. 将当前主窗口内的完整 QSS 提取为可版本化主题表面，并保留真实截图差异验收；
5. 逐步移除 `_presentation_field` 兼容属性，让视图通过显式 render/state transition 工作；
6. 为每个工作区保留普通 Python 状态测试、离屏中文视觉测试与真实 Maya 生命周期测试。

每一步必须保持真实入口、截图、选择联动、取消、热重载和关闭清理通过。禁止一次性搬动全部类、
重新实现已经验证的 QPainter/QGraphicsView，或用“代码分文件了”冒充职责已经分离。

## 当前验证证据

- 普通 Python：196 项通过，19 项仅宿主环境测试按预期跳过；
- Presentation State：新场景代际失效、选择互斥、Lens、Profiler、Runtime、Delta 与字段拼写保护；
- UI Foundation：稳定命名色板、Qt6 分组枚举和拼写拒绝；
- Scene Atlas：节点/边物化、240 节点预算、异常节点优先、选择不回声和动效定时器边界；
- 真实 Maya 2025：PID 35408，19.815 秒自行退出；
- 生命周期：首次启动、重复启动、开发热重载、唯一可见工作区、选择回调和菜单卸载通过；
- 清理：9 个活动计时器归零，残留可见工作区为 0。

`ui/workspace.py` 已从 5414 行降到 4835 行。该证据证明 Foundation 与 Atlas View 迁移没有改变
已覆盖行为，不证明主窗口控制器或其余业务工作区已经完成拆分。
