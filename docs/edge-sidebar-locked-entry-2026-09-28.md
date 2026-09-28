# 侧边栏为什么在用户主机上不工作：锁定模式入口（2026-09-28）

本文只写本轮用代码与配置证实的事实。历史 docs 的"已修好"不作为依据。

## 一、用户真实配置（读取，未修改）

`defaults export std.skyhua.MoonlightMac2` 的 blob 键：

| 范围 | 键 | 值 | 含义 |
| --- | --- | --- | --- |
| `__global__` | `displayMode` | 0 | Windowed |
| `__global__` | `mouseMode` | 1 | 自由/桌面 |
| `__global__` | `edgeSensorSummon` | True | 感应带启用 |
| HOME-PC `86D1F81F…` | `displayMode` | **1** | **全屏** |
| HOME-PC | `mouseMode` | **0** | **锁定（相对）游戏鼠标** |
| HOME-PC | `edgeSensorSummon` | 缺失 | 回落全局 = 启用 |
| 顶层 | `86D1F81F…-hideFullscreenControlBall` | 不存在 | 控制栏未隐藏 |

结论：用户实际路径是**全屏 + 锁定游戏鼠标**。上一轮怀疑的"窗口化总闸
（`edgeMenuShouldBeVisible` 在非全屏非无边框直接 NO）"不是用户路径；它仍是真实的
设计限制（窗口模式改用标题栏按钮，见 `ensureMenuTitlebarAccessoryInstalledIfNeeded`），
记录为已知限制而非本轮缺陷。

## 二、根因（代码证据）

1. 锁定模式没有可悬停的本地光标。`StreamViewController+MouseCapture.m:2226`
   在游戏模式执行 `CGAssociateMouseAndMouseCursorPosition(NO)`，随后把光标 warp 到
   画面中心并 `CGDisplayHideCursor`。因此 `handleEdgeSensorSummonForEvent:` 里的
   `lockedGameMotion = isMouseCaptured && !isRemoteDesktopMode` 必然为真，
   悬停分支按设计不执行：`没有悬停入口`＝用户看到的"完全不能触发"。
2. 替代入口"三次连拨"在现实中不可完成，也不被任何界面告知。
   旧常量 `MLEdgeSensorPushWindowMs = 1200ms` 同时承担两件事：
   两次采样之间的静默上限，以及整段手势的总预算；`MLEdgeSensorPushStrokeCount = 3`。
   即 3 次外拨且每次都要有回拨，总时长 ≤1.2s，中途不敢停顿。
3. 键盘入口打开的是"控制菜单"，侧边栏只是**碰巧**被带出：
   `preferredControlCenterSourceView` 只有在 `edgeMenuPanel.isVisible` 已为真时才
   选择把手作为菜单宿主，否则宿主退化为整个 view，侧边栏不展开。
4. 设置文案与代码不一致，且两个语言都没写锁定模式怎么打开：
   文案称 `4pt`，代码是 `MLEdgeSensorBandWidth = 12.0`；旧测试全部读代码，
   没有任何断言读文案，所以漂移无人发现。

## 三、本轮改动

1. `openEdgeMenuDockForControlCenterShortcut`（MenuUI.m）+ 两处快捷键调用点。
   快捷键经 `summonEdgeMenuDockForEdge:` 展开侧边栏；所有拒绝判断仍只在该方法内部，
   新入口不复制守卫，也不新增所有权标志。返回"是否已展开"。
2. `MLEdgeSensorPushIdleMs = 500ms`（静默即遗忘）与 `MLEdgeSensorPushWindowMs = 1500ms`
   （整段预算）分离；`MLEdgeSensorPushStrokeCount` 3 → 2。防误触条件保持不变：
   外拨必须伴随回拨、按住鼠标键立即作废、方向必须与停靠边一致。
3. 中英文 `Edge Sensor Summon detail` 改为 12pt/250ms/450ms/56pt 并写明锁定模式入口。
4. 测试层：
   - `edge_sensor_runtime_probe.py` 增加可控时钟（`fakeNowMs`/`moveAt`），使双时钟契约可确定复现，
     删除原先 1.35s 真实睡眠用例；新增键盘入口 4 条用例（面板未可见仍展开、窗口拒绝显示时
     不得打开、按住鼠标键不得打断、不得向远端发送按钮事件）。
   - 新增 6 个负向对照：快捷键不带出把手、快捷键谎报已打开、双时钟合并、沿用 1200ms 预算、
     一次外拨即召唤、（沿用）按钮作废等。全部被捕获。
   - `edge-sensor-summon-tests.py` 新增"文案数字必须由代码常量推导"的守卫（en/zh-Hans 双验证），
     并把文案改回 4pt 时确认该守卫确实失败。

## 四、输入所有权与状态转换（本轮验证口径）

| 状态 | 指针归属 | 可发生转换 | 清理者 |
| --- | --- | --- | --- |
| 锁定游戏中 | 远端（本地光标 detach/隐藏） | 悬停不可能；⌃⌥C 或两次外拨 → 召唤 | `summonEdgeMenuDockForEdge:` |
| 自由/桌面 | 本地 | 12pt×把手带停留 250ms → 召唤 | 同上 |
| 主动释放（⇧⌥） | 本地，意图持久 | 点击串流恢复 | `resumeInputForExplicitStreamClick:` |
| 控制栏临时持有 | 本地（`edgeMenuTemporaryReleaseActive`） | 回到画面内或点击串流 | `deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:` |
| 菜单/拖动 | 本地 | 取消/关闭后按上表返回 | `edgeMenuPhase` 单一阶段 + `edgeMenuLifecycleToken` |

本轮未新增布尔量与定时器；未引入第二套坐标转换。

## 五、验收矩阵

图例：自动=本轮自动测试通过；实机=尚未验收（本机屏幕锁定，第 7 次确认，无法注入真实输入）。

| 项 | 状态 |
| --- | --- |
| 锁定模式下 ⌃⌥C 打开侧边栏（面板此前不可见） | 自动（probe，含 2 个负向对照） |
| 锁定模式两次外拨打开；一次外拨不打开 | 自动 |
| 停顿 300ms 仍计；静默 700ms 作废；总时长 1400ms 可成、1900ms 作废 | 自动（确定性时钟） |
| 四边停靠 × 两拨；连续 30 次不失效 | 自动 |
| 按住鼠标键期间手势作废、恢复后需完整重来 | 自动 |
| 慢速漂移/抖动不得刷出笔画 | 自动 |
| 键盘入口不向远端发送按钮事件 | 自动 |
| 文案与常量一致（en/zh-Hans） | 自动（守卫，负向已验证） |
| 键鼠 45 项回归、约束审计、workflow/liquid-glass/enhancement 审计 | 自动（全 rc=0） |
| 全套断言电池 144 项 | 见文末回填 |
| 真实 ⌃⌥C 按键（真键盘按下） | 实机（尚未验收） |
| 真实 ⇧⌥ 修饰键释放 | 实机（尚未验收；纯修饰键无法由工具注入） |
| 真实两次外拨手感、误触率 | 实机（尚未验收） |
| 全屏/窗口切换、Space 切换、失焦恢复、断线重连 | 实机（尚未验收） |
| 多显示器、外置鼠标 vs 触摸板 | 实机（尚未验收） |
| 120/180 FPS 类性能结论 | 未测量，不作声明 |

## 六、构建与部署（本轮实测）

- Release 构建（与 CI 同参数：`-configuration Release -derivedDataPath build -destination
  platform=macOS,arch=arm64 ARCHS=arm64 ONLY_ACTIVE_ARCH=YES BUILD_NUMBER=1689`）：`** BUILD SUCCEEDED **`。
- `build-warning-audit.py --self-test` 与 `--log`：first-party 源码 0 warning（3 条 vendored 忽略）。
- 暂存副本 ad-hoc 签名 `codesign-bundle.sh` → `codesign --verify --deep --strict` 通过。
- 部署前只读确认：运行中的旧实例 `pid 32424` 不持有任何 socket（未在串流），且屏幕锁定、用户未操作；
  `kill -TERM` 后进程正常退出（未强制 kill -9）。
- `scripts/deploy-local-app.sh` 结果（`build-input-review/edge-locked-entry-install-result.json`）：
  安装 `de8db8b5c512539146c0613cdd6cd20efd5e14fb7847f4b5eb206c8771831432`，
  替换前 `0dda4918d98e0a1e5a5dc2d3b40d28cc06c082bec213c3788b0f1dc211c2e0ea`，回滚副本在回收站。
- 启动后核对：实例数 = 1，运行二进制哈希 = 安装哈希。
- 全套断言电池（含本轮改动的副本）：`144/144 mutations caught`。

## 七、CI 仍不能变绿的两个原因（本轮定位，非猜测）

CI run 36363126921（commit 931cf7e）：`Repository audits` 已 success（上一轮的超时与
不可判定门禁修复成立）；随后 4 个 job 失败，原因是两个独立缺陷：

1. `Build arm64` 第 13 步 `input-edge-queue-tests.py` 以
   `SystemExit("input consumer no longer reports edge failures")` 失败。
   该脚本从 `moonlight-common/moonlight-common-c/src/InputStream.c` 抽取
   `inputSendThreadProc` 并要求其中存在 `reportInputEdgeFailureIfPending(ctx)`。
   本机工作树有 2 处、子模块已提交版本（`f262d59`，与父仓 gitlink 一致）有 0 处：
   **C 层的输入边缘队列改动（`src/InputStream.c`、`src/Limelight-internal.h`、`src/Limelight.h`，
   共 +66/−20）至今只存在于本机工作树**，子模块 origin 是 `skyhua0224/moonlight-common-c`，无推送权限。
   推论（同样重要的诚实结论）：CI 产出的 .app 与本机部署的 .app 在 C 层不同，
   在发布前必须承认这一点。
   决策点（需用户批准，本轮未擅自执行）：在自有账号 fork `moonlight-common-c`、提交这 3 个文件、
   把 `.gitmodules` 与父仓 gitlink 指向该 fork，CI 才可能绿；或明确接受"C 层未发布 ⇒ CI 红"。
2. `Static analyzer`：`LiquidGlassTabBar.swift:57: value of type 'NSSegmentedControl' has no member 'role'`。
   本机 Xcode 27.0（SDK macOS 27）有该符号，CI runner 是 `macos-26`（Xcode 26.6，SDK macOS 26），
   符号根本不存在；`if #available(macOS 27.0, *)` 只保证运行期，救不了编译期。
   本轮修法：新增 SDK 条件编译 `ML_APPKIT_TABS_ROLE`（pbxproj 只在 `sdk=macosx27.*` 声明），
   源码内 `#if ML_APPKIT_TABS_ROLE` 包裹赋值，`#available` 继续保护老系统运行。
   本机 `Debug -> DEBUG ML_APPKIT_TABS_ROLE`、`Release -> ML_APPKIT_TABS_ROLE` 实测生效，
   已认可外观不丢；CI 的 SDK 26 走不到该条件，可编译。
   回归防线：`liquid-glass-audit.py` 新增两条规则（无守卫的 `.role =` 判违规；
   源码有守卫但工程未声明条件也判违规），并各带一个自测用例（一拒一收）。

注意：`Build arm64` 是在第 13 步失败后跳过后续步骤，所以这条 Swift 编译错误此前从未在 CI 暴露过。

## 八、本轮实机验收（13:57–14:36，第一次拿到真机证据）

环境（本机单显示器 1920x1080@180，无第二块屏；配置从
`~/Library/Preferences/std.skyhua.MoonlightMac2.plist` 只读取得，未修改）：
HOME-PC 192.168.3.110，`displayMode=1`（全屏）、`mouseMode=0`（锁定）、
`openControlCenter=⌃⌥C`、`releaseMouseCapture=⇧⌥`（modifierOnly，主机级覆盖全局 ⌃⌥）、
`disconnectStream=⌃⌥W`。UI 操作全部经Computer Use，未使用 CGEvent/osascript 合成。

修复前同一台机器的基线（旧构建 a6a4aa5，11:57）：8 次 ⌃⌥C 只有 4 次 `Edge controls opened`，
其余按键完全无日志；且 ⌃⌥C 同时弹模态菜单，一次杂散点击真的选中了"断开连接"。

修复后（安装版 67fd39fb，全部以 `moonlight-debug.log` 为准）：

| 路径 | 结果 |
| --- | --- |
| ⌃⌥C × 10（间隔 3.2s，锁定态） | 10 次 `opened`（capturedBefore=1）+ 10 次 `returned`（grace=2500ms，均 +2.50s）**10/10 实机通过** |
| ⌃⌥C × 10（间隔 900ms，控制栏仍在屏上） | 7 次 `opened`；差额是"栏已可见时再按"按设计不动作；1 次由用户画面内真实单击收回（显式单击路径不打 returned 日志）；0 拒绝、0 模态菜单、0 误断连 **实机通过（含"重复按"设计行为）** |
| 真实外拨手势 `edge-sensor-push` | 会话内 3 次成功打开，其中 1 次指针确实停在栏上 → `visited=1 grace=450ms` **实机通过** |
| 失焦→恢复→再按 | 切到活动监视器再切回，`opened`+`returned` 各 1 次，无卡死 **实机通过** |
| 断开后新建会话 | 同进程第二次会话仍然 `opened`+`returned`；把手复位到右边缘 **实机通过** |
| **⌃⌥C × 30 连测（分 4 批，间隔 3.2s，锁定态，会话 3）** | **30 次 `opened` + 30 次 `returned`（全部 capturedBefore=1、grace=2500ms、0 refused），不存在第一次有效后续失效 15:04:15→15:07:10 实机通过 30/30** |
| 会话 1 总量 | 18 `opened` / 17 `returned`（差额由真实单击收回解释）、0 `refused` **实机通过** |
| 普通 C 键 × 12 | 12 `view-down` / 12 `sent-down` / 12 `sent-up`，0 `dropped-unconfirmed`、0 swallowed **自动+注入实机（真实键盘未验收：注入事件 sourcePid 非本进程）** |
| 相对位移完整性 | 会话 1：moves=184=rel=184，rawΔ=sentΔ，suppressed=0，capture=19/uncapture=18 **实机通过** |
| ⌃⌥D（未绑定组合） | 无任何断连/吞键日志，未被误当作 ⌃⌥W **实机通过** |

原始证据片段：`build-input-review/edge-return-live-check.log`。

## 九、根因与所有权（本轮定案）

1. **收起计时器只由悬停/菜单路径 arm**。锁定模式把本地光标停在画面中心且不动，
   控制栏永远 expanded，下一次召唤被 `already-open` 静默拒绝——这就是"第一次有效、后续失效"。
   修法：显示把手与安排回程是同一次决策（`setEdgeMenuButtonExpanded:` 展开后立刻走
   `handleEdgeMenuHover`），仍然只有一个计时器；`edgeMenuPointerHasVisited` 只决定
   这一个计时器用 2500ms（指针从未上过栏）还是 450ms（上过栏又离开）。
2. **⌃⌥C 在刚召唤出的侧边栏上又叠了一个模态菜单**，指针没有可瞄准的位置，玩家下一次
   键/点击落进菜单（真机日志里真的落到"断开连接"）。两个调用点改为 dock 与菜单二选一，
   窗口模式没有 dock 才回退到菜单。
3. **诊断盲点**：`updateEdgeMenuPointerInsideForPoint:` 在探针里被替身重复实现，生产漏斗
   没被测试覆盖；现在改抽取生产方法本体，并新增 5 个变异体（把栏永久留在屏上、grace 塌回
   450ms、忘记 visit、回程不留日志、两个等待打同一个数字）全部被抓到。

| 状态 | 指针归属 | 进入条件 | 回程/清理者 |
| --- | --- | --- | --- |
| 锁定游戏中 | 远端 | ⌃⌥C 或两次外拨 | `summonEdgeMenuDockForEdge:` |
| 栏可见（指针未上过栏） | 本地（临时释放） | 召唤成功 | 2500ms 计时器 → `deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:` |
| 栏可见（指针在栏上） | 本地 | 指针进入交互区 | 离开后 450ms 同一计时器 |
| 栏可见 + 玩家点击画面 | 交还远端 | 显式单击串流 | `resumeInputForExplicitStreamClick:`（不打 returned 日志） |
| 菜单/拖动 | 本地 | 菜单打开或按住把手 | `edgeMenuPhase` 单阶段 + lifecycle token |

本轮没有新增布尔量拥有生命周期，也没有新增计时器；visit 只是"这一次在屏上停留期间指针是否上过栏"的记录。

## 十、仍未解决 / 未验收（不得当作已通过）

- **真实硬件项**：⇧⌥ 纯修饰键释放（工具无法注入）、真实键盘 C 的 source-check 分支、
  真实触摸板/外置鼠标切换、多显示器与跨屏（本机只有一块屏）——**尚未验收**。
- **拖动把手重新停靠**：Computer Use 在屏幕边界的坐标命中不可靠（`windowNotFoundAtPosition`），
  本轮未能实机拖动；仅有自动测试覆盖（含 `collapsed dock drag`、`stale drag callbacks` 变异体）。
- **"栏已可见时再按 ⌃⌥C"是设计上的空操作**：屏幕上有栏可点，但玩家若期望它是开关，
  需要产品决策（改成 toggle 会连带改文案）；本轮未改语义。
- **显式单击收起不打 `returned` 日志**：日志读起来像"少了一次回程"。可加一条不同措辞的日志，
  本轮未做（避免与 346af90 的"开栏不是拒绝"口径混淆）。
- **会话结束后仍收到指针事件**（旧构建 12:02:55 有 4 条 `cannot-interact` 日志，防护有效、
  功能未受影响）：新构建本轮未复现，但成因（teardown 不移除 tracking area / 面板生命周期）未修。
- **退出串流后遗留 "Desktop" 窗口**（`performCloseStreamWindow: safe close` 之后窗口仍在，
  性能浮层文本停在最后一帧；`窗口 ▸ Close Stream Window` 可关）：本轮新观察到的既存缺陷，未修。
- **普通 C 键 `dropped-unconfirmed`（旧日志 6 次）**：本轮 12 次注入 0 复现，但样本小且依赖
  宿主确认；C 层输入边缘队列改动仍未发布（见第七节），不能宣告关闭。
- **CI**：`Build arm64` 仍会在第 13 步红（C 层三个文件只在本机工作树，子模块无推送权限）——需用户决策。
- **性能**：本轮未做刷新率测量，不作任何 120/180 FPS 声明。

## 十一、本轮构建与部署（实测）

- Release 构建（同 CI 参数，BUILD_NUMBER=1692）：`** BUILD SUCCEEDED **`；
  `build-warning-audit.py --log` first-party 0 warning。
- 门禁：`edge-sensor-summon-tests.py --self-test` rc=0（27 个负向对照，其中 5 个本轮新增 +
  1 个守卫自测）；`local-gates.sh` 73 passed / 0 failed / 14 需 CI 产物；断言电池
  `144/144`（副本 `--allow-dirty`，0 not-caught）；l10n 0、liquid-glass 0、workflow 25 规则通过、
  `constraints-audit --no-battery` 0、键鼠回归 45/45、`git diff --check` 干净。
- 暂存 → `codesign-bundle.sh` → `codesign --verify --deep --strict` 通过 → 确认旧实例 0 socket
  （未在串流）且 HID 空闲 43s → `kill -TERM` → `deploy-local-app.sh`。
- 安装 `67fd39fb0fd339950e5edb295596add5cb3805accb09e5f0fa9fe75734dbcb55`
  （替换前 `a6a4aa5af30c11ea31cea1fe8eff76d47abaf1297d883fc00d2cfd2f0bdca3e4`），
  回滚副本 `~/.Trash/.MoonlightEnhanced-before-edge-return-bar-47B85B5AAE9D4CEF86DD24274E048FF0.app`，
  记录 `build-input-review/edge-return-bar-install-result.json`；安装后实例数 = 1。
- 注意：`build-number.sh` 由提交历史推导，本轮改动未提交时仍是 1692，故区分构建只能靠二进制哈希。

## 十二、CI 复跑结果（run 36387608025，commit 725e180）

- `Repository audits` ✅ 11m58s 通过（上一轮修的超时与不可判定门禁成立）。
- `Build x86_64` / `Build arm64` ❌ 均在"Verify keyboard and mouse edges survive input queue
  congestion"（`input-edge-queue-tests.py`）失败，日志原文
  `input consumer no longer reports edge failures` —— 与第七节结论一致：C 层三个文件只在本机
  工作树，子模块未发布。后续步骤被跳过，故其后的设备级 C 过滤等门禁从未在 CI 跑到过。
- `Static analyzer` ❌ 变成新的失败原因（原来的 `.role` 编译错误已随 75bc354 消失）：
  `accepted finding no longer reported (1): StreamViewController.m [deadcode.DeadStores]
  Value stored to X is never read`，即基线里接受的一条死存储已被本轮前后的改动真的修掉了，
  基线需要删掉这一条。**本机无法安全再生成**：本机只有 Xcode 27.0，CI 是 Xcode 26.6，
  用 27 的转录再生成会把"CI 的分析器并不会报"的条目写进基线。需要一台 26.6 转录，
  或人工删掉这一条后由 CI 自证（若仍存在会改报"unaccepted finding"，同样可见）。
- 结论：本轮不擅自改 analyzer 基线；CI 变绿的前置条件是用户对"C 层是否发布"的决策。

## 十三、第二次续跑：先把上一轮自己欠的四项收掉（代码层已闭合）

### 1. ⌃⌥C 从"只能开"改成开关

- 触发步骤：锁定模式下按 ⌃⌥C 唤起侧边栏，随后再按一次。
- 预期：收起并把指针交还游戏。实际（修复前）：空操作，栏继续持有指针直到自己的定时器到期。
  玩家看到的仍然是"按了没反应"，与最初的故障同一观感。
- 根因：`openEdgeMenuDockForControlCenterShortcut` 只有 summon 一个方向，而
  `summonEdgeMenuDockForEdge:` 的第一组 guard 就把 `edgeMenuButtonExpanded` 挡掉——那个入口是
  dwell/push 共用的，悬停时栏已开绝不能收起，所以"关"的方向只能加在键盘入口自己身上。
- 修法：键盘入口在"已展开且不在拖动"时改走 `deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:`
  （收起唯一出口，含取消菜单跟踪、临时释放意图与归还判定），并返回 YES，`if (![self …])` 的
  模态菜单回退因此不会触发。拖动中不拦截：落到 summon 的拒绝上，既不会把栏从指针手里抢走，
  也不会弹出模态菜单。未新增布尔量，未新增定时器。
- 证据：运行时探针新增 4 条断言（按下开→再按关→再按又开；收起仍归还指针且不外发按键；
  拖动期间既不丢栏也不交出所有权），新增变异体 `the keyboard entry is a one-way switch`、
  `a press during a drag drops the bar out of the pointer`。中英设置文案同步"再按一次收起"。

### 2. 退出全屏串流遗留的 "Desktop" 幽灵窗口

- 触发步骤：全屏会话中断开串流，走 `performCloseStreamWindow:` 的非立即分支。
- 预期：窗口关闭。实际：窗口以 alpha=0 留在 Window 菜单里，性能浮层停在最后一帧，
  `窗口 ▸ Close Stream Window` 才关得掉。
- 日志证据：`performCloseStreamWindow: safe close (style=16399 …)`（16399 含 16384 全屏位）
  之后没有任何 `window-did-exit-fullscreen` 上下文；整份 35184 行日志里该上下文出现 **0 次**。
- 根因：`beginStopStreamIfNeededWithReason:completion:` 先调用
  `tearDownStreamLifecycleObserversAndTimers`（移除 `NSWindowDidExitFullScreenNotification` 观察者），
  之后才执行 completion 里的 `requestSafeCloseOfStreamWindow`。全屏分支置
  `pendingCloseWindowAfterFullscreenExit = YES` 并 `toggleFullScreen:`，然后等待一个已经被移除的
  观察者来消费这个标志——永远等不到，于是 `close` 从未发生。
- 修法：关闭意图自带一次性观察者 `watchFullscreenExitOnceToCloseStreamWindow:`；若其他路径已经
  关过（标志被清）则自行退出；只有 dealloc 才回收它。未新增定时器、未改动重连路径。
- 状态：代码与构建/签名已验证；**实机尚未验收**（见第十五节）。

### 3. "回程"日志收到唯一出口

- 触发步骤：栏可见时玩家在画面里真实单击取回指针。
- 实际（修复前）：会话日志出现 18 条 `Edge controls opened`、只有 17 条
  `Edge controls returned to stream`——栏确实收回去了，但没有任何一行说明它回去了。
- 根因：`returned` 只写在 auto-collapse 定时器块里，而收回指针还有别的路（
  `captureFreeMouseIfNeededForEvent:` → `deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:`），
  那些路是静默的。一条写在某个调用者层面的日志，只能证明它自己那一条路。
- 修法：日志下沉到 `transitionEdgeMenuToPhase:` 的"可见→不可见"唯一转换点，带 `from=`/`to=`
  区分真正归还与隐藏；`grace` 改读 `edgeMenuReturnDelay`，与计时器共用同一条规则，日志不可能再
  和计时器各说一套。定时器块里那条私有日志删除，避免一次收起打两行。
- 证据：新增断言"the click that takes the pointer back also says that the bar went back"，
  变异体 `a bar that vanished on its own is not a return`（只承认计时器路径的日志会立刻失败）。

### 4. 第 4 项（teardown 不摘 tracking area）：评估后不改

`installMouseTrackingArea` 只由 `viewDidAppear` 调用，断线重连复用同一控制器时不会再来第二次，
摘掉它会让第二次会话失去 enter/exit——这是拿真实功能换一个不可见的整洁度。面板本身在
`transitionEdgeMenuToPhase:MLEdgeMenuPhaseHidden` 里已经 `orderOut`，会话结束后的指针事件也已被
`edgeMenuCanInteract` 拦下并有命名日志。本项按"不修"结案，不再重复提出。

## 十四、本轮门禁与构建（实测）

- `local-gates.sh` 73 passed / 0 failed / 14 需 CI 产物；键鼠回归 45/45；
  `edge-sensor-summon-tests.py --self-test` rc=0，运行时断言 **2686** 项、负向对照 **30** 个
  （本轮新增 3 个 + 2 个改写到新实现上）；`git diff --check` 干净。
- 第一次 Release 构建被 `build-warning-audit.py` 拦下：新属性写成
  `@property (nullable, nonatomic, strong)` 让本未做空性标注的
  `StreamViewController_Internal.h` 变成"部分标注"头文件，一次刷出 1308 条
  `-Wnullability-completeness`，first-party 报 1 类失败。已改回该文件既有风格（不带空性标注），
  重建后 first-party 0 warning。**是门禁起了作用，不是把门禁放宽。**
- BUILD_NUMBER=1698（由提交历史推导，本轮两次提交后自然递增）。
- 暂存 `/tmp/ml-stage-edge-5259` → `codesign-bundle.sh` → `codesign --verify --deep --strict`
  通过 → 确认旧实例 0 socket（未在串流）→ `kill -TERM` → `deploy-local-app.sh`。
- 安装 `c11f5cef4ddd4f520321a3592bf8616aa96dc6c5f491fe0c2b8acd435d093733`
  （替换前 `67fd39fb0fd339950e5edb295596add5cb3805accb09e5f0fa9fe75734dbcb55`），
  回滚副本 `~/.Trash/.MoonlightEnhanced-before-edge-switch-3C0A2B372E9540E1A56C5E89CA64657E.app`，
  记录 `build-input-review/edge-switch-install-result.json`；安装后实例数 = 1、版本 1698，
  二进制里能读到新的回程日志格式串（`… captured=%d from=%ld to=%ld`）。

## 十五、本轮实机验收：被 Computer Use 工具阻塞（不得当作已通过）

- 部署后第一次 `cua.getApp("/Applications/MoonlightEnhanced.app")` 成功读到主机列表 AX 树，
  标题栏显示 `Moonlight – Version 1.6.0 (1698)`，说明安装的就是本轮构建。
- 之后按元素索引双击主机行、双击其容器、先 Raise 再双击，AX 树都返回
  "There has been no change in the accessibility tree"；同时 `moonlight-debug.log` 里只有
  `Discovery summary for HOME-PC` 心跳，**没有任何点击或连接日志**——事件根本没到达应用。
- 随后 Computer Use 后端持续返回 `Sky Computer Use native pipe closed before response`；
  `js_reset`、改用完整路径重试均失败，而 `cua.getState()` 仍能列出应用清单，
  判定为 Sky 的 AX 桥接故障，不是本应用故障。
- 因此本轮 **未拿到**：⌃⌥C 开关的实机开→关→开、连续 30 次不衰减、四边停靠与拖动后重触发、
  幽灵窗口在真实全屏断开后确实消失。以上连同第十节的硬件项，一律 **尚未验收**。
- 下一轮第一件事：等 Computer Use 恢复后，从"双击主机行进入 Desktop"重跑第八节的实机矩阵，
  并补测断开后 Window 菜单里是否还有残留窗口。

## 十六、CI 红在 render-probe：先取证，再改判据

`Build arm64/x86_64` 在 run 36429561479 里越过 input-edge 与 nullability 两道门禁后，
红在 `Verify the settings page renders embedded`：
`FAIL the page drew no variation at all (stddev 0.07016)`，而 `note the probe itself also refused:
stddev 0.070, 53 distinct colours`。

- 本机用同一个 Debug 探针跑真实显示器，**同样 FAIL**（`render-probe-local-1698.log`，RC=1）。
- 探针自己导出的截图 `02-settings-page.png` 肉眼完整：分段控件、开关、下拉、中文文案都在。
- 用与生产 `MLProbePixels` 完全相同的算法（3px 采样、5bit 量化、sRGB 亮度）复算该截图：
  `mean 0.9765 / stddev 0.0702 / distinct 53`。**设置页是浅色主题，亮度几乎全压在白附近**，
  所以"渲染正常"的页面本来就只贡献 0.07 的亮度散布；`distinctColours>=40` 才是判别力所在
  （真空白页实测 2 色）。
- 结论：这不是渲染故障，是门禁**词不达意**——`stddev>=0.08` 这个绝对阈值高于真实页面能产出的
  数值，而这一步在 CI 历史上从未真正执行过（前面一直被更早的失败挡住）。
- 处理：**不是随手放宽**。把下限改到 0.02（真实页面 0.0702 仍有 3.5 倍余量，纯色夹具 0.001
  低 20 倍），并补上把两端钉住的夹具：
  - 正向：`a light-theme page measured on a real display`（0.0702/53）必须通过，防止有人再把
    阈值抬回 0.08；
  - 负向：`a flat colour lifted only by antialiasing noise`（0.012/44）必须被拒，防止"只要有色
    就放行"；
  - 生产侧 `AppDelegateForAppKit.m` 的同一条判定同步为 0.02，并注明取证依据。
- 顺手修掉自测夹具的既存缺陷：夹具的 pane 报告从不带 `hostReadsDuringPresent`，于是
  `--self-test` 在 HEAD 上就有 1 个失败（`verify_host_reads` 拒绝夹具自己），把后面所有 refusal
  都变成噪音。夹具补齐读计数（stream 3 / video 1 / app 3），并新增两条负向对照
  （某页读取次数翻倍、关闭期间读库）。`render-probe.py --self-test`：32 ok / **0 失败**。

## 十七、把手按 UU 的设计改：抵达点亮，点击展开

用户反馈原文是"鼠标抵达边缘激活，可以点击，而不是你这种暴力的乱触发"。三条截图显示 UU 远程的
形态是：**把手常驻可见 → 光标到边缘时把手高亮 → 点击才展开控制中心**。

代码层的两个根因（不是"感应太灵敏"，而是"看到的东西和点的东西不是一回事"）：

1. **可见≠命中**。把手在收起态只画 `peek-4 = 4pt` 的细缝并隐藏图标
   （`MLEdgeMenuUI.m` 的 compact 分支），而 `expandEdgeMenuForLocalClickAtCurrentPointer`
   的命中判定用 `edgeMenuInteractionRectInBounds:` —— 那是由 **展开态 56×56 再外扩 padding**
   推出来的矩形。玩家看不见 52pt，却能在 56pt 区域内点开启，且面板透明区也吃点击。
2. **抵达即夺权**。`finishEdgeSensorSummonIfStillAtEdge:` 在 250ms 停留到点时直接
   `summonEdgeMenuDockForEdge:` → uncapture（MUC109）+ 展开面板 + 记一条 `Edge controls opened`。
   光标只是路过边缘，指针就从游戏手里被拿走。

改后的三段状态，只有一个所有者：

| 状态 | 谁拥有指针 | 进入条件 | 退出条件 | 谁清理 |
| --- | --- | --- | --- | --- |
| idle（把手常驻） | 游戏 / 本地自由指针 | 控制栏可见且收起 | 指针进入感应带 250ms | 感应计时器 |
| armed（把手高亮） | **仍然是游戏/本地指针，一个字节都不外发** | 停留到点且仍在带内、无按下键、未被 warp 冷却 | 离开感应带 / 按住键 / 失能 / 阶段变化 | `resetEdgeSensorSummonState` 唯一出口 |
| expanded（控制中心） | 控制栏 | **点击可见把手**（自由/释放态）、⌃⌥C、锁定态连拨两下 | 450ms/2500ms 收起、再按 ⌃⌥C、点击串流 | `deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:` |

- 常量：`VisiblePeek 8→34`（面板在收起态真正露出的厚度）、`HandleIdleThickness 14`、
  `HandleArmedThickness 30`、`HandleLength 48`、`HandleHitSlop 6`。
  idle 时屏幕上是一条距边 2pt、厚 14pt、长 48pt 的圆角条；armed 时加粗到 30pt、露出图标、
  描 accent 边。**绘制厚度与命中矩形都由同一个 `edgeMenuVisibleHandleRectInBounds:` 推导**，
  所以"看见的"和"点得动的"必然一致。
- `finishEdgeSensorSummonIfStillAtEdge:` 改名 `armEdgeMenuHandleIfStillAtEdge:`，方法体内
  **禁止**出现 `summonEdgeMenuDock` / `uncaptureMouse` / `activateEdgeMenuDock`（源码级守卫）。
- 轴向修正：Left/Right 的沿边方向是 y，Top/Bottom 是 x。面板是正方形，读错轴也照样居中，
  所以这类 bug 只在别的停靠边上露头；两处几何都改成按停靠边显式判轴。
- 锁定模式不变：本地没有可信光标位置，绝不猜远端光标；入口仍是 ⌃⌥C（开关语义）与向把手边
  连拨两下。armed 不适用于锁定态（`armEdgeMenuHandleIfStillAtEdge:` 的守卫直接挡住）。
- 文案：设置页中英双语都改成"常驻可见 → 停留 250ms 把手亮起（不展开、指针仍在游戏里）→
  点击亮起的把手才展开"，并保留 12pt/56pt/250ms/450ms/2500ms 全部既有数字契约。

## 十八、本轮门禁、构建、部署与验收状态

### 自动门禁（实测，全部本机执行）

| 门禁 | 结果 |
| --- | --- |
| `edge-sensor-summon-tests.py --self-test` | 通过；新增 4 条负向对照（抵达仍夺指针 / 命中区无视可见把手 / 点亮不可见 / 灯不熄灭）全部如期变红 |
| `input-regression-suite.py` | **45 passed / 0 failed** |
| `l10n-audit.py` | 0 localization failures |
| `liquid-glass-audit.py` | 0 violations（5 文件 / 8 面板） |
| `render-probe.py --self-test` | 32 ok / **0 失败**（修掉夹具既存缺陷 + 新增 3 条对照） |
| `build-warning-audit.py` | first-party 0 警告（3 条 vendored 忽略） |
| `git diff --check` | 干净 |
| `local-gates.sh` | 71 passed / 1 "failed" / 15 需要 CI 产物 |

`local-gates` 唯一红项是 `compile-audit.py --self-test`：它需要 xcodebuild 生成的
`DerivedSources`（CI analyze job 的 `Debug/Audit.build` 产物），本机没有该产物时按设计跳过并以
非零码报告——属既存环境性缺口，CI 的 Static analyzer 覆盖它，与本轮改动无关。

### 构建与部署（实测）

- Release 构建 `build-input-review/uu-handle-build.log`：`RC=0`，产物 **1.6.0 (1702)**，
  二进制 `836076abb38b902f10dce60d254670353697ab50ccd81ac84e0d3bba2f038ae4`。
- 暂存签名 → `codesign --verify --deep --strict` 通过（valid on disk / satisfies DR）→
  部署 `/Applications/MoonlightEnhanced.app`：bundle 哈希
  `17205fd4a3a165bccf4b76c94559de7abf28b70ace637fd9248699a34a138023`（替换前
  `c11f5cef…`，回滚记录 `build-input-review/uu-handle-install-result.json`）；实例数 1。
- 已安装的版本被 Computer Use 的 AX 树直接确认：标题栏 `Moonlight – Version 1.6.0 (1702)`。

### 实机验收：本轮仍被阻塞（不得当作已通过）

- 上一轮的 Sky AX 桥接故障本轮**已恢复**：`cua.getApp(完整路径)` 重新读到主机列表 AX 树
  （`HOME-PC 在线，未配对`、工具栏、版本号）。
- 但双击主机行的动作被系统拒绝：**`The Mac is locked and automatic unlock could not unlock
  it.`** —— Mac 处于锁屏，Codex 无法也不应解锁，因此串流未能进入。
- 于是本轮**仍未拿到**实机证据的项：把手常驻可见的实际观感、抵达点亮→点击展开的真实手感、
  四边停靠与拖动后重新触发、连续 30 次不衰减、⌃⌥C 开关、锁定模式入口、幽灵窗口是否消失。
  以上一律标记 **尚未验收**；自动门禁只证明"实现不再违背契约"，不证明"玩家的问题已消失"。
- 下一轮第一件事：屏幕解锁后立刻重跑第八节的实机矩阵（含本节新增的 armed 观感核对）。

## 十九、CI 变绿（run 36467884750，commit 35e79d9）

`Repository audits / Build arm64 / Build x86_64 / Static analyzer / Build universal / build /
Verify the published images` **全部 success**，`release = skipped`（本轮不打 tag、不发 Release，
跳过符合预期）。

`Build *` 这道门此前红过三次，原因各不相同，全部单独取证后修掉：
1. `input-edge-queue-tests.py` 读子模块里的 C 源文件，而那份 C 改动只存在于本机工作树 →
   子模块 fork 已发布并把 gitlink 指过去（commit 32920c5）。
2. 内部头文件被写成部分可空标注，触发 1308 条 `-Wnullability-completeness`；analyzer 基线里
   留了一条源码已不再报告的 finding（commit 7391af0 / 792b604）。
3. `Verify the settings page renders embedded` 用 `stddev>=0.08` 判"空白页"，而真实浅色页面只
   有 0.0702 → 见第十六节，重锚阈值并把两端用夹具钉住（commit 43fb9eb）。

本轮没有为变绿删除任何断言：新增的是 1 条正向夹具、3 条负向夹具、6 条探针负向对照与 2 条轴向对照。

## 二十、删除"连拨两下"：把开栏留给一次明确的点击（2026-09-29 第五轮）

### 用户反馈与参照（原话）
> 看人家UU远程的 边缘控制栏的设计 鼠标抵达边缘激活 可以点击 而不是你这种暴力的乱触发

三张实机截图给出的设计是：① 顶部只露一小截胶囊；② 光标抵达后变成带描边的圆角方形按钮，明显"可以点击"；③ 点击之后才展开原生样式菜单（画质/窗口/声音/外设/工具/退出）。
即三段式：**抵达 → 点亮 → 点击**，且任何"自己弹开"都必须不存在。第十九节的 armed/click 契约在自由/释放态已经做到，问题在锁定态。

### 根因：不是"感应太灵敏"，是锁定态有一个会自己完成的动作
锁定态的替代入口是位移累加手势：外拨 48pt → 回拨 24pt → 再外拨 48pt，总时长 ≤1.5s 即调用
`summonEdgeMenuDockForEdge:`（MUC109 释放指针 + 展开面板）。
- MOBA/射击中"跟着移动目标瞄准"的正常手感正是 out-back-out，一局会完成几十次；
- 每次完成都把指针从游戏里拿走并弹出面板 → 玩家体验为"控制栏自己乱弹"；
- 该手势没有任何界面告知：玩家既不知道它存在，也无法预期它，更无法避开它。

调阈值、加冷却都只是在"多容易命中"上挪动，不会改变"它在玩家不做任何事时也会命中"这一事实。

### 决策：删除手势本身
- 锁定态**没有任何指针入口**；motion 在该分支唯一允许的效果是熄灭 armed。
- 开栏 = 已配置的"打开控制中心"快捷键（开关语义不变：再按一次收起，拖动把手期间不抢）。
- 交还指针 = 已配置的"释放鼠标"快捷键；交还后把手即恢复"抵达点亮 → 点击展开"。
- 自由/释放态行为完全不变（12pt×把手 250ms 点亮，点击才展开）。
- 点击命中深度：`HandleHitSlop` 6 → 2，即"把手 + 它自己的 2pt 空气 + 2pt"。收起态 16→18pt 深、点亮态 34pt 深。
  原来 22pt 深的隐形区域会吃掉本该属于 HUD/任务栏的点击，那本身就是第二个传感器。

### 当前主机真实快捷键（取证 + 更正上一轮误判）
存储：`~/Library/Preferences/std.skyhua.MoonlightMac2.plist` → 键 `<uuid>-moonlightSettings`（PropertyListEncoder 的 base64 Data）。
上一轮"找不到自定义值"是对 `<key>` 的正则漏了连字符导致的误判，**特此更正**：本轮实测主机 profile `86D1F81F-4D3D-E306-D694-EFDFE6BCD6CE-moonlightSettings`（kVK 8=C/13=W/5=G/11=B/46=M）：

| 动作 | 主机 | 全局 `__global__` |
|---|---|---|
| 释放鼠标捕获 | 仅 `⇧⌥` | 仅 `⌃⌥` |
| 打开控制中心 | `⌃⌥C` | `⌃⌥C` |
| 断开串流 / 退出 / 重连 | `⌃⌥W` / `⌃⇧W` / `⌃⌥R` | 同左 |
| 鼠标模式 / 性能叠加 / 全屏小球 / 无边框 | `⌃⌥M` / `⌃⌥S` / `⌃⌥G` / `⌃⌥⌘B` | 同左 |

即"⇧⌥ 释放 + ⌃⌥C 开栏"是当前主机设置而非全局默认。全程只读，未修改任何用户配置。

### 状态与所有权（更新第十七节表格）
| 状态 | 指针 | 进入 | 退出 | 清理者 |
|---|---|---|---|---|
| idle（把手 14×48） | 游戏 | 可见且收起 | 入带 250ms → armed | 感应计时器 |
| armed（30pt+图标+accent） | 游戏，零字节外发 | 自由/释放态停留到点 | 离开带、按键、失能、阶段变化 | `resetEdgeSensorSummonState` 唯一出口 |
| expanded（控制栏） | 控制栏 | 点击可见把手（18/34pt 深）或 `⌃⌥C` | 450ms/2500ms、再按 `⌃⌥C`、点击串流 | `deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:` |
| locked（锁定游戏） | 游戏 | — | 只有 `⌃⌥C` 能去开栏；motion 只能熄灭 armed | 同上 |

### 门禁：契约变更，不是迁就实现
- 删除 6 条 slam 用例与 6 条 slam 变异体（对应已不存在的代码，留着只会红）。
- 新增负向契约：四边 × 老手势三种计时（含曾经能完成的 1400ms、停顿重瞄、越过 idle 间隔）× 30 次重复 × 按住键 → 一律"指针仍在游戏、面板不展开、把手不点亮"。
- 新增变异体 `locked motion opens the bar again`：把 summon 放回去，套件必须变红 —— 已确认会红。
- 源码级守卫：`handleEdgeSensorSummonForEvent:` 内禁止 `summonEdgeMenuDock`/`uncaptureMouse`/`activateEdgeMenuDock`；`edgePush*` 与 `edge-sensor-push` 符号必须全仓不存在。
- 命中深度改为可测量断言 + 运行时边界用例（18pt 内可开、19pt 不可；点亮 34pt 可、35pt 不可）。
- 结果：runtime 3992 检查 0 失败、30 条变异体全部捕获；input-regression 45/45；l10n 0；liquid-glass 0；render-probe 自测 0；first-party 警告 0；`git diff --check` 干净。
- 设置页文案同步（双语）：删掉"连拨两下"承诺，明确"锁定态边缘不会自己打开控制栏"。

### 本轮验收（构建 1707，已部署）
| 项 | 状态 |
|---|---|
| 锁定态老手势序列 30 次不弹栏、不夺指针 | 自动测试通过 |
| 点击深度 18/34pt 与"越界属于游戏" | 自动测试通过 |
| 自由/释放态抵达点亮 → 点击展开 | 自动测试通过 |
| 实机：正常游戏中不再"自己弹开" | **尚未验收**（Computer Use 仍报 `The Mac is locked`） |
| 实机：`⌃⌥C` 开栏 / `⇧⌥` 释放后把手可点 | **尚未验收** |
| 实机：四边停靠、拖动、30 次重复、断线重连、多显示器、触摸板/外置鼠标 | **尚未验收** |
| 120/180 FPS | 未测量，不做任何声明 |

## 二十一、点亮之后必须点得着：把手在指针回缩时不许熄灯

修完"锁定态会自己弹开"之后，同一个把手还剩下一个反向缺陷：**点亮了，但那一刀点不着**。

原因在所有权上：armed 的存活被绑在 12pt 感应带上（`handleEdgeSensorSummonForEvent:` 里 `inside` 为假就
`resetEdgeSensorSummonState`）。而人点击"亮起的把手"时手指的自然动作是从边缘**往回缩一点**——一缩就离开
12pt 带 → 灯灭 → 命中区从 34pt 收回 18pt → 点在刚刚还被画成把手的位置上，事件却归了游戏。
这就是历史上"点亮但点击不展开"的来源：可见状态、命中区、指针位置三者再次不一致。

改法是把两个判断分开，各管一件事：

| 判断 | 依据 | 作用 |
|---|---|---|
| 能不能开始请求 | 12pt 感应带（不变，仍是 8..16pt 区间的门禁） | 决定 dwell 计时器是否启动 |
| 已点亮的灯能不能留 | 当前画出来的把手矩形 `edgeMenuVisibleHandleRectInBounds:` | 指针在把手上就一直亮 |
| 灯什么时候灭 | 指针离开画出来的把手（或按键、失能、阶段变化） | 唯一出口仍是 `resetEdgeSensorSummonState` |

于是：入带停留 250ms 点亮 → 回缩到把手内任意位置仍然亮 → 点击展开；离开把手即熄灭，
且更深的位置（例如 25pt）不能绕过感应带自己把灯点亮，也不会因为"曾经是把手"就继续吃点击。

新增 5 条运行时用例（入带点亮 → 回缩仍亮 → 点击展开 → 离开熄灭 → 深处既不能点灯也不能开栏）
与 1 条变异体 `the lit tab shrinks under the pointer that is clicking it`（把"离开把手才熄灭"改成
"每次 motion 都熄灭"，套件必须变红）。实测：runtime 3997 检查 0 失败、36 条变异体全部捕获。

## 二十二、x86_64 门禁不稳定：一次真正的取证，不是重跑糊过去

`5cbb3f1` 推上去后 CI 红在 `Verify keyboard and mouse edges survive input queue congestion`（只红 x86_64 job）。
按"先看日志再动手"处理，结论与本轮侧边栏无关：

| 证据 | 观测 |
|---|---|
| 同一 commit 两个 arch job | arm64 该步骤 success，x86_64 两次都 failure（重跑仍红） |
| 失败形态 | `congestionRecovery(mouse)` 四条连锁 FAIL：release 未入队 → 队列上界不符 → FIFO 不符 → 会话未存活；第一次重跑还多一条 shutdown FAIL |
| 探针输入 | 只读 `moonlight-common-c/src/InputStream.c`，本轮提交未触碰任何 C 输入文件 |
| 产品约束 | `INPUT_EDGE_QUEUE_WAIT_MS = 100ms`：生产者最多等 100ms，超时就按设计 fail closed（"persistent congestion fails closed"用例正是断言这个） |
| 本地复现 | 原生 5 次 + 8×40/12×96 并发共 136 次全绿；x86_64 走 Rosetta 60 次全绿 |

根因在**测试自己的调度**：`freeOneSlot`/`stopProducer` 用固定 `PltSleepMs(15)` 去猜"生产者已经阻塞"，
慢 runner 上线程启动延迟 + 15ms 可以超过产品那 100ms 等待窗口，于是生产者按设计 fail closed，
测试把它报成产品故障；shutdown 用例同源于"打断早了没人阻塞、晚了已失败"。

修法只动探针、不动任何断言：新增 `producerStarted` 原子量，`waitForProducer()` 等生产者真的开始发送后
再交还槽位/再打断（上限 500ms 自旋兜底，避免握手失效变成挂死），删掉两处 15ms 猜测。
断言集合、覆盖语义完全不变；验证：原生 5 次 + 并发 10×60 全绿，x86_64/Rosetta 60 次全绿。
**Intel runner 上是否真的稳定，只能等下一次 CI 判定**（本地无法复现原始慢调度）。

## 廿三、对照 UU 远程：把"抵达即激活"做成手感，而不是做成触发（2026-09-29）

用户给了 UU 远程的截图并要求：鼠标抵达边缘就激活、可以点击，而不是"暴力的乱触发"。先做证据核对，再决定改什么。

### 1. 本机当前是否还存在"抵达就弹"的路径：不存在（静态可达性证据）

`summonEdgeMenuDockForEdge:` / `activateEdgeMenuDockForExitEdge:` 的全部调用点只有三类：

| 调用点 | 触发者 |
| --- | --- |
| `MenuUI.m:99`（`openEdgeMenuDockForControlCenterShortcut`） | 用户按"打开控制中心"快捷键（本机关机配置 = `⌃⌥C`） |
| `MouseCapture.m:2784`（`expandEdgeMenuForLocalClickAtCurrentPointer`） | 用户在**画出来的把手**上按下鼠标（`edgeMenuVisibleHandleRectInBounds:` 命中，未展开时面板 `ignoresMouseEvents=YES`，游戏点击不会被它抢走） |
| `MouseCapture.m:2328/3372` | 同一个快捷键的两个入口 |

`handleEdgeSensorSummonForEvent:` 与 `armEdgeMenuHandleIfStillAtEdge:` 内部被静态测试禁止出现
`summonEdgeMenuDock`/`uncaptureMouse`/`activateEdgeMenuDock`（`edge-sensor-summon-tests.py` 断言），
所以抵达边缘能改变的只有把手的**外观**：不外发一个字节、不交还指针、不展开面板。
点击路径也不要求"先点亮"：`expandEdgeMenuForLocalClickAtCurrentPointer` 只看 phase 与绘制条带，
idle 与 armed 两种外观下都能点。这两点与 UU 的行为是同构的。

### 2. 真正与 UU 的差距：点亮的等待时间

UU 的把手是"到了就变大"。本机把点亮压在一个 250ms dwell 之后——对一个已经在边缘的指针来说，
这 250ms 的沉默正是"点亮但没反应/像坏了"的观感来源。点亮没有任何副作用，没有任何理由等这么久。

改动：`MLEdgeSensorDwellSeconds` 0.25 → **0.12**（低于悬停反馈的可感知延迟阈值；仍是定时器，
所以触发时刻的 buttons/可见性/停止/重连/偏好重校验语义完全保留）。
`Edge Sensor Summon detail` 中英文文案同步 250ms → 120ms（该数字是文案与代码的契约，由静态测试推导校验）。

先加契约再改常量：`arriving at the edge waits too long to answer`（>150ms 即失败）在旧代码上确实红，改后绿。

### 3. 与 UU 的结构性差异必须说清楚（不能假装一样）

UU 默认是**绝对鼠标**（桌面模式）：本机光标位置就是远端光标位置，所以"抵达边缘"永远可判定。
Moonlight Enhanced 的**锁定游戏鼠标**是相对位移模式：本机没有权威光标，把相对位移积分当远端坐标
= 猜测，第 廿一 节已经证明这种猜测会在瞄准时每分钟完成多次。因此锁定游戏态刻意**没有任何指针入口**
（第 廿/廿二 节），进入方式是 `⌃⌥C`，或先按释放快捷键（本机配置 = `⇧⌥`）把指针交还本机——释放后
的把手点亮/点击与自由模式、与 UU 完全一致。**桌面/远程模式**（`isRemoteDesktopMode`）下即使处于
"捕获"状态，悬停点亮点亮与点击也照常可用，这才是 UU 那种手感的对应模式。

### 4. 顺带纠正一条测试自己的错误建模（不是放宽断言）

上一轮遗留的 `FAIL the dragged tab lights again where it now is`：诊断显示 `blocker=none`、
`latch=1`、`captured=1`。原因是拖动用例用 `setEdgeMenuButtonExpanded:YES` 直接把面板摆开，
实例停在"已捕获 + 非桌面模式 + 正在拖把手"——真实产品里拖把手只可能发生在面板持有指针（临时释放，
`isMouseCaptured=NO`）期间，所以这条断言在测一个不可能存在的状态；`lockedGameMotion` 分支按设计
在该状态下不接受任何 motion，于是"永远不再点亮"是建模产物而非产品缺陷。

修法：改走真实入口 `openEdgeMenuDockForControlCenterShortcut`（它会交还指针），并**新增**断言而不是删：
开口必须先交还指针、沿边拖动不改 dock 边、band/panel 跟随新位置（含负原点副屏）、离开再回来必须重新点亮、
旧位置不再响应，以及新增的锁定态契约"回到游戏里的指针不得凭猜测坐标点亮拖动后的把手"。
断言净增 4 条，无删除、无放宽。

### 5. 本轮验证

| 项 | 结果 |
| --- | --- |
| 运行时探针（真实生产方法） | 4057 检查 / 0 失败（旧 4055 中 1 失败已定位并纠正建模） |
| 静态+运行时变异测试 | `--self-test` RC=0，33 条 negative control 全被抓 |
| 键鼠回归套件 | 45 passed / 0 failed |
| 本地化 / Liquid Glass / `git diff --check` | 0 / 0 / 干净 |
| Release 构建 | arm64 `** BUILD SUCCEEDED **`，一方源码 0 warning，产物内 120ms 文案已生效 |
| 部署 | 1.6.0 (1710) `a3434f123f9fa96c…`，回滚 1708 `3c2b3be78b0dd214…`（记录 `uu-style-edge-arrival-install-result.json`） |
| 实机验收 | **尚未验收**：Sky Computer Use 仍报 `The Mac is locked…`。抵达即点亮的手感、点击展开、四边停靠与拖动重触发、30 次重复、锁定态 `⌃⌥C`/`⇧⌥` 路径、失焦恢复、断线重连、多显示器/触摸板/外置鼠标、FPS 全部未做人工确认 |

### 6. 顺着"能不能点着"查出一个真的不一致（桌面模式）

对照 UU 时只核对了一件事：**会点亮的状态是否都能点着**。答案是桌面模式不能：

| 事实 | 证据 |
| --- | --- |
| 点亮允许"捕获中 + 桌面模式" | `armEdgeMenuHandleIfStillAtEdge:` 的门槛是 `(isMouseCaptured && !isRemoteDesktopMode)`；桌面模式本地光标仍是权威指针 |
| 捕获态在桌面模式下依然成立 | `captureMouse` 无条件 `isMouseCaptured = YES`（日志本身打印 `remoteDesktop=%d`） |
| 点击却不认这个状态 | `expandEdgeMenuForLocalClickAtCurrentPointer` 原先要求 `!isMouseCaptured` |
| 未展开时面板不吃鼠标 | `MenuUI.m:411` `ignoresMouseEvents = phase == Collapsed/Hidden`；点击只能走 `mouseDown:` 的这条分支 |

结论：**桌面模式（悬停真正可用的那一种模式）里，把手会点亮，但落在把手上的按下被当作远端点击发走**，
`mouseDown:` 在 `expandEdgeMenu…` 返回 NO 后继续 `resumeInputForExplicitStreamClick` + 派发按下。
这正是任务书列的"可见状态 / 命中区域 / 鼠标控制权不一致"，也正是 UU 那类绝对指针用法会踩到的位置。

修法一处门槛：把 `self.isMouseCaptured` 换成 `(self.isMouseCaptured && !self.isRemoteDesktopMode)`，
即按"指针权威"判定而不是按捕获标志判定，与点亮路径同源。`mouseUp` 靠 `edgeMenuClickConsumedLocally`
吞掉配对抬起，因此 down/up 仍成对，不会漏一半按键给主机。锁定游戏态行为完全不变（那里门槛等价于旧条件）。

测试先行：新增 4 条运行时断言（桌面模式点亮中→点击展开、抬起被吞、前提状态自证）+ 1 条静态契约
（门槛必须是指针权威）+ 1 条变异体 `a lit desktop tab cannot be clicked`。旧代码上 2 条断言确实红，改后绿；
`--self-test` RC=0，negative control 由 33 增至 34。

过程说明（不是放宽断言）：插入用例时先用 `s` 承载新实例，污染了紧随其后依赖同一实例的两条
既有断言；改为独立作用域 + 局部实例 `d` 后，那两条恢复原判定。既有条目一字未改。
