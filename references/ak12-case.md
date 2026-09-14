# AK12 实例：历史基线，不是通用预设

日期：2026-09-14；Unity 6000.3.21f1；项目 roach。

## 资源定位

- 场景：`Assets/Demo/Level/DemoLevel.unity`。
- 角色/身体：`Rifle_Full_Body` / `Body_Sportswea`。
- 活动武器：`AK12_Scriptable(Clone)`，附件斜握把及 RK-2。
- 主 Profile：`Assets/RoachArena/Player/RifleGirl/Settings/AnimatorProfile_AK12_49452d19_11400000.asset`。
- **实际 Attach Hand settings**：`Assets/RoachArena/Player/RifleGirl/Settings/AngledGrip_AK12_f5a98ff9_11400000.asset`。
- 专用 pose：`Assets/RoachArena/Player/RifleGirl/Animations/RifleGirl_AK12_LeftAngledGrip.anim`。
- Rig：`Assets/RoachArena/Player/RifleGirl/RifleGirlRig.asset`。
- 详细历史报告：项目根目录 `Documentation/RifleGirl-AK12-Grip-Calibration.md`。

本次最终 Position（米）为 `[-0.03633229,-0.03829134,0.05408673]`，Rotation（xyzw）为 `[0.72168720,0.02732090,0.48297490,0.49513280]`，Unity Euler 为 `[43.49343,93.41058,134.46870]`。必须与上述专用 pose 配套，不能用于原机器人或其他附件。

## 发现与修复

1. Profile 的默认 Attach Hand 被附件替换，调默认 Offset 无效果。
2. 源机器人和女角色的手骨轴向不同，原数值不能直接复用。
3. 刚体拟合无法独立解决所有指节接触，增加了专用一帧手指旋转。
4. 普通 Generic custom pose 在 Humanoid 上未还原人体骨骼，改成仅供 SampleAnimation 的 Legacy pose，并先验证独立副本。
5. LeftHand 链缺少 `index_03_l`，补入索引 31；含手腕后共 16 个条目。不要在其他模型上照抄此索引。
6. 初轮任意关节旋转的离线结果与 Humanoid 最终输出不同；使用运行数据和 20 个手部 muscle 数值导数再次修正。
7. 最终重新装备 AK12 后，658 顶点 + 1,027 三角形中心，共 1,685 点，保守包围面内部采样点 0，最小估计间隙约 1.067 mm；手腕 IK 误差约 0.0045 mm。

没有修改框架运行源码、机器人资产、骨长和蒙皮权重。没有进行完整换弹、其他附件、极端姿态或 Player Build 验收。仍存在先前的 UnityEditor.Graphs.Edge.WakeUp 异常。

## 公开版回归范围

原项目的 `assets/ak12-regression.json` 包含当时的对应点、运行顶点、三角形和保守凸体平面。公开版不分发这些模型衍生数据，也不分发配套 Unity 资产。本页路径和偏移仅作为历史案例说明。

公开版使用 `examples/synthetic-clearance.json` 检查计算。该文件只包含合成立方体和面片。它不能复现上面的 AK12 握姿结果。

```powershell
uv run scripts/calibrate.py verify --input examples/synthetic-clearance.json --clearance-mm 0.5 --output run/synthetic-check.json
```

上述命令从独立仓库根目录执行。原 AK12 案例使用独立 RK-2、安装座与握持区枪身凸包。该历史检查不覆盖完整武器的连续碰撞，不能代表当前场景已通过。
