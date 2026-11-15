# KeyboardRouting 吸收评估（只读）

评估日期：2026-11-15。目标仓 `/Users/<user>/code/moonlight-ci`，基地版为任务级只读浅克隆（上游 Moonlight macOS 增强分支 v1.3.9 RC8，HEAD `2c13fd6f46d1d83ca838dadae011116d0088260a`，评估后已按归属清理）。以下行号对应本次检查时文件版本。

## 结论

**暂缓整体吸收；可考虑只吸收“纯规则决策 + C 单测”的模式，待 per-device 输入路径稳定后再定接口。** 不是因为纯 C 提取本身难，而是基地版模块当前承担的规则与本仓并非同一契约：本仓已经有更复杂的修饰键物理状态采样、输入上下文生命周期、每设备/宿主偏好及合成按键所有权；直接搬 `MLModifierPolicy` / `MLModifierEdges` 会和现有类型、映射器及发送队列重叠。另有明确架构时效风险：基地 README 称 v1.3.9 是“原生架构重建前最后一个版本”（`README.md:25-30`），所以这套 Objective-C 调用方式很可能短期过时；具体重建何时发生及是否推翻此层，源码未证明。

## 已验证：基地 KeyboardRouting 抽出的职责与 API

文件只有 `Limelight/Input/KeyboardRouting.h`（164 行）；未发现同名 `.m`。头注释说明它是无 AppKit 依赖的纯决策层，供 `HIDSupport.m` 与 `StreamViewController+MouseCapture.m` 调用（`KeyboardRouting.h:3-8`）。函数均为 `static inline`：

- 修饰键物理/远端 mask、VK 映射：`HIDRemoteModifierKeyCode(HIDKeyboardRemoteModifierMask)`，`KeyboardRouting.h:13-50`。
- 根据 `MLModifierPolicy` 将物理 mask 映射为远端 mask：`MLDesiredRemoteModifierMask(HIDKeyboardPhysicalModifierMask, MLModifierPolicy)`，策略含 Control/Win 交换、Command→Control、快捷键翻译、Option/Command 顺序及左右 Command 延迟翻译（`KeyboardRouting.h:52-96`）。
- 计算前后远端状态差异并返回有序边列表：`MLModifierEdges(previous, desired)`，按 Shift、Control、Alt、Meta，左先右后输出 `{vk, down}`（`KeyboardRouting.h:98-129`）。
- 判定 performKeyEquivalent 转发后是否立刻发 key-up、由普通 key-up 持有，或交本地 monitor 收尾：`MLPassThroughChordPlan(controlHeld, commandHeld, windowsKeyOrder)`、`MLHeldKeyUpDecision(eventForThisWindow, inputEnabled, windowsKeyOrder, keyIsHeld)`（`KeyboardRouting.h:131-164`）。

**它抽出的是纯策略/边沿计算，不是状态机或事件发送器。** 基地 `HIDSupport.m:1019-1056` 仍读取自身物理状态和兼容设置、组装 `MLModifierPolicy`、更新 `keyboardRemoteModifierMask` 并通过 `HIDDispatchInput` 发送。`flagsChanged:` 仍在 HIDSupport（`1058-1065`）。另一调用方在 `StreamViewController+MouseCapture.m:2038-2065`，持有 key-up monitor 与 held-key set；`2930-2950` 仍负责实际 keyDown/up。

基地包含纯 C 测试 `tests/key-routing/test_key_routing.c`，调用上述 API 覆盖普通/Windows 顺序映射、状态边沿和按键等价路径（例如 `:13-40, :64-119`）；runner 为 `tests/key-routing/run.sh`。本次只读，没有运行测试。

提交史限制：给定的 `95c0e6f1ae`、`03f74b78ad`、`d83c979a`、`f3feb45a0a`、`74618d7613`、`43f860ea54`、`7ab710fc06` 在该浅克隆中不可解析；克隆报告为 shallow，且只有 HEAD/master ref。因此不能逐提交核实各提交引入的独立 diff。关于按字符映射、Windows 键位顺序、Caps Lock、触控板手势的判断应视为任务提供的提交描述，未在本评估里据此推断模块职责。

## 已验证：本仓现状及架构差异

本仓 `HIDSupport.m` 当前由内联逻辑处理。它把左右物理修饰键分别编码（`HIDSupport.m:180-200`），映射物理 keyCode/flags（`:202-242`），并从 device-dependent modifier bits 判定具体哪一侧键按下，避免仅用 Shift/Command 家族位时误保留已松开的左/右键（`:244-291`）。远端 mask/VK/泛化 modifier flags 也在文件内转换（`:294-337`）。

状态同步链是 `updateKeyboardPhysicalModifierStateFromEvent:`（约 `1488-1520`）→ `desiredRemoteKeyboardModifierMaskForEvent:`（`:1522-1557`）→ `syncKeyboardModifierStateForEvent:`（`:1559-1603`），后者以 mask 差分调用 `LiSendKeyboardEventCtx`；`flagsChanged:` 另外处理 Caps Lock 状态变化并发特殊键（`:1630-1685`）。`keyDown:` / `keyUp:` 保存按下时 wire code 与释放债务，协调 IME、输入上下文、重复键及未确认快速敲击（`:1884-2024`）。`releaseAllModifierKeys` 与 `releaseRemoteModifierKeysForUncapture` 负责 teardown/失焦释放（`:2026-2092`）。合成快捷键还按当前远端持有 mask 计算“由合成动作拥有”的修饰键，避免误松用户物理按住的键（`:340-424`, `2288-2384`）。

和基地的关键差异：本仓的核心对象不仅是“物理 mask → desired mask → edges”，而是设备状态采集、宿主偏好映射、捕获/IME门控、输入 lease/串行发送、合成与真实按键所有权共同构成的状态链。基地 C API 只能代替其中的纯映射/边沿规则；把其 mask 名称和决策直接并入会形成两套相近但独立的表示。基地 `MLModifierPolicy` 还按兼容模式集中映射；本仓此处结合 `KMR_*` 映射和 per-host Command preference，见 `desiredRemoteKeyboardModifierMaskForEvent:` 附近（本仓当前 `HIDSupport.m:1522-1603`）。

## 吸收成本与冲突面（逐区域评估）

目标工作树已有未提交改动：`HIDSupport.m` 以及设置 pane/model/persistence/store、桥接和中英文资源共 9 个路径；其中 `HIDSupport.m` 的未提交 diff 是新增 186 行键位布局映射相关内容。以下是估算，不是实际补丁量：

| 区域 | 可行性与冲突判断 |
|---|---|
| 新增 `Limelight/Input/KeyboardRouting.h` | 文件级低冲突；需审视项目文件/构建规则是否自动收录。基地头文件的全局 `HIDKeyboardPhysicalModifierMask` / `HIDKeyboardRemoteModifierMask` 和 VK helper 与本仓同名 typedef/static 函数冲突，不能原样同时保留（对照基地 `:13-50`、本仓 `HIDSupport.m:180-242,294-318`）。 |
| 本仓 modifier 转换/edge send | 高语义冲突。若采用，需选择以 `KMR` 或 `MLModifierPolicy` 为唯一映射真源，再让 `HIDSupport` 只采状态、发送结果；不能继续同时保留本地 `desiredRemote...` 映射与基地映射。`HIDSupport.m:1522-1603` 是主要替换区，约 80 行级别的接线/清理，实际取决于保留的设备侧采样。 |
| 物理状态采样与 capture | 应保留在 HIDSupport。基地 API 不覆盖 NSEvent device bits、`CGEventSourceKeyState` 对账、捕获开关期间状态或释放流程；这些不能按基地抽象删掉（本仓 `:244-291,1488-1520,1605-1625,1630-1685,2026-2092`）。 |
| pass-through 与 key-up monitor | 若目标也吸收这部分，应另改 `StreamViewController+MouseCapture.m` 的 monitor 和 key equivalent 两处（基地 `:2038-2065,2930-2950`）。与 per-device 主要不是文本 hunk 冲突，但需把 host 的键位模式、窗口归属、held set 作用域/生命周期定义一致；仅搬 C 函数不会消除这些耦合。 |
| C 测试 | 可以移植为新测试，但当前仓的验证入口/编译器分层需另核；基地测试是对纯函数和模拟 Host 的测试，不验证 NSEvent、IME、设备来源或真实输入链。 |
| 与当前 0.2/per-device 改造 | 不能仅凭分支名判定逐行无冲突；当前 `HIDSupport.m` 有未提交差异，且目标状态链是本仓 per-device 的承载面。所需变更会落在同一 modifier state/mapping/sync 区，故**重叠面高**；独立新头文件本身冲突低。应等现有改造定稿后再做精确三方 hunk 对比。 |

## 风险判断

- **已验证**：基地 README 明示 v1.3.9 为原生架构重建前最后版本（`README.md:27`）；当前克隆内容包含既有 ObjC `HIDSupport` 和 `StreamViewController` 调用点。
- **未验证/推断**：README 未说明重建时间、键盘模块计划或兼容策略。因而“几周内被推翻”不能当事实；但把一个标记为重建前版本的具体接线方案整体移植到另一个持续演进、per-device 状态模型中，短期返工概率高于只借鉴纯决策/测试边界。
- Caps Lock 与触控板手势提交描述涉及事件转发/捕获语义，不属于 `KeyboardRouting.h` 当前纯规则 API。应各自作为行为修复单独评估，不能因为吸收 header 一并带入。

## 若后续决定部分吸收：建议步骤

1. 等本仓 `HIDSupport.m` 的现有未提交/per-device 改造稳定；先冻结物理 modifier mask、host policy 和 edge-send 的唯一真源。
2. 在 `Limelight/Input/KeyboardRouting.h` 只引入无 AppKit 依赖的纯函数，按本仓术语/类型适配，避免重复 `HID*Mask` 与 `KMR` 映射；首批范围仅映射结果/边沿列表。
3. 将 `HIDSupport` 保留为事件采样、捕获/IME门控、lease发送与释放状态所有者；只把纯计算替换为调用，不把运行态移进 C helper。
4. 后续单独决定是否提取 pass-through plan；届时同步修改 `StreamViewController+MouseCapture.m` 两个调用点及 held-key 生命周期，不与 modifier helper 混作一次改动。
5. 移植/改写 `tests/key-routing` 覆盖左右修饰键、双侧按下松开、capture/uncapture、per-host mapping 与合成/真实键持有交互；C 纯测通过后仍需按本仓门禁验证真实事件路径。
6. Caps Lock 与触控板吞手势各开独立差异和验收，不从提交描述自动吸收。
