# 串流节拍对照：原版 moonlight-qt 最佳实践与本仓修复

本文件记录一次针对「36 FPS 源 / 180 Hz 屏插帧会话读出拍频抖动」的跨实现对照结论，
以及按该结论实施的 gridlock 修复的边界。引用路径均为本仓相对路径；原版路径为
moonlight-qt 上游源码树相对路径。

## 原版 moonlight-qt 的 Mac 渲染路径

文件：`app/streaming/video/ffmpeg-renderers/vt_metal.mm`（上游）。

- 解码完成回调只做一件事：把新帧放入**单槽 latest-frame**（`m_LatestUnrenderedFrame`），
  旧帧直接释放（约 608–612 行）。不排队、不缓存第二帧。
- 显示节拍完全交给 `CAMetalDisplayLink`：系统回调 `metalDisplayLink:needsUpdate:`
  把 `update.drawable` 和 `update.targetTimestamp`（下一 scan-out 槽的时间点）交给
  `renderLatestFrameOnDrawable`（约 919–945 行）。
- `renderLatestFrameOnDrawable` 最多等到 target 时刻的一半周期（`waitTimeMs`）：
  有帧就渲染进系统给定的 drawable 并提交；**没有新帧就不画**。
- present 调用**不带任何 duration 参数**：drawable 由 display link 绑定到确定的
  scan-out 槽，每帧可见间隔是系统网格的整数倍，软件不参与间隔计算。
- 同目录 `pacer/` 的双队列丢帧器（`pacer.cpp`，frameDropTarget 1 或 3）在 Mac 上
  基本不生效：`signalVsync` 仅被 wayland 的 vsync 源调用（`git grep signalVsync` 可核）。

一句话总结：原版的节拍器只有系统 display link 一个；软件侧的职责是「最新帧在手就交
给下一个槽，没有就不画」，从不自己算 hold 时长。代价是 36 FPS 源在 180 Hz 屏上就
是 36 FPS（不补帧），收益是帧间隔永远落在网格上，天然无拍频。

## 增强版（本仓）此前现状

- 拉帧解码同样由 `CVDisplayLink` 每 scan-out 一次驱动（`Limelight/Stream/VideoDecoderRenderer.m`
  的 `displayLinkCallback`），这一半与原版等价。
- present 用 `[commandBuffer presentDrawable:drawable afterMinimumDuration:hold]`
  做**软 hold**：hold 是「从提交时刻起至少 N 个刷新」的时长，而提交时刻落在两次
  scan-out 之间。于是每帧实际可见间隔在 N 与 N+1 个刷新之间交替（180 Hz / N=3 时
  16.7 ms 与 22.2 ms 交替），肉眼读出拍频抖动。
- 为压抖动引入过一层测量驱动的 cadence 决策（`presentationCadenceForInterpolationHold:`）：
  实测源率 + 插帧率 → 整刷新网格 snap + 4 FPS 死区滞回。该层治好了「网格值翻转」
  （build 2228 真机 7001 次 bound 99.8% 锁定），但治不了「提交相位不贴网格」——
  网格值稳定了，帧仍然每帧漂在网格之间。
- VT 低延迟插帧每对源帧补一帧：插帧帧与源帧必须各占不同 scan-out 槽，hold 不能
  简单去掉，只能把 hold 的落点改对。

## 本次改动：hold 锚定 scan-out 网格（gridlock）

改动只动 hold 的落地方式，不动 cadence 决策：

1. `displayLinkCallback` 每次被调用即一次 scan-out，记录 `CACurrentMediaTime()` 到
   `_lastScanoutMediaTime`（C 回调内，经 `self->_` 裸 ivar 访问，与回调内既有写法
   一致）。显示频率变化超过 0.5 Hz 判定为换网格，丢弃已记忆的网格目标。
2. present 时不再把决策函数给的裸时长交给 window server，而是把它换算成**网格
   目标时刻**：稳态下取「上一帧网格目标 + 一个完整 hold」；失锚（空闲、首帧、换
   屏）时取「最近 scan-out 锚点之后第 N 个整网格点」（相位用 `ceil` 补齐）。目标
   时刻落后当前时刻则继续步进一个周期保持单调。`afterMinimumDuration` 传
   `gridTarget - now`。
3. 插帧 Off / 决策返回 NO 的路径保持原样：无 duration 的 `presentDrawable`。
4. 首次进入 gridlock 路径打一条 `Presentation gridlock` 日志（含 N 与 Hz），便于
   真机复验 grep。

为什么这是「最佳实践」而不是补丁：

- **节拍器唯一化**。网格只由 display link 的 scan-out tick 定义，与原版同构；软件
  不再用提交时刻当第二个时钟。
- **帧间隔恒为整刷新周期**。稳态相邻两帧的可见间隔精确等于 N × period，16.7/22.2
  ms 交替消失，拍频消除，而不是被 EMA/死区「压住」。
- **与原版同构而不自算**。原版靠 `targetTimestamp` 免费拿到网格点；CVDisplayLink
  不给 target，就用它的 tick 自己数格子。两者的共同点是「系统 display link 是唯一
  节拍器」，本改动让增强版回到这一条。

## 残留项（本次未覆盖）

- **糊（马赛克）**：归因主机侧 NvEnc 静态帧 2–3 kB/帧 + 客户端 RTSP 协商 24 Mbps
  封顶（主机 sunshine.conf 的 60 Mbps 被客户端压回）。修复点在客户端设置页码率
  上限，非本仓渲染路径。
- **36 FPS 源的插帧上限**：VT 插帧成功率约 50%（现场实测），生产帧率 = 源 + 插帧，
  上限即 2 × 源率；gridlock 只保证落点，不增加产出。
- **未验证**：本修复未经真机回归。复验口径：36 FPS 桌面负载会话，grep 日志确认
  `Presentation gridlock` 出现、`Presentation cadence bound` 网格值不翻转，且主观
  抖动消失；`hardware_validated` 保持 false 直至用户确认。

## 门禁

- `scripts/interpolation-cadence-policy-tests.py`：69 读数 0 错 + wiring 0 gaps，
  新增 4 条 gridlock 锚点断言（tick 记录、ceil 相位补齐、gridHoldSeconds 落地、
  裸时长不得再出现），红证自测两条均挂。
- `scripts/input-regression-suite.py`：45/45。
- `scripts/liquid-glass-tab-bar-tests.py`：rc=0（六标签红线文件未触碰）。
