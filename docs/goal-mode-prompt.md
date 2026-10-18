# Moonlight macOS Enhanced — 目标模式提示词

## 项目定位

Moonlight macOS 客户端的独立增强实现。**完全独立于原项目 skyhua0224/moonlight-macos-enhanced**，不再做任何上游同步或 PR。专注于 macOS 平台的低延迟串流体验，Linux/Windows 特性直接无视。

## 当前状态（2026-10-19）

### ✅ 已完成（P0 核心 99%）

- OpenSSL 构建顺序修复
- Device-redirection 测试字符串修复
- Scalers 测试（MLFramePacer forward-declare）
- Static analyzer（macOS 26 baseline + reasons）
- x86_64 warning（unused const）
- README 完全重写——独立项目定位
- 双托管推送配置（GitHub opsbsligm + GitLab 172.16.130.6）
- 标签页 UI：NSSegmentedControl 原生控件，已用户确认
- LiquidGlass 全页面玻璃效果
- USB 设备页 UI 重设计
- 插帧/超分基础框架（VT FI + MetalFX）
- frame pacing 双队列（从 moonlight-qt 吸收）
- 串流控制栏（边缘把手）
- 约束审计框架（constraints-audit / credential-scan / liquid-glass-audit 等）
- CI 配置（GitHub Actions + GitLab CI）

### 待办优先级

#### P1 🔴 核心功能体验

1. **merge round77 → main** — 42 commits 等待合并，P0 收官
2. **BandwidthTracker 挂接到数据路径** — `DrSubmitDecodeUnit` 中的 `addBytes:` 调用
3. **插帧/超分实机验证** — 需要 Computer Use 做真实串流测试，验证 90fps 动态插帧
4. **VT 解码探测对齐 upstream** — 读取 moonlight-stream 最新代码，吸收 macOS 相关改进
5. **串流控制栏打磨** — 边缘把手 + 快捷键一致性

#### P2 🟢 UI/UX 与架构

6. **首页主机卡片响应式修复** — HostCell.m 的白圈/布局问题
7. **USB 设备页面侧边栏重构** — 设置只配置可重定向设备类型，具体重定向由串流侧边控制栏选择
8. **插帧/超分文案中文化** — Localizable.strings
9. **串流效果持续打磨** — 编解码体验、MetalFX、VideoToolbox 插帧
10. **前端 UI 设计感提升** — LiquidGlass 效果全页面一致性、主框体缩放卡片跟随

#### P3 🔵 长期

11. **USB 重定向** — 需要 Developer ID 签名与主机侧虚拟总线，当前冻结
12. **DriverKit 驱动扩展** — USB 重定向的前提
13. **90fps 动态插帧验收** — 真实串流验证

## 开发纪律（严格执行）

### CICD 工作流
```
改代码 → build (CODE_SIGNING_ALLOWED=NO) → 审计 0 failures → commit → push GitLab
```
- 审计: `scripts/constraints-audit.py --no-battery` (~30s)
- 审计: `scripts/credential-scan-audit.py` (~0.5s)
- 构建: `xcodebuild -project Moonlight.xcodeproj -scheme "Moonlight for macOS" -configuration Debug -derivedDataPath build-render-probe -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build`
- 提交: `git -c user.email="codex-agent@homelab.local" -c user.name="Codex Agent" commit -m "type(scope): subject ≤72 chars"`
- 推送: `git push gitlab <branch>`

### 双托管仓库
- 唯一事实源 = GitLab (http://172.16.130.6)
- GitHub (opsbsligm) 是 CI 自动镜像
- 本地工作区: `/tmp/gitlab-ws-mac`
- remote origin=GitHub, gitlab=GitLab
- 提交身份固定

### 标签页 UI 红线
**NSSegmentedControl 版本不动**（已多次用户确认，任何改动都会引发强烈反弹）

### USB 冻结
Developer ID 不可用，USB 重定向不做（设备页只做诊断）

### 验收标准
- 构建成功 ≠ 完成，真机验证才算
- 实机串流测试验证插帧/超分
- UI 改动必须截图给用户确认
- 桌面/远程模式都需验证

## 重点关注领域

1. **插帧/超分** — 前端文案对齐、实机验证 90fps、MetalFX 超分效果
2. **串流控制栏** — 边缘把手、快捷键、USB 设备侧边选择
3. **前端 UI** — LiquidGlass 全页面一致性、设计感提升、半透明模糊效果
4. **CICD** — pipeline 监控、门禁不绕过
5. **moonlight-stream 上游吸收** — 只吸收 macOS 相关优化

## 执行模式

自主推进，有实质变化才汇报：解决了什么、证据是什么、还缺什么。不反复要求用户小步测试。中文汇报，结论先行。
