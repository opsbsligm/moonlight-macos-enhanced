# Moonlight for macOS — Enhanced Edition

[![Release](https://img.shields.io/github/v/release/opsbsligm/moonlight-macos-enhanced?label=release&color=blue)](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%2026%2B-lightgrey)](https://developer.apple.com/macos/)
[![Upstream](https://img.shields.io/badge/fork%20from-skyhua0224%2Fmoonlight--macos--enhanced-blue)](https://github.com/skyhua0224/moonlight-macos-enhanced)

一个 fork 自 [skyhua0224/moonlight-macos-enhanced](https://github.com/skyhua0224/moonlight-macos-enhanced) 的增强版，该项目本身衍生自 [Moonlight Game Streaming Project](https://github.com/moonlight-stream)。本仓库专注于低延迟串流体验与工业标准键盘映射。

## 核心特性

### 串流标准键盘映射
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
- HDR 支持，以及 HDR→SDR 的 tone mapping 策略选择（含 `No Exposure Shift` 档）
- 多声道音频 + 麦克风传输
- 虚拟手柄 (Xbox 360)，含 Xbox Elite 2 / Betop Zeus 等设备识别修正
- Core HID 高精度鼠标输入，锁鼠/自由鼠标两种模式
- 实时性能叠加层，以及视频管线的运行时状态（MetalFX、VideoToolbox 插帧是否真的生效）
- 中英双语界面（含菜单、权限弹窗、日志面板，见下文「本地化」）

### v1.3.10 起新增或改变的行为

每一项都对应设置页里一个能看见的开关，而不是一句「优化了体验」：

- **指针进入开关**：鼠标指针是否随指针捕获进入串流窗口，可关（upstream Issue #21 / #40）。
- **Menu 长按开关**：长按 Menu 键切换鼠标模式，可关；每次按下都重新读取开关，所以中途改动不会留下半按状态（upstream PR #45 的行为缺口已避开）。
- **Command → Control 开关**：需要 Win 键的场合保留 ⌘=Win，需要 Ctrl 组合键的场合可把 ⌘ 映射成 Ctrl。
- **SAS 预设**：Ctrl+Alt+Del 有一个可绑定的预设快捷键，不必再手打三个键。
- **设置成为主窗口内的一页**，并且「返回」真的能返回。
- **单一选项不再伪装成菜单**：只有一个候选值的下拉框退化为静态文本。
- **一个手势只用一个时钟**：长按判定的两处计时合并为一处（详见 `CHANGELOG.md`）。

### 本地化

中英双语不是「界面有中文」这么简单，本仓库把它当成有回归风险的功能来守：

- 文本走 key，`Limelight/macOS/{en,zh-Hans}.lproj/Localizable.strings` 与 `LanguageManager` 内置表两级；两张表必须声明同一组 key。
- 日志面板的分类名、徽标、日志行标题与详情都是 key（upstream Issue #30 的第二半），过滤框则同时索引两种语言，所以英文界面也能用中文词搜到。
- **日志正文恒为数据**：`scripts/l10n-audit.py` 拒绝任何用中文写的日志正文——它是 `DebugLogParser` 与噪音折叠要匹配的字符串，翻译它的同时就翻译坏了匹配。
- 权限弹窗的文案属于 `Info.plist`，因此 `scripts/dmg-audit.py` 会逐条比对**已发布镜像里**的语言表与仓库源码，而不是在打包之前看一眼就算过。

## 下载安装

### 方式一：下载 DMG（推荐）
1. 从 [Releases](https://github.com/opsbsligm/moonlight-macos-enhanced/releases/latest) 下载最新的 `Moonlight-<版本>.dmg`（每个版本提供 arm64、x86_64、universal 三个镜像，各自附带 sha256）
2. 打开 DMG，将 Moonlight 拖入 Applications
3. 首次运行时，在「系统设置 → 隐私与安全性」中允许运行

### 方式二：从源码构建
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

**构建要求：**
- Xcode 26.x（macOS SDK 26+）
- 运行时 macOS 26.0+：`MACOSX_DEPLOYMENT_TARGET = 26.0`，Liquid Glass 窗口层依赖该版本
- 如需支持 macOS 15/12（upstream Issue #26），必须调低 deployment target 并改造依赖 26.x API 的窗口层代码

> 说明：`scripts/download-frameworks.sh` 会把 OpenSSL 头文件链接到 `libs/`，
> `moonlight-common.xcodeproj` 通过 `HEADER_SEARCH_PATHS = ../libs/**` 解析它们。
> `libs/` 被 gitignore 排除，因此首次构建前必须执行该脚本，否则 common-c 编译失败。

## 质量门控（CI/CD）

每个 push 与 PR 都会跑 `scripts/` 下的门控；它们的共同点是**必须证明自己会失败**——
每个门控都带 self-test，植入若干「本该被拒绝的形状」，一次都没抓到就等于没在跑。

| 门控 | 守的是什么 |
|:---|:---|
| `release-gate.py` | 发布前的总闸；标签、版本号、CHANGELOG 三者对得上同一棵树 |
| `prepare-release.py` | 版本号只有一个来源：`git rev-list --count HEAD` |
| `dmg-audit.py` | 用户真正下载的镜像：架构、版本、校验和，以及镜像内的本地化表 |
| `compile-audit.py` | 每个源文件在每个受支持 SDK 下都能通过类型检查（当前 49/49） |
| `swift-typecheck.py` | Swift 侧全树类型检查，并要求它报告的失败形状确实能失败 |
| `constraints-audit.py` | 行为断言电池（当前 108/108 个植入缺陷被抓到） |
| `l10n-audit.py` | 语言表覆盖率、表对称性、UI 出口不得出现未翻译文本、日志正文不得写成某种语言 |
| `workflow-audit.py` / `source-membership-audit.py` | 工作流本身是否真的跑，以及有没有源文件被静默排除在构建之外 |
| `credential-scan-audit.py` | 密钥、令牌、私钥不得进仓库 |

因此「CI 绿了」在这里不是装饰性检查全绿，而是：这些门控都在跑，而且都抓到了自己植入的缺陷。

## 文档

| 文档 | 内容 |
|:---|:---|
| [`docs/input-mapping-benchmark.md`](docs/input-mapping-benchmark.md) | 键盘/鼠标映射对标 Parsec、UU 远程、Citrix、moonlight-qt 的逐项结论 |
| [`docs/usb-redirection-design.md`](docs/usb-redirection-design.md) | USB 设备重定向的设计与取舍 |
| [`docs/usb-redirection-host-contract.md`](docs/usb-redirection-host-contract.md) | 上述功能需要主机端配合的契约 |
| [`docs/upstream-issue-status.md`](docs/upstream-issue-status.md) | 上游每个 open issue 的核对结论：已修、待补充信息、依赖外部条件，还是我们该做 |
| [`CHANGELOG.md`](CHANGELOG.md) | 逐版本变更，含每条修复的根因而非结论 |

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

每个版本通过 Git annotated tag 标记（tag 名即 `v<主>.<次>.<修订>-build<N>`），详见 [CHANGELOG.md](CHANGELOG.md)。
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
