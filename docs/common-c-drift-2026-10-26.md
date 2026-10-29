# moonlight-common-c fork 漂移审计（2026-10-26）

目的：给 M3/M4/K 线后续是否回吸上游定依据。只记事实，不把"建议"当已实施。

> 2026-10-30 状态更新（不重写下面的原始审计，只标注处置结果）：本文"锚点"表里的
> fork 侧 HEAD `386e79c` 是 2026-10-26 当时的 submodule pin，**已过时**。
> main 的 pin 现为 `abe83b8`（Wave G-2 后），Wave G-3 合入后为 `093098f5`。
> "未取待定"表中 RFI 修复族已处置完，见下。
>
> 2026-10-30（Wave M-2）：下面"未取待定"五项已全部做完源码级评估，结论与证据见
> §未取待定项的源码级评估。其中 `41cedb8`、`5d3c0ec` 两项经核实**fork 早已具备**，
> 原先挂在待定里是审计漏判，不是待办。全部评估只改文档，未动一行子模块代码。

## 锚点（均可复核）

| 项 | 值 |
| --- | --- |
| fork 点（merge-base） | `62687809b1f7410c3db4be2527503a54ae408d70`（"Bump enet from 78cc9b4 to c7353c0"），在上游历史中 |
| fork 侧 HEAD（本仓 submodule pin） | `386e79c976c90d44ca5ace4ada2f053998c3a95c`（`remotes/origin/enhanced/input-edge-queue`） |
| 上游 HEAD（moonlight-stream/moonlight-common-c master） | `5d3c0ec`（"Add missing IDX_DS_ADAPTIVE_TRIGGERS sentinel to packetTypesGen3..7"），2026-10-26 当时记的是 `41cedb8`，其后上游又进一个 commit |
| moonlight-qt v6.2.0 pin 的 common-c | `f900dd4767759c7b9d0e93bcea666b55c69ea62f`（"Add MODIFIER_EXTENDED flag"），**不是** fork 点祖先 |

## 规模

- fork 侧独有 commit：38（fork 点 → 386e79c）
- 上游侧独有 commit：31（fork 点 → 41cedb8）
- 上游侧 diff：35 files, +874/−5922（大头是 nanors 子模块化 + rswrapper 删除）
- fork 侧 diff：27 files, +9219/−5489
- **两侧同时修改的交集文件：17 个**（回吸时的主要冲突面）

## fork 侧 38 commit 归类

| 类 | commit（代表性） | 说明 |
| --- | --- | --- |
| 有意分叉（我们的功能线） | `6c8e931..859f95d` microphone 协议族（含加密上行、地址缓存、诊断 hooks）；`d4d4100`/`5f4dc68` HDR HLG + dynamic-range negotiation；`991396a`/`f262d59` clipboard sync；`607ea68` 7.1.4 surround；`7a7f3e2` 去启动鼠标唤醒 | qiin/Yundi 麦克风流 + 我们自研协议扩展 |
| 有意分叉（签名 commit） | `386e79c` input edge queue | 本仓标志性 commit |
| qiin merge 噪声 | `2fec3dc`、`ecc3964`、`37953cd`、`d41a630`、`e9cea63`、`488bbf9` 等 merge/stash/tune | 回吸时需逐 commit 判断，不能整支 rebase |

## 上游侧 31 commit：按"建议回吸 / 不取 / 未取待定"三类标注

### 建议回吸（与 M3/M4/K 线直接相关，证据在上游源码）

| commit | 内容 | 影响文件 |
| --- | --- | --- |
| `874ac95` | `LI_CTYPE_STEAM` 控制器类型 | `src/Limelight.h`（+1 行） |
| `2600bea` | dual touchpad 支持（`LI_CCAP_DUAL_TOUCHPAD` + index 1） | `src/Input.h`、`src/InputStream.c`、`src/Limelight.h`（+22 行） |
| `4a95eb3` | UTF-8 事件改走 keyboard channel（避免与键盘事件竞态）——与 K1.1 文本路径直接相关 | `src/InputStream.c` |
| `f900dd4` | `MODIFIER_EXTENDED` flag | `src/Limelight.h`、`src/InputStream.c` |
| `0405384` | NV_UNICODE_PACKET dense packing（Sunshine 兼容） | `src/InputStream.c` |
| `970b072` | 修复 queued controller packets use-after-free | `src/InputStream.c` |
| `448b2c6`/`421bd74` | 鼠标 delta latch / batch 收尾修复 | `src/InputStream.c` |

### 不取（与当前构建路径无关，取来只是负担）

| commit | 理由 |
| --- | --- |
| `40d8731`/`82e2514`/`99c45d3`/`47b4d33` | NXDK/3DS/GCC 平台支持，macOS 构建不经过 |
| `1f76427`/`e41355e`/`2ea4775`/`6d0f73e`/`5a26329` | nanors 子模块化与 bump、License——fork 侧仍用 vendored reedsolomon，子模块化是单独决策 |
| `518b244` | MbedTLS PSA API 重写，fork 侧 PlatformCrypto.c 已分叉 54 行，重写风险大于收益 |
| `aeba988`/`5ec8397`/`e2722dc`/`7b026e7` | RTSP parser 重写族——fork 侧 RtspConnection.c 已重写 2802 行，冲突面最大，建议单独立项而不是搭车回吸 |

### 未取待定 → 已评估处置（Wave M-2，2026-10-30）

| commit | 备注 |
| --- | --- |
| `d85371c`/`be43885`/`62e0663` | **已处置（Wave G-3，2026-10-30）**：fork 侧 `5340b26`/`c759034`/`49cfe3a` 已逐 hunk 等价移植，子模块 merge `093098f5`，主仓 bump `6e1aa0b1`（MR 32）。等价性取证与 fork 侧行号见 `docs/goal-mode-prompt.md` §3.5；真机弱网收益待取证 |
| `342b106` | **建议回吸，但须真机验证**（见下 §评估 1）。唯一有真实收益的一项，收益在我们的 clipboard 大分块路径上 |
| `41cedb8` | **已在 fork**，原判定作废。fork 侧等价实现来自 `f65f5b3`（Wave E-B），带 `ctx->peer` 适配 |
| `f1cca2d` | **不取**。我们没有任何 pen 事件生产路径，这是死代码修复（见下 §评估 3） |
| `7022b33` | **不适用**。整段在 `__MINGW32__` 分支内，macOS 走 `#else` BSD 路径，且全仓无 `EMSGSIZE` 使用 |
| `1fddbcb` | **形态不适用**。上游那次改动是把定义搬进 `.c` 加前向声明，动因是上游删了 `rswrapper.h`；fork 根本没有 `src/rswrapper.h`，改的是 `../reedsolomon/rs.h`，不能照搬（见下 §评估 5） |

## 未取待定项的源码级评估（2026-10-30，Wave M-2）

判定口径：吸收 / 拒绝 / 不适用，每项给可复核证据。全部结论来自当前 submodule
（pin `093098f5`）与 `upstream/master`（`5d3c0ec`）的源码对比，**不含任何真机结论**。

### 1. `342b106` control stream 加密 in-place 化 —— 建议回吸（须真机验证）

- 上游现在直接把明文构造在密文目的地：
  `packet = (PNVCTL_ENET_PACKET_HEADER_V2)(((unsigned char*)(encPacket + 1)) + AES_GCM_TAG_LENGTH)`，
  `encryptControlMessage()` 就地加密（输入输出同地址）。
- fork 侧 `sendMessageEnet()` 仍是 `char tempBuffer[256]` + 超限 `malloc` 回退，
  该回退由我们的 `991396a` clipboard sync 引入（`LI_CLIPBOARD_MAX_CHUNK_SIZE 16384`，
  见 `src/Limelight-internal.h:93`、`src/ControlStream.c:2322`）。
- 因此两者互斥且有净收益：取 in-place 后可同时删掉 `tempBuffer` 与 `malloc` 分支，
  每个 >256B 剪贴板分块少一次堆分配加一次整块 memcpy。
- 未闭合风险（所以只写"建议"，不写"已完成"）：需确认 macOS 实际 crypto 后端在
  in-place 下的行为——`PlatformCrypto.c` 有 MbedTLS(`auth_encrypt_ext` 后接 memmove 挪 tag)
  与 OpenSSL(`EVP_EncryptUpdate`) 两条路径，且 fork 的 `USE_MBEDTLS` 默认 OFF。
  真机至少覆盖：配对新主机、>256B 文本剪贴板同步、rumble/LED 控制包。

### 2. `41cedb8` ENet disconnect 只对本机 peer 生效 —— 已在 fork（原待定作废）

- `git show 41cedb8` 的 peerID/sessionID/`enet_address_equal` 三重校验，fork 在
  `src/ControlStream.c` 的 `ignoreDisconnectIntercept()` 已有等价实现，差异仅是
  全局 `peer` 换成 `ctx->peer`（fork 的多连接上下文化），来源 `f65f5b3`（Wave E-B）。
- 复核：`git log -S 'incomingPeerID' -- src/ControlStream.c` → `f65f5b3`。

### 3. `f1cca2d` pen event batching —— 不取

- 修的是 toolType 未参与批处理判定、批内 `enetPacketFlags` 未合并（RELIABLE 丢失）两点，
  上游侧真实存在；但我们这侧**没有任何 pen 生产者**：
  `grep -rn "LiSendPenEvent|LiSendTouchEvent" --include=*.m --include=*.mm --include=*.swift Limelight/`
  命中 0 个文件，`toolType` 只在子模块内部流转。
- fork 的 `src/InputStream.c` 已整体 ctx 化重写，移植有成本而用户可见收益为零。
  若日后接 Apple Pencil / 触控笔事件，再连同此修复一起取。

### 4. `7022b33` BSD socket 错误重构 + EMSGSIZE —— 不适用

- 全部改动落在 `src/PlatformSockets.h` 的 `__MINGW32__`（改为逐项 `#ifdef/#undef`）与
  新增 `EMSGSIZE → WSAEMSGSIZE` 映射；macOS 编译走 `#else` 的 BSD 分支，只 `#include <errno.h>`。
- `grep -rn EMSGSIZE src/` 在 fork 无任何使用点，取来只是无用差异。

### 5. `1fddbcb` 不要把 rswrapper 漏进头文件 —— 形态不适用

- 上游动因是它已删除 `src/rswrapper.h`，于是把 `reed_solomon` 定义移进
  `RtpAudioQueue.c`、头文件只留前向声明。
- fork **不存在 `src/rswrapper.h`**，`src/RtpAudioQueue.h:5` 引的是 `../reedsolomon/rs.h`，
  而 `reed_solomon` 的定义就在 `reedsolomon/rs.h:7`；`RtpAudioQueue.c` 还直接解引用
  `queue->rs->m` / `->parity`（`src/RtpAudioQueue.c:62-63`），照搬前向声明会直接编译不过。
- 同类"内部实现头经 `Limelight-internal.h` 外泄"的问题在 fork 里确实存在，但没有任何
  app 侧消费者引用 `reed_solomon`（全 `Limelight/` 命中 0），属可选整理项，
  不得计入"上游修复已吸收"。

### 6. `5d3c0ec` 给 packetTypesGen3..7 补 Adaptive Triggers 哨兵 —— 已在 fork

- 上游这次是给 `packetTypesGen3/4/5/7` 各补一个 `-1, // Set Adaptive Triggers (unused)`，
  修的是 `IDX_DS_ADAPTIVE_TRIGGERS` 加入后表长不足、控制路径按索引读越界。
- fork 侧五张表（含 `packetTypesGen7Enc` 的 `0x5503`）都已带该槽位，并且我们把它升级成
  编译期约束：`src/ControlStream.c` 的 `ASSERT_CONTROL_TABLE_SIZE()` 对五张表逐一
  `_Static_assert` 表长 == `IDX_CLIPBOARD + 1`，注释里点名了上游这个越界动因。
- 复核：`grep -n "Set Adaptive Triggers" src/ControlStream.c` 命中 5 处；
  `git merge-base --is-ancestor 5d3c0ec HEAD` 为否，说明是等价自研而非已合并该 commit。

### 评估后的净待办

- 只剩 `342b106` 一项可开工，且必须先有真机窗口做加密控制路径回归；无可离线完成的子步骤。
- 本轮把"未取待定"从 5 项收敛到 1 项，其余 4 项分别落到已在 fork / 不取 / 不适用，
  不再作为未完成任务重复出现在下一波的清单里。

## 回吸时的已知冲突面（17 个交集文件）

`CMakeLists.txt`、`src/ControlStream.c`、`src/Input.h`、`src/InputStream.c`、`src/Limelight-internal.h`、`src/Limelight.h`、`src/Platform.c`、`src/PlatformCrypto.c`、`src/PlatformSockets.c`、`src/RtpAudioQueue.c`、`src/RtpAudioQueue.h`、`src/RtpVideoQueue.c`、`src/RtspConnection.c`、`src/SdpGenerator.c`、`src/VideoDepacketizer.c`、`src/rswrapper.c`、`src/rswrapper.h`

`src/InputStream.c` 两侧改动量都很大（fork +3202 行级重写、上游 +343 行），是回吸的主要战场。
