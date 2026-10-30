# 对标来源矩阵（source matrix）

> 日期：2026-10-25（Asia/Shanghai）
> 目的：把 `docs/competitive-polish-roadmap-2026-10-20.md` §1 的"证据纪律"落到每个对比对象上，逐格列出**来源 / 平台 / 版本 / 验证日期 / 证据层级 / 未知项**。
> 规则：本矩阵只记录"我们对它的知识从哪里来、能复核到什么程度"，**不新增能力结论**；能力结论仍归 roadmap 与 input-mapping 系列文档。
> 证据四级沿用 `docs/input-mapping-benchmark.md` §1：本仓库可复核 / 上游已验证 / 仅宣传 / 无证据。

## 1. 来源矩阵（我们的对照系）

| 对象 | 来源（仓库/路径） | 平台 | 版本 / 钉住点 | 验证日期 | 证据层级 | 未知项 |
| --- | --- | --- | --- | --- | --- | --- |
| 本项目（moonlight-macos-enhanced） | GitLab `172.16.130.252:8445` project 6，唯一事实源 | macOS (arm64) | main `8945676e`，build 1993 | 2026-10-25 | 本仓库可复核 | 真机验收（全部里程碑 `hardware_validated=false`） |
| 本项目（moonlight-macos-enhanced） | GitLab `172.16.130.252:8445` project 6，唯一事实源；build 号口径见 `Limelight/build-number.sh` | macOS (arm64) | main `71a623943a68987d2bee08f4f97970ce5839d1e1`，build 2058 | 2026-10-31（`git rev-list --count` 本地重算 = 2058；产物名 `Moonlight-1.6.0-build2058.dmg` 经 pipeline 883 job 5448 trace 回读） | 本仓库可复核 | 真机验收（全部里程碑 `hardware_validated=false`）。旧格记 main `8945676e`/build 1993：两者当时自洽（`rev-list --count 8945676e` = 1993），失效方式是**过期**而非错号。门禁能拦的是两类：SM012（SHA 与 build 号不自洽）、SM013（钉的 commit 不在本历史线内）；**门禁看不见"自洽但已落后 main"**，那一格只能随合并人工更新，本行的验证日期就是这个人工动作的凭据 |
| moonlight-common-c（协议 fork） | 子模块 `moonlight-common/moonlight-common-c` | 跨平台 C | `093098f5f8caa8177598bb9fe3016eab70df845b`（`origin/master`，即 `git submodule status` 当前值） | 2026-10-31（`git submodule status` + `git merge-base --is-ancestor` 回读） | 本仓库可复核 | 与上游 `moonlight-stream/moonlight-common-c` 的漂移未逐文件 diff。旧格记 `386e79c976c90d44ca5ace4ada2f053998c3a95c` 是分支 `enhanced/input-edge-queue` 的头，该分支已并入 master（旧值是过期 fork 点，不是错号） |
| moonlight-qt（上游 Qt 客户端） | `moonlight-stream/moonlight-qt`；源码级快照 `docs/evidence/qt-snapshot/README.md` | 多平台（Win/Linux/Android/Steam Deck） | tag `v6.2.0` → commit `de2467e433821664cdd2224aad8c89a625be1ad9`；快照内 `gamepad.cpp` blob `b649971b693beac4c2db5cc89d220b1168161355`、`streamingpreferences.h` blob `ad611f6a28d1e76aff9b983f20bab8e59b0e9449` | 2026-10-31（本地 `git hash-object` 与 GitHub contents API 的 `sha` 双向一致；tag→commit 另见 `docs/evidence/upstream-refs-2026-10-31/qt-tag-v6.2.0.json`） | 上游已验证（源码级：钉到 blob，可复核到具体行；复核命令见快照 README） | 只钉输入层两个文件，未抓 v6.2.0 完整源码树。旧格自述快照已清理、只记到 tag 名，与仓库现状不符——快照实际在库且已钉 blob，属文档落后于证据 |
| Sunshine（主机端） | `LizardByte/Sunshine`；源码级快照 `docs/evidence/sunshine-snapshot/README.md`；release 存在性投影 `docs/evidence/upstream-refs-2026-10-31/sunshine-releases.json` | 多平台（Win/Linux/macOS） | 钉 master 时刻 commit `a679b059096bcdd502e2192ce4f6a3c3732fbaae`（2026-10-28）；快照内 `windows_input.cpp` blob `73f2acf03837ba990f03a0b07c7bb179167ef53e` | 2026-10-31（blob 经本地 `git hash-object` 重算一致；releases 列表与 tag 直探针均已入库） | 上游已验证（源码级：ViGEm 类型选择逐行可复核；另有协议契约——录制基线 gen4/5 报文、C 层 Sunshine-only 门） | **旧格记的 release `v2026.1018.5342`（2026-10-18）不存在，判定为记录错误而非上游改名**：releases 列表无该 tag，`git/ref/tags/` 直探针返回 404，当时最新 stable 是 `v2026.914.233613`（其后的 `v2026.1028.*` 均 prerelease）；此错误按"记错"保留记录，不静默替换成新号。另有未闭合项：快照只覆盖 Windows 平台 input 路径，GFE 主机侧未取证，主机侧验收待真机；`master` 已前进到 `2c8825ad5b66cf9750f8154691202f0cd8768ac0`（见同目录 `sunshine-master.json`），快照未跟进 |
| 基地版（skyhua0224 fork） | `skyhua0224/moonlight-macos-enhanced`；头指针投影 `docs/evidence/upstream-refs-2026-10-31/skyhua0224-master.json` | macOS | `master` 头 commit `c4dd84daa6440468f4e9a2e48f8c482f24bec965`（2026-10-27T06:09:06Z） | 2026-10-31（GitHub commits API 回读） | 上游已验证（机制级：仓库头指针可复核；本仓库起点，diff 历史可查） | 未逐文件比对该 master 与本仓库分叉后的差异（独立后不再对照）。旧格只记"最后推送 2026-10-13"、无 commit，已过期 14 天且不可复核 |

## 2. 竞品矩阵（证据等级封顶，不直接对照手感）

| 产品 | 来源 | 平台/赛道 | 版本 | 验证日期 | 证据层级 | 未知项 |
| --- | --- | --- | --- | --- | --- | --- |
| Citrix（客户端输入模型） | `FlorianSLZ/scloud` 钉 commit `2f32dfbfbb3c5855d87da8a5b874191afc9c5d37` 的 `Policies/ADMX/Citrix/Receiver-Intune.admx`；`fwmechanic/shell/citrix_alttab`；真实 `.ica` 文件 | Windows 为主 | ADMX 钉住 commit（仓库名 `scloud`，非 sclood——早期文档笔误已核） | 2026-10-25（钉住 URL 回读 HTTP 200；仓库 API 可达） | 上游已验证（机制级：可配热键表 + USB PNP 设备规则，摘自 ADMX 本身；119 个 policy 中 0 处提及 horizon） | 非运行时实测；不比较手感 |
| Citrix Horizon | 同上 ADMX 证据 + 官方文档 | Windows/全平台 | 未钉版本（Horizon 产品侧无公开可钉构件；机制证据继承上一行 Citrix 客户端格钉住的 ADMX commit） | 2026-10-25 | 上游已验证（机制级）+ 仅宣传（产品能力） | 归属已核（2026-10-26）：ADMX 命名空间 `receiver.Policies.receiver`、119 个 policy、0 处提及 horizon，且 `<supersededAdm fileName="icaclient.adm"/>` ——是**通用 ICA Client**（覆盖 Horizon + classic Receiver + DaaS），非 Horizon 专用；"三级键盘捕获"措辞无 ADMX 直接支撑，已改为"可配热键表 + USB PNP 设备规则"；仍无运行时证据 |
| Parsec | ①`parsec.com` 官网（2026-10-25 回读 302→首页可达）；②本机安装的 `Parsec.app` 内 `Contents/Resources/skel/parsecd-150-101a.dylib` 字符串表，快照与复核命令见 `docs/evidence/parsec-snapshot/README.md` | Win/macOS/Linux/iOS/Android | 客户端 `150.101.1`（`CFBundleVersion` 同值），被检 dylib SHA-256 `9cce8505…c596cdd5` | 2026-10-30（dylib 按 SHA-256 钉住；官网仍 2026-10-25） | 机制级证据（配置键 `host_virtual_mouse`/`host_virtual_tablet`/`host_gamepad_mode`/`host_gamepad_type`/`host_exclusive_input`/`client_png_cursor` + `ViGEm`/`ViGEmBus`/`vigem_installed`/Karabiner 虚拟 HID 字符串）；官网部分仍是**仅宣传** | 未反汇编取值域、未抓包、未观察主机设备枚举；未出现 DS4/DualSense/Switch 标识不能证明其不支持；禁止任何"我们超过 Parsec"类断言 |
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

