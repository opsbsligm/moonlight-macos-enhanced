# Moonlight macOS Enhanced — 目标模式提示词（2026-10-24 P2-1 收口后刷新）

> 用途：续跑本仓库对标作战的"目标模式"提示词。所有续接会话先读 AGENTS.md、`docs/baseline-2026-10-22.md`、`docs/campaign-plan-2026-10-20.md`、本文件和 `docs/competitive-polish-roadmap-2026-10-20.md`，再核对 Git、源码、准确 SHA 的流水线。

## 1. 当前基点（截至 2026-10-24 P2-1 收口后）

- 代码基点 main = `9426623b`（P2-1：自由鼠标相对位移改走 `LiSendMouseMoveAsMousePositionEventCtx`，开关默认关）。
- pipeline #430 = 8/8 success；evidence `moonlight-ci-evidence/20261024-p2-1-relative-mouse-as-absolute/`；本地门禁 95 通过 / 0 失败 / 15 跳过（artifact-only）。
- 最新 DMG：`build1968`（P2-1, arm64, 8 284 337 字节, sha256 `89d557aa4a8afbd5bf652befdcc9e084eefcb0c2fec53c1d2a2dce97d157b3ac`，`hdiutil verify` VALID，`codesign --verify --deep --strict` 通过，ad hoc 签名，Developer ID 公证仍未验收）。用户日常 `/Applications/MoonlightEnhanced.app` 仍是 **build1926**，真机验收前需装新 DMG。
- 镜像 60 refs 与 GitLab 完全一致；不绕过门禁。
- `hardware_validated=false` 保留：0.2/M1/M2/M3/M4/K1.1/E1/P2-1 全是代码层完成 + 真机待取证。

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

## 3. 待开工（按优先级，不依赖真机排期）

> 所有未开工项必须遵守：默认值 = 当前行为、UI 纯新增、门控先证明自己会失败再放开。

### 3.1 K2 Ctrl+Alt+Del（无依赖，可并行）
- 扩展 scancode 0x8000 路径已在用；新增月亮动作 `sendCtrlAltDel`，走现有扩展 scancode。
- 先真机验证 Sunshine / GFE 主机能否拉起 SAS；拉不起则降级为"提示用户用主机端工具"，**不虚报**。
- 门控：scancode 0x8000 路径 + 快捷键注册 + 月亮动作配置的真谓词回放；至少 3 项行为变异（无 CAS 走 / 误发送到非 SAS / 与现有 Ctrl+Alt+Tab 等组合冲突）。

### 3.2 P2 对等补齐（各自独立小提交，可与 K2 并行）
1. ~~`LiSendMouseMoveAsMousePositionEvent`~~ —— 已落地于 `9426623b`（见 §2）。
2. **重连退避状态机**：现有 5 种触发点统一退避（1s/3s/9s 最多 N 次）+ "主机确认消失即停"判据；重连期间输入入队上限保留。
3. **qt 对等项打包**：`muteOnFocusLoss` / `backgroundGamepad`（失焦时手柄继续/暂停发事件）/ `playAudioOnHost` UI 开关（协议参数已在 launch URL），每项独立开关、默认维持现行为。
4. **桌面档绝对鼠标默认关**（已写明：旧游戏兼容场景别开）。

### 3.3 K1.2 marked text / 候选窗 / 输入法提交（依赖 K1.1 已收口）
- 真机中文注入未验收；marked text、候选窗、输入法提交、长按重复均属 K1.2。
- 触碰键盘接收路径——若 17 个键盘门禁任一无法转绿，**只保留 K1.1**，K1.2 关闭。

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
4. `git push gitlab main`（https://172.16.130.252:8445/moonlight/moonlight-macos-enhanced.git）；push 后等 30s+ 再查准确 SHA 对应 pipeline，全绿才算通过；失败修复后重推，不绕过
5. GitHub（opsbsligm）由 `publish-github` job 单向镜像，只读，不手推
6. 每波写一份 `moonlight-ci-evidence/<日期>-<主题>/release-verification.json`，记录 commit / pipeline / DMG / SHA256 / `hardware_validated` / mirror refs

## 7. 对标范围（持续维护，不缩水）

- 来源矩阵：`moonlight-qt`（上游客户端）/ `moonlight-common-c`（协议 fork @386e79c）/ `Sunshine` + 基地版（主机）。
- 竞品矩阵：`Citrix Horizon`（ADMX 证据）/ `Parsec`（无证据，不断言）/ `网易 UU 远程`（宣传面，手机赛道不与桌面客户端直接对照）/ `深信服 aDesk` / `锐捷云桌面`（如需新增列入"待调研"）。
- 每格区分：源码 / 官方资料 / 实测 / 宣传 / 未知；既有文档未覆盖的产品继续列为"待调研"，**不编造**已完成全面对标。

## 8. 关键文件（修改前必须先读）

| 用途 | 路径 |
| --- | --- |
| 标签页 UI（系统原生 tabs） | `Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift` |
| 帧节奏（待接入主循环） | `Limelight/Stream/MLFramePacer.h/.m` |
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

## 11. 下一步执行（按本文件 §3 顺序推进）

下一波开工顺序：P2-1 (`9426623b`) 已落地，**P2-3 qt 对等项打包**（muteOnFocusLoss / backgroundGamepad / playAudioOnHost，各自独立小提交，默认关）可立即推进；**K2 Ctrl+Alt+Del** 仍要用户先在 build1968+ 真机验证 Sunshine / GFE 主机侧 SAS 能否拉起才能开 commit（拉不起就降级为提示，不虚报）。P2-2 重连退避与 K1.2 marked text 排第二波。每波按 §6 CICD 标准交付，evidence JSON 写齐 `hardware_validated=false` 与 mirror refs。

---

## 12. 本轮已落地的非代码工作（2026-10-23 现场刷新）

- `docs/baseline-2026-10-22.md` §10 增补：E1/K1.1 收口（v3 核验增量，硬件验证仍 `false`）。
- `docs/goal-mode-prompt.md` 整体刷新到当前 main = `622132b3` 基点；§3 / §11 明确下一波优先项。
- 对标矩阵与 roadmap 未动（P0/P1/P2 仍成立），已在 §7 显式列出维护边界。

## 13. 本轮未落地的代码工作（等待用户/真机配合）

按 AGENTS.md "硬件验证前不写成已完成" 原则，以下必须在用户确认协议可行性后再开 commit：

- **K2 Ctrl+Alt+Del**：扩展 scancode `0x8000` 路径已在 HIDSupport.m 使用（0x8014 等），但 **Sunshine / GFE 主机侧对 `Ctrl+Alt+Del` 三键同按的 SAS 拉起行为未经实测**。先要用户配合在真机一次：装 build1959 → 串流 → 用本地键盘直接发 "Ctrl+Alt+Del" 三键 → 主机侧是否拉起 SAS？若拉起，K2 直接做月亮动作 `sendCtrlAltDel`；若拉不起，降级为"提示用户用主机端工具"，不虚报。
- **P2-1 / P2-3**：纯代码、不依赖真机，下一波可直接开 commit。但建议先做 P2-1（单提交、单门控）；P2-3（3 个独立 UI 开关）拆三个独立 commit，避免单 PR 跨度过大。
- **P2-2 重连退避**：依赖现有 Diagnostics / Connection.m 的退避点位识别，可在 P2-1 / P2-3 收口后并行开工。
- **K1.2 marked text**：碰键盘接收路径，碰前必须重跑 17 个键盘门禁；任一红即整段关闭。

---

## 14. 本轮（2026-10-24）已落地的代码工作

- **P2-1 自由鼠标走绝对坐标 wire path**：commit `9426623b`，pipeline #430 = 8/8 success；
  谓词 `HIDShouldRouteRelativeAsAbsolute`（`Limelight/Input/HIDSupport_Internal.h:851`）
  三条件 = 设置开关 + `mouseMode == "remote"` + 5 秒内有有效绝对参考；UI 仅在 remote
  模式下显示，默认 false 完全保留旧路径。门禁 `scripts/relative-mouse-as-absolute-tests.py`（24 正向 + 4 行为变异 + 4 self-test 植陷），constraints-audit self-test 段调用本
  门禁的 `--self-test`。详见 `docs/baseline-2026-10-22.md` §13。
- 真机侧仍待：主机侧（Sunshine / GFE）连续绝对跟随、首次无参考不跳屏幕中心、
  锁定模式 / 手柄鼠标仍走相对包、窗口化 / 无边框桌面档主机跟随。
  `hardware_validated=false` 不变。
