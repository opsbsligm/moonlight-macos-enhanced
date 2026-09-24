# 贡献者手册：构建要求、质量门控、项目结构与版本约定

> 读者：准备改代码、提 PR，或想弄清「这个仓库为什么敢说自己没坏」的人。
> 只想用起来的读者请读 [`../README.md`](../README.md)。
> 本页内容自 `README.md` 搬移而来（2026-09-24 文档信息架构重构）。搬移时未重新核数，表里两个数字因此在重构当天就已经过时；下列数字均为 2026-09-24 在本机重新跑出来的实测值。

## 从源码构建的要求

**构建要求：**
- 任何带 macOS SDK 26+ 的 Xcode。本仓库 CI 与本机的实测环境是 Xcode 27.0（27A266a）+ `MacOSX27.0.sdk`，`scripts/compile-audit.py` 按「同一厂商的 clang 与 SDK 成对取」探测工具链，不硬编码版本号
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
| `compile-audit.py` | 每个源文件在每个受支持 SDK 下都能通过类型检查（本机实测 82/82；`Limelight/Crypto/CryptoManager.m` 因需要先跑 `download-frameworks.sh` 才有 vendored 头文件，未准备 `libs/` 的检出会把它记成 SKIP 并明说，而不是算成通过） |
| `swift-typecheck.py` | Swift 侧全树类型检查，并要求它报告的失败形状确实能失败 |
| `constraints-audit.py` | 跨文件的行为约束（配对/输入/生命周期/签名/发布），当前 0 failures |
| `assertion-battery.py` | 行为断言电池：逐条植入本该被拒绝的形状，验证门控真的变红（本机实测 140/140 caught，exit 0） |
| `l10n-audit.py` | 语言表覆盖率、表对称性、UI 出口不得出现未翻译文本、日志正文不得写成某种语言 |
| `workflow-audit.py` / `source-membership-audit.py` | 工作流本身是否真的跑，以及有没有源文件被静默排除在构建之外 |
| `credential-scan-audit.py` | 密钥、令牌、私钥不得进仓库 |

因此「CI 绿了」在这里不是装饰性检查全绿，而是：这些门控都在跑，而且都抓到了自己植入的缺陷。

## 本地化的守护方式

中英双语不是「界面有中文」这么简单，本仓库把它当成有回归风险的功能来守：

- 文本走 key，`Limelight/macOS/{en,zh-Hans}.lproj/Localizable.strings` 与 `LanguageManager` 内置表两级；两张表必须声明同一组 key。
- 日志面板的分类名、徽标、日志行标题与详情都是 key（upstream Issue #30 的第二半），过滤框则同时索引两种语言，所以英文界面也能用中文词搜到。
- **日志正文恒为数据**：`scripts/l10n-audit.py` 拒绝任何用中文写的日志正文——它是 `DebugLogParser` 与噪音折叠要匹配的字符串，翻译它的同时就翻译坏了匹配。
- 权限弹窗的文案属于 `Info.plist`，因此 `scripts/dmg-audit.py` 会逐条比对**已发布镜像里**的语言表与仓库源码，而不是在打包之前看一眼就算过。

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
├── docs/                     # 文档（本页、诊断报告、输入映射设计、轮次历史）
├── spikes/                   # 设计阶段的复现物：结论的证据，不进产品也不进 CI
├── staging/                  # 尚未获得签名授权的实现（驱动扩展），刻意留在产品之外
├── scripts/                  # 构建与 CI/CD 脚本
├── Artwork/                  # 图标素材（Sketch）
├── LICENSE                    # 许可证
└── README.md                  # 本文件
```

## 贡献流程

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

类型：`feat` / `fix` / `refactor` / `perf` / `docs` / `chore` / `style` / `build` / `test` / `ci`
（这是本仓库的**约定**，不是门禁：`scripts/` 下没有任何脚本机器校验 commit 类型。真正被门禁读的是 CHANGELOG 与代码本身。）

## 版本控制

本项目遵循 [Semantic Versioning](https://semver.org/)：
- **主版本号**：不兼容的 API 变更
- **次版本号**：向后兼容的新功能
- **修订号**：向后兼容的 Bug 修复

每个版本通过 Git annotated tag 标记（tag 名即 `v<主>.<次>.<修订>-build<N>`），详见 [CHANGELOG.md](../CHANGELOG.md)。
版本号格式：`v<MARKETING_VERSION>-build<BUILD_NUMBER>`，其中 `BUILD_NUMBER` = `git rev-list --count HEAD`。
产物文件名与 tag **不是**一一对应：镜像按架构命名，
`Moonlight-macOS-Enhanced-{universal,arm64,x86_64}.dmg`，版本号在镜像内部
（`dmg-audit.py` 逐条核对镜像里的版本与 `--build` 传入的期望值，而不是靠文件名对账）。
