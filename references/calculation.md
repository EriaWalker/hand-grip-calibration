# 几何与计算输入契约

所有 CLI 命令只输出 JSON 候选或证据，不写 Unity 资源。所有输入显式声明：

```json
{"coordinate_space":"weapon-meters-xyzw"}
```

## 刚体拟合与 Offset

`fit` 输入：

- `source_weapon_points`: N×3，机器人参考手姿上的语义点，已经应用原握把偏移，并转换到共同的武器坐标系。
- `target_hand_points`: N×3，对应女角色点，在目标手腕局部坐标系中。至少三个非共线对应点。
- `weights`: N 个非负权重，至少一个正值。手腕、指根、按骨骼分组的蒙皮中心可联合使用。
- `cached`（可选）：实际 Attach Hand job 缓存的 `position`、`rotation`。

算法为加权 Kabsch 刚体拟合，禁止缩放/镜像。输出 `desired` 是手腕相对武器的目标变换；RMS 是对应点误差，不是接触或穿模指标。源机器人本身可能存在误差，不能只最小化参考误差就结束。

`offset` 输入含 `cached` 和 `desired`，两者都形如：

```json
{"position":[0,0,0],"rotation":[0,0,0,1]}
```

以本项目源码为准，运算为：

```text
p_world = p_weapon + R_weapon * (p_cached + p_offset)
R_world = R_weapon * R_cached * R_offset
p_offset = p_desired_weapon - p_cached
R_offset = inverse(R_cached) * R_desired_weapon
```

Position 在武器坐标系相加，Rotation 在缓存手部旋转后相乘。不要把旋转顺序交换，也不要额外用手腕旋转再旋一次 Position。四元数按 x,y,z,w；SciPy 的普通 XYZ Euler 不等于 Unity Inspector 的欧拉角显示约定。

每次更换 custom pose 后重新测量 cached。若算出超出声明范围的偏移，先查采样、单位、父级缩放、绑定路径与坐标系，不能扩大范围来掩盖问题。

## 接触采样验证

### 快照坐标与缩放

参考姿势必须包含框架对 WeaponBone 的完整处理，不能只采样动画片段。在全武器案例中，FAL 的 Pose Sampler 含绕 X 轴 90° 的 `weaponBoneOffset`；遗漏后会产生约 26 cm 的假修正，计入后拟合修正回到约 14–16 mm。该旋转只属于此资产，不是所有武器的默认补偿。异常偏移先查坐标与采样，不扩大限值强行接受。

部分武器的骨架变换含 100 倍缩放。检查所用 BakeMesh 重载是否已应用缩放，以及后续 TransformPoint 又应用了什么；不能假定两者组合始终正确。可用实际权重显式重建武器坐标顶点，与实际运行烘焙结果及已知部件尺寸交叉验证：

```text
p_weapon = WorldToWeapon * sum_i(weight_i * BoneLocalToWorld_i * BindPose_i * p_rest)
```

这里 `p_rest` 来自原始 sharedMesh，矩阵作用于齐次坐标。不要再对已经位于世界或武器坐标系的结果乘 Renderer 变换。更高影响数、blendshape 等仍须遵守下文的重建契约。

Editor 中遇到不可读网格时，本案例通过 `UnityEditor.MeshUtility.AcquireReadOnlyMeshData` 读取原始顶点和索引，并释放 MeshDataArray；没有为导出更改模型导入设置。读取后核对数量和有限值，不能把失败返回的空数组当成无碰撞。该入口属于 Editor，不能直接搬进 Player 代码。

### 武器实体与有限采样

`verify` 输入：

- `vertices`: N×3，实际运行后 BakeMesh 顶点，已经转到武器坐标系。
- `triangles`: M×3，过滤后重新编号的三角形；可为空，此时证据只覆盖顶点。
- `colliders`: 非空列表，每项选择 `vertices`（凸包顶点）或 `planes`（每行 nx,ny,nz,d）。平面法向朝外，内部满足 n·p+d≤0。

对每个凸体取最大平面值，对多个凸体取最小值；负值表示进入至少一个凸体。该值是平面间隙估计，不是精确欧氏距离。开放的武器网格不适合直接以最近面法向认定内外。

用握把、安装座与邻近枪身的独立保守凸包，避免将整把凹形武器合成一个巨大凸体封住握持空间。裁剪区域必须记录且针对当前握点，不要把 AK12 的区域边界复制到其他武器。

检查所有保留顶点及完整保留三角形的中心。脚本将缺少 collider、非法索引、非有限值、错误坐标声明视为错误。低于显式 `--clearance-mm` 则保存失败证据并返回退出码 1。不要降低阈值来把未知风险改写成“通过”。

这仍不是连续三角形碰撞检测。保留轮廓截图和检查范围；需要严格几何无相交时，应另做三角形相交/连续运动验证。

### 双手联合检查

两手各自不进入武器实体，并不保证彼此没有穿透。双手包握时导出同一帧、同一武器坐标系的左右手最终蒙皮，检查三角形相交；优化可固定一手，为另一手构造局部实体，但对手姿态改变后必须重建实体并再次检查真实表面。

分别记录：武器凸实体的平面采样间隙、两手三角形交线数量与报告阈值、两手表面的最近距离。最近距离应包含顶点到三角形和边到边候选，不能只量顶点对距离。表面接近不等于穿透；开放手腕边界、共面接触和检测容差要说明。

Mk23 终验的两手最近距离约 0.049066 mm，和该左手到武器的约 1.002 mm 平面采样间隙是不同指标。`calibrate.py verify` 只做上述有限采样，**不包含双手三角形相交或连续运动检测**；需要另行执行并保存证据。

## 基于运行蒙皮的小幅手指修正

`refine` 额外需要：

- `wrist`: 导出时手腕相对武器的 position/rotation。
- `skin.joints`: 手腕为第 0 项，parent=-1；后面是父先子后的手指关节。每项 `name,parent,p,q`。p/q 是骨骼局部变换；腕部作为手部局部坐标根，其 p/q 不参与 FK。
- `skin.bones`: 对当前 SkinnedMeshRenderer 的每个骨骼，给 `joint`（手链外为 -1）、`matrix`、`bind`。matrix 为 wrist.worldToLocalMatrix × bone.localToWorldMatrix，bind 为 sharedMesh.bindposes；矩阵按**行优先 16 数值**存储。
- `skin.vertices`: 与 `vertices` 完全相同的顺序。每项 `p` 是原 sharedMesh 的顶点，`indices`/`weights` 为四个骨骼索引/权重；不要拿 BakeMesh 顶点代替 bind 顶点。
- `muscle_basis`: M×(关节数−1)×3，单位 rad / muscle unit。

数值导数的取得：在目标 Avatar 副本中复制当前姿态，HumanPoseHandler GetHumanPose/SetHumanPose，单独扰动一个有关手部 muscle（案例步长 0.05），记录每个手指关节 `inverse(q_base)*q_perturbed` 的旋转向量，再除以步长。每次探针都从同一基准 pose 出发。不要在正在运行的角色上改 muscle 来采样。

传入的 skin 必须先重建实际顶点，脚本拒绝 RMS 超过 0.1 mm 的输入。若有 blendshape、非统一缩放、不同骨骼权重格式或更高影响数，先扩展数据格式和重建验证，不能静默截断。

```powershell
uv run .agents/skills/roach-hand-grip-calibration/scripts/calibrate.py refine --input refinement.json --clearance-mm 1.2 --max-translation-m 0.006 --max-rotation-deg 4.6 --muscle-limit 0.3 --output run/refined.json
```

上述限值来自 AK12 小幅修正案例，按问题规模选择。优化同时惩罚表面进入、偏离当前皮肤和过大改动；输出 muscle delta、局部手指四元数、wrist desired，以及离线检查。求解器“收敛”或命令退出成功只代表生成了候选，不代表接触验收通过。

接入后重新采样并 BakeMesh。Humanoid 最终求解可能约束旋转；重新计算与最终运行形状的误差，必要时刷新数值导数。若只能把整只手推离握把数厘米才能消除微小接触，改查手指自由度与接触面，而不是接受失去握持的平移。
