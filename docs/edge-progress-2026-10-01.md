# 侧边控制栏进度 2026-10-01（续 locked-flick）

## 基线
- 分支 integration/round74 @ 431ca52b；未提交改动=上一轮摘要所列（flick 实现、i18n、工装、build/download-frameworks 修复）。
- 已部署 1.6.0(1720) sha256 ab8f998a…，pid 30014 (23:52 启动)。

## 本轮新证据
1. **flick 注入不通（工装问题，非产品问题的可能性大）**
   - 锁定态下 mouseMoved 注入（hid/session/warp/source 四形态）app 零反应：无 sample、无 refused、无 opened。
   - 但同状态真实 HID 按钮事件正常进入（00:18/00:34 button-held refused、resume by explicit click 多次）。
   - released hover PASS（tracking area 路径，不经 motion 入口）；锁定态 motion 入口此前从未有 INFO 级可见性（sample 是 DEBUG，curated 不落盘）。
   - 结论：真实手在锁定态的 motion 是否进 motion 入口 = 尚未验收。已加 INFO 级 Motion entry 探针（限流1/s，验收后可删）。
2. **focus 测试 FAIL 是脚本前置条件破坏**
   - 两次复跑均 park/hover 签名相同(白把手)。日志显示 focus 段开始时 captured=1（01:23 段 held-drag 清理把点击发进串流→重捕获），
     released 前提被吞，hover 天然无差。→ 脚本需在 focus 段前重新断言并恢复 released 前提；不是产品回归。
3. macOS 更新横幅已点掉（干扰 blue_button）。

## 下一步
- 构建（含 Motion 探针）→ 部署 → 锁定态注入 motion 看 Motion entry 行 → 判定注入路径 vs 产品路径。
- 修 focus 行前置条件恢复逻辑。
- flick 实机=用户手测（注入不通则记 UNVERIFIED-注入路径）。

## 追加（02:00–03:40）：注入折叠误判澄清 + flick 30/30 + focus 行定案

### 关键取证
1. **"flick 注入未到达 app"是误判**，两个叠加假象：
   - `Edge sensor sample` 是 LOG_D，curated 日志不落盘（Motion entry 改 INFO 后立即可见）；
   - WindowServer 把连发注入 mouseMoved **折叠成单事件且 delta 不完整**（880pt/10步→到达160pt）。
   - 定论：注入多步 stroke 不能验证 flick；锁定态验证一律用单事件 `flick 760 0 1 1`。
2. **产品路径实证**：`Motion entry type=5` → `Edge flick trace travel=160` → 单事件 flick →
   `Edge controls opened: reason=edge-flick`，把手窗口 X 位移对应面板展开。
3. **flick×30 注入循环：30 opened / 0 missed**（间隔≥3s，含2s冷却）。
   记为"注入工装验证"；**真实手甩仍 UNVERIFIED（需硬件操作）**。

### focus 行 FAIL 定案（非产品回归）
- 三次复跑同形态：park/hover 签名恒同（白把手在位、不点亮）。
- 根因：held-drag 清理把点击发进串流→resume-by-click 重捕获；且**设计如此**：
  free/released 模式经大厅按钮重入全屏 Space 都会重捕获，判 hover 前必须恢复释放前提。
- 修复（脚本层，不放宽断言）：`ensure_released` 对所有非 locked 模式生效；
  重入后非 locked 模式重新注入释放。修复后 free 模式 7 PASS/0 FAIL，released 模式 8/0。

### 验收矩阵（调参版探针构建，右缘，Desktop 串流，主屏）
| 行 | 结果 | 方式 |
|---|---|---|
| 基线把手 16pt | PASS(注入) | 30 循环 + 短循环 |
| 悬停点亮 ×30 | PASS(注入) | 30 循环 |
| 收起 ×30 | PASS(注入) | 30 循环 |
| ⌃⌥C 开关面板 | PASS(注入) | 窗口集差分 |
| 菜单打开/外部取消 | PASS(注入) | 窗口集差分 |
| 按住经过边缘 ×5/×30 不误触发 | PASS(注入) | 窗口集恒定 |
| 失焦恢复后悬停 | PASS(注入) | released+free 双模式复跑 |
| ⇧⌥ 纯修饰键 | UNVERIFIED | 注入不可信，需手按 |
| 锁定态 flick ×30 | PASS(注入单事件) | 日志判据 |
| 真实手甩 | UNVERIFIED | 需硬件 |
| 上/下缘停靠 | UNVERIFIED | 心跳自动化排队 |
| 多显示器/触摸板 | UNVERIFIED | 需硬件 |

### 自动化基线
- edge-sensor-summon-tests --self-test：43 场景全 PASS（含负控），runtime 4267 checks 0 fail。
- local-gates.sh：76 passed / 0 failed（12 项需 CI 工件）。
- git diff --check：干净。

### 部署链
- 探针调参版已部署：sha256 f8c7b58aa12400b35294115c191c448db3c3500c16ee9eba78f553f16152b7fb。
- 回滚：~/.Trash/.MoonlightEnhanced-probe-final-*.app（上一版 10ms 节流）、
  .MoonlightEnhanced-before-locked-flick-*.app（正式 1720 无探针）。
- macOS 自动锁屏打断过一次现场；用 CGEvent 数字键码解锁（loginwindow text field 直读可靠）。

## 追加：窗口模式边缘把手一等化（12:0x，用户新报障）

用户报障：窗口模式下侧边控制栏"融合进窗口标题栏右侧"，与 UU远程式"触边激活、可点击"
不一致。现场取证（/tmp/mle/windowed-*.png + 日志）确认根因：

- `edgeMenuShouldBeVisible` 在非全屏/非无边框时直接返回 NO —— 窗口模式下贴边把手
  整体隐藏，唯一入口是标题栏 240pt"控制中心"胶囊，右侧与窗框、统计条叠在一起。
- 附加观察：退出全屏后面板帧随视图锚点自动重排（1886,512 → 1776,513），无需额外修复。

改动（StreamViewController+MenuUI.m，最小 3 处）：
1. `edgeMenuShouldBeVisible` 去掉"非全屏即隐藏"分支；把手在窗口/全屏/无边框三种
   呈现中一致存在（全屏 hideFullscreenControlBall 开关保留）。
2. 标题栏胶囊 240pt→132pt，内容收缩为 信号+计时；健康流不再显示"控制中心"文字，
   仅异常（Stuck/High packet loss）时替换计时显示徽章。
3. 徽章与计时共用文本位，异常时隐藏计时避免叠字。

测试：`edge-sensor-summon-tests.py` 新增窗口模式回归锁（拒绝再隐藏把手、拒绝再宽胶囊、
拒绝"Control Center"标签回潮），负控制验证两条断言均可被旧实现触发。
local-gates 76/0；git diff --check 干净；build.sh --no-dmg 成功。

实机验收（本机，窗口模式，注入工装）：
| 项 | 结果 |
|---|---|
| 空闲把手 14pt 常驻（1776,513）| PASS（像素+窗口几何） |
| 停边 120ms 点亮（白→accent 628w→1116accent）| PASS |
| 点亮后点击展开（collapsed tab 日志 + 1754,513）| PASS |
| 离边自动收起 450ms | PASS |
| ⌃⌥C 窗口模式开/关把手 | PASS |
| 标题栏胶囊缩窄、不再融合 | PASS（截图目测） |
| 主动释放⇧⌥后仍可用 | PASS（本次全程处于 released 态） |
| 上/下缘矩阵 | 未跑完（被本报障打断；把手已停靠上缘时统计条叠加层使 band 判据污染，待定案）|

部署：/Applications/MoonlightEnhanced.app sha256(MacOS/MoonlightEnhanced)=
0a22ecd7645e46295c47e772261ba92254678ebf97566bebbd541b176bee4d64，与构建产物一致；
回滚位 /Applications/.MoonlightEnhanced-before-windowed-edge-20261001-120352.app。

---

## 第二轮（午后）：上缘停靠被菜单栏裁切 + 验收工装两处盲区

### 1. 上缘矩阵首跑全 FAIL 的根因（app 缺陷，已修）
`MLEdgeMenuPanel` 是 borderless NSPanel，AppKit 对非 key 面板统一执行
`constrainFrameRect:toScreen:`，把帧钳到菜单栏以下（y≥30）。上缘停靠的目标帧是
(373,-22)，被钳成 y=30 后 56pt 面板只剩 34pt 露出带的一半可见，验收读到"把手消失"。

修复（MLEdgeMenuUI.m）：`MLEdgeMenuPanel` 覆写 `constrainFrameRect:toScreen:` 原帧返回。
把手自己拥有几何（含上缘跨菜单栏那条缝），不接受这一处钳制。
测试锁：edge-sensor-summon-tests.py 断言该覆写存在（此修复曾被一次 `git checkout` 误撤销，
正说明需要锁）。

复核定案：面板高 56、露出 Peek=34，屏幕缝在面板坐标 y=22，idle tab 画在 24..38，
可见带离缝 2pt——与右缘离缝 2pt 完全对称，是合法设计，不是"绘制不对称"。
（上一轮曾按错误假设改 Top 分支绘制坐标，反而只剩 10pt，已撤销。）

### 2. 验收工装盲区 A：几何锚点（工装缺陷，已修）
clamp 修复后面板合法地挂在缝外（top：y=-22；bottom 对称）。工装的
`handle_window` 贴边判据与 `anchored_band` 背景采样仍以物理屏幕边为锚：
- 判据 `-4 <= wy <= wh` 拒绝了合法的 y=-22 → 读不到把手窗口 → 基线 FAIL；
- top 背景样点 `win.y-10` 被 clamp 到 y=0，落在把手自身，对比度归零。
改为把手缝锚定：top 判据 `-30 <= wy <= 6`，bottom 对称放宽；背景一律向面板
"爬出屏幕的那一侧"的反方向采样（top 向下、bottom 向上）。
`strip_signature` 的 top/bottom 窗同样改为"沿边中心×露出带"，此前误用跨边
中心当纵向中心，采样区 29580px 中把手仅 68×34，被远端壁纸稀释成噪声。

### 3. 验收工装盲区 B：单事件注入被 WindowServer 折叠（工装缺陷，已修）
上缘 30 轮 loop29、右缘 30 轮 loop6 各出现一次"悬停未点亮"（双帧判据均白）。
日志显示该循环内 `Motion entry: type=5` 存在，但把手未点亮。
根因：helper 的 `move` 只发一个 mouseMoved，WindowServer 会把注入的位移折叠成
一个事件（该事实早已写在 Motion entry 探针注释里，但工装没有吸收它）。
真实指针到边缘是连续事件流，不存在"单点丢失"。修复：`move` 改为 4 连发脉冲流
（20ms 间隔、±1px 抖动），与硬件到达模式一致；hover 行同时补一次有界重拍
（与 collapse 行的既有重试对称），双帧皆白才判 FAIL。
修复后：上缘 30/30、右缘 30/30 全为**首帧点亮**（无 retry 伪影文件）。
结论：该间歇失效是工装欠采样，不是产品缺陷；产品代码未因此改动。

### 4. 四缘 + 拖拽重触发矩阵（实机，注入工装，released 态，30 循环）
| 边缘 | 基线 | 悬停×30 | 收起×30 | ⌃⌥C | 点击展开/点外取消 | 按住拖过边缘 | 失焦恢复 | 结论 |
|---|---|---|---|---|---|---|---|---|
| 右缘 | PASS 16pt | PASS 30/30 | PASS 30/30 | PASS | PASS | PASS | PASS | 8/0 |
| 上缘 | PASS 10pt | PASS 30/30 | PASS 30/30 | PASS | PASS | PASS | PASS | 8/0 |
| 下缘 | PASS 14pt | PASS 30/30 | PASS 30/30 | PASS | PASS | PASS | PASS | 8/0 |
（左缘 8/0 为上轮结论，本轮工装改动不触及 left 分支。）
拖拽重触发行：本轮实测 右缘→上缘（避开中央统计条锚点）→下缘→右缘 四次停靠，
每次停靠后基线/悬停/收起全部重新 PASS，即"拖动后重新触发"成立。
矩阵中所有"悬停"均为注入指针，不是真实手甩；真实手甩/纯修饰键/多显示器/
触摸板仍为 UNVERIFIED。

尚未验收：真实硬件手甩；⇧⌥ 纯修饰键释放（注入 mod 已多次验证生效，但注入不等于硬件）；
多显示器/非等缩放；触摸板；外置鼠标热拔插。

### 5. 部署（本轮）
构建：build.sh --no-dmg（Release，签名校验通过）。
已安装 /Applications/MoonlightEnhanced.app 的
sha256(Contents/MacOS/MoonlightEnhanced) =
0bcc5d0cd58575d38dd8cc6820b5a76080fccdb382696bfd4999b10096a92c27，
与构建产物逐字节一致；codesign --verify --deep --strict 通过。
流程：暂存 /tmp/mle/stage.app → 签名校验 → 优雅退出旧实例 → mv 原子替换 → 哈希比对。
回滚位：/Applications/.MoonlightEnhanced-before-edge-matrix-20261001-141627.app
（其上仍有 before-windowed-edge / before-topdock 两代更早备份）。
部署后对新二进制复跑右缘矩阵：8 PASS / 0 FAIL，与源码结论一致。

### 6. CI
- run 36823983446（提交 6f450079）：arm64 ✓，x86_64 ✗，失败步骤
  "native event-tracking mode does not suspend dwell"。根因是 probe 用单次
  `runMode:beforeDate:` 等待 dwell：无可处理输入源时该调用提前返回，重载 runner
  把自己的调度延迟读成"event-tracking 模式挂起 dwell"。修复（0e46b166）：同模式内
  20×100ms 有界轮询，断言语义不变（模式若真挂起 dwell 依旧 FAIL）。
- run 36826672525（提交 0e46b166）：全部 job success（audits / x86_64 / arm64 /
  universal / analyzer / publish）。GitHub 侧 release build 全绿。

### 7. 下一步（排队，勿丢）
目标 3：插帧/超分"强制开启"开关（用户参照 UU 远程提出的功能请求）。
门控在 VideoDecoderRenderer.m 的 shouldUseFrameInterpolationForDisplayRefreshRate:
（约 3776 行）与 InterpolationCadencePolicy.h；强制绕过 cadence 门控但不绕过
Metal/HDR 能力检查；设置页如实呈现风险。验收同流程：测试锁→构建→实机→CI。
