# 键鼠输入加固记录（2026-09-27）

> 后续全面审查、进一步修复与最新验证见 [macOS 键鼠全链路审查](input-full-review-2026-09-27.md)。本文保留第一次加固的取证与实现背景。

本轮针对左键伴随 `C`、按键或按钮不能正确释放，以及多条输入路径之间的状态冲突，审查并修改了 AppKit、HID、CoreHID、手柄鼠标模拟和底层发送队列。本文记录可由源码、行为测试及构建结果支持的结论。**真实 AJAZZ 接收器在两台远端主机上的修复效果尚未复测，完整项目门禁也不能据此宣称全绿。**

本报告是当前实现说明；[`input-mapping-review.md`](input-mapping-review.md) 的旧通路表和分期计划，以及 [`memory-ownership.md`](memory-ownership.md) 第 32–37 节，保留为历史取证记录。与本文冲突的旧实现描述不作为现行行为。

## 1. 根因与修复证据

| 已确认的问题 | 可重复的触发方式或证据 | 本轮处理 |
|:---|:---|:---|
| 已知鼠标节点额外产生键盘 C | 第 37 节保存的设备层记录：左键 `0x09/0x01` 有完整按下/抬起，同一节点另报 `0x07/0x06` 按下，观察窗口内没有对应抬起 | 新增按设备身份和事件时间戳归属的 C 过滤器；不把 C 转成额外左键 |
| pending 按下遇到快速抬起不能配对 | 从修复前真实方法提取的探针：C 在确认前抬起，只发 `8043U`，pending 仍有一项 | keyUp 消费 pending，在同一个发送任务内补齐 DOWN/UP |
| 解除捕获后仍可补发按下 | pending C → 释放捕获 → 关闭输入 → 状态轮询，修复前仍发 `8043D` | 释放捕获取消 pending；结算入口检查输入门禁 |
| 两个物理键映射为同一 VK 时提前释放 | Return 与 Keypad Enter 同时按住，松开其中一个，修复前已发送 VK_RETURN UP | 每个物理键保存实际发送码；最后一个所有者离开才发远端 UP |
| synthetic 快捷键松开真实按住的主键 | 按住 W，再触发 synthetic W，旧逻辑无条件发送 DOWN/UP | synthetic 主键若已有物理所有者，不再发送会释放它的按键对 |
| 鼠标重复边沿、换键设置和多来源释放相互覆盖 | 同来源重复 DOWN、按住时切换左右键、鼠标与手柄同时持有同一按钮 | 建立按来源与物理按钮索引的统一账本，保存按下时映射，聚合远端所有权 |
| 第一次点击先派发、后捕获 | 输入仍关闭时发送首次 DOWN，随后才启动捕获，UP 却可以到达 | 先建立可用捕获状态再派发首个 DOWN；游戏和远程桌面模式分别覆盖 |
| 停止或重启后的 CoreHID 延迟任务仍触碰当前状态 | 取消的尾帧定时器、被替换的定时器、旧会话异步回调 | 用 generation 与定时器 token 校验任务归属，取消与清空在同一状态锁下处理 |
| 队列中的旧连接指针及地址复用 | producer 取得旧指针后暂停，连接销毁/重建，再提交旧输入 | producer 只取得 pointer + generation 租约；实际解引用、初始化检查和连接 TLS 选择放在串行输入队列 |
| 重连后旧回调重新绑定输入 | 旧连接的启动回调或延迟绑定任务在停止、重连后到达 | 绑定前核对连接身份、会话代次、停止与取消状态；重连先释放持有、关闭输入并排空旧上下文 |
| 底层队列满时直接丢弃键鼠边沿 | `moonlight-common-c` 有界队列拒收键盘或按钮包 | 边沿进入短暂背压重试；超时或分配失败由输入发送线程报告连接错误，避免静默继续使用失同步状态 |

上述设备层记录证明了“真按钮与额外 C 同时存在”，没有证明固件、宏配置或驱动中哪一处制造了 C。不能继续使用“左键唯一来源就是 C”的旧结论。

## 2. C 来源过滤的精确边界

实现位于 [`HIDKeyboardQuirkFilter.m`](../Limelight/Input/HIDKeyboardQuirkFilter.m)，由每个 HIDSupport 会话持有，在主线程运行循环上启动和停止。

只有下列条件同时成立，设备才属于已知异常来源：

- Vendor ID 为 `0x363C`，Product ID 为 `0xED1C`。
- 节点的 primary usage page 为 Generic Desktop `0x01`，primary usage 为 Mouse `0x02` 或 Pointer `0x01`。
- 节点当前仍在已匹配设备集合中；移除设备后的迟到回调不能重新取得归属。
- 事件为 Keyboard/Keypad page `0x07`、Keyboard C usage `0x06` 的非零输入；AppKit 对应物理码为 `kVK_ANSI_C = 8`。

相同 VID/PID 的 Keyboard 节点不属于上述指针来源。其它接收器、其它键码和未识别设备的宏没有被扩大屏蔽。

IOHID 时间戳先从 mach absolute time 转为开机以来的秒数，再与 NSEvent 创建时间比较，匹配容差为 **±20 ms**；不拿两个回调到达主线程的时间作比较。历史最多保留 64 条 C 观察记录。

可能来自已知设备的可疑 C 使用 **60 ms 确认窗口**，给两类回调留出到达顺序差异。已有指针证据的 pending 不会因为全局键态变为按下而提前下发；普通键盘状态明确为按下、且没有匹配的指针证据时，可以直接转发。等待期间出现真实 keyUp，则立即发送完整按键对：历史设备缺陷表现为只有 DOWN，不能把正常快速点按一并丢掉。

窗口结束时，只有匹配到已知指针 C、且同一匹配窗口没有真实键盘、Keypad 或未知设备的 C 证据，才丢弃这次 pending。**同窗键盘输入优先；没有来源证据、来源冲突、设备移除或监听失败时放行。** “机器上插着一只问题鼠标”本身不构成丢键证据。

监听需要 Input Monitoring。代码只查询已有授权，使用非独占 IOHID 监听，不主动请求权限；未授权或打开失败时记录原因，保留正常键盘转发。`input.disablePointerKeyboardQuirkFilter` 可关闭此设备例外。原有 `input.enableKeyStateHold` 仍为另行启用的全局键态启发式，其超时丢弃行为不能与来源过滤的放行策略混淆；`input.disableKeyStateHeal` 仅关闭丢失抬起补偿，不再连带关闭来源确认。

## 3. 状态与所有权

| 状态 | 所有者与更新位置 | 保持的约束 |
|:---|:---|:---|
| 普通键、pending 与本地消费记录 | HIDSupport 键盘入口和主线程结算 | DOWN 时保存 wire code，UP 使用原码；无已发送或 pending 所有权就不发孤立 UP；重复 DOWN 不新增所有者，repeat 不重置确认期限 |
| 远端共用 VK | 物理键 → wire code 表的剩余所有者 | 松开一个别名键不释放另一个；捕获收尾每个远端码只释放一次 |
| 修饰键 | 物理侧掩码、远端侧掩码及 KeyboardMapResolver | 保留左右侧与 Command 偏好；synthetic 只释放自己新增的修饰键；解除捕获交还远端状态，同时保留真实物理持有信息 |
| 鼠标按钮 | `source → physical button → saved host button`，在同一锁内更新与入队 | 按下时固定换键映射；单个来源只释放自己的持有；最后一个来源退出才发远端 RELEASE |
| CoreHID 位移 | 驱动状态锁、generation、flush token | 老任务不能清掉替代任务的新尾帧，也不能向重启后的会话发送位移 |
| 输入连接 | inputContextLock 下取得租约，inputQueue 串行替换及消费 | 连接地址相同仍需 generation 相同；脱离连接前等待已排队发送，之后的旧租约被拒绝 |
| 底层可靠边沿 | common-c 的有界 FIFO 与输入发送线程 | 键鼠边沿重试最多按 100 ms 策略等待，失败以 `ML_ERROR_INPUT_STREAM = -105` 明确结束会话；不承诺网络或宿主最终接收 |

手柄鼠标模拟和 GameController 鼠标按钮统一通过来源账本交接；模式退出、来源断开、解除捕获和会话结束都需要归还持有。滚轮路径在输入关闭时提前返回，避免局部状态先变化、之后才发现不能发送。

键盘字段只允许键盘事件读取。鼠标诊断现在记录合法的 `buttonNumber`、`clickCount`、`type` 和 `timestamp`，也不再读取未定义的 `keyCode`。诊断日志加入 pid，跨实例的计数不再只依赖时间猜测归属。

本轮没有给 CoreHID 新增按钮或滚轮订阅；它仍只处理 X/Y 位移。NSEvent 的一般键盘账本仍以物理键码为身份，并非所有键盘设备都拥有独立原始 HID 输入通路。UTF-8/IME 传输也不属于本轮新增能力。

## 4. 验证矩阵与限制

行为探针提取实际 Objective-C/Swift/C 实现，替换设备、时钟或发送端依赖。它们验证状态与包序列，不能代替实物接收器、远端游戏、权限对话框或网络故障的端到端验证。

| 范围 | 回归入口 | 已有验证证据与边界 |
|:---|:---|:---|
| 普通键与抬起配对 | [`key-state-heal-tests.py`](../scripts/key-state-heal-tests.py)、[`keyboard-concurrency-tests.py`](../scripts/keyboard-concurrency-tests.py)、[`held-key-identity-tests.py`](../scripts/held-key-identity-tests.py) | 生命周期场景、pending 快速点按、别名 VK、取消、repeat、保存码及故障注入通过 |
| 修饰键与快捷键 | [`key-order-exhaustive-tests.py`](../scripts/key-order-exhaustive-tests.py)、[`held-modifier-keyboard-pair-tests.py`](../scripts/held-modifier-keyboard-pair-tests.py)、[`keyboard-shortcut-modifier-tests.py`](../scripts/keyboard-shortcut-modifier-tests.py)、[`command-to-control-tests.py`](../scripts/command-to-control-tests.py) | 本轮 14 个键盘/快捷键脚本通过，包含 2520 种四键顺序及 synthetic 主键碰撞 |
| 规则消费与类型门 | [`translation-rule-consumption-tests.py`](../scripts/translation-rule-consumption-tests.py)、[`key-code-read-site-audit.py`](../scripts/key-code-read-site-audit.py)、[`input-wire-trace-tests.py`](../scripts/input-wire-trace-tests.py) | 1542 个规则消费场景通过；28 处字段读取、15 个函数均有键盘类型门；诊断读取也无特许路径，负向植入能使审计失败 |
| C 设备归属 | [`keyboard-source-quirk-tests.py`](../scripts/keyboard-source-quirk-tests.py) | 32 项检查与 4 种故障注入通过；含权限、设备身份、同窗键盘优先、移除迟到回调及 mach 时间换算 |
| 鼠标所有权 | [`mouse-button-state-tests.py`](../scripts/mouse-button-state-tests.py) | 18 个行为场景通过，覆盖重复边沿、原始映射、多来源、并发和换会话；不是多型号鼠标硬件覆盖率 |
| 首次点击与拖拽 | [`mouse-first-click-tests.py`](../scripts/mouse-first-click-tests.py) | 6 项检查通过，覆盖两种鼠标模式、双击及捕获失败；旧派发顺序能触发失败 |
| 滚轮与位移 | [`scroll-notch-consumption-tests.py`](../scripts/scroll-notch-consumption-tests.py)、[`discrete-scroll-click-tests.py`](../scripts/discrete-scroll-click-tests.py)、[`input-concurrency-tests.py`](../scripts/input-concurrency-tests.py) | 保留滚动量消费、离散滚动及跨线程位移守恒回归入口；整体结果以本轮最终门禁日志为准，未宣称硬件滚轮全覆盖 |
| CoreHID 生命周期 | [`corehid-lifecycle-tests.py`](../scripts/corehid-lifecycle-tests.py) | 5 个取消、重启和尾帧场景通过；没有据此声称该 AJAZZ 在 CoreHID 上已实际投递位移 |
| 手柄鼠标模拟 | [`controller-mouse-ownership-tests.py`](../scripts/controller-mouse-ownership-tests.py)、[`controller-mouse-emulation-tests.py`](../scripts/controller-mouse-emulation-tests.py) | 覆盖 MFi 来源交接与模拟策略；真实手柄热插拔、与鼠标同时按住仍需实测 |
| 连接租约与排队 | [`input-context-lifecycle-tests.py`](../scripts/input-context-lifecycle-tests.py)、[`input-edge-queue-tests.py`](../scripts/input-edge-queue-tests.py) | 换连接、同地址复用、已销毁连接的迟到 producer、有界队列背压、失败回调线程及故障注入通过 |
| 启动回调与重连绑定 | [`input-bind-retry-tests.py`](../scripts/input-bind-retry-tests.py) | 13 项行为检查及 3 种故障注入通过，覆盖旧连接、旧代次、已取消连接、延迟重试及重连期间的新连接 |
| 失焦、切屏与断连 | [`space-transition-held-key-tests.py`](../scripts/space-transition-held-key-tests.py) 及上述键盘、鼠标、队列生命周期探针 | 状态释放与旧任务拒绝已有行为/源码覆盖；不等同于所有 macOS Space、窗口模式和远端程序组合的实测 |

最终键鼠验证共 **41 条命令通过**：专项回归记录 `build-input-review/input-regression.json` 为 40 passed / 0 failed，另有启动绑定测试 `build-input-review/input-bind-retry.log` 通过。计数包括普通回归与自测命令，不等同于 41 个场景；自测中的负向变体应检出植入缺陷。

最终 Release 构建为 `** BUILD SUCCEEDED **`，日志已保存到 `build-input-review/build.log`；完整编译证据在 `build-input-review/complete-build.log`。第一方源码告警审计为 0 失败，131 份实现文件的构建归属审计通过，产物中的 91 个第一方类均存在，`codesign --verify --deep --strict` 通过。产物为 `build-input-review/Build/Products/Release/MoonlightEnhanced.app`。本轮未替换正在使用的应用，也没有据此宣称真实串流已验证。

全项目约束检查仍有遗留失败：已有、未跟踪的 `enhancement-report-tests.py` 未注册到 CI，`build-input-review/constraints.log` 因此报告两项注册检查失败；该脚本独立执行还报告运行详情方法与旧系统解析分支两项失败。该脚本属于视频增强工作，本轮未据此改写视频实现，也未把相关失败隐藏为通过。

## 5. 交付与后续实测边界

本轮修改跨越主仓库和 `moonlight-common/moonlight-common-c` 子模块。子模块内 `src/InputStream.c`、`src/Limelight-internal.h`、`src/Limelight.h` 仍有未提交改动；仅提交主仓库或只记录现有子模块指针，不能复现底层边沿队列修复。保存、审阅或提交时必须同时保留这三份子模块修改。

后续硬件验证至少应区分普通键盘 C、AJAZZ 左键、双击和拖拽，同时包含正常授权与无 Input Monitoring 两种状态，并按 pid 区分客户端实例。还需要确认两台远端主机上的实际按下/抬起效果。当前没有证据证明设备固件或宏配置已经修复，也没有证据支持扩大到其它 VID/PID 或其它键盘 usage。

另外，第 37 节把 Keyboard page usage `0x02` 写成数字 `1` 是错误解释。本机 SDK 的 `IOHIDUsageTables.h` 定义：`0x01 = KeyboardErrorRollOver`、`0x02 = KeyboardPOSTFail`、`0x03 = KeyboardErrorUndefined`，数字 `1` 为 `0x1E`。旧观察可以保留为“报告过 usage 0x02”，不能再据此断言鼠标产生了数字 1 宏。
