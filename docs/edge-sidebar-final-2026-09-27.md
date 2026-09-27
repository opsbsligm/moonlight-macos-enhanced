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

## 09-28 上午补充：事件源与坐标审查（锁屏阻塞期间的独立复核）

针对"测试通过但用户失败"的历史教训，逐项验证了生产事件链而非再堆断言：

1. **锁定态滑拽的事件源 = 游戏鼠标位移的生产路径本身。** 锁定后
   `CGAssociateMouseAndMouseCursorPosition(NO)` 冻结系统光标，但 HID 位移仍以
   `mouseMoved:` NSEvent 送达 VC 并经 `handleMouseMotionEvent:` 派发到远端
   （玩家游戏操作一直有效即为长期实证）。滑拽在同一入口、同一 event 上读取
   `deltaX/deltaY`，位于 HID 转发之前，事件可得性与游戏鼠标等价。手势绝不使用
   locationInWindow（锁定时恒为 warp 中心），坐标盲区排除。
2. **`acceptsMouseMovedEvents` 条件与控件可见性一致：** 锁定、主动释放、控制栏
   持指针、全屏/无边框+感应开启时为 YES；普通窗口模式为 NO——与"折叠把手仅在
   全屏/无边框显示"的既有设计一致（窗口模式有原生菜单栏），不属失控开关。
3. **`resetEdgeSensorPointerState`（含 120ms 位移忽略）只在转移点调用：** 新会话
   放置、鼠标模式切换、capture 变更、视图生命周期；逐事件路径不重置，无持续忽略。
4. **部署后现场证据缺口：** 新 hash 0dda4918 部署至今日志仅有 Discovery 心跳，
   无串流会话 → 尚无 `Edge sensor sample: locked=1` 现场记录；恢复的 1s 限频采样
   日志就是为下一场串流准备的可判读证据。

## 验收矩阵（09-28 上午；标记口径：实机通过 / 自动通过 / 未验证 / 失败）

| 项目 | 状态 | 依据 |
|---|---|---|
| 滑拽手势四边触发/30 轮重复/负对照（15 项） | 自动通过 | probe 在生产方法上执行，非替身实现 |
| 12pt 悬停带 + 8..16pt 区间守卫 | 自动通过 | summon-tests 守卫 |
| 把手点击展开+按下/抬起成对消费 | 自动通过 | wire 断言（不漏击到主机） |
| 键鼠全量回归 45/45 | 自动通过 | edge-sidebar-regression.json |
| Release 构建+全量重签+原子部署哈希核对 | 实机通过 | install-result.json（安装环节为真实操作） |
| 锁定态真实鼠标滑拽手感 | 未验证 | 需真实 HID；cua 无法合成无按键滑拽 |
| Shift+Option 主动释放 | 未验证 | 纯修饰键无法经 cua 注入（工具限制，冒充实机被禁止） |
| Ctrl+Option+C 控制中心 ×30 | 未验证 | 实机验收被锁屏阻塞（"The Mac is locked"） |
| 四边停靠拖动/快速进出/菜单嵌套/断线重连 | 未验证 | 同上，解锁后按本矩阵逐项执行 |
| 窗口大小变化/全屏切换/失焦恢复 | 未验证 | 同上 |
| 外置鼠标/触摸板/多显示器 | 未验证 | 需用户在场硬件配合 |
| 120/180 FPS 声称 | 不宣称 | 无性能测量，禁止虚假声明 |

## 当前状态与阻塞

- 代码已提交：5347660（feat(edge): make the stream control dock summonable again），
  已推送 origin/integration/round74（用户 fork）。子模块 moonlight-common-c 的
  3 个输入队列遗留文件保持未提交（其 origin 为不可推的上游 skyhua0224）。
- 阻塞：实机验收需解锁 Mac + 用户在场配合真实鼠标/多显示器。

## 09-28 补充二：事件源实证与安装产物核验

1. **锁定态事件源获得直接日志实证。** 9-27 19:34 旧版会话（pid=64920，
   `captured=1 remote=0` 游戏锁定）存在连续的 `Edge sensor sample` 记录：
   `native=(960,540)` 恒为 warp 中心，但事件持续到达且 `delta` 携带真实位移
   （如 `delta=(-2,-11)`、`(3,-3)`）。证明 `CGAssociateMouseAndMouseCursorPosition(NO)`
   之后 `mouseMoved` 仍派发到 VC —— 滑拽手势的锁事件假设不再依赖推断。
   该旧版同时在锁定态用位移积分虚构 `point`（如 1030,212），正是被本轮设计
   禁止、且历史上“误触/失效”抱怨的可疑来源；新版在锁定时明确不产 point。
2. **安装产物核验：** `/Applications/MoonlightEnhanced.app` 主二进制 SHA-256 =
   0dda4918…e0ea（与 install-result.json 一致）；内含
   `edge-sensor-push`、`Edge sensor sample: locked=`、
   `Edge controls opened by local click on collapsed tab` 特征串——
   部署二进制确实携带滑拽与把手点击路径。

## 09-28 补充三：CI 集成与既存失败修复（7c33e3f）

- CI 盲点：本地套件 45 项里有 5 项测试（command-to-control、gamepad-menu-gesture、
  pointer-entry-takeover、sas-preset、shortcut-menu-key）和 enhancement-report-tests
  从未接入远程 CI，已接入；workflow-audit 25 条规则通过。
- 既存失败（区分于本轮改动，属前几轮遗留、从未跑通过）：
  enhancement-report-tests 三处自身缺陷——类方法方式调用实例 dispatcher（clang
  现拒绝）、older-system 接线检查要求生产不可能使用的双重字面写法、no-upscale
  红证明期待一条从未存在的 gap 文本。修复方式：驱动按生产方式实例化调用；接线
  检查接受状态字面或 macOS 26 门变量任一为写者，并新增红证明（门答案改写字面量
  的树仍被拒）；静态检查新增 dispatcher 措辞映射注入性验证——正是该证明命名的
  那次坍塌。现在主检查与全部 6 条红证明通过。
- 生产代码未因此改动：设置页增强报告的行为契约不变，只是门的形状修对了。

## 09-28 补充四：CI 全绿闭环中的审计层真相（288e2d4）

CI #288 的 constraints-audit 失败经干净 clone 复现收敛为恰好 2 项（其余历史
FAIL 变体全部是**我 kill 中途 audit 留下的 planted-mutation 污染**——worktree
与 clone 各中一处，已 git checkout -- 精准恢复）：

1. monitor 消费记账规则魔数 == 3：前几轮 keyed-release shortcut 增加了第 4 个
   记录型消费者，属规则未跟上的漂移；真实防线（bare suppression == 0）不变，
   计数改为下限，丢失消费者仍会跌破。
2. parity 规则要求 CI 门同时被本地 aggregate 调用：7c33e3f 接入 CI 的 5 个脚本
   现已注册进 constraints-audit 的 behaviours aggregate。

工作树级教训（写入门禁提交信息）：
- constraints-audit 不在 input-regression-suite 的 45 项里——45/45 绿不等于
  committed tree 过全审计；推送前必须在**推送树的干净 clone** 上单独跑。
- audit 的 red proof 会临时改写真实文件；中途 kill 会污染被测量的树。必须让
  它自己跑完。
- 干净 clone + --no-battery 串行复跑：2 failures → 修复后 0 failures。
- 全套（battery + mutations）由 CI #289 在推送树上执行，本地并行复跑中。

侧边栏本体代码本轮零改动；以上全部是验证基础设施的债，不改变验收矩阵状态。
