# Moonlight for macOS — Enhanced Edition

[![Release](https://img.shields.io/github/v/release/opsbsligm/moonlight-macos-enhanced?label=release&color=blue)](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%2026%2B-lightgrey)](https://developer.apple.com/macos/)
[![Upstream](https://img.shields.io/badge/fork%20from-skyhua0224%2Fmoonlight--macos--enhanced-blue)](https://github.com/skyhua0224/moonlight-macos-enhanced)

一个 fork 自 [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced) 的增强版，该项目本身衍生自 [Moonlight Game Streaming Project](https://github.com/moonlight-stream)。本仓库专注于低延迟串流体验与工业标准键盘映射。

**与上游原版的差异，一句话**：把键盘/鼠标输入做成与 Parsec、UU 远程、Steam Link 同一套工业标准映射并让它可测试、可诊断，其余能力（编解码、HDR、音频、手柄）沿用上游。
映射表、设计原则与已修复问题的根因见 [`docs/input-mapping-design.md`](docs/input-mapping-design.md)，逐项对标结论见 [`docs/input-mapping-benchmark.md`](docs/input-mapping-benchmark.md)。

## 能做什么

- GameStream / Sunshine 主机发现与配对
- H.265/HEVC & AV1 硬件解码
- HDR 支持，以及 HDR→SDR 的 tone mapping 策略选择（含 `No Exposure Shift` 档）
- 多声道音频 + 麦克风传输
- 虚拟手柄 (Xbox 360)，含 Xbox Elite 2 / Betop Zeus 等设备识别修正
- Core HID 高精度鼠标输入，锁鼠/自由鼠标两种模式
- 实时性能叠加层，以及视频管线的运行时状态（MetalFX、VideoToolbox 插帧是否真的生效）
- 中英双语界面（菜单、权限弹窗、日志面板都是本地化的）
- **设备页**：列出本机 USB 总线上的设备，把每台归因到具体原因（保留类别 / 本地输入设备 / 未匹配规则 / 前置条件未满足），报告当前这个包的签名能不能加载驱动扩展，并把主机声明读成四态（支持 / 不支持 / **无法到达** / 还没问过）——「无法到达」不等于「主机拒绝」：请求没走通、状态码是错、或答复由别的机器签名，都落在这一态，而把它说成拒绝会把用户支去翻一台根本没作答复的主机的设置

## 当前边界（不能做什么）

- **USB 设备重定向不做**：设备页只做诊断，重定向本身还需要 Developer ID 签名与主机侧虚拟总线，两者都未到位，所以它不承诺任何一次交接会成功（取舍见 [`docs/usb-redirection-design.md`](docs/usb-redirection-design.md)，主机侧契约见 [`docs/usb-redirection-host-contract.md`](docs/usb-redirection-host-contract.md)）
- **运行时需 macOS 26.0+**：`MACOSX_DEPLOYMENT_TARGET = 26.0`，Liquid Glass 窗口层依赖该版本；要支持 macOS 15/12（upstream Issue #26）需要的工作见 [`docs/contributing.md`](docs/contributing.md)
- **每个版本都带安装前提**：本构建是 ad-hoc 签名，首次运行需在「系统设置 → 隐私与安全性」里允许

## 下载与安装

1. 从 [Releases](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest) 下载最新镜像：`Moonlight-macOS-Enhanced-{arm64,x86_64,universal}.dmg`，每个都附带同名 `.sha256`。文件名按架构而不是按版本——版本在镜像内部核对，`dmg-audit.py` 会把它和 CI 算出的构建号对上，不靠文件名对账
2. 打开 DMG，将 `MoonlightEnhanced.app` 拖入 Applications（访达、Dock 与「强制退出」列表里显示为「Moonlight 增强版」）
3. 首次运行时，在「系统设置 → 隐私与安全性」中允许运行

> ℹ️ 本构建的 bundle 名是 `MoonlightEnhanced.app`，与 Qt 客户端的 `Moonlight.app` 不再是同一个文件，安装不会互相替换（issue #41），两者可以并存。若 `/Applications` 里还留着本仓库早期版本装的 `Moonlight.app`，请先删除它：两者 bundle 标识符相同（`std.skyhua.MoonlightMac2`），同时存在时 LaunchServices 可能仍启动旧的那一份，权限授予也会跟着旧路径走。

## 快速开始（从源码构建）

```bash
# 克隆仓库
git clone --recurse-submodules <repo-url>
cd moonlight-macos-enhanced

# 下载依赖框架（FFmpeg / SDL2 / OpenSSL）
scripts/download-frameworks.sh

# 编译
scripts/build.sh

# 打包 DMG
scripts/package-dmg.sh
```

首次构建前必须执行 `scripts/download-frameworks.sh`，否则 common-c 编译失败（原因见 [`docs/contributing.md`](docs/contributing.md)）。

Xcode 与 deployment target 的要求见 [`docs/contributing.md`](docs/contributing.md)。

## 如何反馈

**先拷贝诊断报告。** `设置 → 应用 → 调试日志 → 拷贝诊断报告…` 会把一份可直接粘贴的报告放进剪贴板；配对失败的弹窗里也有同一个按钮。

**如果问题是鼠标不动，请先打开 `设置 → 应用 → 调试日志 → 输入诊断（Input Diagnostics）` 再复现一次，然后拷贝报告。**

在此基础上请补充：
- 主机端软件与版本（Sunshine 或 GeForce Experience）
- 是否启用了 Mos / BetterMouse / SteerMouse 等第三方鼠标工具
- 复现步骤，以及你期望看到的结果

报告里具体有哪些字段、为什么鼠标问题必须先开开关、以及离开本机前如何脱敏，见 [`docs/diagnostics-report.md`](docs/diagnostics-report.md)。

## 文档

全部文档的读者与目的见 [`docs/README.md`](docs/README.md)。逐轮变更记录见 [`CHANGELOG.md`](CHANGELOG.md)；从本页归档出去的历史内容见 [`docs/history/rounds.md`](docs/history/rounds.md)。

## 贡献

Fork → 特性分支 → 遵循 [Conventional Commits](https://www.conventionalcommits.org/) 提交 → PR。
质量门控清单、Commit 类型与版本号/tag 约定见 [`docs/contributing.md`](docs/contributing.md)。

## 许可证

本项目基于 [GPL-3.0](LICENSE) 许可证发布。

包含的第三方组件：
- moonlight-common-c (GPLv3)
- OpenSSL (Apache 2.0)
- FFmpeg (LGPLv2.1+)
- SDL2 (zlib)
- MASPreferences (BSD-2-Clause)
- Roboto Font (Apache 2.0)

## 致谢

- [Moonlight Game Streaming Project](https://github.com/moonlight-stream) — 原始上游项目
- [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced) — 直接 fork 来源原作者
- [Parsec](https://parsec.app) — 键盘映射最佳实践参考
- 所有贡献者与测试用户
