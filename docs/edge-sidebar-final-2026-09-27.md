# 侧边栏最终修复轮（2026-09-27 深夜 → 09-28）

## 现场根因证据（非推断）

- 21:35 部署版（374a36e0）实机日志（pid=10748，21:45–21:46）：游戏锁定模式整场
  capture=1；零条 Edge sensor 采样/悬停/唤出记录；uncapture 仅发生在 perform-close。
  → 锁定模式下锁时感应对用户完全不可用，与设计一致（上一轮直接删除了锁定态入口，
  只留快捷键），用户实际得到的是“完全不能触发”。
- Shift+Option 释放（MUC103）在该场日志中同样零记录：入口存在但从未经过实机验证。
- 当前主机实际配置逐项核对（std.skyhua.MoonlightMac2，非磁盘 plist 而是 cfprefsd）：
  mouseMode=0（游戏锁定）、releaseMouseCapture=Shift+Option(modifierOnly,655360)、
  openControlCenter=Ctrl+Option+C。未修改任何用户配置。

## 本轮改动（三个入口 + 一个可点击面）

1. 锁定模式滑拽手势（新增）：朝停靠边重复“推-回”3 次（每段净位移 ≥48pt、
   回程 ≥24pt、总窗口 1200ms、按住按键即作废、单调瞄准/慢速漂移/噪声抖动均不计）。
   只读原始位移，绝不推断远端光标位置；触发=临时释放+展开控制栏（450ms 宽限沿用）。
2. 自由/已释放态悬停带 4pt→12pt（×56pt 把手段）：旧 4pt 是“缩小到难以命中”；
   24pt 旧回归仍被负对照钉死（8..16pt 区间守卫）。
3. 折叠把手点击展开：本地指针权威时点击可见把手=展开控制栏，按下/抬起成对消费，
   不漏击到主机；游戏锁定态（点击位置恒为中心）行为不变。
4. 限频 1s 的 `Edge sensor sample` DEBUG 采样日志恢复，下轮现场报告可直接判读。

状态机不变量沿用上一轮：MLEdgeMenuPhase 独占；滑拽状态单一族累加器，
所有捕获/模式/生命周期转移统一 resetEdgePushGesture 清理；无新增定时器。

## 验证状态

- 自动化：edge-sensor-summon-tests --self-test 全绿（含滑拽四边触发、30 轮重复、
   5 项负对照、12pt 带守卫、把手点击消费）；键鼠回归 45/45（edge-sidebar-regression.json）；
   零警告审计、liquid-glass 审计 0 违规、git diff --check 干净；Release 构建成功。
- 已部署：0dda4918d98e0a1e5a5dc2d3b40d28cc06c082bec213c3788b0f1dc211c2e0ea
  （旧 374a36e0 在 ~/.Trash，edge-sidebar-install-result.json）。
- 实机验收：进行中，逐项结果见本文件末尾矩阵；未通过项回到诊断。

## 下一步

- 实机注入验证：滑拽×30、Ctrl+Option+C、Shift+Option 释放、释放后 12pt 悬停、
  把手点击展开、收起回收；外置鼠标/多显示器/纯手势手感=用户验收项。
