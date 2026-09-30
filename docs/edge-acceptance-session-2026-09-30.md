# 边缘控制栏实机验收会话 — 2026-09-30（进行中）

## 会话结论（截至本轮）
- HOME-PC 失联已修复并重新配对（见 host-connection-incident-2026-09-30.md），串流
  1920x1080@180 HEVC 成功建立，延迟 ~8ms。
- 验收首跑 FAIL "hover lights the handle"，**根因不是 app**：
  1. 检测器盲区已修（胶囊把手外缘抗锯齿暗像素，允许 ≤4px gap 起步；自测 6/6）。
  2. 随后发现验收环境本身失效：macOS 进入锁屏/显示器睡眠
     （app 日志 `currentSpace=1`、`window-resigned-key`、CGWindowList 仍有
     56×56 把手窗口但截屏全黑）。锁屏后所有像素判据均不可信。
- 心跳自动化 home-pc-gamestream-recovery-watch 已删除（判据过期，恢复已人工闭环）。

## 本轮修复的工具缺陷（scripts/，均在锁屏前完成并自测）
1. `shot()`：`screencapture -R` 在 Space/全屏动画期间瞬态失败
   （"could not create image from rect"）会导致整跑中断。改为全屏抓取+裁剪，
   原点 0,0 时像素等价。
2. helper `key <code> <flags>` 预设 flags 的注入不可靠：app 侧事件被 HID 层按
   物理键盘状态重建 flags。新增 `combo <keyCode>`：control down → option down
   （flags 真实累积）→ key down/up → 逆序释放。
   **同时发现脚本原有 `key 8 0x180000` 是 ⌘⌥C 的笔误**（ctrl+option 应为
   0xC0000），这就是"快捷键 CHECK 无面板"的直接原因——此前对该入口的怀疑
   部分是测试工具的错。
3. helper `mod` 子命令参数错位（args[1]/[2] 应为 args[2]/[3]），已修；
   ⇧⌥ 注入路径此前实际会把子命令名当键码解析失败。
4. 新增 `pos` 子命令：回读注入后的指针位置，move 后实测粘滞（已验证）。

## 已确认事实（可复用）
- 把手窗口 CGWindow 56×56 @(1886,512)，把手本体 14pt、贴右缘内 2px、中心 y≈540。
- 基线判据：idle ≤18pt、hover 增量 ≥6pt 且 ≥22pt；实测 idle=16pt。
- 串流会话在锁屏后仍存活（音频 underrun 持续、窗口列表完整）；app 对
  resign-key/app-resigned 的 uncapture 处理有日志（MUC003/MUC006，行为正确）。

## 环境更新（18:45）
- 权威锁屏判据：helper `locked` 子命令（CGSessionCopyCurrentDictionary），
  前台 App 启发式在锁屏+全屏串流共屏时会说谎。验收脚本加了环境门控：锁屏时
  直接退出并说明"environment gate, not an app failure"。
- 完整解释链：远端 HOME-PC console 已锁屏（LogonUI.exe 存活、屏保开启），
  Sunshine 对锁屏桌面推黑帧；本机同时 30s 熄屏（pmset 日志）。所以"画面全黑、
  把手不可见"是双重环境问题，串流会话与把手窗口全程在位。
- 心跳 automation 已改用 locked 判据，解锁后自动：caffeinate 包裹 → 唤醒远端
  显示 → 通过串流通道键入远端密码 → 跑 30 循环矩阵。
- 远端显示器策略：monitor-timeout-ac 已设 0（不再自动熄灭）。
- 远端 console 密码键入模板（键码→shift 按需）：
  `python3 - <<'PY' … for ch in "Xuesecanyang110": helper key <code> <flags>; helper key 36 0`（本文件历史版本，或见本仓库本 commit 前文说明）。

## 环境更新（18:20）
- 注入密码两次均短暂解锁（前台回到 app），但随即再次锁屏（用户设置了短锁屏
  + 远端/本机显示器睡眠 30 分钟）。串流会话全程存活（音频 underrun 持续、
  CGWindow 56×56 把手窗口始终在位）——app 生命周期行为正确，锁屏期间
  resign-key/uncapture 路径均有日志且无异常。
- 已挂心跳 automation：屏幕点亮解锁后自动重跑 30 循环验收并报告。
- CI run 36700910217（62d3c79b）运行中，另有独立心跳盯结果。

## 环境恢复后的下一步（阻塞项：Mac 处于锁屏，需用户解锁）
1. 重跑 `python3 scripts/edge-handle-live-acceptance.py --loops 30 --edge right
   --mode free --yes`；先看模式（本机记录为全屏锁定鼠标，则走 --mode locked +
   combo 8 入口）。
2. CHECK 项改用 open/close 帧 diff + 右缘浅色宽区判据（面板几何已知的部分可自动判）。
3. 四边停靠、菜单打开/关闭、按住经过边缘（helper down/up 已有）、失焦恢复。
4. 纯修饰键 ⇧⌥ 释放、真实硬件、多显示器：保持"尚未验收"直到人工确认。

## 矩阵（当前）
| 项 | 状态 |
|---|---|
| 把手基线可见（idle 16pt） | 实机通过（锁屏前） |
| 悬停点亮 ×30 | 未验证（环境中断；上一 FAIL 已定位为工具问题） |
| Ctrl+Option+C 开合 | 未验证（脚本笔误已修，待重跑） |
| ⇧⌥ 释放（注入） | 未验证（helper mod 已修，待重跑） |
| ⇧⌥ 释放（硬件） | 尚未验收 |
| 四边/拖动/菜单/失焦/重连 | 尚未验收 |
| 多显示器 | 尚未验收 |
