# USB 设备重定向的主机契约（Stage 2 提案）

状态：**提案**。本仓库不实现任何未经协商的消息类型；这份文档的目的不是往客户端里塞代码，而是把"客户端已经就位的那半"与"主机必须答的那半"写成一份可以被评审、可以被拒绝、也可以被照着提 PR 的契约。第 4 项（设备直通）在客户端侧已经没有可以零虚构推进的部分，理由与取证如下。

标记约定沿用 `docs/usb-redirection-design.md` §2.4：**verified** = 本次读到原文（HTTP 200 或本地文件行号）；**n/e** = 未取得证据，不作为依据。

## 1. 取证（每条都可复现）

| # | 事实 | 证据 |
|---|---|---|
| 1 | 本仓库使用的 core 子模块里没有任何 USB 相关符号 | `grep -rni "usb" moonlight-common/moonlight-common-c/src/*.h` → 0 行（大小写不敏感；子模块已 checkout，`git submodule status` 无异常前缀） |
| 2 | 上游公共 core 的头文件同样没有 | `curl -sS -w '%{http_code}' https://raw.githubusercontent.com/moonlight-stream/moonlight-common-c/master/src/Limelight.h` → `200`，`grep -cE "Usb\|USB"` → `0` |
| 3 | 客户端 core 有"可靠控制通道 + 自动分块"的先例，剪贴板正走它 | `moonlight-common/moonlight-common-c/src/Limelight.h:855-866`（`LiBindClipboardSession` / `LiRequestClipboardSnapshot` / `LiSendClipboardItem`，注释明写 text/image/file payloads 走 reliable control channel 并由 core 分块） |
| 4 | 同一头文件里有既有的"能力位"先例 | 同文件 `:889` `#define TOUCHPAD_FLAG 0x100000` 起的一组按钮能力位 |
| 5 | 客户端侧存在承载主机应答的结构入口 | 同文件 `:648` `LiInitializeServerInformation(PSERVER_INFORMATION)` |
| 6 | 主流开源主机有虚拟 HID 输入实现 | `api.github.com/repos/LizardByte/Sunshine/contents/src/platform` → 含 `virtualhid_input.cpp` / `virtualhid_input.h` |
| 7 | 该主机的 `/serverinfo` 应答就在一处拼装，加字段有明确落点 | `raw.githubusercontent.com/LizardByte/Sunshine/master/src/nvhttp.cpp` → `:1214 serverinfo(...)`，`:1272 tree.put("root.PairStatus", ...)`，`:1273 tree.put("root.currentgame", ...)`；路由注册在 `:1699` 与 `:1718` |
| 8 | 该主机仓库里没有任何 USB 重定向议题 | `api.github.com/search/issues?q=repo:LizardByte/Sunshine+USB+redirection` → `total_count: 0` |
| 9 | 本 fork 的能力读取只认显式"是" | `Limelight/Stream/DeviceRedirectionPolicy.m:310-319`，tag 名在 `:43`（`usbRedirection`） |

结论：主机侧的"输入虚拟设备"与"应答拼装点"都存在（#6、#7），协议层的设备通道不存在（#1、#2），并且已经有一条同形态的载荷通道可以照抄（#3）。所以 Stage 2 缺的不是客户端能力，而是一次跨仓库协商。

## 2. 客户端已经就位的部分（不是占位，是可执行代码）

| 能力 | 位置 | 现状 |
|---|---|---|
| 主机应答读取：显式 `1`/`"1"` 才是是，缺字段/旧主机/解析失败/非 1 值一律为否 | `Limelight/Stream/DeviceRedirectionPolicy.m:310`（`hostAdvertisesDeviceRedirectionInServerInfo:`） | 已实现，**无生产调用点**（见 §6） |
| 默认全拒的策略：未配对、未加密、身份不全、保留类别、无规则匹配各自独立成否 | 同文件 `verdictForDevice:`（`:321` 起，门禁逐项单独驱动） | 已实现 |
| 设备身份只读枚举，序列号在读取处即归约为摘要，对象上不留序列号字段 | `Limelight/Stream/USBDeviceEnumeration.h/.m` | 已实现 |
| 拒绝原因的可读名，日志与界面共用同一拼写 | `MLDeviceRedirectionDenialName()` | 已实现 |

这三层的门禁见 `scripts/device-redirection-policy-tests.py` 与 `scripts/usb-device-enumeration-tests.py`（由 macOS 构建作业里的渲染证据驱动，登记表见 `scripts/constraints-audit.py` 的 `DRIVEN_BY`）。

## 3. 契约一：能力宣告

主机在 `/serverinfo` 增加一个字段：

- 字段名：`usbRedirection`
- 值域：`1` = 支持；其余一切（缺失、`0`、空串、非数字文本、任何解析失败）= 不支持
- 语义：仅表示"该主机具备接收设备描述的能力"，不表示"任何设备都会被接受"——后者由客户端策略决定，客户端的答案在主机侧不可覆盖
- 版本：能力字段本身即版本；不引入新的版本号语义，避免"版本说了但行为没做"

客户端读法已经按上面这条实现，并且**只认 `1`**：`NSNumber` 要求等于 1，`NSString` 要求等于 `"1"`，其余返回否（`DeviceRedirectionPolicy.m:310-319`）。这条读法的含义是：一个忘了发字段的新主机，与一个从不知道这个字段存在的旧主机，得到同一个答案，且这个答案是拒绝。

## 4. 契约二：会话内消息（草案，本仓库未实现）

形态照抄剪贴板（§1 #3），因为它是同一条可靠控制通道上已经被双端实现过一次的三段式：

| 草案调用 | 作用 | 剪贴板对应物 |
|---|---|---|
| `LiBindDeviceRedirectionSession()` | 把当前会话声明为设备重定向会话 | `LiBindClipboardSession()` |
| `LiRequestDeviceRedirectionState()` | 向主机索取当前可接收设备数与已占用槽位 | `LiRequestClipboardSnapshot()` |
| `LiSendDeviceRedirectionItem()` | 上传单个设备的描述与后续 I/O 帧 | `LiSendClipboardItem()` |

明确标注：**以上三个符号在 moonlight-common-c 与本仓库里都不存在**，它们是本提案请求的东西，不是对现状的描述。任何一端单方面实现都不构成兼容。

最小设备集合建议限定为 HID 启动输入类之外、且未被本 fork 划为保留类别的设备；智能卡与诊断类接口在本 fork 侧被永久拒绝（`isReservedInterfaceClass:`，`DeviceRedirectionPolicy.m:306`），提案不建议主机为它们开路径。存储类设备不进最小集：它们的失败模式是数据丢失，不是延迟。

## 5. 主机侧最小实现路径（Sunshine 为例）

1. 在 `src/nvhttp.cpp` 的 `serverinfo()`（`:1214`）里，与 `root.PairStatus`（`:1272`）同一处写入 `root.usbRedirection`，取值只在"虚拟 HID 子系统真正可用"时为 `1`；不可用（缺驱动、权限不足、平台不支持）必须写 `0` 或不写，两种写法在客户端等价。
2. 设备落地复用 `src/platform/virtualhid_input.cpp`（§1 #6）：主机把描述转成虚拟设备，不引入新的总线层。哪些类别能映射进现有虚拟 HID 属于主机侧判断，本提案不代为决定。
3. 主机不得反向要求客户端放宽策略：客户端的答案（§2 第 2 行）不接收主机输入。

## 6. 为什么客户端现在不接线

`hostAdvertisesDeviceRedirectionInServerInfo:` 在生产路径里没有调用点，这是有意状态而非遗漏：没有任何东西去消费"主机支持"这个答案（不发消息、不开设备、无 UI），提前接线只会得到一段无法验证的死代码——真实主机永远不发这个字段（§1 #8），因此连"读到一次是"都无法被观测。等到 §3 在任一主机实现里落地，接线才是能被验证的改动。

## 7. 验收：双方各自要证明什么

- 客户端侧（已有）：负向矩阵逐条单独驱动——缺字段、`0`、`"0"`、`"yes"`、空字典、nil、数字 2 都必须为否；允许答案是"唯一正向"，任何"默认通过"的实现会被门禁抓住。
- 主机侧（待实现）：同一份字段在 `/serverinfo` 与配对后的会话里答案一致；虚拟子系统未就绪时不得为 `1`；不得因为客户端发了描述就绕过自身权限模型。
- 双端共同：旧主机 × 新客户端 = 拒绝且不影响其它功能；新主机 × 旧客户端 = 字段被忽略，其它功能不变。任何一端要求"必须升级才能串流"的实现都不满足本契约。

## 8. 本提案不覆盖的部分

Stage 3（DriverKit 直通、DEXT 安装/卸载生命周期、Developer ID 与公证、崩溃与热插拔回退）不在本文范围内，前置条件见 `docs/usb-redirection-design.md` §6。主机侧驱动与总线实现细节、跨平台差异、以及任何未经 §1 取证的竞品能力，都不作为本文依据。
