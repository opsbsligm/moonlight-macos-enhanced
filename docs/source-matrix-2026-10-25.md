# 对标来源矩阵（source matrix）

> 日期：2026-10-25（Asia/Shanghai）
> 目的：把 `docs/competitive-polish-roadmap-2026-10-20.md` §1 的"证据纪律"落到每个对比对象上，逐格列出**来源 / 平台 / 版本 / 验证日期 / 证据层级 / 未知项**。
> 规则：本矩阵只记录"我们对它的知识从哪里来、能复核到什么程度"，**不新增能力结论**；能力结论仍归 roadmap 与 input-mapping 系列文档。
> 证据四级沿用 `docs/input-mapping-benchmark.md` §1：本仓库可复核 / 上游已验证 / 仅宣传 / 无证据。

## 1. 来源矩阵（我们的对照系）

| 对象 | 来源（仓库/路径） | 平台 | 版本 / 钉住点 | 验证日期 | 证据层级 | 未知项 |
| --- | --- | --- | --- | --- | --- | --- |
| 本项目（moonlight-macos-enhanced） | GitLab `172.16.130.252:8445` project 6，唯一事实源 | macOS (arm64) | main `8945676e`，build 1993 | 2026-10-25 | 本仓库可复核 | 真机验收（全部里程碑 `hardware_validated=false`） |
| moonlight-common-c（协议 fork） | 子模块 `moonlight-common/moonlight-common-c` | 跨平台 C | `386e79c976c90d44ca5ace4ada2f053998c3a95c`（分支 `enhanced/input-edge-queue`） | 2026-10-25（git submodule status 回读） | 本仓库可复核 | 与上游 `moonlight-stream/moonlight-common-c`（最后推送 2026-10-24）的漂移未逐文件 diff |
| moonlight-qt（上游 Qt 客户端） | `moonlight-stream/moonlight-qt` | 多平台（Win/Linux/Android/Steam Deck） | 最新 release `v6.2.0`（2026-10-04）；本文取证基于抓取快照（`/tmp/qt_gamepad.cpp`、`streamingpreferences.h`，抓取时 HTTP 200，快照文件现已清理，未钉 commit） | 2026-10-25（release 经 GitHub API 回读）；快照抓取日期见 roadmap §1 | 上游已验证 | 快照未钉 commit/SHA，无法复核到具体行；未抓 v6.2.0 完整源码树 |
| Sunshine（主机端） | `LizardByte/Sunshine` | 多平台（Win/Linux/macOS） | 最新 release `v2026.1018.5342`（2026-10-18） | 2026-10-25（release 经 GitHub API 回读） | 上游已验证（协议契约：录制基线 gen4/5 报文、C 层 Sunshine-only 门） | 未抓源码逐行核对虚拟手柄类型/震动/触摸板行为；主机侧验收待真机 |
| 基地版（skyhua0224 fork） | `skyhua0224/moonlight-macos-enhanced` | macOS | 默认分支 `master`，最后推送 2026-10-13；本仓库 2026-10 起独立（README 声明） | 2026-10-25（GitHub API 回读） | 上游已验证（本仓库起点，diff 历史可查） | 其 master 后续演进未跟踪（独立后不再对照） |

## 2. 竞品矩阵（证据等级封顶，不直接对照手感）

| 产品 | 来源 | 平台/赛道 | 版本 | 验证日期 | 证据层级 | 未知项 |
| --- | --- | --- | --- | --- | --- | --- |
| Citrix（客户端输入模型） | `FlorianSLZ/scloud` 钉 commit `2f32dfbfbb3c5855d87da8a5b874191afc9c5d37` 的 `Policies/ADMX/Citrix/Receiver-Intune.admx`；`fwmechanic/shell/citrix_alttab`；真实 `.ica` 文件 | Windows 为主 | ADMX 钉住 commit（仓库名 `scloud`，非 sclood——早期文档笔误已核） | 2026-10-25（钉住 URL 回读 HTTP 200；仓库 API 可达） | 上游已验证（机制级：热键表 + 三级键盘捕获，摘自 ADMX 本身） | 非运行时实测；不比较手感 |
| Citrix Horizon | 同上 ADMX 证据 + 官方文档 | Windows/全平台 | 同上 | 2026-10-25 | 上游已验证（机制级）+ 仅宣传（产品能力） | ADMX 归属（Horizon 专用 vs 通用 Receiver）未逐节核对；无运行时证据 |
| Parsec | `parsec.com` 官网（2026-10-25 回读 302→首页可达） | Win/macOS/Linux/iOS/Android | 未钉版本 | 2026-10-25 | **仅宣传**（无源码/协议证据） | 禁止任何"我们超过 Parsec"类断言 |
| 网易 UU 远程 | `uu.163.com` 官网（2026-10-25 回读 200） | 手机→PC 为主 | 未钉版本 | 2026-10-25 | **仅宣传**（300+ 触屏按键映射方案，宣传页可见） | 与 macOS 桌面客户端不同赛道，不直接对照 |
| 深信服 aDesk | `sangfor.com.cn` 官网（2026-10-25 回读 200） | Windows 云桌面为主 | 未钉版本 | 2026-10-25 | **仅宣传 / 待调研** | 输入映射细节无公开可复核来源 |
| 锐捷云桌面 | `ruijie.com.cn` 官网（2026-10-25 回读 200） | Windows 云桌面为主 | 未钉版本 | 2026-10-25 | **仅宣传 / 待调研** | 输入映射细节无公开可复核来源 |

## 3. 证据层级纪律（执行时引用本矩阵）

- 引用"我们 vs X"的能力结论时，必须同时给出 X 所在的证据层级；`仅宣传` 级不得用于设计决策或对外断言。
- `上游已验证` 必须可复核：钉 commit/SHA 或给出可重跑的抓取命令（见 `docs/input-mapping-benchmark.md` §6 取证命令）。
- 本矩阵中所有"未钉版本"条目，在下次触碰对应结论前必须先钉住版本。
- 竞品官网可达性（HTTP 200/302）只证明"来源存在"，不证明任何功能声明。

## 4. 与旧矩阵的关系

- `docs/competitive-polish-roadmap-2026-10-20.md` §2.5 的竞品段落保留为历史能力结论；本文件是其**来源侧**补全，两者冲突时以本文件的来源证据为准重判等级。
- `docs/input-mapping-benchmark.md` 的 §2 Sources 表仍是输入面结论的权威来源；本文件不重复其结论。

