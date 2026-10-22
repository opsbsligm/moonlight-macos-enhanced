# Moonlight macOS Enhanced — 目标模式提示词（2026-10-22 刷新）

## 2026-10-23 现场复核（覆盖下方历史描述）

- 已验证代码基点：`19b68a225402d82f36971496dbc4a1a23948148b`；GitLab pipeline 393 八项成功，镜像日志确认 60 refs；本地快速门禁 78 passed / 0 failed / 15 skipped。跳过项不算通过。
- 0.2 已拆出 per-device 表，并修复表未初始化、同型号设备 key 合并、借用 CF 对象释放与满槽复用 0。真实方法编译回放及三项行为变异通过。
- 0.2 仍缺完整发送序列等价证据；tuple 回放不能代替它。M1 已有 arrival 调用，但发送结果、驱动隔离、会话代数、拔出清位、鼠标模式与能力真实性尚未闭环。
- 通告生命周期已新增修复：输入队列按会话代数去重，发送失败不记录成功；诊断回调校验代数与设备存活；绑定和热插拔补空闲通告；拔出通过有效 lease 幂等清位。真实方法回放及四项变异通过，发布状态以本提交对应 CI 为准，仍不代表 M1 全部交付。
- `hardware_validated=false`。build1933 不含上述新代码，不得用于验收 0.2/M1。
- 下文“单一 Controller”“arrival 零调用”“0.2/M1 尚未开工”为历史状态，已失效；下文统一宣告 analog+rumble 的方案撤销，按设备实际实现逐项决定。

## 可直接使用的目标模式提示词

持续完成 Moonlight macOS Enhanced 的对标作战。先读 AGENTS.md、基线、作战计划和本段现场纠正，再核对 Git、源码、准确 SHA 的流水线。沿用当前目标，增量执行，不把文档勾选或绿色编译当成功能完成。

优先完成 M1 正确性：只在 inputQueue 验证 lease 后访问 C context；依据发送返回值与会话代数记录通告，失败允许重试；HID/MFi 输入隔离；重连、空闲热插拔、移除清位有真实行为回放；恢复手柄鼠标模式与 per-device 输入之间的一致性；能力位仅报告实际实现，按号震动未完成不得泛称支持多手柄震动。不要用异步块后的局部 BOOL 判断发送成功，不新增主线程/输入队列互等死锁。

然后补完整单手柄事件序列基线和双设备回放，准备与提交对应的 CI 产物，再分别记录真机验收。后续依次推进 K1 文本与键码互斥、K2 安全注意序列可行性、E1 侧边栏参数化、P2 重连和会话选项。M2/M3/M4 在生命周期可靠后推进；DualSense 自适应扳机不等于 Xbox impulse trigger，Joy-Con 不得直接套 Pro Controller 解析。

对标范围完整保留：Moonlight Qt、原项目上游、协议 fork、Sunshine 与基地版，以及 Parsec、网易 UU、Horizon、Citrix、深信服、锐捷。分别维护输入、会话恢复、显示音频、设备重定向、诊断与交付能力矩阵；每格区分源码、官方资料、实测、宣传和未知。既有文档未覆盖的产品继续列为待调研，不编造成已完成全面对标。

不可突破：macOS27 原生 NSSegmentedControl + tabs、既有设置默认值及侧边栏手感；GitLab 唯一事实源、CI 单向 GitHub 镜像；不绕门禁；USB 真重定向、正式签名公证和自动更新保持冻结。每波先修复、行为测试、构建与适当门禁，再提交推 GitLab，核对准确 SHA 的 CI 和产物。明确区分代码通过、产物验证、真机验收；持续记录 WeKnora 增量，不上传凭据。

## 历史计划（保留追溯，现场状态以上段为准）

## 当前目标（对标作战，顺序即优先级）

对标来源：`docs/competitive-polish-roadmap-2026-10-20.md`（能力矩阵 + P0/P1/P2）、
`docs/input-mapping-benchmark.md`（输入映射四级证据）。对标对象：moonlight-qt（上游）、
moonlight-common-c fork @386e79c（协议层）、Sunshine（主机）、基地版 skyhua0224（起点）；
竞品 Citrix Horizon / Parsec / 网易 UU / ToDesk。执行波次见
`docs/campaign-plan-2026-10-20.md`，不可撼动基线见 `docs/baseline-2026-10-22.md`。

1. **0.1 控制器探针真机验收** ⏳（代码完成 `a85c5879`，1933 产物已验收）
   诊断报告已能输出 vid:pid/族/传输/电池/驱动/未通告文案。真机验收 = 装 1933 后
   串流一次接两块手柄，核对分类、driver、arrival 文案与日志。`hardware_validated=false`。
2. **0.2 per-device 状态表** ⏳（下一开发重点）
   HID 驱动仍是单一 `Controller`（`HIDSupport_Internal.h:49`）、mask 硬编码 1
   （`HIDSupport.m:1263`）。第一步：单手柄发包逐字节等价录制基线；再按设备索引拆状态，
   playerIndex 由连接顺序分配。等价证不出来就停（计划 §4 风险节）。
3. **M1 类型/能力通告 + mask 修正 + 拔出清位** ⏳（依赖 0.2）
   `LiSendControllerArrivalEvent` 全仓 0 调用。首轮只报 `ANALOG_TRIGGERS|RUMBLE`，
   没实现的不报。验收 = Sunshine 主机侧虚拟手柄类型随设备变化 + 拔出及时断开。
4. **M2 三回调 + 按号震动** ⏳（依赖 M1）
   `rumbleTriggers`/`setControllerLED` 接线；震动先按 controllerNumber 找设备
   （现在 HID 路径 `getFirstDevice`，第二只手柄的震动必丢）。
5. **M3 陀螺仪/加速度计** ⏳（依赖 M1）
   解析字段已在 PS4/PS5 状态包里，缺的是启用 feature report + 节流 + 单位换算 + 关闭复原。
6. **M4 电池/触摸板/Joy-Con 扩容** ⏳（依赖 M1）
   isNintendo 补 057E:2006/2007；评估 fork 对齐 `LI_CTYPE_STEAM`/`DUAL_TOUCHPAD`/`TouchEvent2`。
7. **K1 中文/文本注入** ⏳（无依赖，可并行）
   `LiSendUtf8TextEvent` 0 调用 = 键盘面最后硬缺口。先已提交文本与 keyCode 互斥，
   marked text 单独提交单独验收。
8. **K2 Ctrl+Alt+Del** ⏳（无依赖，可并行）
   扩展 scancode `0x8000` 路径已在用；先真机验可行性，拉不起 SAS 就降级为提示。
9. **E1 全屏侧边栏参数化** ⏳（无依赖，可并行）
   感应带 8–16pt/驻留 60–300ms/收起 300–1000ms 变设置项，默认值 = 现常量；
   甩动阈值与冷却维持编译期常量。门控先改再改默认。
10. **P2 对等补齐** ⏳（各自独立小提交）
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
