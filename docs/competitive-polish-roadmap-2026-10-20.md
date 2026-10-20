# 对标分析与持续打磨路线图（2026-10-20）

## 1. 本文比较的对象与证据纪律

| 角色 | 对象 | 在本仓库中的形态 |
| --- | --- | --- |
| 上游客户端 | moonlight-stream/moonlight-qt | 源码快照（`/tmp/qt_gamepad.cpp`、streamingpreferences.h 等，抓取时 HTTP 200） |
| 协议层 | moonlight-stream/moonlight-common-c | 我们的 fork `moonlight/moonlight-common-c`，pin 在 `386e79c`，含自有增强（剪贴板同步、7.1.4、HDR dynamic-range、输入边缘完整性） |
| 下游主机 | Sunshine | 经 `Limelight/Network/HttpManager.m` 的显示/虚拟显示器/screenMode/HDR 亮度覆盖扩展 |
| 基地版 | skyhua0224/moonlight-macos-enhanced | 本仓库的起点，2026-10 起完全独立（README） |
| 竞品 | Citrix Horizon、Parsec、网易 UU 远程 | 仅采用 `docs/input-mapping-benchmark.md` 已归档的证据面 |

证据分四级，沿用 `docs/input-mapping-benchmark.md` §1：**本仓库可复核 / 上游已验证 / 仅宣传 / 无证据**。
Parsec 文档在取证时 403，UU 只有宣传页：两者只列"对方宣称有"，一律不作为设计依据。
文中所有代码位置均以本文提交时的 main 为准；凡未真机验证的推断，标注 `hardware_validated=false`。

## 2. 能力矩阵（只列有证据的结论）

图例：✅ 已具备且可复核 · ◐ 部分具备 · ✗ 未具备 · ➕ 我们领先

### 2.1 控制器（当前最大差距）

| 能力 | 我们 | moonlight-qt | 证据 |
| --- | --- | --- | --- |
| 基础摇杆/按键/扳机 | ✅ `LiSendMultiControllerEventCtx`（HIDSupport.m:1261、ControllerSupport.m:376） | ✅ | 本仓库可复核 |
| **控制器类型与能力通告** | ✗ 从不调用 `LiSendControllerArrivalEvent` | ✅ gamepad.cpp:763 | 本仓库 grep 全量为 0；上游已验证 |
| 扳机震动 rumbleTriggers | ✗ 回调未接（Connection.m:2670 只挂 `rumble`） | ✅ | 本仓库可复核 |
| 陀螺仪/加速度计 setMotionEventState | ✗ 回调未接，HID 层无 IMU 解析 | ✅ | 同上 |
| 触摸板 LiSendControllerTouchEvent(2) | ✗ | ✅ TouchEvent2 | 同上 |
| 电池上报 LiSendControllerBatteryEvent | ✗ | ✅ | 同上 |
| LED setControllerLED | ✗ 回调未接 | ✅ | 同上 |
| Joy-Con 左/右 (057E:2006/2007) 识别 | ✗ isNintendo 仅 2009（HIDSupport_Internal.h:393-397） | ✅（SDL 类型表） | 本仓库可复核 |
| Steam Controller / LI_CTYPE_STEAM | ✗ 协议层缺常量（fork Limelight.h 止于 LI_CTYPE_NINTENDO） | ✅ | 与 `/tmp/qt_limelight_upstream.h:781` 对比 |
| PS4/PS5/Switch 专用震动编码 | ✅ HIDSupport+Rumble.m（qt 依赖 SDL 黑盒） | ✅ | **➕ 我们可读可控** |
| Xbox Elite2/Betop Zeus 轴序修正 | ✅（qt 无此处理） | ✗ | **➕** |

后果：主机端永远按 Xbox 360 虚拟手柄对待我们（README 亦如此声明），DS5 自适应扳机、
陀螺仪、触摸板、主机端原生布局提示全部不通。这不是"少一个功能"，是**协议面上的一整个维度缺失**。

### 2.2 键盘

| 能力 | 我们 | qt | 备注 |
| --- | --- | --- | --- |
| 修饰键映射 Command→Win | ✅ 固定表 + 每主机 Command→Ctrl 开关 | ✅ 固定 | 本仓库可复核 |
| 用户自定义规则（97 键×修饰键 + 10 个月亮动作） | ✅ **➕ qt 只有 10 个硬编码 Ctrl+Alt+X** | ◐ | `KeyboardTranslationRule` |
| 接管系统快捷键三态 | ✅ | ✅ captureSysKeysMode | 对等 |
| IME/中文文本注入 LiSendUtf8TextEvent | ✗ 全仓库 0 调用 | ◐（qt 走 SDL textinput，`hardware_validated=false`） | 我们发中文只能逐键，实际不可用 |
| Ctrl+Alt+Del 入口 | ✗ 无任何 CAD 代码 | ◐（qt 有 Ctrl+Alt+Shift+Del 类组合，未在本次取证中复核到具体键） | Sunshine 支持扩展 scancode（0x8000 标志，HIDSupport.m 已在用），可行路径存在 |

### 2.3 鼠标 / 全屏边缘控制栏

| 能力 | 我们 | qt | 备注 |
| --- | --- | --- | --- |
| 绝对/相对/自由三模式 + CoreHID 1000Hz | ✅ | ◐ 仅 absoluteMouseMode | **➕** |
| 亚像素灵敏度、报告率可调、滚轮三通道独立调速 | ✅ | ✗ | **➕** |
| 边缘把手：四边停靠+拖拽+比例记忆 | ✅ `edgeMenuDockEdge`/`edgeMenuButtonEdgeRatio`（MenuUI.m:945-990） | ✗ | **➕** |
| 把手触发参数可调 | ✗ 感应带 12pt、驻留 120ms、甩动 700pt/250ms 全是编译期常量（StreamViewController_Internal.h:100-162） | — | 设置页目前只有总开关+抵达即展开 |
| `LiSendMouseMoveAsMousePositionEvent` | ✗（仅 LiSendMousePositionEvent，HIDSupport+Pointer.m:359/940/997） | ✅ | 相对增量走绝对坐标，桌面向兼容更好 |
| 触屏/手写笔 LiSendTouchEvent/PenEvent | ✗ | ✅ | macOS 场景价值低，暂缓 |

### 2.4 视频/音频/串流（我们领先的区域，如实记录）

- ➕ MetalFX 超分辨率、VT 插帧+强制插帧、6 档 HDR tone-map、VRR(displaySyncMode)、双队列 Pacer、
  7.1.4 Opus 双拓扑、增强音频 EQ/空间化参数（StreamConfiguration 已有一整组 enhancedAudio*）。
- ➕ Sunshine HTTP 扩展：目标显示器/虚拟显示器/screenMode/HDR 亮度覆盖（HttpManager.m:403-450），qt 没有。
- ➕ 剪贴板同步（fork 私有协议 LiBindClipboardSession）、WOL、每主机快捷键、诊断导出、15s 无帧自动重连
  + payload stall 重连（Diagnostics.m:110-116/1074/1100）。
- qt 有而我们无（streamingpreferences.h 逐项核对）：`playAudioOnHost`（UI 层；launch URL 已带 localAudioPlayMode 参数）、
  `muteOnFocusLoss`、`backgroundGamepad`、`packetSize`、`detectNetworkBlocking`、renderer 选择（我们纯 Metal，不适用）、
  `quitAppAfter`（我们有等价：StreamViewController.m 已存在）、23 种语言（我们中英双语）。
- README《当前边界》维持：USB 重定向冻结（Developer ID）、自动更新待实现（Developer ID+Sparkle）。

### 2.5 竞品（证据等级封顶）

- **Citrix Horizon**：ADMX 证据显示其输入模型是"热键表可配 + 三级键盘捕获"，与我们的规则系统同向；
  我们没有它的任何运行时证据，不比较手感。
- **Parsec**：无证据，不做任何断言（含"我们超过 Parsec"这类表述同样禁止）。
- **网易 UU 远程**：仅宣传页证据（300+ 触屏按键映射方案），是手机→PC 场景，与 macOS 桌面客户端不同赛道。

## 3. 打磨路线图

优先级依据：对用户体验的影响 × 实现成本 × 是否被外部条件阻塞。每项附验证方法与硬件验证状态。

### P0 — 控制器协议面补齐（唯一"维度缺失"，收益最大）

分四个可独立交付的小步，全部不动现有 HID/GameController 双驱动结构：

1. **类型与能力通告**：控制器插入时改发 `LiSendControllerArrivalEvent(number, mask, type, buttons, caps)`，
   类型由 vid/pid 判定（isPS4/isPS5→LI_CTYPE_PS，isNintendo→LI_CTYPE_NINTENDO，其余 LI_CTYPE_XBOX），
   能力先报 `LI_CCAP_ANALOG_TRIGGERS|LI_CCAP_RUMBLE`（震动已有）。
   同步修复单控制器模式 `activeGamepadMask` 恒为 1 的写法（HIDSupport.m:1261 传参 `1`），
   手柄拔出时补发清位事件（现在只靠下一次按键的 mask 变化，拔出后主机可能长时间认为手柄仍在）。
   验证：Sunshine 主机 ViGEm 设备管理器可见手柄类型变化；游戏内提示图标从 Xbox 变 DS5/NAS。`hardware_validated=false`
2. **回调接线**：`_clCallbacks` 补 `rumbleTriggers`（透传现有 PS5/Switch 编码或先降为普通 rumble）、
   `setMotionEventState`、`setControllerLED`（Connection.m:2670 附近）。
   LED 先做 DS4/DS5 lightbar（HID output report，参考 +Rumble.m 的写包通道）。
3. **陀螺仪/加速度计**：CoreHID 路径订阅 IMU 元素（PS 全系原生 HID report 内含 6 轴；GameController 路径用 `GCExtendedGamepad` 的 gyroscope/accelerometer），
   按 setMotionEventState 要求的采样率节流后走 `LiSendControllerMotionEvent`。
   能力通告加 `LI_CCAP_ACCEL|LI_CCAP_GYRO`。主机端 DSUDev/DS4Windows 即可吃到原生陀螺仪。`hardware_validated=false`
4. **电池 + 触摸板 + 设备面扩容**：IOHID `BatteryPercent`/`BatteryLocation` 属性 → `LiSendControllerBatteryEvent`；
   PS4/PS5 触摸板 HID 元素 → `LiSendControllerTouchEvent`；isNintendo 补 057E:2006/2007（单只 Joy-Con），
   能力含 `LI_CCAP_TOUCHPAD|LI_CCAP_BATTERY_STATE|LI_CCAP_RGB_LED`（按型号裁剪）。
   顺带评估把 common-c fork 与上游对齐 `LI_CTYPE_STEAM`/`LI_CCAP_DUAL_TOUCHPAD`/`TouchEvent2`（上游已验证存在）。

设置页对应增量（遵守 UI 外观规则，纯新增行）：控制器行内展开"原生能力"状态芯片（类型/陀螺仪/触摸板/电池 已通告与否），
让用户能看到握手结果而不是猜。

### P1 — 键盘与边缘栏打磨

1. **中文/IME 注入**：文本输入提交（marked text 结束、粘贴入聊天框等场景）走 `LiSendUtf8TextEvent`，
   与逐键路径互斥去重。当前中文只能靠剪贴板，这是键盘面最后一个硬缺口。验证：主机端微信/浏览器输入法实测。`hardware_validated=false`
2. **Ctrl+Alt+Del 动作**：新增月亮动作 `sendCtrlAltDel`，走扩展 scancode 路径（0x8000 标志已在用），
   需先对 Sunshine/GFE 各验证一次能否真的拉起 SAS；不行则降级为"提示用户用主机端工具"，不虚报。`hardware_validated=false`
3. **边缘栏参数暴露**：把感应带宽度（8–24pt）、驻留时长（60–300ms）、自动收起（300–1000ms）三档做成
   设置页滑杆（默认值=现编译期常量，不改已验收手感），甩动阈值维持锁定不动——那是防误触的安全垫。
   多显示器下把手跟随当前流窗口所在 screen（现有 anchorRect 逻辑已按窗口算，需要真机双屏确认一处）。`hardware_validated=false`

### P2 — 对等补齐与小改进

1. `LiSendMouseMoveAsMousePositionEvent`：相对模式在"主机是桌面"档（Sunshine 桌面场景）改发增量绝对化事件，
   旧游戏兼容路径保留。带开关，默认关。
2. 自动重连策略收敛：现有 5 种触发点各自为政，补统一退避（1s/3s/9s，最多 N 次）与"主机确认消失即停"判据；
   重连期间输入事件入队上限维持现状。
3. qt 对等项打包：`muteOnFocusLoss`、`backgroundGamepad`（失焦时手柄继续/暂停发事件）、`playAudioOnHost` UI 开关
   （协议参数已在），每项独立开关、默认维持现行为。
4. 被阻塞项维持冻结：USB 重定向、自动更新（Developer ID 一票否决），README 边界表如实保留。

### P3 — 观察项（不排期）

- 多显示器双实例串流（协议支持多会话，但 macOS 窗口/输入捕获复杂度高，等 P0–P2 消化完再评估）。
- `LiSendTouchEvent`/`PenEvent`（iPad 侧栏触摸板模拟可用 macOS 触控板替代，需求未证实）。
- UU 式"按键映射方案库"——那是触屏场景，桌面键鼠规则系统已覆盖需求，不跟。

## 4. 明确不做

- 不改任何用户已验收的 UI 外观与默认值（AGENTS.md 规则；本页所有 UI 增量均为纯新增）。
- 不以 Parsec/UU 的宣传面为设计依据；不把未真机验证的条目写成已完成。

## 5. 本文取证命令

```sh
cd /tmp/gitlab-ws-mac
grep -rn "LiSendControllerArrivalEvent\|LiSendControllerMotionEvent\|LiSendControllerTouchEvent\|LiSendControllerBatteryEvent\|LiSendUtf8TextEvent" --include="*.m" Limelight | grep -v moonlight-common   # 预期：空
grep -n "rumbleTriggers\|setMotionEventState\|setControllerLED" Limelight/Stream/Connection.m   # 预期：空
grep -n "activeGamepadMask 恒 1" /dev/null; sed -n '1259,1262p' Limelight/Input/HIDSupport.m    # 看传参 1
grep -n "0x2009" Limelight/Input/HIDSupport_Internal.h                                          # isNintendo 只有 Pro
sed -n '100,162p' Limelight/macOS/ViewControllers/StreamViewController_Internal.h               # 边缘栏编译期常量
```

上游对照文件：`/tmp/qt_gamepad.cpp`（ArrivalEvent:763、battery:154、TouchEvent2:485、三个回调实现:901/915/950）、
`/tmp/qt_limelight_upstream.h`（LI_CTYPE_STEAM:781、DUAL_TOUCHPAD:790、TouchEvent2:809）。
