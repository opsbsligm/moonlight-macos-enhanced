# moonlight-common-c fork 漂移审计（2026-10-26）

目的：给 M3/M4/K 线后续是否回吸上游定依据。只记事实，不把"建议"当已实施。

## 锚点（均可复核）

| 项 | 值 |
| --- | --- |
| fork 点（merge-base） | `62687809b1f7410c3db4be2527503a54ae408d70`（"Bump enet from 78cc9b4 to c7353c0"），在上游历史中 |
| fork 侧 HEAD（本仓 submodule pin） | `386e79c976c90d44ca5ace4ada2f053998c3a95c`（`remotes/origin/enhanced/input-edge-queue`） |
| 上游 HEAD（moonlight-stream/moonlight-common-c master） | `41cedb89d6b8592f99c09975c764ca3875034726`（"Only intercept ENet disconnects addressed to our peer (#162)"） |
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

### 未取待定（有价值但需先评估）

| commit | 备注 |
| --- | --- |
| `d85371c`/`be43885`/`62e0663` | RFI 修复族（multi-block 帧损、partial IDR、speculative loss）——影响弱网体验，但 fork 侧 VideoDepacketizer/RtpVideoQueue 已改 |
| `342b106` | control stream 加密 in-place 化 |
| `41cedb8` | ENet disconnect 只拦发给自己的——小而安全，但需真机验证 |
| `f1cca2d` | pen event batching |
| `7022b33`/`1fddbcb` | BSD socket 错误重构 / rswrapper 头泄漏 |

## 回吸时的已知冲突面（17 个交集文件）

`CMakeLists.txt`、`src/ControlStream.c`、`src/Input.h`、`src/InputStream.c`、`src/Limelight-internal.h`、`src/Limelight.h`、`src/Platform.c`、`src/PlatformCrypto.c`、`src/PlatformSockets.c`、`src/RtpAudioQueue.c`、`src/RtpAudioQueue.h`、`src/RtpVideoQueue.c`、`src/RtspConnection.c`、`src/SdpGenerator.c`、`src/VideoDepacketizer.c`、`src/rswrapper.c`、`src/rswrapper.h`

`src/InputStream.c` 两侧改动量都很大（fork +3202 行级重写、上游 +343 行），是回吸的主要战场。
