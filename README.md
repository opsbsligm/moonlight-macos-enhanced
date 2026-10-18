# Moonlight for macOS — Enhanced Edition

<p align="center">
  <a href="https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest"><img src="https://img.shields.io/github/v/release/opsbsligm/moonlight-macos-enhanced?label=release&color=blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="License"></a>
  <img src="https://img.shields.io/badge/platform-macOS%2026%2B-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/macOS-27%20beta-supported-blue" alt="macOS 27 beta">
  <img src="https://img.shields.io/badge/status-independent%20project-brightgreen" alt="Independent">
  <a href="https://github.com/opsbsligm/moonlight-macos-enhanced/actions"><img src="https://img.shields.io/github/actions/workflow/status/opsbsligm/moonlight-macos-enhanced/build.yml?branch=main" alt="CI"></a>
</p>

**Moonlight macOS 客户端的独立增强实现** — 完全脱离上游 fork 关系，专注 macOS 平台，对标 Parsec / Steam Link 工业标准的低延迟串流体验。

本仓库始于 [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced)（其上游为 [Moonlight Game Streaming Project](https://github.com/moonlight-stream)）。自 2026-10 起**完全独立**，删除所有上游 remote，不再同步任何上游更改，所有开发方向自主决定。

---

## ✨ 核心特性

### 🎮 串流引擎
| 特性 | 说明 |
|------|------|
| GameStream / Sunshine 发现与配对 | 自动发现局域网主机，支持配对码配对 |
| H.265/HEVC & AV1 硬件解码 | 利用 VideoToolbox 进行 GPU 加速解码 |
| HDR 支持 | HDR→SDR tone mapping 策略可配置（含 No Exposure Shift 档） |
| 多声道音频 + 麦克风传输 | 支持 7.1 声道及语音回传 |
| 帧节奏控制（Pacer） | 双队列 + vsync 对齐 + 自适应丢帧，平滑输出 |
| 90/120 FPS 支持 | 高帧率串流，需 Sunshine 端配合 |

### 🎯 画质增强
- **MetalFX 超分辨率** — 在解码后画面放大时使用 GPU 重建细节，支持画质/性能档位
- **VideoToolbox 低延迟插帧** — 显示器刷新率高于串流帧率时自动启用
- **强制插帧开关** — 允许 180Hz 屏跑 120FPS 串流时也挂载插帧，详见 [`docs/force-interpolation-2026-10-01.md`](docs/force-interpolation-2026-10-01.md)
- **运行时状态监控** — 实时显示渲染路径、实际缩放引擎、实际插帧引擎及帧率数据

### ⌨️ 输入系统（核心差异化）
| 特性 | 说明 |
|------|------|
| CoreHID 高精度鼠标 | 1000Hz 回报率支持，自由鼠标/锁定鼠标两种模式 |
| 工业标准键盘映射 | 与 Parsec、UU 远程、Steam Link 同一套映射标准 |
| 双键并发支持 | W+Space（行走+跳跃）等组合键正确握持 |
| 手柄模拟 | Xbox 360 虚拟手柄，支持 Xbox Elite 2 / Betop Zeus 识别修正 |
| 修饰键可靠性 | Ctrl/Shift/Alt/Win 映射正确，快捷键冲突已修复 |
| 详细文档 | 映射表与已修复问题根因见 [`docs/input-mapping-design.md`](docs/input-mapping-design.md)，对标结论见 [`docs/input-mapping-benchmark.md`](docs/input-mapping-benchmark.md) |

### 🪟 串流中控制栏（边缘把手）
- 常驻贴在画面边缘（收起态 14×48 逻辑点），可拖拽重新停靠四边
- 锁定鼠标模式下快捷键 `⌃⌥C` 唤起
- 自由鼠标模式下光标悬停 120ms 点亮把手，点击展开
- 离开后 450ms 自动收起，始终未触达时 2500ms 交还指针
- 设计与真机取证详见 [`docs/edge-sidebar-locked-entry-2026-09-28.md`](docs/edge-sidebar-locked-entry-2026-09-28.md)

### 🎨 Liquid Glass 设计语言
- 全设置面板系统玻璃材质（`.glassEffect`）+ 磨砂卡片布局
- 首页主机卡片液态玻璃化
- 原生 NSSegmentedControl 页签，Activity Monitor 风格 — 选中段磨砂玻璃滑块 + 深色文字

### 🔌 USB 设备诊断
- Citrix Horizon VDI 风格设备卡片布局
- 40×40 圆角图标 + 三行设备层级 + 颜色编码状态芯片
- 归因到具体原因（保留类别/本地输入设备/未匹配规则/前置条件未满足）
- 主机声明四态：支持 / 不支持 / 无法到达 / 还没问过

### 🌐 其他
- 中英双语界面（菜单、权限弹窗、日志面板本地化）
- 实时性能叠加层
- 诊断报告一键导出

---

## 🚧 当前边界

| 项目 | 状态 | 备注 |
|------|------|------|
| **USB 设备重定向** | ❌ 冻结 | 需 Developer ID 签名 + 主机侧虚拟总线 |
| **自动更新** | ❌ 待实现 | 需 Developer ID 证书 + Sparkle 框架 |
| **macOS 15/12 兼容** | ❌ 不支持 | 需 Liquid Glass 窗口层，见 `docs/contributing.md` |
| **Linux/Windows** | ❌ 不关注 | 本项目专注 macOS 平台 |

---

## 📦 下载与安装

从 [Releases](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest) 下载最新 DMG 镜像：

```
Moonlight-macOS-Enhanced-{arm64,x86_64,universal}.dmg
```

1. 打开 DMG，将 `MoonlightEnhanced.app` 拖入 Applications
2. 首次运行 → 系统设置 → 隐私与安全性 → 允许运行

> ⚠️ 本构建是 ad-hoc 签名。bundle 名为 `MoonlightEnhanced.app`，与 Qt 客户端的 `Moonlight.app` 可并存。如需清理旧版：删除 `/Applications/Moonlight.app`。

---

## 🔧 从源码构建

### 前置要求
- macOS 26.0+
- Xcode 27 beta（macOS 27 SDK）
- 命令行工具：`xcode-select --install`

### 快速构建

```bash
# 克隆
git clone --recurse-submodules https://github.com/opsbsligm/moonlight-macos-enhanced.git
cd moonlight-macos-enhanced

# 下载依赖（FFmpeg / SDL2 / OpenSSL）
scripts/download-frameworks.sh

# Debug 构建
scripts/build.sh

# Release 构建
scripts/build.sh --release

# 打包 DMG
scripts/package-dmg.sh
```

### 手动 Xcode 构建

```bash
xcodebuild -project Moonlight.xcodeproj \
  -scheme "Moonlight for macOS" \
  -configuration Debug \
  -destination 'platform=macOS' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

---

## ✅ CI/CD 质量门禁

每个提交经过四阶段自动化门禁：

```
audit → build_arch(both slices) → build_universal → verify
```

### 审计体系（98 个脚本）
| 类别 | 数量 | 说明 |
|------|------|------|
| 约束审计 | 60+ | 液态玻璃视觉效果、页签行为、内存泄漏、凭证扫描、国际化、CI 完整性 |
| 输入系统测试 | 20+ | 键盘并发、修饰键映射、鼠标状态、游戏手柄迁移 |
| USB 虚拟化测试 | 5+ | 设备枚举、策略引擎、总线快照 |
| 视频管线测试 | 8+ | 渲染模式、增强可用性、HDR 曝光 |
| 静态分析审计 | 3+ | 引用泄漏、定时器泄漏、分析基线对比 |

### 提交规范
- [Conventional Commits](https://www.conventionalcommits.org/)
- Subject ≤ 72 字符
- 类型：`feat` / `fix` / `style` / `refactor` / `ci` / `docs` / `test`
- 每个提交必须通过所有本地审计

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [`docs/input-mapping-design.md`](docs/input-mapping-design.md) | 键盘/鼠标映射设计原则与已修复问题 |
| [`docs/input-mapping-benchmark.md`](docs/input-mapping-benchmark.md) | Parsec/UU/Steam 对标结论 |
| [`docs/edge-sidebar-locked-entry-2026-09-28.md`](docs/edge-sidebar-locked-entry-2026-09-28.md) | 串流控制栏边缘把手设计 |
| [`docs/force-interpolation-2026-10-01.md`](docs/force-interpolation-2026-10-01.md) | 强制插帧开关设计与限制 |
| [`docs/diagnostics-report.md`](docs/diagnostics-report.md) | 诊断报告字段说明 |
| [`docs/contributing.md`](docs/contributing.md) | 贡献指南与质量门控清单 |
| [`CHANGELOG.md`](CHANGELOG.md) | 逐轮变更记录 |
| [`docs/README.md`](docs/README.md) | 全部文档索引 |

---

## 📋 开发路线图

| 优先级 | 模块 | 状态 |
|--------|------|------|
| P0 🔴 | CI 门禁、README、仓库配置 | 进行中 |
| P1 🟡 | 自适应码率、解码探测对齐、控制栏体验 | 待开始 |
| P2 🟢 | 首页卡片响应式、USB 诊断侧边栏、文案优化 | 待开始 |
| P3 ⚪ | USB 重定向、自动更新 | 依赖 Developer ID |

---

## 🐛 如何反馈

1. 打开 `设置 → 应用 → 调试日志 → 拷贝诊断报告…`
2. 粘贴报告，补充以下信息：
   - 主机端软件与版本（Sunshine / GeForce Experience）
   - 是否使用了 Mos / BetterMouse / SteerMouse 等第三方工具
   - 复现步骤与预期结果

> 鼠标类问题请先开启 `设置 → 应用 → 调试日志 → 输入诊断（Input Diagnostics）` 再复现。

---

## 📄 许可证

本项目基于 [GPL-3.0](LICENSE) 许可证发布。

### 第三方组件
| 组件 | 许可证 |
|------|--------|
| moonlight-common-c | GPLv3 |
| OpenSSL | Apache 2.0 |
| FFmpeg | LGPLv2.1+ |
| SDL2 | zlib |
| MASPreferences | BSD-2-Clause |
| Roboto Font | Apache 2.0 |

---

## 🙏 致谢

- [Moonlight Game Streaming Project](https://github.com/moonlight-stream) — 原始上游
- [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced) — 历史起点（已完全独立）
- [Parsec](https://parsec.app) — 键盘映射参考
- 所有贡献者与测试用户
