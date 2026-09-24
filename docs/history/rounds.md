# 版本演进与开发记录归档

> 读者：想知道「某个行为是哪一轮引进来的」的人，以及整理文档的人。
> 本页只做**归档与去重**：逐轮完整流水的唯一真相源是仓库根目录的
> [`../../CHANGELOG.md`](../../CHANGELOG.md)（含每条修复的根因），本页不复制它，
> 以免出现第二个会各自漂移的流水账。
> 下面第一节是从 `README.md` 原文搬来的版本性小节（2026-09-24 文档信息架构重构），事实未删改。

## v1.3.10 起新增或改变的行为

每一项都对应设置页里一个能看见的开关，而不是一句「优化了体验」：

- **指针进入开关**：鼠标指针是否随指针捕获进入串流窗口，可关（upstream Issue #21 / #40）。
- **Menu 长按开关**：长按 Menu 键切换鼠标模式，可关；每次按下都重新读取开关，所以中途改动不会留下半按状态（upstream PR #45 的行为缺口已避开）。
- **Command → Control 开关**：需要 Win 键的场合保留 ⌘=Win，需要 Ctrl 组合键的场合可把 ⌘ 映射成 Ctrl。
- **SAS 预设**：Ctrl+Alt+Del 有一个可绑定的预设快捷键，不必再手打三个键。
- **设置成为主窗口内的一页**，并且「返回」真的能返回。
- **单一选项不再伪装成菜单**：只有一个候选值的下拉框退化为静态文本。
- **一个手势只用一个时钟**：长按判定的两处计时合并为一处（详见 `CHANGELOG.md`）。

> 归档说明：本节标题沿用了搬移时的版本号写法。仓库另有「README 与下载入口不写死版本号」的约定
> （见 `.github/release-notes/v1.3.10-build1544.md`），版本性内容放进归档页正是为了让那条约定
> 在 `README.md` 里成立；本节标题作为历史原文保留。

## 本次文档重构的搬移对照（2026-09-24）

| 原 `README.md` 章节 | 新位置 |
|:---|:---|
| 核心特性 › 串流标准键盘映射（映射表与三条承诺） | [`../input-mapping-design.md`](../input-mapping-design.md) |
| 核心特性 › v1.3.10 起新增或改变的行为 | 本页上一节 |
| 核心特性 › 本地化（守护方式） | [`../contributing.md`](../contributing.md) |
| 质量门控（CI/CD） | [`../contributing.md`](../contributing.md) |
| 项目结构 | [`../contributing.md`](../contributing.md) |
| 键盘映射设计文档（设计原则、修复的关键 Bug 根因） | [`../input-mapping-design.md`](../input-mapping-design.md) |
| 反馈问题（报告内容清单、输入诊断前提、脱敏规则） | [`../diagnostics-report.md`](../diagnostics-report.md) |
| 贡献指南 / Commit 规范 / 版本控制 | [`../contributing.md`](../contributing.md) |
| 下载安装 › 方式二的构建要求与 `libs/` 说明 | [`../contributing.md`](../contributing.md) |

文档索引见 [`docs/README.md`](../README.md)。
