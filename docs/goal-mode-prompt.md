# Moonlight macOS Enhanced — 目标模式提示词

## 当前目标

Moonlight macOS Enhanced 性能与体验优化：
1. ⏳ **(队列调整已实测，持续延迟目标未闭合)** 29ms 队列延迟 — MLFramePacer 未驱动实际渲染。当前生效路径是拉帧阈值与 Metal drawable/inflight；刷新率未知时先建 3/3，首个有效刷新率后在绘制前、安全排空旧命令再切换 2/2。90FPS/180Hz 请求已实测切换，VSync pending 保持 1。首帧或提交队列的一次下降不能证明持续延迟改善。
2. ⏳ **(性能边界已暴露，稳定 180FPS 未验收)** 90FPS 插帧稳定性 — 本机 Apple M2 的历史 VT 单次调用为 18-141ms，本轮另实测 150ms 调用触发 22ms 预算的过载保护。该结论仅适用于已测硬件和配置。当前源画面为 Windows 锁屏，实际到达约 33FPS，不能用请求 90FPS 或目标 180FPS 日志代替有效负载验收。设置页已区分节拍准入、处理能力与过载回退，强制开关不能绕过后两者。
3. ✅ **(已完成)** 快捷键OSD视觉反馈 — 串流中操作名+按键组合提示，1.8s 淡出。
4. ✅ **(已完成)** Settings 面板硬件信息展示 — 解码器/渲染器状态摘要行。

## 已验证事实与待验证结论

| 项 | 已验证事实 | 结论边界 |
| --- | --- | --- |
| 29ms 队列 | pacer 未接入；Metal 队列 3/3→2/2 已实测 | 拉帧 pending 是解码单元阈值；不能将 buffer 数量直接等同于 29ms 根因 |
| 90FPS 插帧熔断 | 本机出现超预算调用与实际回退 | 不推导所有硬件都不可行；不靠关闭保护或伪造上屏指标验收 |
| 实际上屏统计 | 读取 drawable.presentedTime，0 表示未呈现或跳过 | 无新鲜样本显示 --；恢复呈现后重建统计窗口，拒绝迟到旧回调 |

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
| GitLab 构建与自动镜像 | `.gitlab-ci.yml` |
| 镜像端补充审计 | `.github/workflows/build.yml` |

## 约定

- 完全独立原项目，不接受任何 PR 或 fork 关系
- 专注 macOS，Linux/Windows 特性无视
- USB 重定向代码已就绪但功能冻结（需 Apple Developer Program 签名）
- 所有改动必须 build + audit 0 failures + commit + push GitLab
- "完成"必须基于真实运行证据（log/CUA/用户主观），不能由代理代答
- 中文汇报，结论先行
