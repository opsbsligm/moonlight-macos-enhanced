# 插帧呈现时序与超分现实（2× 验收缺口）— 2026-10-09

## 本轮定位
整除门限（336d96d1）修的是"节拍配不上导致结构性 judder"。用户实机体感
仍不可用，说明门内还有第二层问题：**2× 是否真的到达面板**从未被验收。
本轮不改行为，把现状钉死并定下验收/实现方案。

## 已验证事实
1. **本主机 VT 超分现实**（/tmp/mle/sr-probe 实测重跑，macOS 27.2/M2）：
   LL SR 1920x1080 与 2560x1440 的 supportedScaleFactors 均为空——
   1080p 源在本硬件上没有任何 VT 超分档位（Apple 限制 M2/1080p 组合）。
   LL SR 全局因子 {1.5,2.0,4.0}；VT Quality SR 仅有整数 4。
   结论：本面板上超分可做的正事是"低分辨率源放大"（如 720p@120 → 1080p），
   1:1 场景它不该也不会被激活。超分暂时不是蜂蜜感的来源。
2. **上次"插帧激活"的验收样本本身不合法**：统计条 +32.3fps 出自
   80 FPS 会话（+32.3≈40 产出×~80%），80Hz 面板 ÷ 160 输出 = 0.5，
   不整除——按新门限这类配对根本不该放行。真正的整除对
   （90 FPS/180Hz 或 60 FPS/120Hz）从未做过主观验收。**蜂蜜感未修复，
   只是还没被正确测试。**

## 呈现路径的三个结构性缺口（代码证据：VideoDecoderRenderer.m）
A. **呈现时钟与 vsync 解绑**：`_metalView.preferredFramesPerSecond =
   MAX(self.frameRate, 60)`（setupMetalRenderer）。面板 180Hz 时 MTKView
   的 CVDisplayLink 只按 60/s 生成 drawable；插帧帧经 displayLink 回调
   →requestEnhancedDraw→主线程 CFRunLoopPerformBlock→`[MTKView draw]`
   再补一刀。源帧与中间帧各自占多久面板完全由 draw 线程调度决定，
   "每帧恰好持 k 拍"在架构上无保障——这就是 2× 名不副实的机制。
B. **插帧提交在呈现关键路径上同步执行**：stageInterpolatedFrame→
   copyInterpolatedFrame…→`processWithParameters:error:`（同步版）阻塞
   解码回调线程；drawInMTKView 又在主线程同步提交超分。VT 调用一次
   数毫秒，直接变成 draw 抖动。
C. **每个源帧触发两次 draw**（源帧一次、中间帧一次），draw 之间没有
   任何持帧/配对约束；超分缓冲每帧新建+CVBufferRelease，无在飞深度
   控制与超时回收。

## 方案（按投入排序）
1. **合法配对主观验收（先行，零代码）**：部署 336d96d1 后，HOME-PC 会话
   设 90 FPS + 插帧（180Hz 面板唯一整除档），主观判定蜂蜜感是否消失。
   它同时是"呈现层有没有问题"的判据：若 90/180 仍粘，问题在 A/B/C；
   若消失，先前体感全部由非整除配对解释，实现只做 2、4 两个加固。
2. **呈现时钟对齐面板**：preferredFramesPerSecond 取整对齐实测刷新率
   （含 179.82→180 的取整），并限制 draw 唤醒频率不高于面板节拍；
   中间帧与源帧的 draw 按节拍配对提交。
3. **超分务实化**：UI 依据实际 supportedScaleFactors 呈现可用性
   （1080p/1440p 源=不可用如实说）；720p 源 1.5× 为唯一主推组合。
4. **插帧管线异步化**（A/B/C 的正解）：presentation-time 调度队列，
   VT 提交移出主线程，输出缓冲带在飞深度与超时回收。改动大，排在
   验收结论之后，避免为错误假设修大架构。

## 待办
- [ ] 90 FPS/180Hz 主观验收（用户会话，判据见上）
- [ ] 呈现层缺口 2 的最小实现 + 新测试（draw 次数与节拍断言可用
      DebugVideoProbeExpectations 通道）
- [ ] 超分 UI 如实化（依赖 3 的评估）
