# Moonlight macOS Enhanced — 目标模式提示词

## 当前目标

Moonlight macOS Enhanced 性能与体验优化：
1. ⏳ **(待 CUA 验收)** 帧队列 29ms 瓶颈 — 已识别真因：90FPS×180Hz 下 desiredEnhancedDrawableDepth/InflightLimit 与 desiredPendingFrames 均未做 doubled-cadence 短路。上一回合 6e3c7321 仅改 MLFramePacer 内部 frameDropTarget，但 pacer 路径未启用（缺 initializeWithMaxVideoFps 调用），等同于无效接线。新提交将在 doubled-cadence 时把 drawable/inflight 3→2、pending 减 1，CUA 实测 desktop 串流验证。
2. ⛔ **(结构性失败已确认)** 90FPS 插帧稳定性 — 180Hz 下 VTLLFI 单次 18-141ms 远超 5.555ms 节拍预算，breaker 持续熔断。需在 UI 上为 force=true 提示"插帧不可保证，仅源帧流"。
3. ✅ **(已完成)** 快捷键OSD视觉反馈 — 串流中操作名+按键组合提示，1.8s 淡出。
4. ✅ **(已完成)** Settings 面板硬件信息展示 — 解码器/渲染器状态摘要行。

## 真因 vs 误诊（参考）

| 项 | 误诊 | 真因 |
| --- | --- | --- |
| 29ms 队列 | MLFramePacer frameDropTarget=3 | pacer 路径未启用（无 initialize），真正生效路径是 CAMetalLayer.maximumDrawableCount + dispatch_semaphore，smoothness=3 时固定 3 |
| 90FPS 插帧熔断 | 单点调参可解 | 180Hz 节拍 5.555ms < VTLLFI 单次 18ms+，结构性不可行 |

## CICD 标准（每轮执行）

1. 改代码 → `xcodebuild build` → BUILD SUCCEEDED
2. `scripts/liquid-glass-audit.py` → 0 violations
3. `scripts/constraints-audit.py --no-battery` → 0 failures
4. `git commit`（`git -c user.email="codex-agent@homelab.local" -c user.name="Codex Agent"`）
5. `git push gitlab main`（http://172.16.130.6/moonlight/moonlight-macos-enhanced.git）
6. CI 自动镜像到 GitHub（opsbsligm/moonlight-macos-enhanced）

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
| CI配置 | `.github/workflows/build.yml` |

## 约定

- 完全独立原项目，不接受任何 PR 或 fork 关系
- 专注 macOS，Linux/Windows 特性无视
- USB 重定向代码已就绪但功能冻结（需 Apple Developer Program 签名）
- 所有改动必须 build + audit 0 failures + commit + push GitLab
- "完成"必须基于真实运行证据（log/CUA/用户主观），不能由代理代答
- 中文汇报，结论先行
