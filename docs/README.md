# 文档索引

> 这里是全部设计文档与记录的入口。使用者不需要读完它们：
> 只想把串流跑起来，请读 [`../README.md`](../README.md)（是什么、怎么装、边界在哪、怎么反馈）。
>
> 本页存在的理由：`README.md` 只承担「决定要不要用这个项目」所需的最少信息，
> 其余按读者拆开，避免一个文件同时服务评估者、贡献者和取证者。

## 面向使用者与支持者

| 文档 | 读者 | 目的 |
|:---|:---|:---|
| [`../README.md`](../README.md) | 评估者、新装机用户 | 项目是什么、与上游的差异、下载安装、快速开始、当前边界、反馈入口、许可 |
| [`diagnostics-report.md`](diagnostics-report.md) | 要提交问题报告的用户 | 诊断报告里具体有哪些字段、为什么鼠标问题必须先开输入诊断、离开本机前如何脱敏 |
| [`upstream-issue-status.md`](upstream-issue-status.md) | 想知道上游 open issue 到底算什么状态的人 | 逐个 issue 的核对结论：本分支已修、缺信息、依赖外部条件，还是我们该做（英文） |

## 面向贡献者

| 文档 | 读者 | 目的 |
|:---|:---|:---|
| [`contributing.md`](contributing.md) | 准备改代码、提 PR 的人 | 构建要求、质量门控清单与它们各自守住什么、项目结构、贡献流程与 Commit 规范、版本与 tag 约定 |
| [`repository-layout.md`](repository-layout.md) | 维护协议与客户端的人 | 单仓结构、依赖版本、历史仓用途与修改流程 |
| [`input-mapping-design.md`](input-mapping-design.md) | 改输入路径之前必读的人 | 键盘映射表与其四条设计原则、「双击鼠标触发开始菜单」的根因与修复方式 |
| [`input-mapping-benchmark.md`](input-mapping-benchmark.md) | 想验证「竞争力」这个说法的人 | 键盘/鼠标映射逐项对标 Parsec、UU 远程、Citrix、moonlight-qt 的结论与取证纪律（英文） |

## 设备重定向与主机契约

| 文档 | 读者 | 目的 |
|:---|:---|:---|
| [`usb-redirection-design.md`](usb-redirection-design.md) | 评估重定向可行性的人 | 可行性结论、架构分层、CI 基线，以及为什么设备页只做诊断 |
| [`usb-redirection-host-contract.md`](usb-redirection-host-contract.md) | 主机端（Sunshine 等）实现者 | 客户端已就位的那半与主机必须答的那半之间的可评审契约（提案状态） |
| [`windows-auto-signin-design.md`](windows-auto-signin-design.md) | 关注 issue #43 的人 | 保存 Windows 凭据这件事在写代码之前必须先回答的三个问题（英文） |

## 历史与记录

| 文档 | 读者 | 目的 |
|:---|:---|:---|
| [`history/rounds.md`](history/rounds.md) | 追溯某个行为来源的人 | 从 `README.md` 归档出来的版本性小节，以及 2026-09-24 文档重构的搬移对照表 |
| [`history/incidents/`](history/incidents/) | 追溯某段早期行为来源的人 | 2026-09-27 至 2026-10-31 的历史工作文档与故障记录（点击 C 事故、输入审查、VT/插帧压测、USB 侧栏等），结论已被后续文档与 CHANGELOG 吸收，路径随本目录搬移更新 |
| [`history/design/`](history/design/) | 评审对象存储与用户记忆设计的人 | 设计评审稿与 `spikes/` 复现物（2026-10 从仓库根搬入，结论已归档，不充当现行事实源） |
| [`../CHANGELOG.md`](../CHANGELOG.md) | 所有需要逐轮流水的人 | 逐版本变更与每条修复的根因——**逐轮记录的唯一真相源**，其它文档不复制它 |

> 开发波次的工作文档（2026-10-20 起对标作战四件套：目标模式提示词、作战计划、基线、
> 对标路线图）描述的是**当时**的波次契约与证据，会随合并过期，不作为当前功能的事实源；
> 当前状态以 `main` 的 CI 与 `hardware-acceptance-checklist.md` 为准。Wave AO 起它们
> 只保存在开发机本地（路径见根 `AGENTS.md`），不再入库——镜像是公开的，波次文档带着
> 本机主机名与账号；公开读者需要知道"我们对照了谁、证据层级是什么"，那部分留在
> [`source-matrix-2026-10-25.md`](source-matrix-2026-10-25.md) 与
> [`input-mapping-benchmark.md`](input-mapping-benchmark.md)，由 `source-matrix-audit.py` 把守。

## 三份文档的职责边界

- `README.md`：装与用、能与不能、如何反馈。不写实现细节。
- 本页与各设计文档：为什么这样设计、证据是什么。
- `CHANGELOG.md` 与 [`history/rounds.md`](history/rounds.md)：发生过什么。
