---
name: roach-hand-grip-calibration
description: >-
  用于 roach Unity 项目中 KINEMATION FPS Animation Framework 的武器手部绑定、
  Hand Pose Offset 不生效、机器人到 RifleGirl 的握姿复用穿模、手腕与手指校准。
  检查运行时附件覆盖，结合两套骨骼与蒙皮计算偏移，必要时制作专用一帧握姿，
  并验证运行蒙皮及重新装备。适用于分析或明确授权的修复，不用于普通摄像机、移动或材质问题。
---

# Roach 手部绑定与握姿校准

## 目标与依赖

让当前武器附件上的手腕目标、手指姿势和实际蒙皮相互吻合。以当前源码和运行绑定为准；案例路径、数值和骨骼索引不是通用默认值。

- Unity 操作需要已安装的 KINEMATION FPS Animation Framework 和可用的 Unity 工具连接。环境提供 `unity-mcp-orchestrator` 时复用该技能；否则按 [运行时检查](references/unity-workflow.md) 使用已有连接。先读取实例、编辑器状态及 custom-tools。不要复制 MCP 客户端或硬编码端口。
- 代码发现优先 `codebase-memory-mcp`。图中路径失效或结果不足时，再查当前源码。
- 框架/API 行为的本地证据不足时，使用项目的 Context7/官方文档工作流；文档不替代实际实现。
- 离线脚本使用 `uv run`，声明 NumPy/SciPy 依赖。脚本不调用业务网络 API，也不修改 Unity 资源。

确认当前工作区为目标 Unity 项目。此技能来自 roach；迁移到其他项目时重新定位框架、骨架与资产。继承用户授权：“为什么”以诊断为主；计算/修复请求可在指定范围应用并验证。不要要求重复批准已经授权的步骤。

## 快速使用

从项目根目录执行；输入格式见 [计算契约](references/calculation.md)。

```powershell
uv run .agents/skills/roach-hand-grip-calibration/scripts/calibrate.py fit --input landmarks.json --output run/fit.json
uv run .agents/skills/roach-hand-grip-calibration/scripts/calibrate.py offset --input wrist-target.json --max-position-m 0.2 --output run/offset.json
uv run .agents/skills/roach-hand-grip-calibration/scripts/calibrate.py verify --input runtime-skin.json --clearance-mm 0.5 --output run/verification.json
```

`0.2 m` 是 AK12 案例的异常值保护示例，应按角色尺寸确定。输出四元数采用 Unity **x,y,z,w** 顺序；欧拉角由 Unity `Quaternion.eulerAngles` 转换。

## 工作流

### 1. 确认真正生效的绑定

读 [运行时检查](references/unity-workflow.md)，核对当前场景、角色、可见身体蒙皮、手侧、活动武器与附件，然后检查：

- `FPSAnimatorEntity.animatorProfile`、`FPSBoneController._activeProfile`，以及实际 AnimationLayer job 的 `GetSettingAsset()`。
- 有效层权重、缓存 `_handPose`、IK 目标与手腕误差、custom pose 和手部链。
- Inspector 内存值与磁盘值分别备份；记录 GUID/哈希，防止覆盖用户同时调整的值。

**附件能够替换 Profile 默认的同类型层配置。** 实际 job 使用握把自己的 settings 时，修改该资源，而非已被替换的默认层。

批量修复时先列出“武器 × 实际握把 × 手侧”，区分握把覆盖与不改变手部设置的配件。当前实现按设置类型替换所有匹配层；增加右手 Attach Hand 前先查是否会被左手附件一起覆盖。双手分工、动作权重与单手武器配置见 [运行时检查](references/unity-workflow.md#左右手层分工与动作权重)。

### 2. 区分绑定错误与接触误差

先排除错误资产、错误索引、零权重、未更新的帧、未重新采样和缺失手指链。这些不能靠增加 Offset 补救。

同为 Humanoid 不等于相同骨架、局部轴、骨长或蒙皮。手腕到达 IK 目标也不代表手掌和指尖贴合。绑定正确后再比较几何。

### 3. 构造可复现的几何快照

在独立预览场景或隐藏且不活动的父对象下创建副本，先禁用行为脚本，再采样；不要激活额外输入、相机或射击系统。

- 机器人：独立副本依次采样对应基础姿势、附件 custom pose，再应用原附件偏移。
- 目标角色：记录当前骨骼和**可见的那套蒙皮**；导出 bindposes、boneWeights、骨骼矩阵、顶点及三角形。
- 统一到同一武器坐标系，单位米、四元数 x,y,z,w；核对父级缩放和矩阵定义。
- 将 Pose Sampler 的武器偏移计入参考姿态；检查 BakeMesh 与后续变换是否重复应用缩放。读 [快照坐标与缩放](references/calculation.md#快照坐标与缩放) 后再处理异常大的拟合结果。
- 按骨骼语义建立对应点，不按两张网格顶点编号配对。按类别均衡取样，避免高密度网格支配拟合。
- 记录资产、姿态、附件、导出帧与筛选规则。状态改变后重导，不能混用不同动作的网格和武器变换。

### 4. 计算偏移，必要时制作专用握姿

读 [计算契约](references/calculation.md)。先做无缩放刚体拟合，再按当前 AttachHandLayerJob 的公式反解 Offset。副本中先验算缓存与目标手腕；异常结果不要先写入运行资产。

若整只手对齐后仍有个别手指穿模，单个 Offset 不够。保留骨长和蒙皮权重，通过旋转制作目标角色专用的 **0 秒一帧握姿**；不要默认缩小网格。

`refine` 脚本支持用实际 LBS 数据和数值 muscle 导数做小幅修正，结果仍是候选。不要把 15 个手指关节任意 45 自由度优化后的结果视为 Humanoid 运行结果。

### 5. 接入并重新采样

- 只改实际生效的附件 settings、目标角色专用 pose，以及确实缺失的手部链条目。保留原机器人资源的用途。
- 片段类型、曲线与采样规则见 [运行时检查](references/unity-workflow.md)。区分普通 Generic、Humanoid muscle clip 和仅供 SampleAnimation 的 Legacy pose。
- 手部链按需包含手腕和各节手指，逐项核对 name/index，不能只核对总数。
- 更改 pose 引用或曲线后重新链接该层，或原生切走再切回武器。只改每帧读取的 Offset 通常无需重新采样，仍以源码为准。
- 使用 Undo、精确资源保存和并发变更检查；失败只恢复本次修改。
- 按武器的预期基础姿势同步 Profile 默认层与对应附件层的 pose 和 Offset；不可假定每把武器的 `Left0` 都表示同一种握把。

### 6. 以运行结果收尾

1. 确认帧号推进，等待装备/瞄准过渡完成。
2. 重新 BakeMesh，检查手腕误差、手指旋转与接触；离线数据不替代运行数据。
3. 检查相关角度的真实渲染，保留数值证据与截图。用几何计算修正，以截图发现明显异常；尊重用户要求的手动微调方式。
4. 原生切到另一件装备再切回，验证 settings、缓存和接触不漂移；保存后核对磁盘资源。未验证的动作/附件明确列出。
5. 区分静态、Play Mode、Player Build 证据。顶点和三角形中心对凸包的检查是**有限采样的保守估计**，不证明全部三角形或所有动作完全无穿模。

双手包握还要检查同帧两手表面相交，方法与距离定义见 [双手联合检查](references/calculation.md#双手联合检查)。分别验证瞄准、换弹释放及恢复、单手武器攻击；禁用左手 IK 的武器不以左手到未使用目标的误差判失败。

不停止用户或其他任务拥有的 Play Mode。临时修改后台运行/输入策略后恢复原值；退出本任务启动的 Play Mode。清理临时对象，不向 Assets 写调试脚本引发无关编译。

## 常见误判

- 主 Profile 正确，实际 Attach Hand settings 仍可能被附件替换。
- 大旋转可能来自骨轴差异；米级位移可能是采样失败，在副本中拒绝异常值。
- 普通 Generic 人体曲线可能被 Humanoid Animator 忽略，不能以更大偏移补偿。
- 缓存已更新但失焦时帧未推进，读到的是中间状态。
- 本案例版本的 AttachHandLayerJob 不读取 `overridePoseWeight`；先检查当前实现。
- 原机器人本身也可能有接触误差，参考拟合后仍要检查枪体几何。

## 案例与回归

[AK12 案例](references/ak12-case.md) 记录历史配置与验证范围。公开版不包含角色或武器的网格回归数据。

[全武器案例](references/all-weapons-case.md) 记录 5 件装备、14 个手部案例的新增经验。处理多附件、右手校正、双手相交或匕首单手握持时读取；案例数值不是可直接安装的握姿预设。

[合成样本](examples/synthetic-clearance.json) 用立方体和面片检验接触计算。[对应点样本](examples/landmarks.json) 可用于拟合与 Offset 命令。这些样本不代表当前 Unity 场景状态。

```powershell
uv run .agents/skills/roach-hand-grip-calibration/scripts/calibrate.py self-test --output run/skill-tests.json
```

交付应包括实际资产、Offset 单位和四元数、配套 pose、验证范围与恢复方法。只要求分析时不要应用候选。
