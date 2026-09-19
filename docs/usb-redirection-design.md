# USB 设备重定向：可行性、架构与 CI 基线（Stage 0）

> English summary: device-level USB redirection cannot be built on today's protocol.
> `moonlight-common-c` carries HID *semantics* and no device channel; a driver extension
> would have to be Developer ID signed and notarised, which this project's adhoc identity
> cannot do. Stage 0 ships the part that must exist first and is testable today: a policy
> engine that refuses by default, and a capability negotiation that cannot lie.

## 1. 结论

1. **设备级 USB 重定向当前不可实现**，阻断点有三个，每一个都在本仓库之外或需要证书/主机侧组件：
   - 协议没有承载设备的通道与消息类型（只有 HID 语义事件）；
   - 主机侧（Sunshine / GameStream）没有虚拟设备总线可对接；
   - macOS 侧的 DriverKit extension 必须 Developer ID 签名 + 公证，而本仓库产物是 adhoc 签名。
2. **可以先建的是决策层**：谁能被交给哪台主机、以什么理由、留下什么记录。这一层一旦缺失，后面每一层都会在压力下"先放行再补审计"。
3. Stage 0 已实现并进门禁：`Limelight/Stream/DeviceRedirectionPolicy.{h,m}` + `scripts/device-redirection-policy-tests.py`。它不打开任何设备、不加任何 entitlement、不发任何字节。

## 2. 已核实的事实（写结论前先取证）

### 2.1 上游没有这个需求

上游 `skyhua0224/moonlight-macos-enhanced`：`search/issues?q=repo:skyhua0224/moonlight-macos-enhanced+USB` 命中 3 条，全为巧合（#26 闪退、#34 闪退、#38 我们自己的 PR）。**USB 重定向是新需求，不是上游缺口**，因此它的验收标准由安全模型给出，而不是由"别人的 issue 里写了什么"给出。

### 2.2 协议层只有语义输入，没有设备通道

| 事实 | 位置 |
|---|---|
| 控制流 ENet 通道数 `CTRL_CHANNEL_COUNT = 0x30` | `moonlight-common-c/src/Limelight-internal.h:48` |
| 非 Sunshine 主机一律把 `channelId` 归零：`if (!IS_SUNSHINE_CTX(...) \|\| channelId >= ctx->peer->channelCount) { channelId = 0; }` | `src/ControlStream.c:980` |
| 全部输入统一走控制流：`sendInputPacket` → `sendInputPacketOnControlStream*` | `src/InputStream.c:410-435` |
| 对外只有语义事件：键盘、鼠标相对/绝对、touch、pen、scroll/hscroll、controller、`LiSendControllerBatteryEvent`、`LiSendMicrophoneControl` | `src/Limelight.h` 的 `LiSend*` 全集 |
| 没有任何"任意数据/隧道"发送接口（`arbitrary` 仅命中 `CAPABILITY_SUPPORTS_ARBITRARY_AUDIO_DURATION`） | `grep -rniI arbitrary src/` |
| 客户端能力位全集：`0x1 DIRECT_SUBMIT`、`0x2/0x4/0x40 RFI(AVC/HEVC/AV1)`、`0x8 SLOW_OPUS`、`0x10 ARBITRARY_AUDIO_DURATION`、`0x20 PULL_RENDERER`、`0x800000 SLICES_PER_FRAME(x)` | `src/Limelight.h:278-320` |

结论：**没有可复用的设备通道，也没有可复用的消息类型**。48 个 ENet 通道是 Sunshine 为输入做的 QoS 分优先级，不是可扩展的数据面；能力位里也没有任何设备相关位。

### 2.3 macOS 侧的签名前置条件

- `Moonlight.entitlements` 只有 `device.audio-input`、`network.client`、`network.server`、`com.apple.security.cs.disable-library-validation`（最后一项为加载第三方 FFmpeg/Opus/SDL2/OpenSSL 所需，文件内已注释说明）。**没有 App Sandbox，也没有 DriverKit/USB 相关 entitlement**。
- 当前产物 `Signature=adhoc`、`TeamIdentifier=not set`。DEXT 必须由 Developer ID 证书签名并公证才能被加载 → **在现有分发形态下 DEXT 根本无法安装**。
- 项目已有特权形态先例可参照：`/Library/PrivilegedHelperTools/std.skyhua.MoonlightMac2.AwdlPrivilegedHelper`（与 `...MoonlightMac.AwdlPrivilegedHelper` 并存，均运行中）。其安装走 `SMJobBless` + `SMAuthorizedClients` 代码要求串（`Limelight/macOS/Helpers/AwdlAuthorizationHelper.m:359`、`scripts/build_awdl_privileged_helper.sh`），并明确记录 `SMAppService` 尚不支持 privileged helper（同文件 10-13 行注释）。任何未来的设备重定向控制面都必须复用这套"代码要求串绑定调用方"的做法，而不是新开一个不受约束的进程。

### 2.4 竞品能力（按证据强度标注）

- **本仓库可直接复核**：`uuyc.163.com` 首页功能列表为文件传输、高清画面、隐私防护、多屏协作、远程开机（WOL）、按键映射、Mac 被控、无线副屏 —— **没有 USB 设备重定向**；`parsec.app/features` 为键盘映射、手柄支持、手柄管理、屏幕共享、多端 —— **同样没有 USB 设备重定向**。也就是说，两个以"串流体验"为卖点的竞品走的是**语义输入**路线，与 moonlight 的模型一致。
- **未在本仓库内验证**（结论不依赖它，仅作方向参考）：Citrix Workspace 与 ToDesk 的 USB/外设重定向能力，业界公开做法是"类别级重定向 + 主机侧虚拟设备驱动 + 管理端白名单策略"。本设计的**默认拒绝 + 显式白名单 + 类别门**取自这一类通行做法的安全含义，而非引用其具体配置项。

## 3. 架构：分层交付，每层各自解锁下一层

```
Stage 0  决策与协商（纯本地、零设备访问）        ← 已实现
Stage 1  设备枚举可见性与诊断（只读，本机关）
Stage 2  语义旁路（新消息类型 + 能力位，需主机契约）
Stage 3  设备直通（DEXT + 主机虚拟设备 + 签名公证）
```

| Stage | 内容 | 前置条件 | 交付物 | 主要风险 |
|---|---|---|---|---|
| 0 | 策略引擎 + 能力协商 + 审计串 | 无 | `DeviceRedirectionPolicy`、门禁 harness、本文档 | 逻辑黑洞（顺序/绕过）；以门禁变异覆盖对冲 |
| 1 | 本机设备枚举、类别归因、"为什么被拒"的 UI | Stage 0；`IOKit` 只读枚举 | 设备面板 + 诊断文案（走本地化审计） | 枚举信息进入日志造成指纹聚合 → 只落摘要令牌 |
| 2 | 主机侧虚拟 HID/存储：新增 RTSP 协商项、新能力位、新消息类型 | 主机实现 + 上游协议共识 | 上游 PR + 双端兼容矩阵 | 与旧主机误协商 → 严格"未知即否"（Stage 0 已实现该读法） |
| 3 | DriverKit 直通 | Developer ID 证书 + 公证 + 主机虚拟总线 + 安装/卸载生命周期 | DEXT + helper 生命周期 + 崩溃回退 | 权限提升面、热插拔竞态、驱动残留 |

**为什么不是先做 Stage 3 再补安全**：Stage 3 的失败模式是权限提升与设备劫持，属于不可回滚的那类；Stage 0 的失败模式是一个错误答复，属于可回滚的那类。顺序由此决定。

## 4. 安全模型

1. **默认拒绝**：没有任何规则命中就是拒绝。门禁把"默认值被反转"作为必被抓的变异之一。
2. **规则必须能描述一台真实设备**：VID/PID 为 `0x0000` 或 `0xFFFF` 的规则**永不参与匹配**（inert）。写错一个十六进制数字的后果是"授权整条总线"还是"什么都不授权"，这里选择后者。
3. **设备身份同样不接受哨兵值**：读到哨兵值的设备按"身份不完整"拒绝，因此不可能出现"哨兵规则匹配哨兵设备"。
4. **门序固定且逐门单独驱动**：功能开关 → 配对 → 主机能力 → 身份完整 → 保留类别 → 本地输入保留 → 类别允许 → 规则匹配。每门都用"其它门全开 + 规则命中"来驱动，否则无法证明是这一门在起作用。
5. **保留类别优先于白名单**：`0x0B`（智能卡 / 内容安全，FIDO 密钥同码）与 `0xDC`（诊断设备）无论规则怎么写都拒绝。复合设备（扩展坞 = 存储 + 智能卡）整体拒绝，因为只检查第一个接口就会让设备自己挑选被看到的脸。
6. **本地输入保留在类别门之前**：允许 `0x03` 用于手柄，不得顺手把启动键盘/鼠标（HID boot protocol）交给主机 —— 那等于让远端在本机输入口令时接管本机。要交，必须另开一个显式开关。
7. **审计不可旁路且脱敏**：唯一落盘形态是 `auditLine`，其中序列号只以 SHA-256 前 4 字节摘要出现；无序列号时显式写 `none`，不伪造。`.m` 内禁止 `NSLog`/`printf`（门禁断言），日志出口只有一个。
8. **可重放**：策略不读 `NSUserDefaults`、不读时钟、不看当前插拔状态，全部依赖注入状态；同样的输入必须给同样的判决与同样的审计串（门禁断言）。
9. **现有风险的处置**：`disable-library-validation` 是为第三方多媒体库保留的既有放宽。任何未来 helper/DEXT 都不得复用该放宽，且必须像 AWDL helper 一样用 `SMAuthorizedClients` 代码要求串绑定调用方。

## 5. CI 基线

| 项 | 现状 |
|---|---|
| 新门禁 | `scripts/device-redirection-policy-tests.py`：逐字抽取 shipping 头文件与实现 → 真 clang（`apple_toolchain.clang_and_sdk`）+ `-Wall -Werror` 编译 → 真值表 + 审计断言 |
| 行为断言 | 33 条：Stage 0 出厂态、三门各自触发、唯一 allow、无规则/类别不符/规则被禁用/产品号不匹配、family 规则与非法规则、三类身份缺失、保留类别（含复合设备）、启动键盘两条顺序敏感断言、手柄非启动键盘、能力协商 8 种答复、审计脱敏 4 条、确定性 |
| 结构断言 | 头文件只 import Foundation；实现只 import CommonCrypto 与自己；无 IOKit/DriverKit/Usb import；`.m` 内无 `NSLog`/`printf`；`Moonlight.entitlements` 未新增 usb/driverkit；类别门不可能先于保留类别门 |
| 变异 | 8 个，全部被抓：默认改为放行、配对门移除、保留类别清空、本地输入门移除、两输入门交换顺序、产品号允许匹配任意规则、身份门退化为"全不可读才拦"、序列号写入日志 |
| 构建纳入 | `Moonlight.xcodeproj` 的 `membershipExceptions` 已加入 `Stream/DeviceRedirectionPolicy.m`（`source-membership-audit.py` 通过：118 files / 126 entries / 3 documented exclusions） |
| 由谁执行 | macOS 每个 build 的 `scaling-output-evidence-tests.py` step 调用本 gate；`constraints-audit.py` 的 `DRIVEN_BY` 记录了这条依赖并校验"driver 确实是 CI step 且确实调用它"。原因：该 gate 需要真 clang 与 macOS SDK，Ubuntu audits job 跑不了，而新增 step 需要带 `workflow` scope 的凭证，当前推送凭证没有 |

**后续 gate（Stage 1 前完成）**：枚举脱敏 gate（禁止序列号/设备名进入日志）、本地化 gate（新诊断文案必须过 `l10n-audit.py`）、Stage 2 的协商 gate（未知能力位/缺字段/版本偏斜必须全部落 `host-unsupported`）。

## 6. Stage 1 的解锁条件与今天不做的事

- 不做：设备枚举、IOKit 调用、任何 UI 开关、任何网络消息。原因不是"来不及"，而是这些都会扩大攻击面，而在主机侧能力存在之前，它们能带来的唯一变化是**用户以为这个功能可用**。
- 解锁 Stage 2 需要主机契约：新能力位 + 新 RTSP 协商项 + 至少一个主机实现的 PR。在此之前，`hostAdvertisesDeviceRedirectionInServerInfo:` 永远返回否，这是事实而不是占位。
- 解锁 Stage 3 需要：Developer ID 证书与公证流水线、DEXT 安装/卸载生命周期、主机虚拟设备组件、崩溃与热插拔回退策略。缺任一项时 Stage 3 的工时估算没有意义。

## 7. 与 issue/PR 驱动的整合 backlog

USB 重定向不是本期唯一缺口。下面每一项都先在本仓库里核对过实现状态，因为把已经实现的东西列为缺口，比漏列一项更糟：它会让人去重做，并且不再相信这张表。

| 议题 | 核对到的现状 | 结论 |
|---|---|---|
| #32 剪贴板不同步 | 已实现：`StreamViewController.m` 有剪贴板监视（0.25s 轮询、单图 4 MiB 上限、FNV 去重、会话所有权与启动宽限），设置项 `clipboardSyncMode`，中英双语文案含 Foundation 主机说明；协议侧 `LiBindClipboardSession` / `LiRequestClipboardSnapshot` / `LiSendClipboardItem` 与 `LI_FF_CLIPBOARD_TEXT/IMAGE` 齐备 | 不是缺口，无需重复实现 |
| #23 ⌘ 当 Win 键 | 已实现为快捷键翻译模式：`Swap Left Ctrl ↔ Left Win`、`Windows Shortcuts + Left Ctrl ↔ Left Win`、`MoonlightClassic`（⌘→Ctrl、Control→Win） | 不是缺口，只需确认默认档与文案 |
| #42 鼠标模式智能切换 | `mouseMode` 设置项与 200 余处相关实现存在（默认 `remote`），但未看到"按场景自动切换"的证据 | 待逐条核对，可能是"有多种模式"而非"会自动选" |
| #47 Metal HDR 三点 | `EDR` / `PQ` / headroom 相关实现存在 83 处，本 fork 已有 HDR 策略族 | 需按 #47 的三点逐个对齐，不能笼统说已实现 |
| #45 Menu 长按开关 | `Limelight/` 内 `holdMenu` / `longPressMenu` / `menuHold` 零命中；本地化仅有"长按修饰键释放鼠标" | 未实现 |
| #21 悬停自动激活 | 仅有 `dimNonHoveredArtwork`（封面变暗）；`autoActivate` / `focusActivate` 零命中 | 未实现，且需默认关闭的显式开关 |
| #40 ⌘Tab 被抢回 | 未核对 | 下一轮先取证再判断 |
| #44 英文本地化覆盖 | `l10n-audit.py` 通过且中英表对称 | 覆盖机制已有，缺口需按具体页面核对 |

上游他人 PR 的未整合项同样在核对范围内：#47（Metal HDR）、#45（Menu 长按开关）、#44（本地化覆盖）。它们的共同点是都不需要签名、公证或主机侧改动，因此可以先于 USB 的任何一层交付。

