# MayaScope 2025 安装、自检与恢复

## 1. 原则

当前交付只面向 Maya 2025 + PySide6。安装器只注册一个用户级 `.mod` 文件，不复制工程、
不修改 `userSetup.py`、不写 Maya Preferences，也不启动可见 Maya。所有写入都使用临时文件
加原子替换；遇到同名但非 MayaScope 管理的 Module 会拒绝覆盖。

## 2. 安装与升级

从 `D:\3D\_tools` 运行：

```powershell
python -m MayaScope.install status
python -m MayaScope.install install
python -m MayaScope.doctor
```

默认目标是 `%USERPROFILE%\Documents\maya\2025\modules\MayaScope.mod`；如果设置了
`MAYA_APP_DIR`，则使用该目录下的 `2025\modules`。`doctor` 会启动一个隐藏、离屏、短生命周期
的 Maya 2025 `mayapy`，验证 Maya/API、PySide6 和 MayaScope 导入，不打开 Maya 主界面。

升级同一受管 Module 可重复执行 `install`。工程仍从 `D:\3D\_tools\MayaScope` 加载，因此代码
更新后不需要复制文件；重启 Maya 或显式 reload 包即可载入新版。

## 3. 卸载与恢复安装

```powershell
python -m MayaScope.install uninstall
```

卸载不是删除：Module 会重命名为带 UTC 时间戳的
`MayaScope.mod.uninstalled-*.bak`。需要恢复时，在 Maya 关闭后把该备份改回
`MayaScope.mod`。安装器不会删除任何历史备份。

## 4. Crash Bisect 中断恢复

每个完成的 Probe 都会在
`%LOCALAPPDATA%\MayaScope\runner\<plan-id>\bisect-journal.json` 原子记录。用户取消、关闭
工具或 Maya 宿主退出后，可重新打开 Failure Prism 并点击 `RESUME BISECT`；也可在命令行运行：

```powershell
python -m MayaScope.runner resume <调查目录>\bisect-journal.json
```

恢复前会同时验证 Journal 校验和与源场景 SHA-256。源场景丢失或变化时会拒绝继续，不会把旧
outcome 套到新文件。已完成候选集从缓存重放，不再次启动 Maya；新的 attempt 从连续序号继续。

最终证据为同目录的 `repro-capsule.json`：

```powershell
python -m MayaScope.runner verify <调查目录>\repro-capsule.json
```

## 5. 后台进程与资源

- Probe 严格串行，同一调查最多运行一个隐藏 `mayapy.exe`；
- 每个 Probe 有独立 timeout，超时进程会被回收并记为 FAIL；
- 关闭 MayaScope 时若 Probe 正在运行，窗口先隐藏，当前 Probe 安全退出后再销毁线程；
- 所有删除、Reference 卸载、求值、保存和重开只发生在 attempt 工作副本；源场景按 SHA-256
  锁定且从不以写模式打开；
- `.ma` 支持 pre-open isolation；`.mb` 只支持 post-open evaluate/save/reopen 隔离。

## 6. 日志与人工排障

运行日志位于 `%LOCALAPPDATA%\MayaScope\logs\mayascope.jsonl`，单文件 2 MiB，保留四个轮转
备份。日志是 JSON Lines，记录 plan id、attempt、阶段、outcome、时长和 Capsule hash；默认
不记录完整场景节点清单。Runner 的 `attempt-*` 目录还保留 request、stage progress、结果、
stdout/stderr 尾部和 Maya crash artifact。

排障顺序：

1. 运行 `python -m MayaScope.doctor`，确认宿主边界；
2. 运行 `python -m MayaScope.install status`，确认 Module 未被外来文件替代；
3. 校验 `repro-capsule.json`，再查看失败 attempt 的 `progress.json` 确认最后阶段；
4. 若源 SHA 已变化，创建新计划，不要绕过校验继续旧调查；
5. 若 `.ma` slicer 因动态 `parent`、歧义路径或编码拒绝，保留原文件并转为人工 Intake，不要
   手工修改唯一源文件来强行通过。

## 7. Scene Clinic CI / 发布门禁

```powershell
python -m MayaScope.audit D:\shots\shot010.ma --profile publish --fail-on error --report clinic-audit.json --summary
python -m MayaScope.audit --verify-report clinic-audit.json
```

Audit 严格串行，只启动一个隐藏 Maya 2025 `mayapy`。场景以 `executeScriptNodes=False` 打开，
分析全程只读，并在打开前后核对源 SHA-256。退出码 `0` 为通过，`2` 为命中门禁阈值，`1` 为
宿主、配置或规则失败。不要把 `1` 当作“没有问题”；它表示审计结果不可采信。

`--report` 使用原子替换写入，包含稳定节点身份、证据、逐规则耗时、配置指纹、Maya/API、
快照规模、源文件与报告 SHA-256。下载或转移 artifact 后必须运行 `--verify-report`；任何内容漂移
都会 fail closed。`--summary` 只减少终端 JSON，不改变完整报告。

### 7.1 回归基线

```powershell
python -m MayaScope.audit D:\shots\shot010.ma --profile publish --fail-on error `
  --performance-samples 7 --report clinic-baseline.json --summary
python -m MayaScope.audit D:\shots\shot010.ma --profile publish --fail-on error `
  --baseline-report clinic-baseline.json --gate-mode regression `
  --max-slowdown 0.20 --min-slowdown-ms 2 --report clinic-regression.json --summary
```

`absolute` 模式检查当前场景是否越过严重度门槛；`regression` 模式只阻断新增/加重的原子 Finding
或真实性能退化，因此基线中已知且未恶化的问题不会持续阻断。比较前强制验证基线报告签名，
并要求 Clinic profile、配置指纹、Maya 版本和 Evaluation Mode 一致。

Finding 以 `rule_id + stable node id` 比较，而不是以聚合卡片比较。性能使用至少三个样本的中位数，
只有当前减基线的差值同时超过 `--max-slowdown`、`--min-slowdown-ms` 和三倍双方 MAD 噪声带才失败。
性能采样会在内存中交替相邻时间、dirty DG 并拉取几何包围盒，最终恢复原时间；它不会保存场景，
但可能触发表达式和求值回调，因此只应对可信制作场景显式启用。

报告同时记录 `worker_exit_code`（worker 的绝对检查结果）和 `audit_exit_code`（应用 gate mode 后的
最终 CI 结果），避免基线已有错误时混淆两种状态。Workspace 的 `RIFT` 入口只接受签名有效且含
regression evidence 的报告。

## 8. 历史格式与迁移

Snapshot 和 Scene Clinic Audit 只允许注册式逐级迁移。读取旧 artifact 时顺序固定为：读取原始
payload → 验证原始 checksum → 深复制 → 逐级 `N → N+1` 迁移 → 当前模型验证。历史文件不会在
读取时被重写；若要固化成新版本，必须显式重新导出。

当前 Snapshot 为 schema 8、Audit 为 schema 2，已覆盖旧版本真实/构造夹具。高于当前版本、缺少
版本字段、迁移链断裂或迁移函数跳级都会 fail closed。Store envelope 与业务 payload 分别版本化，
不能因为外层压缩容器仍为 v1 就跳过内部模型迁移。

## 9. Runtime Observatory 安全边界

Workspace 的 `RUNTIME` 扫描运行在 Maya 主线程的短时间片中，不启动第二个 Maya，也不修改场景。
扫描 expression、plug-in 与节点 callback 时会安装临时 node-added/node-removed guards；完成、取消、
异常或场景漂移都会移除。扫描期间 Capture、Clinic、Profiler 和 Crash Bisect 被互斥禁用。

Runtime inventory 永远不执行修复：不 kill scriptJob、不 remove 未归属 callback、不 unload plug-in、
不编辑/mute/delete expression，也不把 opaque callback ID 推断为具体 Python/MEL 函数。

Maya standalone/batch 不支持真实 interactive scriptJob inventory，报告会写入
`script_jobs_available=false` 以及 limitation。只有 Workspace 所在的交互式 Maya 会话能证明当前
job 清单；CI 的“不可用”不能解释为“没有 job”。expression 源码只记录短预览、长度和 SHA-256，
完整 Audit artifact仍应按制作资产权限保存。

```powershell
python -m MayaScope.audit runtime_audit_fixture.ma --profile all `
  --performance-samples 5 --report runtime-audit-evidence.json --summary
python -m MayaScope.audit --verify-report runtime-audit-evidence.json
```

该 fixture 应产生 `runtime-script-nodes` 与 `runtime-expressions` 两类证据。scriptNode 在打开时被
禁用执行，expression 只在显式 performance sampling 时进入可信场景的 demand-driven evaluation。

## 10. Query Kernel 性能门槛

Query Kernel 的发布预算为：百万唯一边索引构建 <5 s、估算常驻索引 <128 MiB、5,000 节点/
40,000 边受限冷查询 <50 ms、缓存查询 <5 ms。基准必须把 Snapshot 构建和索引构建分开计时，
并核对 `unique_graph_edges == requested_edges`，避免并行 Plug 压缩造成虚假的百万边结果。

```powershell
python work\query_kernel_benchmark.py --edges 100000 1000000 `
  --output outputs\query-kernel-benchmark.json
```

Lens 出现 `NODE-BUDGET`、`EDGE-BUDGET` 或 `DEADLINE` 是可信的渐进调查边界，不是完整因果域。
需要扩大范围时应显式提高预算或转入离线分析，不应移除边界后阻塞 Maya UI。当前索引由后台
Clinic Worker 预热，进程内最多缓存两个不可变快照；长会话如需回收可调用
`invalidate_graph_indexes(snapshot_id)` 或全局失效。

## 11. Atlas 语义窗口门槛

Atlas 固定最多物化 240 个节点，但该上限是可换入的渲染预算，不代表分析数据被裁剪。Lens、Delta、
Profiler 与 Runtime 请求的节点若被折叠，必须增量换入；完整 Snapshot 和 Query Kernel 始终保留。
百万规模发布门槛为后台索引+排名 <5 s、前台 Atlas apply <250 ms、语义换窗 <100 ms。

```powershell
"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" `
  work\atlas_virtualization_benchmark.py
```

报告必须同时证明 `snapshot_edges=1000000`、`rendered_nodes<=240`、
`folded_focus_materialized=true`，并保留离屏截图。当前本机结果为 2.83 s / 63.5 ms / 32.8 ms。

## 12. 增量捕获与精确失效

第二次及后续 Workspace 捕获会把当前 Snapshot 传给 collector。`CSR REUSED` 只在稳定节点顺序和
完整 edge tuple 由 collector 精确复用时出现；它不表示场景完全相同，节点属性、Reference、selection
和 plugin metadata 仍可能变化并进入 Delta。rewire 后如果仍显示复用，应视为严重契约故障。

```powershell
"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" `
  work\incremental_capture_benchmark.py
python work\incremental_million_benchmark.py
```

真实 Maya 基准必须覆盖 unchanged、attribute-only 和 rewire；百万模型基准必须证明共享 tuple 时
两个索引均 alias、单边 rewire 时 alias 为 0。手工回收仍可使用 `invalidate_graph_indexes()`；普通
快照轮换由容量为 2 的 QueryKernel 自动淘汰，不需要用户干预。

## 13. 长会话证据生命周期

Runtime、Profiler、Counterfactual、Regression、Lens 和 Delta 均绑定生成它们的 Snapshot。新捕获会
清除旧证据；Runtime 额外校验 `source_snapshot_id`。如果 UI 在新 capture id 下仍展示旧 Runtime
轨道或旧 Regression 样本，必须停止采信并保存日志，这是跨快照污染而不是可接受缓存。

关闭 Workspace 会停止全部视觉 timer、清空 Atlas 并调用全局 Query Kernel invalidation。验证命令：

```powershell
"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" `
  work\evidence_lifecycle_smoke.py
```

证据必须满足 `stale_runtime_and_regression_cleared=true`、关闭前索引数 2、关闭后 0，且
`animation_timers_stopped=true`。QueryKernel 另有 100 次 alias 链单元回归，防止长期重捕获导致驻留增长。

## 14. Maya 双向选择桥

工作区顶部 **MAYA · 联动** 使用一个受所有权约束的 `SelectionChanged` callback：

- Maya → Atlas：读取长 DAG 路径，45 ms 去抖后映射到当前 Snapshot 的稳定 ID；
- Atlas → Maya：通过长路径写回选择，并抑制由本次写回产生的精确回声；
- 重名短节点不会猜测归属，只有唯一名称或精确 DAG 路径才能命中；
- 联动关闭或 Workspace 关闭时 callback 必须立即移除；失败不得泄漏异常到 Maya 事件循环；
- 新 Snapshot 的身份索引由 Clinic 后台线程构建，可取消且以不可变 Mapping 交回 UI。

十万节点 / 二十万身份基准：后台索引 0.129 秒、峰值 11.0 MiB；1000 次精确查询总计
0.393 ms。实机视觉证据中的 `host_to_atlas_focus=driver_00`、
`atlas_to_host_selection=matrix_driver_03` 且关闭后 `selection_bridge_active_after_close=false`。

## 15. 场景制片契约与发布一致性

场景单位和色彩策略不采用内置“正确答案”。团队在 Clinic 配置 schema 2 的 `scene_contract`
显式声明允许的时间单位、必要单位/上轴、色彩管理、渲染空间和插件策略；未声明的字段不检查。
旧 schema 1 配置会在内存中升级，不改写源文件。

契约命中会产生场景级 `scene-contract` Finding，不伪造受影响节点；每个偏差分别携带“要求 / 当前”
中文证据。该规则自动加入内置 `all` 与 `publish` Profile。设置自 Snapshot schema 3 起保存，当前
schema 4 继续保留；Delta
能指出具体改变的设置字段，Audit 的 `snapshot.scene_settings` 与 `plugins_in_use` 可供 CI 复核。

验证命令：

```powershell
python -m MayaScope.audit scene-contract-probe.ma --profile publish --fail-on error `
  --config examples\clinic.team.json --report scene-contract-audit.json --summary
python -m MayaScope.audit --verify-report scene-contract-audit.json
```

故意违规的夹具应返回 `worker_exit_code=2`、`gate_failed=true`、`rule_failures=[]`，并输出
`场景制片规范不一致`。配置字段拼写错误、X 上轴、重复条目、同一插件同时必要和禁用都会
fail closed，而不是忽略策略。

## 16. 外部文件依赖健康

MayaScope 只读取 Maya `filePathEditor` 已注册的路径与状态，不遍历任意字符串属性，也不递归
扫描文件夹、展开 UDIM 序列或打开依赖内容。插件注册到 Maya 路径表的 Alembic/USD/代理类型会
自然进入清单；未注册自定义属性不被假装已覆盖。

Snapshot schema 4 的 `external_dependencies` 逐项记录 stable dependency id、owner node UUID、
plug、语义类型、原始/解析路径、存在状态、路径形态、工作区归属和序列 token。规则边界：

- `missing-external-files`：Maya 明确返回不存在，ERROR；
- `nonportable-external-files`：文件存在但使用工作区外绝对路径或网络路径，WARNING；
- 环境变量路径和工作区相对路径不会仅凭形态误报；
- Reference 继续由第一类 `SceneReference` 处理，不在外部文件清单重复计数。

真实 Maya 2025 的 1000 个缺失 UDIM 依赖基准完整捕获 1000 个唯一身份，用时 0.377 秒（包含
首尾路径表 refresh 与一致性复核），预算为 3 秒；报告见 `external-dependency-benchmark.json`。发布门禁验证：

```powershell
python -m MayaScope.audit external-dependency-probe.ma --profile publish --fail-on error `
  --report external-dependency-audit.json --summary
```

预期 `worker_exit_code=2`、`rule_failures=[]`，且报告内依赖的 `exists=false`、
`sequence_pattern=<UDIM>`。

## 17. 工作区与场景内存生命周期

隐藏 Audit 的隔离 `MAYA_APP_DIR` 不等于制作项目。路径判断按以下优先级选择工作区：

1. 命令行显式 `--workspace D:\show\project`；路径必须是现有目录；
2. 从场景目录向上查找最近的 `workspace.mel`；
3. 找不到时回退到场景所在目录，并在报告写入 `workspace_source=scene-directory`。

推荐发布系统始终显式传入项目根：

```powershell
python -m MayaScope.audit D:\show\shots\shot010.ma --workspace D:\show `
  --profile publish --fail-on error --report clinic-audit.json --summary
```

Snapshot schema 5 的 `scene_lifecycle` 记录 modified、文件类型、实际工作区、当前时间、播放范围和
动画范围。`unsaved-scene-changes` 只在 Maya 明确返回 modified=true 时报告，不把“不可读取”当作
干净或脏。交互场景修改属性后应命中；保存后应清除。隐藏 Audit 打开正常磁盘场景时应为
modified=false；若插件/open callback 在打开后改脏场景，则报告会保留该差异。

## 18. 分片快照宿主上下文一致性

节点新增/删除和连接 mutation callback 之外，collector 还会在首尾比较不可变宿主上下文签名：
场景单位/色彩设置、modified/工作区/时间范围、使用中插件，以及 Maya 刷新后的完整注册路径表。
任一项在分片采集中变化都会抛出 `SceneChangedDuringCapture`，清理 callback 并要求重试。

该签名只查询 Maya 已维护的状态；不读取依赖内容、不展开序列、不递归目录。真实 Maya 回归分别
在捕获中途改 `fileTextureName` 和 `currentUnit`，两者都被拒绝。1000 路径基准已包含首尾 refresh，
总捕获仍为 0.377 秒，低于 3 秒预算。

## 19. 回归 Finding 原子主体

一张 UI 聚合卡可以携带多个 `atomic_subjects`，每项由稳定 subject id 与可选 owner node UUID 组成。
Audit 原样序列化，Regression 以 `rule_id + subject_id` 比较：外部依赖使用 dependency id，场景契约
使用具体策略字段。旧规则继续按稳定节点拆分；无节点且无显式主体的历史报告按 Issue id 回退。

因此同一 file 节点从 1 条增加到 2 条缺失路径会产生 1 个新增 Finding，而不是被节点级 key 覆盖；
场景契约从帧率偏差变成上轴偏差会分别显示 resolved/new。原子主体引用不存在节点、空 id 或重复 id
会 fail closed。Regression 还要求双方显式工作区和关键 SceneSettings 相同，否则拒绝比较，避免
把项目根或 fps/色彩环境变化误写成代码性能退化。

## 20. 项目级发布门禁

项目审计包只消费已经通过 SHA-256 验证的单场景 Audit，不重新打开 Maya，因此聚合本身不会干扰
前台会话。实际场景审计仍应由发布系统串行执行，再汇总：

```powershell
python -m MayaScope.project_audit build shot010-audit.json shot020-audit.json `
  --report project-audit.json --summary
python -m MayaScope.project_audit verify project-audit.json --summary
```

聚合前强制要求 Profile、Clinic 配置指纹、Maya 版本/API 与
`snapshot.scene_lifecycle.workspace_root` 完全相同；重复源场景、空场景、报告篡改或上下文混用都
返回退出码 1。项目包按规范化场景路径确定性排序，内嵌每份原始签名报告、派生回执与汇总，再对
整个包增加 `project_sha256`。验证会重新计算两层签名、每份回执、上下文、场景顺序、严重级/规则
汇总和最终门禁状态，不能仅信任顶部 summary。

退出码延续 Scene Clinic：0 为全部通过，2 为至少一个场景命中门禁，1 为包不可采信。Maya 中的
**项目门禁** 按钮只展示验证后的包；点击发布列车中的场景可查看场景签名、项目签名、严重级与
原子 Finding 数。完整报告仍包含路径和制作证据，应按项目资产权限保存。

## 21. 可恢复的串行项目审计队列

先创建不可变计划。计划会锁定每个场景的绝对路径与 SHA-256，以及可选 Clinic 配置的内容哈希、
工作区、Profile、严重级门槛、mayapy 路径和单场景超时：

```powershell
python -m MayaScope.project_queue create D:\show\a.ma D:\show\b.ma `
  --plan publish-plan.json --profile publish --fail-on error `
  --config clinic.team.json --workspace D:\show `
  --mayapy "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
```

运行与恢复使用同一条命令：

```powershell
python -m MayaScope.project_queue run publish-plan.json `
  --journal publish-queue.json --report-dir audit-reports `
  --project-report project-audit.json
python -m MayaScope.project_queue verify publish-queue.json --plan publish-plan.json
```

队列始终一次只调用一个隐藏 Maya。每个场景开始前原子写入 `运行中`，结束后写入 `通过`、`阻断`
或 `失败`，并在每个边界刷新 `journal_sha256`。正常暂停只在当前场景完成后生效；进程异常结束留下
的 `运行中` 在下一次执行时转回 `待运行` 并增加恢复计数。已完成报告会重新验证 SHA、来源场景和
计划归属，不重复执行。源场景或 Clinic 配置在计划创建后改变会 fail closed，要求重新创建计划。

只有全部场景都产生可信报告时才生成最终项目审计包。退出码为 0（全部通过）、2（完整运行但有
阻断）或 1（暂停、失败、数据漂移或不可采信）。Maya 内 **批量审计** 使用同一状态机；关闭工具
时会请求安全暂停并等待当前隐藏 Maya 退出，不会销毁仍在运行的 QThread。

## 22. 队列所有权、磁盘预检与崩溃恢复

`run` 在读取旧断点之前先取得与 journal 同名的 `.lock` 内核文件锁；`.lock.json` 只是可读回执，
记录 owner PID、主机、计划签名、断点路径、心跳和当前 mayapy 身份，不能替代内核锁。第二个进程
会直接失败并报告当前持有者，不会再启动一个 Maya。正常退出后回执保留为 `已释放`，便于追责。

计划签名同时锁定 `minimum_free_bytes` 与 `estimated_report_bytes`。执行前按卷聚合断点、场景报告、
项目报告和系统临时目录的需求，同卷取最大预算而不是重复相加；任一卷不足会把结构化证据写进
签名 journal 的 `storage_preflight`，状态设为 `预检失败`，且不会启动 mayapy。默认保留 512 MiB，
每个待运行报告估算 8 MiB，可在 `create` 时用 `--minimum-free-mib` 和 `--estimated-report-mib` 调整。

Windows 下子 mayapy 被加入启用 `KILL_ON_JOB_CLOSE` 的 Job Object，MayaScope 崩溃或被强制结束时
内核自动回收子进程。断电或旧运行方式留下的孤儿只在以下条件全部成立时恢复：计划签名相同、
journal 绝对路径相同、可执行文件是 mayapy、记录路径一致、PID 与进程启动 ticks 精确一致。任何
PID 复用或身份漂移都拒绝终止。界面底部会显示容量余量、Maya PID 和“崩溃联动开启/降级”。

## 23. 缺失插件与 unknown 节点取证

Snapshot schema 6 使用 Maya 的只读 `unknownPlugin` / `unknownNode` 查询采集：缺失插件名、场景
要求版本、注册节点/数据类型，以及 unknown 节点保存的原插件和原始类名。采集不会调用
`loadPlugin`、不会修改插件搜索路径，也不会移除 unknown 登记。命令语义以 Autodesk 的
[unknownPlugin](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/unknownPlugin.html)
和 [unknownNode](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/unknownNode.html)
文档为准。

`missing-plugin-requirements` 是根因规则：只要 Maya 的场景登记仍列出不可用插件，就产生 ERROR，
并为每个插件保留独立 atomic subject。`unknown-nodes` 是结果规则：展示已经降级的节点、本地/引用
边界、来源插件和原始类型；本地节点仍只能通过预览 ChangePlan 删除，引用节点保持保护。规则不会
猜测应安装哪个版本，也不会自动从网络或磁盘搜索插件。

```powershell
python -m MayaScope.audit examples\unknown-plugin-probe.ma --profile publish `
  --fail-on error --config examples\clinic.team.json --workspace . `
  --report unknown-plugin-audit.json --summary
python -m MayaScope.audit --verify-report unknown-plugin-audit.json
```

预期退出码为 2，报告中 `snapshot.unknown_plugins[0]` 为 `studioGhostTools 4.7`，并包含
`missing-plugin-requirements` 与 `unknown-nodes`。该夹具故意缺失插件，Maya 打开时的缺失插件警告
属于预期失败路径，不应被隐藏成“干净场景”。

## 24. 引用解析与 namespace 归属

Snapshot schema 7 对每个 `SceneReference` 同时记录：Maya 实例路径、原始 unresolved 路径、
`withoutCopyNumber` 规范化源文件、`{N}` 复制编号、存在状态、namespace、父引用、加载/预览状态、
成员稳定 ID 和失败 edit。Autodesk 的
[referenceQuery](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/referenceQuery.html)
明确区分 resolved、unresolved 与 `withoutCopyNumber`；MayaScope 不会把正常的 `{1}` 多实例引用
当作错误，而是用 canonical path 归并源文件身份。

源文件存在检查只对非 UNC 路径调用 Maya 自身的 `file -q -exists`。UNC/网络路径在 Maya 主线程
保持 `exists=null`，避免因为网络挂起冻结交互；这意味着网络源的“未知”不是“存在”，发布系统应
在有超时隔离的 Runner 或农场预检中补充验证。

`missing-reference-files` 对明确 `exists=false` 的引用产生 ERROR；同一 canonical path 的多个实例
合并为一个 atomic finding。`reference-namespace-intrusion` 对引用 namespace 及其子 namespace 中的
本地节点产生 ERROR，并保留节点稳定 ID。两条规则都只诊断：不会创建替代文件、重载引用、移动
namespace 或重命名节点。

```powershell
python -m MayaScope.audit examples\reference-health-probe.ma --profile publish `
  --fail-on error --config examples\clinic.team.json --workspace . `
  --report reference-health-audit.json --summary
python -m MayaScope.audit --verify-report reference-health-audit.json
```

预期为两个引用实例、一个 canonical source、复制编号 0/1、两个明确缺失实例和一个
`assetA:localIntruder`。Audit 必须返回退出码 2、规则异常 0，并在 `reference_inventory` 中保留所有
解析字段。

## 25. 依赖谱系与序列缺口

Snapshot schema 8 为外部依赖增加序列类型、成员数、已观测编号跨度、内部缺口样例、扫描是否完整
以及停止原因。支持 `<UDIM>`、`<UVTILE>`、`<f>`、`####` 和 `%04d`。UDIM/UVTILE 只统计成员，
不会把合法的非连续 tile 编号误报成缺帧；帧序列只检查磁盘中已观测最小/最大编号之间的内部空洞，
不使用可能由安全 Audit 禁用的 UI scriptNode 播放范围，也不推断未知的首尾帧。

目录扫描只触碰模式所在的本地单层目录，默认最多检查 10,000 个条目、50 ms；网络路径、未展开环境
变量、文件系统错误和超预算目录都保持 `sequence_scan_complete=false`。`external-sequence-gaps`
仅对完成扫描后确定存在的内部空洞发出 WARNING，不把未知状态当成通过或失败。

```powershell
python -m MayaScope.audit examples\dependency-sequence-probe.ma --profile publish `
  --fail-on warning --workspace . --report dependency-sequence-audit.json --summary
python -m MayaScope.audit --verify-report dependency-sequence-audit.json
```

预期识别两个序列依赖：UDIM 有 1001/1002 两个成员；帧序列有 0001/0003，并明确缺少 0002。
发布包中的 `.exr` 只是路径存在性文本占位，不是可渲染图像。

## 26. 真实 Maya GUI 生命周期验证

`MayaScope.gui_lifecycle` 会在启动前记录全部现有 `maya.exe` PID，然后用隔离 `MAYA_APP_DIR`、
`-noAutoloadPlugins` 和隐藏窗口创建一个独立 Maya GUI。宿主通过真实 `launch.run("workspace")`
加载工作区，并验证父窗口确为 `MayaWindow`，不是离屏仿制界面。

```powershell
python -m MayaScope.gui_lifecycle `
  --maya "C:\Program Files\Autodesk\Maya2025\bin\maya.exe" `
  --output mayascope-gui-lifecycle.json `
  --screenshot mayascope-real-maya-gui.png `
  --timeout 90
```

可选 `--scenario instruments` 会在同一受管 Maya 中真实执行一次 DG/视口 Profiler 采样与 Runtime
清点，随后截图并实际清除采样；`--width` / `--height` 可验证 800 × 560 以上的停靠尺寸。仪器场景
回执额外记录事件数、节点映射、Runtime 信号、清除按钮复位、派生证据失效、Runtime 保留以及 Maya
modified 状态前后一致。默认场景不执行这些额外操作，干净安装回放继续使用默认生命周期。

`--scenario runtime-cancel` 专门覆盖 Runtime 分片采集的取消路径。探针先启动真实采集并冻结取消态
截图，再推进一个安全分片，确认控制器释放 Maya 回调守卫、运行时/捕获/诊所入口恢复、旧证据仍在，
且场景 modified 状态没有变化。该场景也会继续完成重复启动、开发热重载、计时器归零和菜单卸载。

探针依次检查首次绘制与捕获、重复启动只保留一个可见工作区、开发热重载先关闭旧窗口、选择回调
移除、全部动态计时器停止、菜单卸载和宿主退出。超时时只在 PID、启动 ticks 和可执行路径仍与本次
创建身份完全一致时终止进程。最终回执同时证明测试进程已经结束、启动前 Maya 身份逐一保持不变。

2026-08-27 的仪器实证同时覆盖 1480 × 900 与 800 × 900：宽屏 PID 44988 采集 584 个事件，
窄屏 PID 15124 采集 865 个事件；两者均完成 Runtime 清点、清除采样恢复、重复启动、热重载和关闭，
9 个活动计时器归零且 Maya modified 状态不变。结构化回执与截图使用
`mayascope-instruments[-narrow]-lifecycle.json` 和 `mayascope-instruments[-narrow].png`。

## 27. Release ZIP 干净安装回放

普通 Module 测试只能证明安装器会写文件，不能证明最终 ZIP 解压后能被一套全新的 Maya 配置发现。
`MayaScope.install_replay` 把发布包当作唯一输入，完整复演：

```text
验证 release-manifest 与全部文件 SHA-256
→ 解压到临时 release 目录
→ 使用解压副本安装隔离 MayaScope.mod
→ 清空开发 PYTHONPATH 与 MAYA_MODULE_PATH
→ 通过真实 Maya 2025 首次启动工作区
→ 核对 MayaScope.__file__ 确实来自临时 release
→ 卸载并保留备份
→ 恢复备份并重新识别
→ 再次卸载
→ 删除完整临时安装环境
```

运行示例：

```powershell
python -m MayaScope.install_replay MayaScope-3.0.0-dev-Maya2025.zip `
  --maya "C:\Program Files\Autodesk\Maya2025\bin\maya.exe" `
  --output mayascope-clean-install-replay.json `
  --screenshot mayascope-clean-install-first-launch.png `
  --timeout 100
```

涉及 Profiler/Runtime 视图或状态恢复的候选包使用 `--scenario instruments`；涉及 Runtime 会话、
取消和控件恢复时使用 `--scenario runtime-cancel`。该参数会原样传给从
临时 Module 启动的真实 GUI 探针，因此能证明仪器闭环来自 ZIP 解压副本，而不是开发源码。可同时
传入 `--width 800 --height 900` 验证窄停靠。

它复用真实 GUI 生命周期探针：记录启动前已有 Maya PID，只操作自己创建的隐藏 GUI，超时仅在
PID、启动 ticks 与 `maya.exe` 路径仍精确匹配时回收。开发目录不会加入子进程环境；Module 内容、
实际加载包目录、安装/恢复/卸载状态、真实 GUI 回执和临时目录清理结论全部进入结构化 JSON。

2026-08-27 的首次实证使用候选 ZIP SHA-256
`e96ac44af36a553bf31343afcab9e753e05f0546cbdcdd0798127d14787b91d2`。Maya 2025 测试进程
PID 50220 在 18.292 秒内自行退出；解压包来源核对、首次启动、重复启动、热重载、9 个计时器归零、
菜单卸载、Module 备份恢复、最终无活动 Module 和临时目录删除全部通过。最终发布包重建后必须
重新运行本命令，以最终 ZIP 的哈希回执替代该候选证据。
