# 作战计划（2026-10-20 起）：控制器协议面 → 键盘 → 边缘栏 → 对等补齐

 本计划把 `docs/competitive-polish-roadmap-2026-10-20.md` 的 P0/P1/P2 转成可依次交付的波次。
 不可撼动基线（已验收控件、手感常量、协议诚实、验证纪律、冻结项）独立固化在
 `docs/baseline-2026-10-22.md`，任何波次冲突时先读那份文档。
每波都定义了**完成边界**（做到哪一步才算完）、**验收方法**、**回滚**。凡未真机确认的条目，
状态只允许写到 `hardware_validated=false`，不得写成已完成。

## 0. 开工前新核实的三个架构事实（它们改变了工作量估算）

取证方式：本机 grep/sed，位置随文标注。这三条决定波次顺序，先摆在这里。

1. **默认 HID 驱动只有一份手柄状态**。`Limelight/Input/HIDSupport.m:1166` 只创建一个 `Controller`，
   `myHIDCallback`（:2229）按 vid/pid 选轴序但把值写进同一份 `self.controller`；`sendControllerEvent`（:1233/:1261）
   用未赋值的 `playerIndex`（恒 0）与**硬编码 mask `1`**。
   ⇒ 在默认驱动下，"多手柄"与"按手柄类型通告"缺的不是调用，而是 **per-device 状态表**。这是 P0 的真实前置。
   另一驱动的 `ControllerSupport` 已有 `_controllers` 字典（:242 按号取），天然多手柄，但 `GCController` 不暴露 vid/pid，
   类型判定只能退到 `productName` 字符串或 `LI_CTYPE_UNKNOWN`。
2. **IMU 与触摸板的原始数据其实已经在解析路径里**。`myHIDReportCallback`（`HIDSupport.m:2490+`）已把
   PS4/PS5 状态包按 `PS4StatePacket_t` 解出，六轴与触摸板字段就在这个包里，只是没人读。
   缺的是**让手柄开始上报**：PS4 feature report 0x05（`pSmPowerSettings`）、PS5 0x09、Switch subcommand 0x40，
   而 `HIDSupport+Rumble.m` 已经有 `writeSubcommand:`/`hidGetFeatureReport:` 可复用的写包通道。
   ⇒ 陀螺仪的成本主要在"启用 + 节流 + 单位换算"，不在解析。
3. **震动分发在 HID 路径忽略 `controllerNumber`**。`StreamViewController.m:1786` 里 MFi 路径按号取手柄，
   HID 路径直接 `rumbleLowFreqMotor:` → `getFirstDevice`（`HIDSupport+Rumble.m:214` 取集合里第一个）。
   ⇒ 第二个手柄的震动今天就是丢的；接 `rumbleTriggers` 之前先补"按号找设备"。

顺带核实：主机触摸板能力可判定（`Connection.m:2747` 已暴露 `LiGetHostFeatureFlags`，查 `LI_FF_CONTROLLER_TOUCH_EVENTS`）；
手柄拔出回调 `myHIDDeviceRemovalCallback`（`HIDSupport.m:2787`）已存在，只清状态不发清位事件。

## 1. 波次与完成边界

顺序约束：**0 → M1 → (M2/M3/M4) → 键盘 → 边缘栏 → 对等项**。
M1 未落地前不要碰 M2/M3/M4——能力没通告，主机不会发 `rumbleTriggers`/`setMotionEventState` 请求，接了也不会有回调。

### 第 0 波：地基（不改任何用户可见行为）

**0.1 手柄能力探针（纯新增，先有仪表再动手术）**
- 在诊断日志/诊断报告里输出每块手柄的 vid/pid、判定结果、当前驱动、通告后的 type/caps 占位。
- 完成边界：串流一次后，诊断报告能读出"看到几条 HID 身份、分别被判成什么、用哪个驱动"。
  报告按 VID/PID/协议族分组计数，`nodeCount` 是分组内节点数；同型号多只手柄会合成一行，
  所以"几条身份"不等于"几只物理手柄"。不改变发包行为。
- 验收：`scripts/diagnostics-report-tests.py` 扩展一条断言；本机插两块手柄看日志。

**0.2 HID 路径 per-device 状态表（M1 的硬前置）**
- 把 `HIDSupport` 的单 `Controller` 改为按 `IOHIDDeviceRef` 索引的状态表；`myHIDCallback`/`myHIDReportCallback` 按 sender 设备写各自槽位；
  `sendControllerEvent` 改为按活动设备扇出，`playerIndex` 由连接顺序分配并可复用。
- **风险控制**：这一步只允许保持行为等价（单手柄时发包序列必须与改前逐字节一致）。
  用录制对比证明等价，不靠"看起来没问题"。
- 完成边界：单手柄回归测试发包序列不变；双手柄时两路状态不再互相覆盖。
- 回滚：单文件族回退（HIDSupport.m / HIDSupport_Internal.h / Controller.h），无协议变更。

### 第 1 波：P0 控制器协议面（四个可独立发布里程碑）

**M1 类型与能力通告 + mask 修正 + 拔出清位**
- 接入点：连接建立后与设备热插拔时发 `LiSendControllerArrivalEvent(number, mask, type, buttons, caps)`；
  类型由 vid/pid 判（isPS4/isPS5→`LI_CTYPE_PS`，isNintendo→`LI_CTYPE_NINTENDO`，其余 `LI_CTYPE_XBOX`）；
  能力首轮只报 `LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE`（两者我们确实有）。
- 同批改掉 `HIDSupport.m:1261` 的 mask 硬编码 `1`，并在 `myHIDDeviceRemovalCallback` 发 mask 清位事件。
- **不做**：不报 ACCEL/GYRO/TOUCHPAD/BATTERY/RGB——那时还没实现，虚报会让主机发我们接不住的请求。
- 完成边界：Sunshine 主机侧虚拟手柄类型随设备变化；拔手柄后主机及时看到断开。
- 验收：主机设备管理器/`DS4Windows` 列表截图入 docs；App 侧日志有通告记录。`hardware_validated=false` 直到该截图存在。
- 预期收益（这一步单独就有用户可感知的价值）：主机端按键提示图标与原生布局随手柄变化。

**M2 三回调接线 + 按号震动**
- `Limelight/Stream/Connection.h` 协议、`Connection.m:2670` 回调表、`Connection.m` 的 `Cl*` 桥函数、
  `StreamViewController.m` 实现四处同层新增：`rumbleTriggers`、`setMotionEventState`、`setControllerLED`。
- 震动先决条件：把 HID 路径改成按 `controllerNumber` 找设备（第 0 波事实 3）。
- `rumbleTriggers` 实现优先级：PS5（DualSense 有独立扳机马达）→ PS4/Switch 降级为普通 rumble → Xbox 系忽略（无硬件）。
- `setControllerLED`：先做 DS4/DS5 lightbar（HID output report，复用 `+Rumble.m` 写包通道），Switch/NAS 不做（无对应 LED 语义）。
- 完成边界：主机请求扳机震动时 PS5 扳机真的动；LED 颜色跟随主机请求；无对应硬件时静默忽略且日志说明原因。
- 设置页**不动外观**：仅在既有"控制器"高级区新增状态芯片（纯新增行，遵守 AGENTS.md 规则）。

**M3 陀螺仪/加速度计**
- 启用：PS4 0x05 / PS5 0x09 feature report、Switch subcommand 0x40；关闭路径同样要做（手柄拔出/流结束时复原，否则手柄一直高带宽上报）。
- 解析：复用 `PS4StatePacket_t` 已有字段 + Switch IMU 包（`+Rumble.m` 的 subcommand 应答通道）。
- 节流：按 `setMotionEventState` 给的 Hz 采样，超采样窗口丢帧而不是排队（陀螺仪要新鲜度，不要积压）。
- 单位换算须写清依据（`LiSendControllerMotionEvent` 单位是 m/s² 与 dps），并加断言门控防单位漂移。
- M1 的能力通告此时补上 `LI_CCAP_ACCEL|LI_CCAP_GYRO`。
- 完成边界：主机 DSUDev/DS4Windows 读到非零六轴；关闭流后手柄功耗回到基线（肉眼判据：手柄灯/发热不做断言，以主机侧无残留请求为准）。
- `hardware_validated=false` 直到真机记录。

**M4 电池 + 触摸板 + 设备面扩容**
- 电池：`IOHIDDeviceGetProperty(device, CFSTR("BatteryPercent"))` + `BatteryLocation`（当前全仓库 0 引用）；
  有线手柄无该属性时报 `LI_BATTERY_STATE_NOT_PRESENT`，不要报 0%。
- PS4 一系连读属性都不用：`PS4StatePacket_t.ucBatteryLevel` 已在包里（`HIDSupportRumbleTypes.h:47`），
  与六轴/触摸板字段同源；其余手柄才走 IOHID 属性路径。
- 触摸板：PS4/PS5 包里已有 touch 字段；发 `LiSendControllerTouchEvent`，先查 `LiGetHostFeatureFlags()` 的
  `LI_FF_CONTROLLER_TOUCH_EVENTS`，不支持则退化为鼠标输入（qt 的 clickpad 仿真思路），不要空转。
- 扩容：`isNintendo` 补 057E:2006/2007（单只 Joy-Con）；评估把 common-c fork 与上游对齐
  `LI_CTYPE_STEAM`/`LI_CCAP_DUAL_TOUCHPAD`/`LiSendControllerTouchEvent2`（改 fork 需单独提交、单独门禁）。
- 完成边界：主机端看到电量百分比；PS5 触摸板在主机上表现为触摸板；Joy-Con 单只被判成任天堂。

### 第 2 波：P1 键盘（两个独立里程碑）

**K1 中文/文本注入（当前键盘面唯一硬伤）**
- 现状：`LiSendUtf8TextEvent` 全仓库 0 调用；`keyDown:`（`HIDSupport.m:1472`）自己翻译 keyCode，无 `NSTextInputClient`。
- 分两步，第一步就能解决绝大多数实际痛点：
  1. **已提交文本注入**：`event.characters` 含翻译表覆盖不到的字符（中文、 emoji、全角）时，改发 `LiSendUtf8TextEvent`，
     并与 keyCode 路径**互斥**（同一次按键不能既发键码又发文本，否则会双字）。
  2. **marked text（拼音候选）**：需要 `StreamView` 实现最小 `NSTextInputClient`（`hasMarkedText`/`setMarkedText`/`insertText`），
     候选窗留在 Mac 本地。这一步风险更高（会碰键盘事件的接收路径），单独提交、单独验收。
- 完成边界：主机端微信/记事本能打中文；英文/游戏按键路径无回归（17 个键盘门禁必须全绿）。
- 明确降级：如果 K1.2 引发握键/修饰键回归且不可控，只交付 K1.1 并在 docs 记为部分完成。

**K2 Ctrl+Alt+Del 月亮动作**
- 复用扩展 scancode 路径（`0x8000 | vk`，`HIDSupport.m:1494` 已在用），新增 `sendCtrlAltDel` 动作进 10 个月亮动作表。
- 先做一次真机可行性验证（Sunshine 与 GFE 各一次）。拉不起 SAS 就**降级为提示 + 不做该动作**，禁止虚报可用。
- 完成边界：要么真机拉起安全注意序列并记录，要么明确记录"不可行"并保留代码开关关闭。

### 第 3 波：P1 边缘栏参数化（注意门控会挡路）

- **先改门控，再改默认**：`scripts/edge-sensor-summon-tests.py` 现在直接断言
  `MLEdgeSensorBandWidth` ∈ [8.0, 16.0]（正则匹配编译期常量）。把常量变成运行时设置项会让门禁变红。
  同一次提交里把门控改成"校验默认值与允许区间"，**保留 16pt 上限的防回归语义**（当年 24pt 太宽会吞边缘点击）。
- 暴露范围：感应带宽度（8–16pt）、驻留（60–300ms）、自动收起（300–1000ms）。**默认值必须等于现常量**，
  已验收手感一个都不改。
- 不做：甩动阈值 700pt/250ms 与 2s 冷却维持编译期常量——那是锁定模式的防误触安全垫，不该被调松。
- 多显示器：`edgeMenuAnchorRectInScreen` 已按窗口算，需真机双屏确认把手跟随与全屏 menu-bar 遮挡各一次。`hardware_validated=false`
- 完成边界：三项设置持久化并即时生效；门控仍会拒绝越界默认值；单屏行为逐帧不变。

### 第 4 波：P2 对等补齐（各自独立小提交）

1. 自动重连退避收敛：现有 7 个触发点（`StreamViewController+Diagnostics.m` 的
   connect-timeout-auto / timeout-overlay-manual / manual-address-change / risk-recommended-profile /
   adaptive-drop-mitigation / startup-no-payload-reconnect / payload-stall-reconnect）统一到一处退避状态机
   （1s/3s/9s，上限次数，主机确认不可达即停）。**只加纪律，不改任何触发条件**。
2. qt 对等项：`muteOnFocusLoss`、`backgroundGamepad`、`playAudioOnHost`（协议参数已在 launch URL，只缺 UI 开关）。默认值维持现行为。
3. `LiSendMouseMoveAsMousePositionEvent`：仅"主机是桌面"档启用，带开关默认关。
4. 冻结项不动：USB 重定向、自动更新（Developer ID 阻塞），README 边界表保持如实。

## 2. 每波通用的执行标准

```sh
bash scripts/local-gates.sh         # 门禁清单取自 workflow，新增门禁会被自动带上
xcodebuild build                    # BUILD SUCCEEDED
git -c user.email="codex-agent@homelab.local" -c user.name="Codex Agent" commit
git push gitlab main                # 推 GitLab，GitHub 由 publish-github 镜像
# 等 30s 以上再查 project 6 pipeline，立刻查会拿到旧 pipeline 误判
```

- 一个里程碑一个提交一个 pipeline；门禁红了就修，不绕过。
- 新增行为尽量带**纯新增**的设置项 + 新门控脚本（含 self-test），沿用本仓库"门控必须证明自己会失败"的纪律。
- UI 一律遵守 AGENTS.md：已验收控件与默认值不改，只允许纯新增。
- 手柄类真机验收建议做一支 `scripts/controller-handshake-live-acceptance.py`，沿用 `edge-handle-live-acceptance.py` 的取证风格。

## 3. 状态板（开工时逐条更新，不批量勾）

| 里程碑 | 依赖 | 代码可完成 | 真机验收 | 状态 |
| --- | --- | --- | --- | --- |
 | 0.1 探针 | — | 是 | 本机日志即可 | 代码与 68 项回归完成，真机待验证（hardware_validated=false）；真机验收需先装 build1933（日常应用仍是 1926） |
 | 0.2 per-device 状态表 | 0.1 | 是 | 双手柄本机 | 等价基线已交付（21 用例/8 变异）；per-device 拆分完成（每设备独立 Controller/playerIndex/mask 位/变化检测器），9aa5c6b9 pipeline 388 8/8 全绿，本地 xcodebuild 无第一方 warning；双手柄真机待验证（hardware_validated=false） |
| M1 类型/能力通告 | 0.2 | 是 | 需 Sunshine/GFE 主机 | 代码完成（arrival 通告/真实 mask/拔出清位/诊断报告记录通告类型），本地门禁 77 过 + 基线 21 用例等价；主机侧虚拟手柄类型验证待真机（hardware_validated=false） |
| 0.2b HID 鼠标路由 | 0.2 | 是 | 双手柄本机 | 代码完成（每设备 gesture、单一指针 owner 接管/恢复、进入中性帧、拔出只清 owner），routing 门禁 13 正向+8 变异，pipeline 396；双手柄真机待验证（hardware_validated=false） |
| M2 三回调 + 按号震动 | M1 | 是 | 需 PS5 手柄 + 主机 | 按号震动完成（rumble 路由到 player index 指向的 pad，去重按设备）；setControllerLED 已接（macOS 侧三回调首个落地：C 回调→forwarder→owner→按号写灯，PS4/PS5 写路径回显马达不互踩，RGB 能力位仅对 PS4/PS5 通告），routing 门禁各 4 正向+2 变异；rumbleTriggers/setMotionEventState 仍待开工；PS4/PS5 真机待验证（hardware_validated=false） |
| M3 陀螺仪 | M1 | 是 | 需 PS 系手柄 + 主机 | 待开工 |
| M4 电池/触摸板/Joy-Con | M1 | 是 | 需对应硬件 | 待开工 |
| K1 文本注入 | — | 是 | 需主机输入法 | 待开工 |
| K2 CAD | — | 是 | 需主机（可能不可行） | 待开工 |
| E1 边缘栏参数化 | — | 是 | 需双屏 | 待开工 |
| P2 四项 | 各自独立 | 是 | 部分需双机 | 待开工 |

## 4. 风险与放弃条件

- **0.2 是本计划唯一的大重构**：它改的是输入主路径。等价性证不出来就停在这一步，
  M1 退化为"仅在 MFi 驱动下通告类型"，HID 驱动维持现状并在 README 说明边界。**不接受"先上了再说"。**
- M3 的启用/关闭不对称会留下手柄持续高带宽上报（用户能感知为发热/掉电），关闭路径未验证前 M3 不得标记完成。
- K1.2 触碰键盘接收路径，若出现握键/修饰键回归且 17 个键盘门禁任一无法转绿，只交付 K1.1。
- 硬件不可得（无 Joy-Con、无 GFE 主机）的条目长期保持 `hardware_validated=false`，不因此推断可用。

## 5. 明确不做

- 不做多显示器双实例串流、`LiSendTouchEvent`/`PenEvent`、UU 式触屏按键映射库（理由见 roadmap §3 P3）。
- 不以 Parsec/UU 宣传面为依据；不把未真机验证的条目写成已完成。

## 6. 0.1 探针增量（2026-10-21，代码完成，真机待验证）

- 诊断报告已能输出 controller vid:pid + family + transport + battery + nodeCount +
  会话启动时捕获的 driver，并明确输出四行诚实状态：
  - `driver captured at session start; type-map is a local candidate`（driver 是开流瞬间的，
    设置随后改了不追）
  - `controller arrivals sent to host: no (0.1 probe; M1 owns arrival)`
  - `advertised controller type/caps: not advertised`（0.1 没有任何通告，不假装候选 map 已发出）
  - `HID identity groups: N (VID/PID/family groups, not a physical controller count)`
- 报告读同一张 `MLControllerInventory` 表，协议类型映射是候选，不是已向主机通告的事实；
  M1 未实现前绝不把 type-map 写成主机已被告知。
- 控制器格式化已移到 Foundation-only 的 `DiagnosticsReportBuilder`，Live 只把 snapshot 交给它；
  `scripts/diagnostics-report-tests.py` 对真实格式化输出做回放，共 68 项：六类分类/协议类型
  映射、同身份多节点合并、idle 记录不臆造 driver、session 开关、空 driver 不保留上一次的
  名字、旧 snapshot 不被新会话改写（模型回放，非真机路径复现）、arrival/type/caps 未通告
  文案、HID identity groups 计数边界、空列表与未观察的区别、电池缺读与真实 0% 的区别。
  18 个格式化行为变异及 6 个 inventory 状态变异在临时目录编译运行，另有 1 个静态分析负向检查。
  正向基线失败时立即停止，编译错误或崩溃不计作行为变异被断言捕获。
- `MLControllerDriverNameForIndex` 在 Foundation-only 的 `MLControllerInventory.m` 中映射驱动名，
  非 0/1 的索引返回 `unknown`。
- 顺带修复模型里 `noteSessionStarted` 没有把 live 状态/代数/driver 写回已有 snapshot 的缺陷
  （用模型回放证明，未作真机路径复现）。`local-gates.sh` 默认不再误跑完整
  assertion-battery，skip 统计逐项说明原因，快速/完整模式选择自测接入 GitLab。
- 编译审计识别 `scripts/build.sh` 实际使用的 `build/xcode/derivedData`，并使用 `libs`
  中的 OpenSSL 头文件路径；本地 Swift 审计也识别该构建目录。
- 真机验收仍待做：串流一次后接两块手柄看诊断报告分类、driver、arrival 文案与日志。
  `hardware_validated=false` 直到完成；M1 类型/能力通告仍属于下一里程碑，不在本波宣完成。

## 7. 下一步执行节奏（2026-10-22 盘点后固化）

1. **0.1 真机验收（先于新代码）**：本机日常应用仍是 build 1926，0.1 诊断代码在 1933 里。
   用验收过的 1933 产物替换日常应用（旧版留备份目录），串流一次、接两块手柄，
   导出诊断报告核对分类/driver/未通告文案。通过即把 0.1 的 hardware_validated 翻 true。
2. **0.2 开发（下一提交）**：先写单手柄发包录制对比脚本（等价基线），再拆 per-device 状态表。
   等价证不出来就停，按计划 §4 风险节处理。
3. **M1 起**：依赖 0.2 完成；能力只通告已实现的。
4. 键盘 K1/E1/P2 与控制器波次无依赖，可在 0.2 真机验收期间并行另开提交，
   但每个提交独立门禁、独立回滚。


### 2026-10-23 复核纠正

0.2/M1 此前 CI 全绿仅证明已有门禁通过，未证明真实多设备路径正确。
复核发现状态表未初始化、序列号/VID-PID key 合并同型号设备、借用 CF 对象被错误释放，
以及槽位满时复用 0。当前修复按 live IOHIDDevice 对象区分状态、初始化表、满槽拒绝新增，
新增真实编译状态表方法的双设备/重复回调/拔出复用/16 槽耗尽回放。
单手柄 tuple 回放不能证明整条发包序列等价；hardware_validated=false 保持。
M1 的发送成功记录、驱动隔离、热插拔时机与能力真实性仍须复核，不能提升为完整交付。
M2 未提交草稿已撤回并保存在外部证据目录；自适应扳机与 trigger rumble 不得混用。

### M1 通告生命周期修复（2026-10-23，待本提交 CI）

- 成功通告按 inputContextGeneration 在 inputQueue 去重；C 函数失败不记录成功，后续事件可重试。
- C context 仅由现有 lease consumer 验证并访问；主线程诊断完成回调再次核对 context、代数和设备是否仍存在。
- context 绑定、捕获开启与设备接入均尝试通告空闲设备；仅 HID 驱动且捕获开启时入队。
- 拔出先移除设备表，再通过有效会话的输入队列无条件发送幂等清位（普通状态包可能在 arrival 失败后成功），不依赖滞后的诊断标志；MFi 模式也清理本地表。
- 新门禁编译发货 arrival/removal 方法，回放失败重试、去重、过期 lease、旧完成回调、初始化门控、驱动/捕获门控及拔出竞态；四项行为变异须被断言捕获。
- Release 构建与 first-party warning 审计通过。此波仍未解决统一能力位、按号震动、鼠标模式共享状态和未知 HID 节点问题；hardware_validated=false。

### HID 鼠标路由修复（2026-10-23，69eb84ef）

此前 per-device 表只管了按钮/轴/摇杆，鼠标模式还挂在旧的共享 `Controller` 上：
指针 displaylink 读 `self.controller` 但轴值写进各 entry，摇杆驱动的鼠标不会动；
Menu 长按手势计时也是共享的，两只手柄互串；从未按过 Menu 的一次 release 也可能
被当成旧 hold 误触发；拔出任意手柄会无条件释放鼠标所有权。

本波选择的行为：**单个远端鼠标，明确一个当前控制设备**。
- 每设备独立的 gesture 与物理按钮/轴状态；长按 Menu 的手势按 entry 计时。
- 第二只手柄进入鼠标模式时接管 `mouseModeEntry` 与 `self.controller` 指针源，
  旧 owner 恢复真实 held 的 gamepad 状态；其余手柄不变成鼠标按钮、不抢摇杆。
- 进入鼠标模式先向 owner 发一帧中性事件（保留 playerIndex/mask，零 tuple），
  释放远端 held 状态，避免退出模式后按钮/轴卡住；退出时恢复真实物理状态。
- 切换与 displaylink 读取都在 `@synchronized(self)` 内，指针源不悬空。
- 拔出只清 owner 自己的所有权；非 owner 拔出不释放鼠标。
- 多设备时切换反馈震动暂抑制（legacy rumble 不按号，避免震错手柄），
  单手柄保留原反馈；按号震动留 M2。
- 单手柄默认手势时长、鼠标速率与现常量一致，设置外观/默认值不动。

验收证据：
- 新门禁 `scripts/controller-mouse-routing-tests.py` 从真实源码抽取 myHIDCallback
  轴/按键生产者、真实 removal 回调、Pointer 真实鼠标消费块与 HIDDrainRelativeDelta，
  回放 13 条正向路径与 8 项行为变异（非 owner 写共享、旧 owner 不恢复、指针不切换、
  gesture 共享、无中性帧、所有 pad 转鼠标按钮、退出丢物理 A 位、未按 Menu 误触发）。
  fake 边界仅 IOHID 取值/C 发送记录/clock/所有权 stub，不称真硬件或完整发包等价。
- 本波的中性帧是修复卡键行为，**不能宣称完整单手柄发送序列等价**（0.2 等价基线仍是独立项）。
- Release 构建 first-party 零 warning；本地门禁 80 passed / 0 failed / 15 skipped
  （skip 为已知缺 Debug 产物/慢速探针/CI-only 项）。
- GitLab pipeline 396（SHA 69eb84ef）结果见收尾记录；`hardware_validated=false` 保持。

### 单手柄发包逐字节等价基线（2026-10-23，6109b363）

0.2 的风险节点要求"单手柄时发包序列必须与改前逐字节一致"，用机器比较，不靠记忆。
此前 tuple 级基线（`controller-event-baseline.py`，21 用例）只覆盖 Mac 侧交给 C 层的
9 个参数；本波补上 C 层到线上字节这一段：

- 新门禁 `scripts/controller-wire-baseline.py` 从真实 `InputStream.c` 抽取
  `sendControllerEventInternal` / `LiSendMultiControllerEventCtx` /
  `LiSendControllerArrivalEventCtx` 与 `PACKET_HOLDER`，用真实 clang 编译；
  15 条录制场景（Sunshine gen4/5、GFE gen3/4/5、扩展按钮溢出 buttonFlags2、
  符号扩展客户端、16 槽回绕、gen3 legacy 包、arrival+中性回退）打进真实队列，
  按出队顺序逐字节、逐 channel 与独立 Python 参考实现比对。
- 参考实现复刻 wire 语义：size 字段 BE32、magic LE、GFE 4 槽回绕+mask 4 位
  +MISC→Guide、Sunshine 16 槽回绕、buttonFlags2 仅 Sunshine、gen5 magic 减一、
  C 层 signed int32 的符号扩展防护。
- `--self-test` 种 8 项字节级变异（gen5 magic、buttonFlags2 丢失、槽回绕删除、
  MISC→Guide 丢失、legacy header 漂移、arrival 能力漂移、GFE mask 漂移、MC tail 漂移），
  每项都必须改变至少一个字节或 channel，当前 8/8 拦截。
- 顺带修复 `constraints-audit.py` 不向 assertion battery 子进程转发 `--allow-dirty`
  的问题（父进程已豁免的脏检出，子 battery 会重新判死）。
- 本地：正向 15 场景 + 8 变异全过；constraints audit 146/146 种缺陷全拦；
  综合门禁 82 passed / 0 failed / 15 skipped。
- 边界：基线证明"当前源码的线上字节"，是后续 per-device 改动的对照物；
  它不等价于真机抓包，`hardware_validated=false` 保持。

### M2 按号震动（2026-10-23，待本提交 CI）

主机按 player index 点名某只手柄震动，但旧 HID 写路径忽略编号、永远发给
`getFirstDevice` 的第一只；去重状态 `previousLowFreqMotor/High` 是全局共享的，
多手柄互相吞帧或发错对象。本波：

- `runRumbleLoop` 拆成循环与 `rumbleForControllerNumber:`；`rumbleDeviceForPlayerIndex:`
  按 entry 的 playerIndex 解析 pad（找不到回退 first device，保持单手柄旧行为）。
- 去重状态移到 `HIDDeviceControllerEntry`（`previousLowFreqMotor/High`），
  每设备独立比较，邻居的帧不再被吞。
- entry 保留自己的一份 `hidDevice` 句柄：`entryForDevice:` 存 `CFRetain` 句柄、
  entry `dealloc` 释放——拔出回调移除 entry 后，震动手柄路径解析到的是自有句柄，
  不依赖已释放的总线对象。`HIDSupport_Internal.h` 增加 `<IOKit/hid/IOHIDDevice.h>`
  （macOS IOKit 无 `IOHIDDeviceRetain`，句柄管理走 CF 语义）。
- 新门禁 `scripts/controller-rumble-routing-tests.py` 编译真实 rumble 方法集 +
  `entryForDevice:`，双 pad 回放：按号路由、first-device 回退、每设备去重
  （第一帧必发、邻居不互吞、各自重复被抑制、单 pad 变更只到该 pad）；
  两项行为变异（编号被忽略、去重退回共享）均须被断言拦截。
- `constraints-audit.py` 的 per-class CF 规则新增具名豁免
  `IOHIDDeviceRef hidDevice (HIDDeviceControllerEntry)`，豁免靠 entry 自身 dealloc
  的 release 成立；自测种两个同类同属性的类证明豁免按类名而非属性形状清除。
- 三个既有 harness（device-table/mouse-routing/rumble-routing）的桩补上新属性与
  CF 句柄 stub，编译真实 `entryForDevice:` 后仍全绿。
- Release 构建 first-party 零 warning；本地门禁 83 passed / 0 failed / 15 skipped。
- 边界：三回调（`rumbleTriggers`/`setMotionEventState`/`setControllerLED`）仍待开工；
  Switch 分支与 Xbox 直写路径只验证了去重与路由，未抓真机报文，
  `hardware_validated=false` 保持。

### M2 setControllerLED 接线（2026-10-23，待本提交 CI）

macOS 侧三回调此前一个都没接，主机发来的灯色包被 `FakeCallbacks` 吞掉。本波接
`setControllerLED`（签名最简单、无会话/速率状态、与按号震动同为按编号路由的写
路径），是三回调里第一个落地：

- 回调链补齐：`Connection.m` 新增 `ClSetControllerLED` 并注册到
  `_clCallbacks.setControllerLED`；`ConnectionCallbacks` 加可选方法
  `setControllerLED:red:green:blue:`；forwarder 按 `forwardIfCurrentNamed:`
  模式转发；`StreamViewController` owner 收到后 gated 在
  `hidSupport.shouldSendInputEvents` 上，调 `ledForControllerNumber:`。
- 写路径镜像按号震动：`ledForControllerNumber:` 复用 `rumbleDeviceForPlayerIndex:`
  解析 pad（first-device 回退保持单手柄旧行为），`writeLEDForDevice:` 只对
  PS4/PS5 写（它们才有灯条），Xbox/Switch 无写路径。
- 不踩正在响的马达：PS4/PS5 的效果报告同时含马达与灯色，纯灯色写会 clobber
  正在进行的震动，所以写包回显该设备 `previousLow/HighFreqMotor`，去重只按灯色
  （`previousLEDRed/Green/Blue`，0xFF 表示本会话未写过）。
- 能力位只在能兑现的地方通告：entry 新增 `capabilities`，创建时按
  `isPS4||isPS5` 决定是否加 `LI_CCAP_RGB_LED`，`sendControllerArrivalForEntry:`
  改读 entry 的能力位——符合 M1 "只通告能兑现的能力"，主机不会向 Xbox/Switch
  要它给不了的颜色。
- 新门禁 `scripts/controller-led-routing-tests.py` 编译真实 `ledForControllerNumber:`
  / `rumbleDeviceForPlayerIndex:` / `writeLEDForDevice:` / `entryForDevice:`，双 PS4 pad
  回放：按号路由、first-device 回退、马达回显、每设备灯色去重（两 pad 首帧都写、
  各自重复被抑制、单 pad 变灯只到该 pad）；两项行为变异（编号被忽略、去重退回
  共享）均须被断言拦截。
- 四个既有 harness（arrival/device-table/mouse-routing/rumble-routing）的 entry 桩补
  `capabilities` 与 LED 去重属性；arrival 桩删掉现在未引用的能力位常量，mouse 桩
  因已 import 真实 `Limelight.h`（`LI_CCAP_*` 是宏）只保留本地 `kHIDArrivalCapabilities`。
- Release 构建 first-party 零 warning；本地门禁 84 passed / 0 failed / 15 skipped。
- 边界：`rumbleTriggers`/`setMotionEventState` 仍待开工；PS4/PS5 写路径只验证了
  去重、马达回显与路由，未抓真机报文，`hardware_validated=false` 保持。
