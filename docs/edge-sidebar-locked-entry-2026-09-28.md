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
