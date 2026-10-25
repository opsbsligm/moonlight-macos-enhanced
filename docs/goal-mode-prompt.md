# Moonlight macOS Enhanced — 目标模式提示词（2026-10-25 K1.2/SAS 门禁在途刷新）

> 用途：续跑本仓库对标作战的"目标模式"提示词。所有续接会话先读 AGENTS.md、`docs/baseline-2026-10-22.md`、`docs/campaign-plan-2026-10-20.md`、本文件和 `docs/competitive-polish-roadmap-2026-10-20.md`，再核对 Git、源码、准确 SHA 的流水线。

## 1. 当前基点（截至 2026-10-24 P2-2b + P2-3a 双 MR 合并落地）

- 代码基点 main = `b65db5fb`（`Merge branch 'p2-3a-direct-enhanced-backends' into 'main'`），
  pipeline #482 = 8/8 success。P2-2b 与 P2-3a 两个 MR 均已合并：
  - **P2-2b 诊断触发器 + host-gone 真 caller**：`41477a83`（merge `3b5ae07c`，pipeline #471/#473 绿）。
    connect-timeout / startup-no-payload / payload-stall 接入退避状态机；graceful (0) 与
    unexpected-early (-102) 触发 `markHostConfirmedGoneFromDiagnosticsWithReason:`；
    transient 错误码仍走 1s/3s/9s 退避。
  - **P2-3a 失焦静音三后端**：`dc1135bc`（原分支 `254c5dc4`，merge `b65db5fb`，pipeline #482 8/8）。
    `Connection.setAudioFocusMuted:` 单入口覆盖 LegacyQueue `kAudioQueueParam_Volume` /
    Enhanced `mainMixerNode.outputVolume`（mute 缓存当前值、regain 恢复 1.0）/
    Direct 渲染回调按 latch 帧级静默（output unit 无公开 volume 参数，编译实证）。
- 审批边界：开发分支 → MR → 准确 SHA 的 CI → 实际审核者审批。禁止借 VM root 或 Rails 代替他人审批。
- 在途待 owner（liguangming）Web UI 批 MR（Codex 账号 Developer 不能自批）：
  - **MR 5** = 本刷新（`docs-goal-mode-refresh-b65db5fb`）；
  - **MR 6** = K1.2 本地输入法组合（`k1-2-local-ime-composition` @ `5c0dbfa3`，pipeline #487 7/7 success）；
  - **MR 7** = SAS 门禁补进 GitLab（`ci/sas-preset-gate` @ `7223f23d`，pipeline #489 7/7 success，
    merge pipeline #490 全绿）。evidence 20261025-k1-2-local-ime/。
- 镜像 64 refs 与 GitLab 完全一致；不绕过门禁。
- 最新 DMG：`build1978`（P2-3a 三后端落地，arm64，本轮 pipeline #482 产物）。用户日常
  `/Applications/MoonlightEnhanced.app` 仍是 **build1926**，真机验收前需装新 DMG。
- `hardware_validated=false` 保留：0.2/M1/M2/M3/M4/K1.1/E1/P2-1/P2-2a/P2-2b/P2-3a/P2-3b
  全是代码层完成 + 真机待取证。

## 2. 已完成（代码层；CI/产物验收；真机仍待）

| 编号 | 提交 | 状态 | 备注 |
| --- | --- | --- | --- |
| 0.1 控制器诊断 | `a85c5879` | 代码+CI+DMG 完成 / 真机待 | `Moonlight-1.6.0-build1933.dmg` |
| 0.2 per-device HID 状态 | `19b68a22`/`f42f4002`/`aa99a860`/`69eb84ef`/`85ac0008` | 代码完成 / 真机待 | 单手柄逐字节等价已录制 |
| M1 arrival/type/caps + 拔出清位 | `cd42716a` | 代码完成 / 主机侧待 | `LiSendControllerArrivalEventCtx` 已接 |
| M2 按号震动 + setControllerLED + rumbleTriggers | `81f404be`/`e8c943a0`/`b8925df5`/`6109b363` | 代码完成 / 真机待 | per-number 去重 + 单手柄基线 |
| M3 IMU + 电量 + 触摸板 | `75ed217d`/`f5f5520a`/`c0707e70` | 代码完成 / 真机待 | PS4/PS5 触摸板 12 位坐标状态机 |
| M4 Joy-Con 收口 | `7c5b687f` | 代码完成 / 真机待 | 单只 Joy-Con 057E:2006/2007 |
| K1.1 可打印 Unicode | `34e921a3`/`798050d9`/`08616a19` | 代码完成 / 真机待 | 与键码路径互斥 |
| E1 边缘栏参数化 | `622132b3` | 代码完成 / 真机待 | 感应带 8–16pt / 驻留 60–300ms / 收起 300–1000ms，默认值 = 现常量 |
| P2-1 自由鼠标走绝对坐标 wire path | `9426623b` | 代码完成 / 真机待 | 默认关闭；UI 纯新增；谓词三条件，5 秒绝对参考 |
| P2-2a 退避状态机（terminated/stage/menu）| `c5c87fd2` | 代码完成 / 真机待 | `MLStreamReconnector` 1s/3s/9s，host-gone wrapper 写出但当时无 production caller |
| P2-2b 诊断触发器 + host-gone 真 caller | `41477a83`（merge `3b5ae07c`）| 代码完成 / CI 全绿（#471/#473）/ 真机待 | connect-timeout / startup-no-payload / payload-stall 接入退避；graceful + unexpected-early trigger `markHostConfirmedGoneFromDiagnosticsWithReason:`；transient 错误码仍走退避 |
| P2-3a 失焦静音（三后端）| `4e6fba87` + `dc1135bc`（merge `b65db5fb`）| 代码完成 / CI 全绿（#482）/ 真机待 | `Connection.setAudioFocusMuted:` 单入口：LegacyQueue `kAudioQueueParam_Volume` / Enhanced `mainMixerNode.outputVolume` / Direct 渲染回调帧级静默；默认 false |
| P2-3b 失焦抑制手柄事件 | `26d20062` | 代码完成 / CI 全绿 / 真机待 | 6 个 controller-wire 入口 + MFi `updateFinished:` 加门；4 焦点观察者对称；默认 off；键盘/鼠标不挂门 |
| K1.2 本地输入法组合 | `5c0dbfa3`（MR 6，待批） | 代码完成 / CI 全绿（#487）/ 真机待 | `HIDLocalIME` NSTextInputClient；per-host `imeLocalComposition` 默认 off；uncapture 先 flush 再 end；`keyboard-ime-routing-tests` 双管线 |
| SAS 预置规则 GitLab 门禁 | `7223f23d`（MR 7，待批） | CI 全绿（#489/#490）/ 待合 | `sas-preset-tests.py` 补进 GitLab test job；SAS 功能本体早在 `6968286d`（翻译规则预置） |

## 3. 待开工（按优先级，不依赖真机排期）

> 所有未开工项必须遵守：默认值 = 当前行为、UI 纯新增、门控先证明自己会失败再放开。

### 3.1 K2 Ctrl+Alt+Del（2026-10-25 复核：功能本体已存在）
- **SAS 能力本体早在 `6968286d`（2026-09-20）落地**：`KeyboardTranslationProfile.secureAttentionSequencePresetRule()`
  在设置 > 快捷键 > "Add Preset Rule" 提供预置翻译规则，Ctrl+Option+FwdDel（macOS 键位）→
  Ctrl+Alt+FwdDel（主机 SAS 键位），走已有 translation-rule 机制，`sas-preset-tests.py` 守护。
- 机制选择 = 发现性而非新机制：macOS 不像 Windows 吞 SAS，普通转发路径本就能送三键；玩家缺的是找到它的方式。
- **剩余缺口（已修，MR 7）**：该门禁此前只接在 GitHub workflow（镜像侧），GitLab 事实源缺跑 →
  `7223f23d` 补进 GitLab test job。
- **真机验证仍待**：用户装新 build 串流 → 用预置规则（或默认 Ctrl+Alt+FwdDel 直发）→ 主机 SAS 是否拉起。
  拉不起 → 文档降级为"提示用主机端工具"，不虚报。

### 3.2 P2 对等补齐（各自独立小提交，可与 K2 并行）
1. ~~`LiSendMouseMoveAsMousePositionEvent`~~ —— 已落地于 `9426623b`（见 §2）。
2. 重连退避状态机：
   - ~~terminated + stage-failed + menu retry~~ —— P2-2a (`c5c87fd2`) 已收口（main 8/8 success）。
   - ~~connect-timeout + startup-no-payload + payload-stall 三个诊断触发点 + host-gone 真 caller~~ —— P2-2b (`41477a83`) 已收口（已合并，历史 pipeline #471/#473 success）。
   - 当前覆盖全部 5 类自动 trigger 与 menu retry；host-gone 仅在 graceful (0) 与 unexpected-early (-102) 触发；transient 错误码仍走退避。
3. ~~qt 对等项打包~~ —— 拆为 §3.2.1 三条独立计划。
4. **桌面档绝对鼠标默认关**（已写明：旧游戏兼容场景别开）。

### 3.2.1 P2-3 收口状态（2026-10-24 P2-2b / P2-3a / P2-3b 全部落地后复核）

- `playAudioOnHost` —— 已存在（xib checkbox → `playAudioOnPC` → launch URL
  `localAudioPlayMode=%d`）；roadmap 描述已修，不留 TODO。
- `muteOnFocusLoss` —— **三后端已收口并在 main**：LegacyQueue `4e6fba87`（#433）+
  Direct/Enhanced `dc1135bc`（merge `b65db5fb`，pipeline #482 8/8）。Enhanced 走
  `mainMixerNode.outputVolume`（mute 缓存当前值、regain 恢复 1.0）；Direct 因 output unit
  无公开 volume 参数（macOS SDK 下 `kAudioUnitParameters_Volume` 不存在，编译实证）改为
  渲染回调按 latch 帧级静默。StreamViewController 接线与 SettingsModel 均不变。
- `backgroundGamepad` —— **已收口**（commit `26d20062`，pipeline #434 = 8/8 success）。
  HID 6 个 controller-wire 入口 + MFi `updateFinished:` 同步加门；4 个焦点观察者对称
  （window/app resign 按 per-host pref 写 YES，window/app become 无条件恢复 NO）；
  默认 off 保留 shipped 行为；键盘 + 鼠标路径不挂新门。详见 §14 + baseline §15。

### 3.3 K1.2 marked text / 候选窗 / 输入法提交（依赖 K1.1 已收口）
- 实现已提交（MR 6 `5c0dbfa3`，见 §2）：`HIDLocalIME`（`MLLocalIMETextClient` + `MLLocalIMESession`）挂
  keyDown/keyUp/flagsChanged；`HIDIMECurrentInputSourceComposes` 走 TIS 公开属性；候选窗屏幕坐标；
  原始键码与文本所有权互斥；断流 uncapture 先 flush 再 end。验收契约以 §15 为准，真机取证待 owner 批 MR 后。
- 真机中文注入未验收；marked text、候选窗、输入法提交、长按重复均属 K1.2。
- 现状：没有接通的 `NSTextInputClient` 路径。仅回放 `insertText:` 不构成真实输入法验收。
- 下一实现须为默认关闭的本地输入法选项；使用公开 TIS 属性读取 API，不能把不透明输入源强转字典，不能按语言白名单判断组合输入法。
- 组合文本保存实际字符串、选区与屏幕坐标；提交、取消、焦点丢失、断流均需覆盖。原始键码与文本按物理按键保持所有权互斥；不能把提交文本中的换行全部删除后补一个 Enter。
- 触碰键盘接收路径——若 6 个键盘门禁脚本（keyboard-concurrency /
  keyboard-modifier-mapping / keyboard-shortcut-modifier / keyboard-source-quirk /
  keyboard-unicode-routing / held-modifier-keyboard-pair）任一无法转绿，**只保留 K1.1**，K1.2 关闭。

### 3.4 工具链 / 流程增量（与上述并行）
- 升级约束：将 M4.3/M4.4 的 `device_table` / `touch_events` / `diagnostics` 门禁**全部纳入 GitLab `audit:sources` job** 必跑项（部分已在 M4 收口时接入，复核有无遗漏）。
- 已知 CI 教训：reconfigure 后 nginx :80 → SSL-only，runner URL/tag 必须回读；Mac runner 短暂失联+macos tag 丢失会让 job 落到 Linux（swiftlint 缺失）。

## 4. 待真机验收（独立保留，不阻塞下一波代码）

> 真机验收不阻塞代码侧下一波；但每波必须保留 `hardware_validated=false` 标签。

1. 装 `build1959` 接入两块手柄（建议 PS5 + Xbox Series / 单只 Joy-Con + Pro Controller），开流并核诊断分类、会话驱动、通告状态、玩家编号。
2. `Sunshine` 与 `GFE` 双主机侧：虚拟手柄类型、按键图标、拔出时序、IMU/电量/触摸板事件。
3. 键盘 K1.1：主机端微信/浏览器输入法实测中文 + emoji + 全角字符 + 长按重复。
4. 全屏侧边栏参数化（E1）：单屏 + 双屏 + 全屏菜单栏遮挡场景。

## 5. 冻结项（不动）

- USB 真实重定向通道、Developer ID 公证 / 正式签名、自动更新 → README 边界表如实保留，不自行解冻。
- 设置页原生外观（macOS27 `NSSegmentedControl` + `role=.tabs`）+ 既有手感默认值 → 不可撬动。
- 90FPS 插帧稳定性、29ms 队列延迟 → 单独排期，不因对标作战自动解冻。

## 6. CICD 标准（每轮执行，不可降级）

1. 改代码 → `bash scripts/local-gates.sh`（默认快速，完整变异电池仅 `--all`）→ 0 failed，skip 逐项列名
2. 新行为 → 新增门控脚本（必须含 self-test，证明自己会失败）并接入 CI
3. `git -c user.email="codex-agent@homelab.local" -c user.name="Codex Agent" commit`
4. `git push gitlab <branch>`，创建指向受保护 main 的 MR；push 后等 30s+ 再查准确 SHA 对应 pipeline，全绿才算通过；失败修复后重推，不绕过
5. GitHub（opsbsligm）由 `publish-github` job 单向镜像，只读，不手推
6. 每波写一份 `moonlight-ci-evidence/<日期>-<主题>/release-verification.json`，记录 commit / pipeline / DMG / SHA256 / `hardware_validated` / mirror refs

## 7. 对标范围（持续维护，不缩水）

- 来源矩阵（逐格版本/验证日期/证据层级）：`docs/source-matrix-2026-10-25.md`。对象：`moonlight-qt`（上游客户端）/ `moonlight-common-c`（协议 fork @386e79c）/ `Sunshine` + 基地版（主机）。
- 竞品矩阵：`Citrix` 与 `Horizon`（分别评估；旧 ADMX 证据需核对归属）/ `Parsec`（无证据，不断言）/ `网易 UU 远程`（宣传面，手机赛道不与桌面客户端直接对照）/ `深信服 aDesk` / `锐捷云桌面`（如需新增列入"待调研"）。
- 每格区分：源码 / 官方资料 / 实测 / 宣传 / 未知；既有文档未覆盖的产品继续列为"待调研"，**不编造**已完成全面对标。

## 8. 关键文件（修改前必须先读）

| 用途 | 路径 |
| --- | --- |
| 标签页 UI（系统原生 tabs） | `Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift` |
| 帧节奏（已接入 VideoDecoderRenderer：6 处 `_pacer` 引用 + `MLFramePacerDelegate`，见 VideoDecoderRenderer.m:1546/1696/2124/3507/5952/6161/6209） | `Limelight/Stream/MLFramePacer.h/.m` |
| 真正生效的帧队列 | `Limelight/Stream/VideoDecoderRenderer.m`（desiredEnhancedDrawableDepth / desiredPendingFramesForDisplayRefreshRate） |
| 带宽追踪 | `Limelight/Stream/MLBandwidthTracker.h/.m` |
| 解码渲染核心 | `Limelight/Stream/VideoDecoderRenderer.m` |
| 串流控制栏 | `Limelight/macOS/ViewControllers/MLEdgeMenuUI.m` |
| 设置面板 | `Limelight/macOS/ViewControllers/` |
| USB 侧边状态 | `Limelight/Stream/USBMenuStatus.h` |
| 玻璃容器 | `Limelight/macOS/Views/GlassOverlayContainer.h/.m` |
| 快捷键 OSD | `Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m` |
| 控制器诊断 / HID | `Limelight/Input/HIDSupport+Inventory.m`、`Limelight/Input/MLControllerInventory.h/.m` |
| 诊断报告 | `Limelight/macOS/Helpers/DiagnosticsReportBuilder.h/.m` |
| 审计基线 | `scripts/analyzer-baseline.json` |
| GitLab 构建/镜像 | `.gitlab-ci.yml` |
| 镜像端补充审计 | `.github/workflows/build.yml` |
| 边缘栏手感常量 | `Limelight/macOS/ViewControllers/StreamViewController_Internal.h:100-162` |

## 9. 不可撬动的底层（与 `docs/baseline-2026-10-22.md` §1–§7 对齐）

- 唯一事实源 GitLab `http://172.16.130.6`（VM IP `172.16.130.252:8445`），project id 6。
- 提交身份固定 Codex Agent / codex-agent@homelab.local；不绕门禁。
- 设置页原生 `NSSegmentedControl` + `role=.tabs`（commit `00315f0f`）。
- 全屏侧边栏手感默认值：感应带 12pt / 驻留 0.12s / 收起 0.45s / 召唤宽限 2.5s / 甩动 700pt-0.25s / 把手 14-30-48pt / 点击余量 2pt；E1 只参数化其中三项，默认值 = 现常量。
- 协议诚实：未实现的能力不向主机通告；type-map ≠ 已通告；报告/UI 必须区分两者。
- 验证纪律：未真机一律 `hardware_validated=false`；"单手柄发包不变"必须用录制的逐字节对比证明；跳过的门禁逐项列名，skip 不算 pass。
- 新增设置项：默认 = 当前行为；UI 纯新增。
- 冻结项不自行解冻（USB 真重定向、Developer ID 公证/正式签名、自动更新）。

## 10. 历史计划（保留追溯；当前基点以上文 §1–§9 为准）

- 作战计划原文：`docs/campaign-plan-2026-10-20.md`
- 对标矩阵原文：`docs/competitive-polish-roadmap-2026-10-20.md`
- 输入映射证据：`docs/input-mapping-benchmark.md`、`docs/input-mapping-design.md`、`docs/input-mapping-review.md`

## 11. 下一步执行

（2026-10-25 刷新）**代码层里程碑 0.1→P2 已全部在 main**；在途 MR 5/6/7 待 owner 批，批准后 main 即含 K1.2 + SAS 门禁。

1. **owner 批 MR**（Web UI，顺序不限，建议 MR 7 先行、MR 6 次之、MR 5 收尾）；每 MR 合入后回读 main pipeline 全绿。
2. **真机验收矩阵**（不阻塞代码侧）：用户装新 DMG（build ≥ 1978）→ 串流 → 逐项取证：
   0.1 双手柄诊断分类 / 0.2 双手柄互不覆盖 / M1–M4 主机侧类型、震动、IMU、电量、触摸板 /
   K1.1 中文 + emoji / **K1.2 本地输入法组合（MR 6 合入后 build 上开 per-host 开关验 §15 契约）** /
   K2 SAS 拉起 / E1 单双屏边栏 / P2-1 绝对鼠标 / P2-2 断网退避与主机关闭 / P2-3a 三后端失焦静音 / P2-3b 后台手柄抑制。
3. **下一波代码**（若 owner 认可继续）：对标来源矩阵已补全（`docs/source-matrix-2026-10-25.md`）；其余 P2 对等项已全落地，无新增开工项；后续新增对标结论前先回矩阵钉版本。
4. 每波开发分支、MR、准确 SHA CI、实际审核者审批；审核未完成保留 MR，不代批。

## 12. 历史与现状的界限

历史 CI、DMG、应用安装版本与 refs 数量均注明原验证波次，可能随开发变化。当前交付必须重新读回准确 ref 的流水线与产物；跳过项不能算通过。硬件未验收继续保留 `hardware_validated=false`。

## 15. 本轮 review 与下一波验收契约（2026-10-24）

- 已撤下本轮未接入的 K1.2 草稿：存在输入源误判、组合范围丢失、候选窗坐标为零、提交函数缺输入准入门等问题。未发布，既有输入路径不变。
- 当前 §2 表示代码/历史 CI 状态；本轮未重新验证硬件、安装版本、DMG 哈希或全仓镜像，不将这些历史值作为当前验收结论。
- 首要交付：K1.2 默认关闭实验项，先建立真实方法回放与失败变异，再接生产入口。覆盖英文/游戏按键不变、组合提交/取消、AttributedString、重复键、同键切换路由、失焦/断流取消、候选窗屏幕坐标。
- 第二交付：统一真机验收矩阵：双控制器身份与隔离、主机能力通告/反馈、中文提交、全屏单双屏边栏、三音频后端焦点恢复、断网退避与主机关闭。
- 对标补证：moonlight-qt 与本项目源码上游分别列版本；Sunshine 与基地版明确仓库身份；Parsec、UU、Horizon、Citrix、深信服、锐捷分别列来源/平台/版本/验证日期/未知项。旧矩阵保留为历史，不把宣传升级为实测。
- AI Native 定位：诊断数据结构化、关键事件可订阅、验证结果回流知识库、自然语言动作可追溯；Agent-first OS 与 Agent Swarm 先作架构探索，不引入常驻代理或改变串流热路径。
- 发布边界：默认行为、原生设置 tabs、已验收边栏手感、协议能力诚实及冻结项均保持；每波交付准确 SHA、MR、CI、跳过清单与 `hardware_validated`。
