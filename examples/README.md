# MayaScope 自生成演示素材

本目录只保存 MayaScope 团队自行编写的轻量夹具与配置，不包含商业项目资产或第三方模型。

## 未知插件因果链

`unknown-plugin-probe.ma` 是确定性的 Maya ASCII 2025 夹具。它声明不存在的
`studioGhostTools 4.7`，注册一个 `studioGhostSolver` 节点类型，并创建 `ghostSolver1`。打开时
Maya 会把该实例降级为 `unknown`，用于复现场景 `requires` 中的缺失插件登记、未知节点到原插件
与原始类名的归因、Scene Clinic 发布门禁、Atlas 聚焦、Delta 和签名 Audit。

推荐使用 MayaScope 打开后点击制片信号带中的 **插件幽灵**，再扫描或查看已经产生的
**场景依赖的插件缺失**。工具不会自动查找、加载、删除或替换任何插件。

该夹具为纯文本自生成素材，不依赖外部文件。仓库当前没有声明公共开源许可证，因此它只用于
本项目的内部开发、测试和作品展示，不应被理解为向第三方授予独立再分发权。

## 引用解析与 namespace 归属

`reference-health-probe.ma` 是 Maya 2025 语义生成后压缩整理的失败夹具：同一个不存在的
`missing/reference-health-asset.ma` 被引用两次，第二个实例由 Maya 标记 `{1}`；同时创建一个
本地 `assetA:localIntruder`，故意侵入引用 namespace。它用于验证规范化源路径、复制编号、缺失
状态、unloaded 边界，以及本地/引用对象归属。夹具不包含实际资产文件，Maya 的缺失引用警告是
预期行为。MayaScope 不会自动移动 namespace、重命名节点或创建替代引用。

## 依赖谱系与序列缺口

`dependency-sequence-probe.ma` 由 `generate/dependency_sequence_probe.py` 在 Maya 2025 中生成。
场景播放范围为 1–3：`plateSequence` 只拥有 0001 与 0003，因此确定性缺少 0002；`heroUdim`
拥有 1001 与 1002 两个 tile，但 UDIM 不假定连续 tile 范围，所以只统计成员而不制造缺口告警。

`assets/` 下四个 `.exr` 是仅用于路径存在性检查的文本占位文件，不是可渲染图像，也不冒充商业
素材。扫描只枚举模式所在的本地单层目录，并同时受条目数和时间预算限制；UNC、环境变量路径与
超预算目录保持“未完整扫描”。工具不会打开文件内容、递归子目录或在 Maya 主线程探测网络共享。

## 三镜头项目门禁

`generate/project_gate_fixture.py` 会生成三个轻量 Maya ASCII 2025 场景、三份带 SHA-256 的 Scene
Clinic 回执和一个经过二次签名的项目审计包。镜头 010 是干净基线；镜头 020 故意声明发布缓存缺失，
必须阻断；镜头 030 带一个非阻断插件登记警告。生成器随后调用生产 `build_project_audit` 和
`verify_project_audit` 复核场景排序、上下文、内嵌回执和项目摘要，不会用手写 JSON 冒充通过。

```powershell
python -m MayaScope.examples.generate.project_gate_fixture D:\MayaScopeDemo\项目门禁
```

输出目录中的 `fixture-manifest.json` 记录每个场景与回执的校验值、预期结论和最终项目签名；
`project-audit-showcase.json` 可通过 MayaScope 顶栏的 **项目门禁** 打开。

## 根因透镜绑定驱动链

`generate/lens_chain_scene.py` 使用真实 `maya.cmds` 生成并保存一条四级上游驱动链，并让
`faceDriver.outputX` 同时连接 `heroFace_CTRL.translateX` 与 `secondaryFace_CTRL.translateX`。
它用于演示“症状节点不一定是原因”：聚焦 `heroFace_CTRL` 后，Root Cause Lens 会显示四个候选、
一条按距离排布的因果走廊、精确 Plug 路径和 fan-out 评分证据。夹具完全自生成，不含第三方资产。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -m MayaScope.examples.generate.lens_chain_scene D:\MayaScopeDemo\lens-chain.ma
```

## Atlas 千节点压力场景

`generate/atlas_scale_scene.py` 确定性生成 1,200 个网络节点和 4,800 条扇出连接，用来验证真实
Maya 捕获、增量语义换窗、图元复用和绘制预算。素材完全自生成、采用 CC0-1.0，不含第三方资产。

```powershell
& "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -m MayaScope.examples.generate.atlas_scale_scene D:\MayaScopeDemo\atlas-scale.ma
```
