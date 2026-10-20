# Moonlight macOS Enhanced — Agent 规则

## UI 外观变更规则：必须尊重用户已验收的控件

设置页标签栏（设置导航 串流/视频/音频/输入/应用/设备）**已被用户验收为 macOS 27 系统原生的 `NSSegmentedControl` + `role=.tabs`**（即 system settings / Activity Monitor 风格的标签切换器）。这一决定记录在 commit `00315f0f`（"let the system's own tab picker draw the selection"），验收语料为"已恢复了"。

- **严禁**以任何理由（"观感更好""可见性增强""统一风格"等）替换为自绘替代方案。
- **严禁**改 UI 前不查该文件最近的验收提交；至少检查 `git log --oneline Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift` 最近 10 条提交。
- 任何涉及用户已验收外观的改动，必须先横向对比用户验收时截图的像素级表现，并在 PR/提交中附上实测截图。
- 这条规则只有用户本人可以解除。
