# Moonlight for macOS — Enhanced Edition

[![Release](https://img.shields.io/badge/release-v1.3.9--build19-blue)](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/tag/v1.3.9-build19)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%2026%2B-lightgrey)](https://developer.apple.com/macos/)
[![Upstream](https://img.shields.io/badge/fork%20from-skyhua0224%2Fmoonlight--macos--enhanced-blue)](https://github.com/skyhua0224/moonlight-macos-enhanced)

一个 fork 自 [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced) 的增强版，该项目本身衍生自 [Moonlight Game Streaming Project](https://github.com/moonlight-stream)。本仓库专注于低延迟串流体验与工业标准键盘映射。

## 核心特性

### 串流标准键盘映射 (v1.3.9-build19 重构)
采用与 **Parsec / UU 远程 / Steam Link** 一致的直接映射方案，彻底消除旧版兼容模式导致的映射混乱：

| macOS 物理键 | Windows HID 功能 |
|:---:|:---:|
| **Command (⌘)** 左/右 | Windows Win 键 (VK_LWIN 0x5B / VK_RWIN 0x5C) |
| **Control (⌃)** 左/右 | Windows Ctrl 键 (VK_LCTRL 0xA2 / VK_RCONTROL 0xA3) |
| **Option (⌥)** 左/右 | Windows Alt 键 (VK_LALT 0xA4 / VK_RALT 0xA5) |
| **Shift (⇧)** 左/右 | Windows Shift 键 (VK_LSHIFT 0xA0 / VK_RSHIFT 0xA1) |

- **零延迟**：修饰键按下即发送，无 120ms 延迟判定
- **零耦合**：鼠标事件不会影响键盘修饰键状态（修复了「双击鼠标触发开始菜单」的根因）
- **单一真相源**：所有映射通过 `KeyboardMapResolver` 的静态表驱动，无运行时分支

### 其他功能
- GameStream / Sunshine 主机发现与配对
- H.265/HEVC & AV1 硬件解码
- HDR 支持
- 多声道音频 + 麦克风传输
- 虚拟手柄 (Xbox 360)
- Core HID 高精度鼠标输入
- 实时性能叠加层
- 中英双语界面

## 下载安装

### 方式一：下载 DMG（推荐）
1. 从 [Releases](../../releases) 下载最新 `Moonlight-1.3.9-build19.dmg`
2. 打开 DMG，将 Moonlight 拖入 Applications
3. 首次运行时，在「系统设置 → 隐私与安全性」中允许运行

### 方式二：从源码构建
```bash
# 克隆仓库
git clone --recurse-submodules <repo-url>
cd Moonlight-macOS

# 下载依赖框架（FFmpeg / SDL2 / OpenSSL）
scripts/download-frameworks.sh

# 编译
scripts/build.sh

# 打包 DMG
scripts/package-dmg.sh
```

**构建要求：**
- macOS 15.0+
- Xcode 16+
- Swift 5.0+

## 项目结构

```
Moonlight-macOS/
├── Limelight/                 # 主应用源码
│   ├── Input/                 # 输入处理（键盘/鼠标/手柄）
│   │   ├── KeyboardMapResolver.h/.m   # 键盘映射单一真相源
│   │   ├── HIDSupport.m/.h            # HID 事件处理核心
│   │   └── ControllerSupport.m        # 手柄支持
│   ├── Stream/                # 串流核心（连接/解码/渲染）
│   ├── Network/               # 网络层（发现/配对/HTTP）
│   ├── Crypto/                # 加密与证书管理
│   ├── Database/              # 数据持久化
│   └── macOS/                 # macOS 平台层
│       ├── ViewControllers/   # MVC 控制器
│       ├── Views/             # 自定义视图
│       └── Helpers/           # 工具类
├── moonlight-common/          # ENet 协议库（GPLv3 子模块）
├── scripts/                  # 构建与 CI/CD 脚本
├── Artwork/                  # 图标素材（Sketch）
├── LICENSE                    # 许可证
└── README.md                  # 本文件
```

## 键盘映射设计文档

### 设计原则（CI/CD 最佳实践）

1. **单一真相源 (Single Source of Truth)**
   - 所有映射逻辑集中在 `KeyboardMapResolver`，通过静态表 `s_mapTable` 定义
   - 消除了旧版 4 处重复 switch/case 映射

2. **无状态 (Stateless)**
   - 映射函数是纯函数，无副作用，无全局变量
   - 修饰键状态由 `flagsChanged:` 事件驱动，不依赖定时器或状态机

3. **零耦合 (Zero Coupling)**
   - 鼠标事件路径完全不触碰键盘修饰键状态
   - `HIDEffectivePhysicalModifierMaskForEvent()` 不再从 `event.modifierFlags` 推断修饰键

4. **可测试性 (Testable)**
   - 映射表在编译期确定，可通过单元测试验证
   - `KMR_LogActiveMapping()` 在启动时打印完整映射矩阵

### 修复的关键 Bug

**「双击鼠标触发 Windows 开始菜单」根因分析：**
- 旧版 `HIDEffectivePhysicalModifierMaskForEvent()` 会从鼠标事件的 `event.modifierFlags` 中推断修饰键状态
- 当用户按住 ⌘ + 点击鼠标时，鼠标事件携带 `NSEventModifierFlagCommand` → 被注入物理掩码 → 触发 VK_LWIN DOWN
- **修复**：该函数现在完全忽略 `event.modifierFlags`，物理修饰键状态只从键盘事件追踪

## 贡献指南

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改，遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范
4. 推送分支并创建 Pull Request

### Commit 规范
```
type(scope): subject

body (可选)

footer (可选)
```

类型：`feat` / `fix` / `refactor` / `docs` / `chore` / `test` / `ci`

## 版本控制

本项目遵循 [Semantic Versioning](https://semver.org/)：
- **主版本号**：不兼容的 API 变更
- **次版本号**：向后兼容的新功能
- **修订号**：向后兼容的 Bug 修复

每个版本通过 Git annotated tag 标记（如 `v1.3.9-build19`），详见 [CHANGELOG.md](CHANGELOG.md)。
版本号格式：`v<MARKETING_VERSION>-build<BUILD_NUMBER>`，其中 `BUILD_NUMBER` = `git rev-list --count HEAD`。
DMG 文件名与 tag 一一对应：`Moonlight-<MARKETING_VERSION>-build<BUILD_NUMBER>.dmg`。

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
