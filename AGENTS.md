# Moonlight macOS Enhanced — Agent 规则

## UI 外观变更规则：必须尊重用户已验收的控件

设置页标签栏（设置导航 串流/视频/音频/输入/应用/设备）**已被用户验收为 macOS 27 系统原生的 `NSSegmentedControl` + `role=.tabs`**（即 system settings / Activity Monitor 风格的标签切换器）。这一决定记录在 commit `00315f0f`（"let the system's own tab picker draw the selection"），验收语料为"已恢复了"。

- **严禁**以任何理由（"观感更好""可见性增强""统一风格"等）替换为自绘替代方案。
- **严禁**改 UI 前不查该文件最近的验收提交；至少检查 `git log --oneline Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift` 最近 10 条提交。
- 任何涉及用户已验收外观的改动，必须先横向对比用户验收时截图的像素级表现，并在 PR/提交中附上实测截图。
- 这条规则只有用户本人可以解除。

## 基础设施基线（具体值在本地基线文档，不在仓内）

Wave AO 起，真实基础设施值从本文件迁出到**仓外本地文档**
`~/Documents/ChatGPT/moonlight/infra-baseline/infra-baseline.md`（不入库），
本文件只保留规则与占位约定，不再持有地址。

- **唯一事实源**：家庭 GitLab（域名 / 端口 / project id 见本地基线文档），
  项目 `moonlight/moonlight-macos-enhanced`。开发 PAT `~/.config/gitlab-1306/pat`，
  审查 PAT `~/.config/gitlab-1306/review-pat`（均 mode 600，不入库、不出日志）。
- **GitHub 镜像**：`opsbsligm/moonlight-macos-enhanced`（镜像账号本身是公开设计，
  徽章 / 下载链接 / About 框依赖真实名），由 `publish-github` job 单向推送，只读，不手推。
- **串流主机（HOME-PC）**：真实 LAN 地址见本地基线文档；仓内文档与 fixture
  一律使用 RFC 5737 占位符 `192.0.2.1`。
- **目标文档（波次四件套）**：已迁出仓外，
  `~/Documents/ChatGPT/moonlight/infra-baseline/`（`goal-mode-prompt.md` 等）。
  对标来源矩阵 `docs/source-matrix-2026-10-25.md` 留在仓内（公开证据层级文档），
  `scripts/source-matrix-audit.py` 硬编码该仓内路径，仅由 GitHub 镜像 CI 把守
  （GitLab 事实源与 `local-gates.sh` 不跑它）。
- **提交身份**：`Codex Agent / codex-agent@homelab.local`；审查、批准、合并用 owner 账号
  （真实账号名见本地基线文档）。
- **runner**：本机 Mac M2（实例级共享 runner，tag `macos`）承接全部 macos job；不可迁移。
