# USB 设备重定向：可行性、架构与 CI 基线（Stage 0-1）

> English summary: device-level USB redirection cannot be built on today's protocol.
> `moonlight-common-c` carries HID *semantics* and no device channel; a driver extension
> would have to be Developer ID signed and notarised, which this project's adhoc identity
> cannot do. Stage 0 ships the part that must exist first and is testable today: a policy
> engine that refuses by default, and a capability negotiation that cannot lie. Stage 1 adds
> the read side only: an IORegistry identity, an interface-class verdict, and a
> diagnostic line that carries a digest instead of a serial number. There is no interface for
> it yet, and section 6 says why that is deliberate.

## 1. 结论

1. **设备级 USB 重定向当前不可实现**，阻断点有三个，每一个都在本仓库之外或需要证书/主机侧组件：
   - 协议没有承载设备的通道与消息类型（只有 HID 语义事件）；
   - 主机侧（Sunshine / GameStream）没有虚拟设备总线可对接；
   - macOS 侧的 DriverKit extension 必须 Developer ID 签名 + 公证，而本仓库产物是 adhoc 签名。
2. **可以先建的是决策层**：谁能被交给哪台主机、以什么理由、留下什么记录。这一层一旦缺失，后面每一层都会在压力下"先放行再补审计"。
3. Stage 0 已实现并进门禁：`Limelight/Stream/DeviceRedirectionPolicy.{h,m}` + `scripts/device-redirection-policy-tests.py`。它不打开任何设备、不加任何 entitlement、不发任何字节。
4. **Stage 1 已实现并进门禁**：`Limelight/Stream/USBDeviceEnumeration.{h,m}` +
   `scripts/usb-device-enumeration-tests.py`。它把"本机插着什么"读成一个可归因、可审计、可拒绝的身份，
   并且**只到这一步**：不接 UI、不打开设备、不加 entitlement（可行性取证见 2.5，UI 的取舍见 6）。
   归因入口有两个，因为真机给的就是两个形状：`...FromRegistryProperties`（单节点）与
   `...FromRegistryNodes`（设备节点 + 其接口节点的并集，2.5 的实测形状）。只有前者时，4.5 的
   "复合设备整体拒绝"在真实总线上一句话也说不出来——复合设备根本不是一个节点。

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

### 2.5 IOKit 只读枚举的可行性（Stage 1 的前置取证）

- 在 Command Line Tools 工具链下（未签名、无 entitlement 的普通用户进程）调用
  `IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOUSBHostDevice"), &iterator)`
  返回 `KERN_SUCCESS` 且 iterator 有效 → **读取本机 USB 设备的属性不需要新 entitlement，也不需要 DEXT**。
  2.3 的签名前置挡住的是"打开并接管设备"，不是"看见它插着"。
- 由此确定 Stage 1 的边界：枚举与归因是纯读取，可以今天做完并进门禁；任何"把设备交给主机"的动作仍留在 Stage 3。
- **真机取证已完成**（macOS 27.2，一台 Apple Silicon 机器，读取时挂着的全部设备：8 个设备节点与 8 个接口节点，
  取证程序是一次性 clang 构建的只读探针，`IOServiceGetMatchingServices` + `IORegistryEntryCreateCFProperties`，
  不打开任何设备、不使用任何 entitlement；`IOUSBHostDevice`/`IOUSBHostInterface`/`IOUSBDevice`/`IOUSBInterface`
  四类匹配全部返回 `KERN_SUCCESS` 且有节点）。实测推翻了写代码前的两个假设：

  | 写代码前的假设 | 实测 | 后果 |
  |---|---|---|
  | 标识符首选键是 `USB Vendor ID` | 8+8 个节点上**一次都没出现**；真正生效的是第二个候选 `idVendor`/`idProduct`，形态是 **CFNumber**（`USB_Vendor_ID` 同样从未出现） | 候选键顺序仍保留（多键名是有意的宽容），但"harness 用哪种形状驱动"这件事从此有了依据：形状 = 短键名 + 数值 |
  | 接口类别可能按接口以**数组**到达设备节点 | 每个接口是**独立 registry 节点**（`IOUSBHostInterface`），各自发布**单个数值** `bInterfaceClass`/`bInterfaceSubClass`/`bInterfaceProtocol`；`interfaceClasses`/`interfaceProtocols` 两个数组候选键从未出现 | 复合设备不是"一条记录里两个类别"，而是"同一设备的两个节点各带一个类别"。**4.5 的复合设备整体拒绝在旧的单节点 API 下无法表达**——按节点逐个归因时，扩展坞会以"存储设备"的身份通过类别门。已补 `MLUSBDeviceIdentityFromRegistryNodes(...)`：标识符取第一个拼得出来的节点，接口是所有节点的并集（含重复项，节点说两个就是两个） |
  | 序列号通常读得到，`token=none` 是异常路径 | **没有任何节点发布 `USB Serial Number` 或 `kUSBSerialNumberString`** | `none` 是真机默认路径；摘要脱敏保护的是一条本就不常带号的路，而审计行必须先把"没有号"说清楚 |
  | 产品名是可选装饰 | `USB Product Name` 在**每个**节点上都有；接口节点的 registry name 甚至可以是 `http://help.vesa.org/dp-usb-type-c/` 这类可关联字符串。接口节点也带 `idVendor`/`idProduct` | "读取路径不看产品名"这条静态断言现在有了物证：泄露向量确实存在，而只遍历接口节点也必须能归因（否则可见设备被记成匿名设备，策略只能拒） |

- **仍未观测的部分**：Apple 文档里出现过的 Data 形态标识符（`USB Vendor ID` 为 NSData 那一类）在本次取证的 16 个节点上**一个都没出现**，本机既不能证实也不能证伪。实现**不接受** Data 形态，按不利处理成 `unread`，由身份门拒绝——也就是说：如果哪天在一台机器上只见到 Data 形态，症状是"看得见设备但身份不完整"，而不是把两个字节猜成厂商号。这一条留作观测记录，**不构成放宽解析的依据**。


## 3. 架构：分层交付，每层各自解锁下一层

```
Stage 0  决策与协商（纯本地、零设备访问）        ← 已实现
Stage 1  设备枚举可见性与诊断（只读，本机关）        ← 已实现（不含 UI）
Stage 2  语义旁路（新消息类型 + 能力位，需主机契约）
Stage 3  设备直通（DEXT + 主机虚拟设备 + 签名公证）
```

| Stage | 内容 | 前置条件 | 交付物 | 主要风险 |
|---|---|---|---|---|
| 0 | 策略引擎 + 能力协商 + 审计串 | 无 | `DeviceRedirectionPolicy`、门禁 harness、本文档 | 逻辑黑洞（顺序/绕过）；以门禁变异覆盖对冲 |
| 1 | 本机设备枚举、类别归因、"为什么被拒"的诊断串 | Stage 0；`IOKit` 只读枚举（取证见 2.5） | **已交付**：`USBDeviceEnumeration`（身份 + 摘要令牌 + 诊断行）及其门禁。**未交付**：设备面板 UI | 枚举信息进入日志造成指纹聚合 → 序列号只在读取处摘要，对象上不保留序列号字段；UI 缺席是有意为之（见 6） |
| 2 | 主机侧虚拟 HID/存储：新增 RTSP 协商项、新能力位、新消息类型 | 主机实现 + 上游协议共识 | 上游 PR + 双端兼容矩阵 | 与旧主机误协商 → 严格"未知即否"（Stage 0 已实现该读法） |
| 3 | DriverKit 直通 | Developer ID 证书 + 公证 + 主机虚拟总线 + 安装/卸载生命周期 | DEXT + helper 生命周期 + 崩溃回退 | 权限提升面、热插拔竞态、驱动残留 |

**为什么 Stage 1 不含 UI**：在主机协议没有设备通道（2.2）、签名身份装不了 DEXT（2.3）之前，一份"被拒绝设备列表"能告诉用户的只有一件事——"这功能存在，但你的设备不行"。它把系统层面的不可用伪装成用户的设备问题。所以本轮只交付能力层，UI 与 Stage 2 的主机契约同时解锁。

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

10. **读不到的字节按不利处置，读到的字节如实上报**：接口 protocol 字节缺失时 `isBootInputInterface` 返回 YES（宁可拒一个并不存在的设备，也不放行一个可能是启动键盘的设备）；标识符两半边的读取**互相独立**——VID 拼不出十六进制就报 `unread`，同时如实报告 PID 读到了什么。审计的意义是报告实际看见了什么，把"半边没读到"扩大成"什么都没读到"会让诊断说谎。两条都由门禁锁定：前者是 Stage 0 的第 9 个变异，后者是 Stage 1 里"逐字段独立"这一语义的守门断言。

## 5. CI 基线

| 项 | 现状 |
|---|---|
| 新门禁 | `scripts/device-redirection-policy-tests.py`：逐字抽取 shipping 头文件与实现 → 真 clang（`apple_toolchain.clang_and_sdk`）+ `-Wall -Werror` 编译 → 真值表 + 审计断言 |
| 行为断言 | 33 条：Stage 0 出厂态、三门各自触发、唯一 allow、无规则/类别不符/规则被禁用/产品号不匹配、family 规则与非法规则、三类身份缺失、保留类别（含复合设备）、启动键盘两条顺序敏感断言、手柄非启动键盘、能力协商 8 种答复、审计脱敏 4 条、确定性 |
| 结构断言 | 头文件只 import Foundation；实现只 import CommonCrypto 与自己；无 IOKit/DriverKit/Usb import；`.m` 内无 `NSLog`/`printf`；`Moonlight.entitlements` 未新增 usb/driverkit；类别门不可能先于保留类别门 |
| 变异 | 9 个，全部被抓：默认改为放行、配对门移除、保留类别清空、本地输入门移除、两输入门交换顺序、产品号允许匹配任意规则、身份门退化为"全不可读才拦"、未读到的 protocol 字节被当成无害、序列号写入日志 |
| 构建纳入 | `Moonlight.xcodeproj` 的 `membershipExceptions` 已加入 `Stream/DeviceRedirectionPolicy.m`（`source-membership-audit.py` 通过：120 files / 128 entries / 3 documented exclusions） |
| 由谁执行 | macOS 每个 build 的 `scaling-output-evidence-tests.py` step 调用本 gate；`constraints-audit.py` 的 `DRIVEN_BY` 记录了这条依赖并校验"driver 确实是 CI step 且确实调用它"。原因：该 gate 需要真 clang 与 macOS SDK，Ubuntu audits job 跑不了，而新增 step 需要带 `workflow` scope 的凭证，当前推送凭证没有 |
| Stage 1 门禁 | `scripts/usb-device-enumeration-tests.py`：把 `USBDeviceEnumeration.m` 与 Stage 0 的 `DeviceRedirectionPolicy.m` 作为**同一翻译单元**用真 clang + `-Wall -Werror` 编译（摘要实现只有一份，不复刻第二套），输入是注入的 registry 属性字典，**不链接 IOKit** |
| Stage 1 断言 | 行为断言在编译出的二进制里执行，条数由二进制自己打印（当前那次运行 23 条），harness 拒绝低于下限的用例清单——用例被悄悄删掉时，只有那个数字会发现不对。覆盖的形状：数值/十六进制文本/`0x` 前缀/无标识符/过长文本/半个十六进制/4 字符的半十六进制、候选键名、接口与 protocol 的三种配对、**真机节点形状**（短键名 + 单数值 + 每接口一个节点 + 无序列号 + 每节点都有产品名）、只遍历接口节点也要能归因、重复接口节点不得折叠、复合设备以分离节点到达时 whichever-face-first 都被拒、诊断行不含序列号与产品名、摘要令牌一对一。另有 5 条静态断言（不链接 IOKit、除摘要外只 import 一个系统头、枚举自身无日志出口、读取路径不看产品名、`Moonlight.entitlements` 未新增 usb） |
| Stage 1 变异 | 9 个，全部被抓：序列号写出、序列号丢弃使所有设备同形、超长文本仍按标识符解析、半个十六进制被采信、一个 protocol 字节摊给两个接口、候选键名被删一个、归并只取第一个节点、只从"非接口节点"取标识符、把重复接口折叠成一个。第 4 个只有 4 字符输入才能抓到——长度护栏会掩盖它，所以那条断言是补上的缺口，不是装饰；后三个是 2.5 实测之后补的，它们各自对应一条真实总线会让 4.5 静默失效的归因错误 |


**剩余 gate**：枚举脱敏（禁止序列号与设备名进入日志）已由 Stage 1 门禁覆盖；剩下的两处随各自的交付走——UI 落地时新诊断文案必须过 `l10n-audit.py`，Stage 2 的协商 gate 必须让未知能力位、缺字段、版本偏斜全部落`host-unsupported`。

## 6. Stage 1 已交付的边界，与 Stage 2/3 的解锁条件

- Stage 1 的边界（本轮已按此交付）：做枚举、归因与诊断串；不做 UI、不做网络消息、不打开设备。理由见第 3 节末尾——主机与签名两个前置到位之前，一份被拒列表只会把系统层面的不可用伪装成用户的设备问题。枚举本身经 2.5 取证，不需要新 entitlement，因此它属于"能今天做完并锁进门禁"的那一类。
- 解锁 Stage 2 需要主机契约：新能力位 + 新 RTSP 协商项 + 至少一个主机实现的 PR。在此之前，`hostAdvertisesDeviceRedirectionInServerInfo:` 永远返回否，这是事实而不是占位。契约本身已写成可评审的草案：`docs/usb-redirection-host-contract.md`（取证、字段语义、双向验收、以及为什么客户端此刻不接线都在那里）。
- 归因入口对**调用方**也有一条硬规则，它是 2.5 实测的直接后果：一次设备 = 一个设备节点 + 挂在它下面的全部
  接口节点，接口节点不得被当成独立设备各自过门。真机上复合设备就是这样分开的，所以并集这一步必须在归因里做，
  否则"扩展坞 = 存储 + 智能卡 → 整体拒绝"会变成"先看哪一面就放行哪一面"。反过来也成立：只遍历到接口节点时
  仍要能报出身份，否则看得见的东西会被记成匿名设备而只能拒。
- 该读取目前没有生产调用点，这是有意状态：没有消费者（不发消息、不开设备、无 UI）时接线只会得到一段无法验证的死代码——真实主机不发这个字段，连"读到一次是"都无法观测。主机侧任一实现落地后，接线才是可验证的改动。
- 解锁 Stage 3 需要：Developer ID 证书与公证流水线、DEXT 安装/卸载生命周期、主机虚拟设备组件、崩溃与热插拔回退策略。缺任一项时 Stage 3 的工时估算没有意义。

## 7. 与 issue/PR 驱动的整合 backlog

每一项都读过上游原文并在本仓库里核对过实现状态。把已实现的东西列为缺口，比漏列一项更糟：它会让人重做，并让这张表不再被相信。

| 议题 | 核对到的现状（证据路径） | 结论 |
|---|---|---|
| #21 悬停触发自动激活 | 根因确认：`StreamViewController+MouseCapture.m` 的 tracking area 带 `NSTrackingActiveAlways`（背景态仍收 `mouseEntered:`），入口路径调用 `ensureStreamWindowKeyIfPossible` → `activateIgnoringOtherApps:`。本轮已交付：判定收进 `MLPointerEntryActionsForState`（`Limelight/macOS/PointerEntryPolicy.{h,m}`），鼠标面板新增开关，默认为"是"（保持既有行为） | **本轮已解决**，`scripts/pointer-entry-takeover-tests.py` 把关 |
| #40 ⌘Tab 后被抢回 | 与 #21 同一入口：⌘Tab 后鼠标掠过窗口即触发 `mouseEntered:`。另一条候选路径 `scheduleTransientKeyLossRecoveryWithReason:` 已排除 —— 其调用点要求 `shouldSuppressTransientKeyLossUncaptureForCode:` 为真，而该函数要求全屏 + 已捕获 + app 仍 active + 450ms 内有顶边点击，#40 的"自由模式 + 窗口化"不满足 | **随 #21 一并解决**（关闭开关后需点击一次） |
| #42 鼠标模式自动切换 | 上游作者本人已在 issue 内回复：功能已内测实现、正在重构、可能在下一版本带来（comment 5399187926） | **不做**，与上游重复实现只会制造合并冲突 |
| #45 手柄 Menu 长按开关 | **本行上一版记录是错的，现已改正。** 该手势在本 fork 早已实现，而且在两条输入路径上各有一份：`ControllerSupport.m` 的 16ms `mouseTimerCallback:`（GCController/MFi，读 `gamepad.buttonMenu.pressed`）与 `HIDSupport.m` 的 `updateButtonFlags:state:`（CoreHID，`PLAY_FLAG`），两处都用 `Controller.startButtonDownTime` 与私有的 `< -1.0` 秒比较，松手即翻转 `isMouseMode` 并震动提示。上一版只查了 `toggleMouseMode` 的调用点（那是键盘快捷键路径），据此断言"全仓无此手势"，把已完成项记成了缺口——issue 作者"两条路径统一读取"的描述才是对的 | 真实缺口只有开关：本轮已交付主机级开关（默认开，保持既有行为），两条路径改为共用 `MLGamepadMenuGestureToggles`，边界与开关因此只有一处；门禁 `scripts/gamepad-menu-gesture-tests.py` 真 clang 编译该判定、驱动样本表、并需抓住 6 个植入缺陷 |
| #47 Metal HDR 三点 | **本轮逐点分处**：① Auto→PQ 不改默认（显式 PQ 今天已是可选项，取向分歧不靠翻转默认解决）；② "Auto 用满显示器 headroom" 等价于既有 `Peak` EDR 策略，无需新增；③ "移除硬编码曝光" 已实现为 Tone Mapping Policy 的新档 `No Exposure Shift`（`MLHDRSdrExposureForPolicy` 对它返回 1.0），Auto／三个 Preserve／Reference 仍分别施加 0.82（PQ）与 1.08（其它），与改动前逐位一致；④ 上游删掉的传输色彩空间探测辅助函数在本 fork 仍被 Auto 判断使用，不适用 | 门禁 `scripts/hdr-sdr-exposure-tests.py`：真 clang 下 18 组 policy×transfer 断言 + 结构断言（常数只有一处、kernel 必须被传值、picker 与 C 枚举同集合）+ 7 个变异全抓 |
| #44 英文本地化覆盖 | **两处真实缺口已闭合**。(1) 主表侧的"缺译"不需要逐页人工核对：`l10n-audit.py` 要求源码请求的每个 key 在中英两表都存在且对称，少一个即失败，"系统语言无匹配时回落英文"由 CFBundle 的开发语言保证（`knownRegions` 以 en 居首）。(2) Info.plist 侧有两处错：`NSLocalNetworkUsageDescription` 以中文写死在 plist 里（英文系统只能显示中文），已改为开发语言、中文进语言表；而 `InfoPlist.strings` 从未进入 bundle——Xcode 在"手写 Info.plist + 文件系统同步组"配置下不产出该文件（日志里的 `INFOSTRINGS_PATH` 只是设置项而非产出步骤；从一次 green run 的 artifact 里既找不到 strings 也找不到 `.loctable`），因此上一轮"把语言表挪到 plist 旁边"并没有改变产物 | 现由 `scripts/codesign-bundle.sh` 在签名密封之前安装并回读计数校验（缺表即拒绝签名），`scripts/build.sh` 调用同一步以保持本地与发布一致；源侧三类缺陷由 `l10n-audit.py` 拒绝并自带用例 |
| #32 剪贴板不同步 | 已实现：`StreamViewController.m` 剪贴板监视（0.25s 轮询、单图 4 MiB、FNV 去重、会话所有权）+ `clipboardSyncMode` 设置 + 双语文案；协议侧 `LiBindClipboardSession` / `LiRequestClipboardSnapshot` / `LiSendClipboardItem` 与 `LI_FF_CLIPBOARD_TEXT/IMAGE` 齐备 | 不是缺口 |
| #23 ⌘ 当 Win 键 | 已实现为快捷键翻译模式：`Swap Left Ctrl ↔ Left Win`、`Windows Shortcuts + Left Ctrl ↔ Left Win`、`MoonlightClassic` | 不是缺口 |

结论：不需要签名、公证或主机改动就能交付的项里，#21/#40 已完成，#42 由上游在做，#45 的前置不成立，#47 已按取向分歧逐点分处，#44 的两处真实缺口已闭合。这张表里不再有"能直接交付却没做"的项；还能往前推的，都要先等到外部前置落地：协议的设备通道、主机的虚拟设备总线、Developer ID 与公证。

