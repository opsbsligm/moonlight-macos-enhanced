# Moonlight macOS Enhanced — 目标模式提示词（2026-10-23 现场刷新）

## 2026-10-23 K1.1 与 M4 发布复核

- 代码基点 `798050d9`，pipeline 423 八项 success（lint:toolchain / audit:python /
  download-deps / build-app / test-app / audit:sources / package-dmg / publish-github），
  镜像 60 refs 一致。
- M4.1–M4.4 完成：Joy-Con `057E:2006/2007` 已识别为任天堂家族；PS 触摸板
  在 `LiGetHostFeatureFlagsCtx & LI_FF_CONTROLLER_TOUCH_EVENTS` 不支持时停发；
  设备表与触摸板门禁真实方法编译回放 + 14 变异全拦；M4 整体仍是部分完成，
  真机报文兼容性与主机侧 touch/电量/Joy-Con 状态仍 `hardware_validated=false`。
- K1.1 实现事件内已有可打印 Unicode 的转发，与键码路径互斥。ASCII、
  Cmd/Ctrl/Option 快捷键、功能键、控制字符仍走原键码路径；已持有的 wire 键
  不被 repeat 改走文本；异步块捕获 `__strong NSData`，发送时读字节。
- K1.1 不等于 IME 已提交文本：marked text、候选窗、输入法提交、文本长按
  重复、真机中文注入效果属 K1.2，仍待实现 + 真机验收。
- 真机验收基线：build1933 不含 K1.1/M4 代码，build1959 不含 798050d9 起的 K1.1
  CI wiring，下一轮真机验收需重新构建对应 SHA 的产物。
- 本地键盘门禁复核：`key-state-heal-tests.py` 的 shipping 一遍 0 失败，4 个
  known-bad 变体各失败 1–5 项正是门禁要证明的捕获能力；读日志时不要把
  `known-bad` 段的预期 `FAIL` 当成回归。

## 2026-10-23 现场复核（覆盖下方历史描述，本波刷新至 pipeline 409）

- 已验证代码基点：`cd42716a`（GitLab main，pipeline 414 八项成功）；其下 `c0707e70` 的触摸板代码由 pipeline 409 build1957 DMG 验收（SHA256 2f4fac89…，验收目录 moonlight-ci-evidence/20261023-touch-event）。跳过项不算通过。M4.3/M4.4 代码在本波提交，待对应 pipeline。
- M2 三回调全部接通；M3 setMotionEventState 已接（PS4/PS5 状态包六轴原生携带，启用语义=主机请求即发，按类型节流 + SDL HIDAPI 比例换算 + 拔出/断流/显式停止三路径统一 stop）；M4 全部子项代码完成：M4.1 电池、M4.2 PS 触摸板（12 位坐标 DOWN/MOVE/UP 状态机 + pointer id 锁定，仅 PS 系通告 BATTERY_STATE/TOUCHPAD）、M4.3 单只 Joy-Con 识别（isNintendo + 诊断身份表补 057E:2006/2007，走既有 0x3F 简单状态解析，arrival 判 NINTENDO，device-table 门禁真谓词回放 + 回归变异全拦）、M4.4 触摸板退化路径（派发前查 LiGetHostFeatureFlagsCtx 的 LI_FF_CONTROLLER_TOUCH_EVENTS，主机不支持即停发，touch 门禁 8 变异全拦）。本地综合门禁 91 通过 / 0 失败 / 15 跳过。
- M3 边界：计划中的 PS4 0x05 / PS5 0x09 feature report 显式启用写未实现（HID 状态包本身携带六轴字节，启用即"主机请求→发送"），完成边界仍以真机主机侧读到非零六轴 + 断流后无残留请求为准。
- `hardware_validated=false`：PS5 BT 短包存疑、未抓真机 IMU/电量/触摸报文；日常应用现为 build1933（0.1 诊断代码），build1957 未替换日常应用。
- CI 基建教训（2026-10-23）：gitlab-ctl reconfigure 后 nginx :80 按 external_url 变 SSL-only，纯 HTTP 全 400；Linux VM runner 改 `https://www.bsligm.com:8445` + tls_skip_verify（备份 config.toml.bak-20261023）；Mac M2 runner 曾短暂失联且 macos tag 丢失，误加给 VM runner 后 job 落到 Linux（swiftlint 缺失）。**reconfigure 后必须回读 runner URL 与 tag**；本地 push 被 :80 阻时直接推 8445 HTTPS，不改 remote。
- 0.2 已拆出 per-device 表，并修复表未初始化、同型号设备 key 合并、借用 CF 对象释放与满槽复用 0。真实方法编译回放及三项行为变异通过。
- 0.2 仍缺完整发送序列等价证据；tuple 回放不能代替它。M1 已有 arrival 调用，但发送结果、驱动隔离、会话代数、拔出清位、鼠标模式与能力真实性尚未闭环。
- 通告生命周期已新增修复：输入队列按会话代数去重，发送失败不记录成功；诊断回调校验代数与设备存活；绑定和热插拔补空闲通告；拔出通过有效 lease 幂等清位。真实方法回放及四项变异通过，发布状态以本提交对应 CI 为准，仍不代表 M1 全部交付。
- `hardware_validated=false`。build1933 不含上述新代码，不得用于验收 0.2/M1。
- 下文“单一 Controller”“arrival 零调用”“0.2/M1 尚未开工”为历史状态，已失效；下文统一宣告 analog+rumble 的方案撤销，按设备实际实现逐项决定。

## 可直接使用的目标模式提示词

持续完成 Moonlight macOS Enhanced 的对标作战。先读 AGENTS.md、基线、作战计划和本段现场纠正，再核对 Git、源码、准确 SHA 的流水线。沿用当前目标，增量执行，不把文档勾选或绿色编译当成功能完成。

输入面代码已交付（0.2 per-device 状态表、M1 通告与清位、M2 三回调按号震动、M3
六轴、M4 电池/触摸板/Joy-Con、K1.1 文本与键码互斥），CI 全绿即视为代码通过，
不等于功能完成：手柄、触摸板、六轴、电量、真机中文一律 `hardware_validated=false`，
直到用对应 SHA 产物在真机 + Sunshine/GFE 主机侧取证。DualSense 自适应扳机不等于
Xbox impulse trigger，Joy-Con 不得直接套 Pro Controller 解析；没实现的能力不向主机通告。

下一开发重点：在真机验收排期之外，优先推进未开工且不依赖硬件的对标项——E1 全屏侧边栏
参数化（感应带 8–16pt、驻留 60–300ms、收起 300–1000ms 变设置项，默认值 = 现编译期
常量，甩动阈值与冷却维持常量；门控先证明自己会失败再放开）、K2 安全注意序列可行性、
P2 对等补齐（重连退避、失焦静音/后台手柄/主机出声开关、桌面档绝对鼠标默认关）。
K1.2（marked text / 候选窗 / 输入法提交）触碰键盘接收路径，若 17 个键盘门禁任一无法
转绿则只保留 K1.1。

对标范围完整保留：Moonlight Qt、原项目上游、协议 fork、Sunshine 与基地版，以及 Parsec、网易 UU、Horizon、Citrix、深信服、锐捷。分别维护输入、会话恢复、显示音频、设备重定向、诊断与交付能力矩阵；每格区分源码、官方资料、实测、宣传和未知。既有文档未覆盖的产品继续列为待调研，不编造成已完成全面对标。

不可突破：macOS27 原生 NSSegmentedControl + tabs、既有设置默认值及侧边栏手感；GitLab 唯一事实源、CI 单向 GitHub 镜像；不绕门禁；USB 真重定向、正式签名公证和自动更新保持冻结。每波先修复、行为测试、构建与适当门禁，再提交推 GitLab，核对准确 SHA 的 CI 和产物。明确区分代码通过、产物验证、真机验收；持续记录 WeKnora 增量，不上传凭据。

## 历史计划（保留追溯，现场状态以上段为准）

## 当前目标（对标作战，顺序即优先级）

对标来源：`docs/competitive-polish-roadmap-2026-10-20.md`（能力矩阵 + P0/P1/P2）、
`docs/input-mapping-benchmark.md`（输入映射四级证据）。对标对象：moonlight-qt（上游）、
moonlight-common-c fork @386e79c（协议层）、Sunshine（主机）、基地版 skyhua0224（起点）；
竞品 Citrix Horizon / Parsec / 网易 UU / ToDesk。执行波次见
`docs/campaign-plan-2026-10-20.md`，不可撼动基线见 `docs/baseline-2026-10-22.md`。

1. **0.1 控制器探针真机验收** ⏳（代码完成，仅差真机）
   诊断报告已能输出 vid:pid/族/传输/电池/驱动/未通告文案。真机验收 = 装对应产物后
   串流一次接两块手柄，核对分类、driver、arrival 文案与日志。`hardware_validated=false`。
2. **0.2 per-device 状态表** ✅代码 / ⏳真机
   `HIDDeviceControllerEntry` + `deviceControllerTable` 已落地（每设备独立 Controller、
   playerIndex、mask 位、变化检测器）；单手柄逐字节线基线已录制
   （`scripts/controller-wire-baseline.py`，21 用例/8 变异）。双手柄真机待验证。
3. **M1 类型/能力通告 + 拔出清位** ✅代码 / ⏳主机侧验收
   `LiSendControllerArrivalEventCtx` 已接（HIDSupport.m:1321），能力位按设备实际实现
   逐项通告；发送结果按会话代数记账、拔出幂等清位已有真实回放。主机侧虚拟手柄类型
   与断开时序 `hardware_validated=false`。
4. **M2 三回调 + 按号震动** ✅代码 / ⏳真机
   rumble 按 controllerNumber 路由并按设备去重；setControllerLED、rumbleTriggers 已接，
   TRIGGER_RUMBLE/RGB 能力位仅对真正具备的家族通告。
5. **M3 陀螺仪/加速度计** ✅代码 / ⏳真机
   setMotionEventState 已接（PS4/PS5 状态包六轴 + 按类型节流 + SDL HIDAPI 比例换算 +
   三路径统一 stop）；无 feature report 显式启用写，差异已记录。
6. **M4 电池/触摸板/Joy-Con 扩容** ✅代码 / ⏳真机
   PS 系电池、PS 触摸板（12 位坐标状态机）、Joy-Con 057E:2006/2007 识别、
   主机不支持触摸即停发均已完成；真机报文兼容性未验证。
7. **K1 中文/文本注入** ⏳（K1.1 ✅代码，K1.2 未开工）
   K1.1：`LiSendUtf8TextEventCtx` 已接，与键码路径互斥，门禁 6 变异全拦。
   K1.2：marked text/候选窗/输入法提交未做；真机中文注入未验收。
8. **K2 Ctrl+Alt+Del** ✗未开工（无依赖，可并行）
   扩展 scancode `0x8000` 路径已在用；先真机验可行性，拉不起 SAS 就降级为提示。
9. **E1 全屏侧边栏参数化** ✗未开工（无依赖，可并行）
   感应带 8–16pt/驻留 60–300ms/收起 300–1000ms 变设置项，默认值 = 现常量；
   甩动阈值与冷却维持编译期常量。门控先改再改默认。
10. **P2 对等补齐** ✗未开工（各自独立小提交）
    重连退避状态机；`muteOnFocusLoss`/`backgroundGamepad`/`playAudioOnHost` UI 开关；
    桌面档绝对鼠标默认关。
11. **历史遗留（保持状态）**：29ms 队列延迟（pacer 未接入，持续改善未闭合）、
    90FPS 插帧稳定性（本机 VT 过载保护已触发，有效负载验收未做）。
    这两项不因对标作战自动解冻，单独排期。

## 对标结论速查（为什么是这个顺序）

- 控制器 = 唯一"维度缺失"：qt 全链路已用 Arrival/Motion/Touch/Battery 事件，
  我们全仓 0 调用 → 主机永远把我们当 Xbox 360。P0 收益最大。
- 键盘规则系统（97 键×修饰键 + 10 月亮动作）领先 qt；中文注入是最后硬缺口。
- 鼠标/边缘栏/视频/音频我们领先（三模式 + 1000Hz、MetalFX SR、VT 插帧、VRR、
  7.1.4、剪贴板同步、Sunshine HTTP 扩展），保持领先不返工。
- 竞品证据封顶：Citrix 仅 ADMX 机制证据；Parsec 文档 403 不做断言；
  UU 仅宣传面（触屏场景不同赛道）；ToDesk 仅宣传面。

## 已验证事实与待验证结论

| 项 | 已验证事实 | 结论边界 |
| --- | --- | --- |
| 29ms 队列 | pacer 未接入；Metal 队列 3/3→2/2 已实测 | 拉帧 pending 是解码单元阈值；不能将 buffer 数量直接等同于 29ms 根因 |
| 90FPS 插帧熔断 | 本机出现超预算调用与实际回退 | 不推导所有硬件都不可行；不靠关闭保护或伪造上屏指标验收 |
| 实际上屏统计 | 读取 drawable.presentedTime，0 表示未呈现或跳过 | 无新鲜样本显示 --；恢复呈现后重建统计窗口，拒绝迟到旧回调 |

## CICD 标准（每轮执行）

1. 改代码 → `bash scripts/local-gates.sh`（快速模式，完整变异电池仅 `--all`）→ 0 failed，skip 逐项列名
2. 涉及新行为 → 新增门控脚本（含 self-test）并接入 CI；门控必须证明自己会失败
3. `git -c user.email="codex-agent@homelab.local" -c user.name="Codex Agent" commit`
4. `git push gitlab main`（http://172.16.130.6/moonlight/moonlight-macos-enhanced.git）
5. 等 30s+ 再查 project 6 pipeline，准确 SHA 对应、全绿才算通过；失败修复后重推，不绕过
6. GitHub（opsbsligm）由 `publish-github` job 单向镜像，只读，不手推

## 当前架构关键文件

| 用途 | 路径 |
|------|------|
| 标签页 UI（液态玻璃滑块） | `Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift` |
| 帧节奏控制（暂未启用主循环） | `Limelight/Stream/MLFramePacer.h/.m` |
| 真正生效的帧队列策略 | `Limelight/Stream/VideoDecoderRenderer.m`（desiredEnhancedDrawableDepth/InflightLimit、desiredPendingFramesForDisplayRefreshRate） |
| 带宽追踪 | `Limelight/Stream/MLBandwidthTracker.h/.m` |
| 解码渲染核心 | `Limelight/Stream/VideoDecoderRenderer.m` |
| 串流控制栏 | `Limelight/macOS/ViewControllers/MLEdgeMenuUI.m` |
| 设置面板 | `Limelight/macOS/ViewControllers/` |
| USB 侧边状态 | `Limelight/Stream/USBMenuStatus.h` |
| 玻璃效果容器 | `Limelight/macOS/Views/GlassOverlayContainer.h/.m` |
| 快捷键OSD | `Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m` |
| 审计基线 | `scripts/analyzer-baseline.json` |
| GitLab 构建与自动镜像 | `.gitlab-ci.yml` |
| 镜像端补充审计 | `.github/workflows/build.yml` |

## 约定

- 完全独立原项目，不接受任何 PR 或 fork 关系；专注 macOS，Linux/Windows 特性无视
- 所有改动必须 local-gates 0 failed + commit + push GitLab + pipeline 全绿
- "完成"必须基于真实运行证据（log/CUA/用户主观），不能由代理代答；
  未真机一律 `hardware_validated=false`
- 设置 UI 已验收控件与默认值不动（AGENTS.md），新增设置项默认 = 当前行为
- 冻结项不自行解冻：USB 真实重定向、Developer ID 公证/正式签名、自动更新
- 中文汇报，结论先行；一个里程碑一个提交一个 pipeline
