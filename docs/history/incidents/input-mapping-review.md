# 键鼠映射全面 review（通路、事实、问题清单、分期整改）

> **最新实现与验证边界见 [`input-hardening-2026-09-27.md`](input-hardening-2026-09-27.md)。**
> 本页保留本轮加固前的审阅快照；下文通路、旧过滤策略、行号与第 6 节分期计划属于历史记录，
> 不表示当前代码仍按该计划运行。设备层事实的后续纠错也见新报告与 `memory-ownership.md` 第 38 节。

> 读者：准备改动输入路径的人，以及需要判断「某条映射为什么长这样」的人。
> 本页是**审阅结论**：通路事实、审计证据、按严重度排序的问题、分期计划。
> 设计原则与已修复根因见 [`input-mapping-design.md`](input-mapping-design.md)；
> 逐项对标 Parsec / UU / Citrix / ToDesk / moonlight-qt 的来源分级见
> [`input-mapping-benchmark.md`](input-mapping-benchmark.md)（本页不重复其证据分级，只引用其结论等级）。
> 本轮起始于 2026-09-27 的「左键完全失效」事故，那份取证教训见
> [`memory-ownership.md`](memory-ownership.md) 第 36 节。

## 1. 键盘：一条按下要走的跳

| 跳 | 位置 | 做什么 |
|:---|:---|:---|
| 1 AppKit 派发 | `StreamViewController+MouseCapture.m:2703` `keyDown:` | 记录 `keyboard-wire view-down`；设置页占用时吞掉 |
| 2 类型门 | `StreamViewController+MouseCapture.m` `onKeyboardEquivalent:` | 非键盘事件的 `keyCode` 未定义，一律不吃（2026-08-02 的单点门） |
| 3 查表 | `HIDSupport.m:1856` `translateKeyCodeWithEvent:` → `HIDSupport.m:89` `keys[]` | macOS 物理码 → Win32 VK；无条目返回 0，两端一起忽略 |
| 4 否认判定 | `HIDSupport.m` `holdKeyboardPressIfUnconfirmedForKeyCode:` | `CGEventSourceKeyState` 说没人按着的可打字键，先扣在本地 |
| 5 结算 | `HIDSupport.m` `settleHeldKeyboardPresses` | 状态翻转→补发；始终否认→交给 `strayKeyPressHandler` 决定用途，否则丢弃 |
| 6 上线 | `HIDSupport.m:1546` `LiSendKeyboardEventCtx(inputCtx, 0x8000\|VK, DOWN, mods)` | 高位 `0x8000` 表示「这是 VK」 |

**修饰键**不走查表：`KeyboardMapResolver.m` 的 `KMR_RemoteMaskForPhysical:` /
`KMR_RemoteMaskForAppKitFlags:` 维护物理侧与远端侧两份掩码，chord 由 `flagsChanged:` 与
`releaseAllModifierKeys` 负责。这是「双击鼠标触发开始菜单」当年被修好的地方。

## 2. 协议事实（一手来源，别按直觉理解）

- `moonlight-common/moonlight-common-c/src/Limelight.h:832-840`：
  `LiSendKeyboardEvent()` 的注释明写 *"Key codes are Win32 Virtual Key (VK) codes and interpreted as
  keys on a US English layout."* —— **这条通道传的是 VK，不是 HID scancode**。
  「我们缺 scancode 直通」这种说法不成立：协议在这条通道上就没有 scancode 语义，
  宿主（Sunshine/GFE）拿到 VK 之后自己按 US 布局反查。README 表格里的表头
  「Windows HID 功能」因此是误导措辞（设计文档表头已在同一次提交里改成 Win32 VK，见 §5 P2）。
- 同文件 `:842-846`：`LiSendKeyboardEvent2()` + `SS_KBE_FLAG_NON_NORMALIZED`（Sunshine 扩展）
  = 告诉宿主「这个码不是从 US 布局 scancode 反查出来的，请原样解释」。**本仓库当前不使用**
  （`grep -rn "LiSendKeyboardEvent2\|SS_KBE_FLAG" Limelight/` 为空）。我们发的是「物理位置 → US 布局
  上的键」，与 moonlight-qt 的 SDL scancode→VK 同构，属于 normalized，所以默认不加标记是对的；
  若哪天改成按字符映射，就必须加。
- 同文件 `:849-850`：`LiSendUtf8TextEvent()`，走 `CTRL_CHANNEL_UTF8` 可靠通道
  （`InputStream.c:1304`，无能力协商、无特性位）。这是唯一能表达「宿主键盘上没有的字符」的通道，
  **本仓库当前完全未使用**。

## 3. 映射表当前状态的审计结论

`HIDSupport.m:89` 起 `keys[]` 共 **114 行**，映射到 **112 个**不同的 host 码。两条新增审计（都在
`scripts/constraints-audit.py`，且逐条验证过能红）：

1. **每个 host 码都必须是 Windows 官方定义过的 VK**。权威集合内嵌在
   `scripts/mac_keycodes.py:WINDOWS_VK_DEFINED`（195 项，来源与再生成命令写在该处注释）。
   当前结果：**114/114 全部已定义**，即表内不存在「发出去被宿主丢弃、本机却记录为已发送」的键。
   植入 `0xFF` 会报 `the mapping table sends codes Windows does not define`。
   这一条的由来：review 过程中 `0xFE` 曾被当作 NumLock 的笔误，实为 **VK_OEM_CLEAR**
   （Mac 数字键盘 Clear 键的真实对应）。凭直觉改它就是把唯一正确的值改错。
2. **共享同一 host 码必须是登记过的配对**。当前登记两组：`0xBB`（`=` 与小键盘 `=`）、
   `0x0D`（Return 与小键盘 Enter）——PC 侧码比 Mac 侧键少，这是事实而不是复制粘贴错误。
   把 `KeypadEquals` 挪到未登记的值会报 `declared pairings no longer used`。

未映射的 SDK 键全部带理由登记在 `scripts/mac_keycodes.py:UNMAPPED_BY_CHOICE`（Fn、JIS 五键），
审计保证「有缺口」与「有说明」两件事同步。

## 4. 鼠标：当前只有两条通路、两种模式

| 用途 | 位置 | 现状 |
|:---|:---|:---|
| 按钮 | `StreamViewController+MouseCapture.m:2744` `mouseDown:` → `:1674` `dispatchMouseButton:` → `HIDSupport+Pointer.m:739` `mouseDown:withButton:` 或 `:905` `sendMouseButton:pressed:syncedToViewPoint:` | **唯一输入源是 AppKit `NSEvent`** |
| 位移（游戏） | `HIDSupport+Pointer.m` `mouseMoved:` 相对位移 | AppKit |
| 位移（Core HID） | `CoreHIDMouseDriver.swift:174/185/257` | 只订阅 `GD X`/`GD Y`，**按钮与滚轮都不订阅** |
| 滚轮 | `HIDSupport+Scroll.m` | AppKit，含 25–50 ms 量化去重与 GCMouse 回显抑制 |
| 模式 | `SettingsModel+DerivedValues.swift:423 mouseModes = ["game","remote"]` | 只有这两种；`isRemoteDesktopMode` 决定绝对/相对 |

`CoreHIDMouseDriver` 只订阅位移不是疏忽，是当时的能力边界：它解决的是「报告率」，按钮继续由
AppKit 负责。**「这台接收器在捕获态把左键报成键盘 usage、按钮彻底没有输入源」这一条已被设备层实测
推翻**（2026-09-27，`hidwatch`：IOHIDManager 监听模式）：一次左键在设备层是完整的
`page=0x09 usage=0x01 value=1` → `value=0`，也就是**真按钮照常上报**；同一次按下之后约 80–220 ms，
同一节点又上报了一个 `page=0x07 usage=0x06 value=1`（键盘 C），而**全程没有 `value=0`**——一个只有
按下、永不抬起的假按键。这只接收器（`AJAZZ 2.4G` vid=0x363C pid=0xED1C，primary=0x1:0x2 鼠标）在同一
HID 节点里同时挂着 `0x07` 键盘页与 `0x0C` 多媒体页，其宏/配置文件层还会把别的键绑成 `usage 0x02`
（键 '1'）。真正的缺陷因此不在按钮通路上，而在**键盘侧没有按设备归属判别**：指针类设备上报的键盘
usage 被当成玩家敲的键发上了线（VK 0x43），宿主自动重复出一串 `c`。之前那条 `left-down=0 /
right-down=32` 计数是**仪器混淆**：当时机器上同时活着两个 MoonlightEnhanced 实例，诊断行不带 pid，
无法判断是谁写的。

## 5. 问题清单（按严重度）

| 级别 | 问题 | 证据 | 影响 |
|:---|:---|:---|:---|
| **P0** | 键盘事件没有设备归属：primary usage 是鼠标的复合设备上报的键盘 usage 被当作 keystroke 上线 | 设备层实测 `AJAZZ 2.4G` 一次左键 → `0x09/0x01` 完整按下抬起 **+** `0x07/0x06 value=1` 且永不 `value=0`；app 侧 `sent-down code=0x8043` 24 次、`sent-up` 仅 6 次 | 宿主收到玩家从没敲的键并被自动重复；把这条 C 翻译成左键会变成双击，只能丢弃该按下 |
| **P1** | 归属判别需要 listen 权限：`NSEvent` 不带设备身份，按设备过滤要用 IOHIDManager 监听流（Input Monitoring），无权限时必须退回现有行为并说明 | 本机 shell `IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)=0`（已授权）；枚举不需要授权，足以在会话开始打印「哪些指针设备携带 0x07 页」 | 没有它，过滤只能继续依赖「key state 否认 + 无抬起」这类间接判据 |
| **P1** | 给 `CoreHIDMouseDriver` 增加按钮/滚轮元素订阅与去重（原 P0，降级：按钮在设备层与 AppKit 侧都正常，缺的是冗余而非唯一入口） | `CoreHIDMouseDriver.swift:257 isMovementUsage` 只认 X/Y；**且该驱动在这台机器上从未投递过位移**（日志无 `CoreHID mouse active` 也无 `fallback`），先要回答「它能不能看见这台设备」 | 决定按钮是否值得有第二条通路 |
| **P1** | `LiSendUtf8TextEvent` 未使用：宿主键盘上不存在的字符无法输入 | `Limelight.h:849-850`、`grep` 为空 | 与向日葵/UU 的「直接文字输入」能力差距；`translateKeyCodeWithEvent:` 返回 0 的键只能被忽略 |
| **P1（已修）** | README 承诺的「映射表」不存在 | `docs/input-mapping-design.md` 现含 `keys[]` 全 114 行，`constraints-audit.py` 比对数据行数 | 新用户可直接查表，改表者有依据；鼠标语义仍缺 |
| **P2（已修）** | `input-mapping-design.md` 表头原写「Windows HID 功能」，实际是 Win32 VK | §2 的 `Limelight.h:832-840` | 读者会以为有 scancode 直通，进而提出错误的整改 |
| **P2** | `input.enableKeyStateHold` 与 stray 翻译共用「否认即非 keystroke」判据，边界只在 C 上 | `HIDSupport.m` `HIDKeyCodeIsStrayClickCandidate` | 若换一台设备泄漏别的 usage，兜底不覆盖；已有守卫场景钉住行为 |
| **P2** | unmapped（返回 0）语义与 `keyboardSuppressedKeyDownKeyCodes` 交织，`releaseAllModifierKeys` 与 chord 的既有边界靠注释维持 | `HIDSupport.m` `keyUp:` | 缺一条把「忽略的键两端都不发」钉住的独立审计 |

**尚未证明、不得当已证的事**：该接收器为什么在左键之后绑定一个 `C`（宏配置文件还是固件缺陷，需要在
AJAZZ 配置端确认）；丢弃这条按下之后，玩家在两台宿主上是否都看不到 `c`；同一节点上报的其它宏键
（实测见过 `usage 0x02`）是否需要同样处理；`left-down=0` 那一次究竟由哪个实例写出（诊断行不带 pid）。
**已推翻、不得再引用的旧结论**：「该设备在捕获态把左键报成键盘 usage、按钮没有输入源」。

## 6. 分期整改计划（每期都有完成判据，不按「做了」算）

| 期 | 内容 | 完成判据 |
|:---|:---|:---|
| 1 | 值域与配对审计（本页 §3 两条） | 已交付：审计存在、植入错误值能红、`--no-battery` 仅剩两条遗留 FAIL（`enhancement-report-tests.py` 未接 CI，属上一轮超分改动） |
| 2 | 补 `input-mapping-design.md`：把 `keys[]` 114 行渲染成表（含 VK 名称、来源行号）、写清鼠标四要素（位移/按钮/滚轮/模式矩阵）与「VK 而非 scancode」 | 文档表格行数与 `keys[]` 行数一致（可由审计比对），README 指向的两件事都真实存在 |
| 3 | 回答「CoreHID 能否看见这台设备」，再决定按钮订阅 | 有 `CoreHID mouse active` 或明确的 permission/匹配失败原因；据此实现按钮订阅 + 与 AppKit 的边沿去重，并新增 gate 同时登记进 `.github/workflows/build.yml` 与 `constraints-audit.py` |
| 4 | `LiSendUtf8TextEvent` 兜底未映射字符 | 宿主能力实测（Sunshine 版本行为）、开关与文案落地、丢键回归场景进 harness |
| 5 | 把「忽略的键两端都不发」「修饰键 chord 边界」写成独立审计 | 每条都能红一次 |

## 7. 对标结论的引用方式

对标等级一律以 [`input-mapping-benchmark.md`](input-mapping-benchmark.md) 为准，本页不重新评级。
需要提醒的两点：那份文档已声明 **Parsec 无公开可引用证据（HTTP 403）**，任何「Parsec 怎么做」的
断言都不能进入代码注释或提交说明；§2 的三条协议事实是本轮新增的一手依据，若与那份文档将来冲突，
以 `Limelight.h` 与 `InputStream.c` 的源码为准。
