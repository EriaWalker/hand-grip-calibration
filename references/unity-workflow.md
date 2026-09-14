# Unity 运行绑定、采样与持久化

## 先定位当前实现

本案例源码入口（项目相对路径；先核对当前文件）：

- `Assets/KINEMATION/FPSAnimationFramework/Runtime/Core/FPSAnimatorEntity.cs`
- `Assets/KINEMATION/FPSAnimationFramework/Runtime/Core/FPSBoneController.cs`：`LinkAnimatorLayer`、`GetLayerWeight`、`_animationLayers`。
- `Assets/KINEMATION/FPSAnimationFramework/Runtime/Layers/AttachHandLayer/AttachHandLayerJob.cs`：`OnInitialized`、`ProcessAnimation`。
- `Assets/Demo/Scripts/Runtime/AttachmentSystem/AttachmentGroup.cs`：装备/附件切换替换层配置。
- `Assets/KINEMATION/Shared/KAnimationCore/Runtime/Rig/KRigComponent.cs`：按 KRigElement 查找骨骼的实际行为。
- `Assets/RoachArena/Editor/HumanoidWeaponClipBaker.cs`：现有 Generic→Humanoid 离线转换，含骨轴补偿；不能盲目复用其缓存状态。

先图搜索符号取得 qualified_name，再读取源码。反射字段只用于诊断当前插件内部状态，字段变化时重新定位，不把历史反射调用当永久 API。

## 只读绑定探针

`scripts/inspect_runtime.cs.txt` 是可通过 Unity MCP `execute_code(action="execute")` 执行的方法体。默认角色为本案例的 `Rifle_Full_Body`，使用前按用户目标设置，核对 Unity 实例；输出紧凑诊断文本。

同时读取 Entity Profile、活动 Profile、实际 job settings。两个同类型层存在时逐一记录，不把第一个名字相符的结果当唯一所有者。检查该层的完整曲线权重和手腕误差，确认挂载点与绑定的是同一手侧。

记录 `Time.frameCount` 两次，确认动画确实运行。Unity 在失焦且 runInBackground=false 时，直接调用 SampleAnimation 后可能留下尚未经过最终 IK 的中间姿态。此时“手腕距目标 15 cm”不能立即归因为 IK 失败。

可以在已经授权的验证期间短暂允许后台运行；事先保存原值，完成后恢复。输入策略仅在验证真实输入需要时修改，并单独恢复；不要默认改变项目 Player Settings。

## 备份与隔离

分别保存内存 `EditorJsonUtility.ToJson`、磁盘资源副本及 SHA-256。Disk 可能仍是机器人原值，Inspector 已被用户归零；恢复时明确要恢复哪一份。

预览副本置于隐藏、不活动的父对象下，防止 Instantiate 时启动额外角色脚本。禁用 MonoBehaviour、Animator Controller 与不需要的物理/相机组件；需要采样/验证 Animator 时仅启用必要部分。所有临时对象在 finally 中清理。

一段源动画使用一套新初始化的采样状态，或明确恢复整个相关骨架。未键控的 Skeleton/根变换会继承前一片段的状态，曾导致 FAL 武器朝向错误。不要以“该 clip 没有这条曲线”为理由忽略起始姿态。

## 一帧握姿

优先使用符合目标 Avatar 的已有姿势并做最小调整；只有 Offset 无法解决局部手指误差时才制作专用片段。

- 第 0 秒保存目标握姿；可在 0 和 1/60 秒使用相同关键帧，frameRate=60。
- 对手指记录旋转，不通过移动指骨改变骨长。
- 若改变手腕/上臂/前臂定位，采样片段必须能还原手腕**相对 WeaponBone** 的关系：记录必要祖先与 WeaponBone 变换。避免记录角色 GameObject 的空路径 Transform，移动真正的玩家根。
- 检查每条绑定路径真实存在；再逐项核对手部链。
- 普通 Generic Transform 曲线在本案例 Humanoid Animator 上被忽略。可以烘焙为 Humanoid muscle clip；需要精确 Transform 采样时，本案例使用 `legacy=true` 的自定义片段，仅供 Attach Hand `SampleAnimation`，不添加到 Humanoid Controller/Playable 常规动作轨道。
- 使用 `new UnityEngine.Keyframe(...)`，本项目有同名命名空间，简写 Keyframe 曾导致动态代码编译失败。
- 先在副本采样并验证 cachedP/Q 和手指，再保存/接入运行配置。本案例未验证的普通 Generic 采样曾产生超过 1 m 的假偏移，不能重复“先应用再测量”。

`customHandPose` 在初始化或 `OnLayerLinked` 时读取；Offset 在 ProcessAnimation 每帧读取。修改片段或引用后调用原生 LinkAnimatorLayer 或重新装备。当前版本 `overridePoseWeight` 不参与手指覆盖，实际使用层有效权重，未来版本应重查。

## 运行验证和恢复

有效层权重为 1 时分别测量：手腕与 IK 目标位置/角度、手相对真实武器位置、各手指实际旋转、BakeMesh 顶点。链缓存正确也不表示 Humanoid 最终输出不再改变手指旋转。

通过原生装备流程切走再切回，而非直接激活武器 GameObject。调用原生方法的测试要标明“原生流程验证”；只有实际输入事件触发才称“输入验证”。保留用户原来的武器，避免不相关的射击等动作。

只对本次修改的资产 Undo/SetDirty/SaveAssetIfDirty，保留 GUID，不执行全局 SaveAssets 来顺便保存其他人修改。重新读取磁盘、资源和活动引用，防止只改了临时实例。

截图工具有时即使 include_image=false 仍返回 image 内容块。不要 `text(result)` 输出整个 Base64；只转发文本/structuredContent，需查看时用 image(block) 或本地 view_image。

报告本次新增错误与已有 Console 错误的区别。AK12 案例已有 UnityEditor.Graphs.Edge.WakeUp 异常，不能写成“Console 零错误”。若另一个任务正在编译/Play Mode，不停止它来制作方便的验证环境。
