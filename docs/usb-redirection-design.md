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
- **真机取证已完成**（macOS 27.2，一台 Apple Silicon 机器，**该时刻**挂着的全部设备：探针自报的 `COUNT` 行为
  **10 个设备节点与 11 个接口节点**（`IOUSBDevice` 与 `IOUSBHostDevice`、`IOUSBInterface` 与 `IOUSBHostInterface`
  各自是同一批对象的别名匹配，去重后 21 个唯一节点）。取证程序是一次性 clang 构建的只读探针，
  `IOServiceGetMatchingServices` + `IORegistryEntryCreateCFProperties`，不打开任何设备、不使用任何 entitlement；
  四类匹配全部返回 `KERN_SUCCESS` 且有节点）。

  **这张表的第一版把序列号那一行写反了，此处按改正后的版本记录。** 上一轮的数字来自一个手写键名清单的探针：
  它查的是 `USB SerialNumber`（无空格），而内核发布的是 `USB Serial Number`（有空格）。探针不会为"自己问错了名字"
  报错，它只会安静地报告一个干净而虚假的世界，而这里的安全规则是照着那张表写的。同一份旧程序还把每类匹配截断到
  8 个节点，于是"16 个节点"是截断上限而不是总线上的节点数。两处都已修：键名清单现在**由 `scripts/usb-registry-shape.py`
  从解析器自己的五组候选键抽取生成**（"探针少问一个键"在结构上不再可能），节点数由探针自报的 `COUNT` 行给出。
  改正后的实测推翻了写代码前的三个假设：

  | 写代码前的假设 | 实测 | 后果 |
  |---|---|---|
  | 标识符首选键是 `USB Vendor ID` | 21 个唯一节点上**一次都没出现**；真正生效的是第二个候选 `idVendor`/`idProduct`，形态是 **CFNumber**（10/10 设备节点、11/11 接口节点；`USB_Vendor_ID`/`USB_Product_ID` 同样从未出现） | 候选键顺序仍保留（多键名是有意的宽容），但"harness 用哪种形状驱动"这件事从此有了依据：形状 = 短键名 + 数值 |
  | 接口类别可能按接口以**数组**到达设备节点 | 每个接口是**独立 registry 节点**（`IOUSBHostInterface`），各自发布**单个数值** `bInterfaceClass`/`bInterfaceSubClass`/`bInterfaceProtocol`；`interfaceClasses`/`interfaceProtocols` 两个数组候选键从未出现 | 复合设备不是"一条记录里两个类别"，而是"同一设备的两个节点各带一个类别"。**4.5 的复合设备整体拒绝在旧的单节点 API 下无法表达**——按节点逐个归因时，扩展坞会以"存储设备"的身份通过类别门。已补 `MLUSBDeviceIdentityFromRegistryNodes(...)`：标识符取第一个拼得出来的节点，接口是所有节点的并集（含重复项，节点说两个就是两个） |
  | 序列号通常读得到，`token=none` 是异常路径 | **上一版这一行写反了，现已改正**：正确键名（带空格）在 **7/10 设备节点与 11/11 接口节点**上发布，`kUSBSerialNumberString` 在 **7/10 设备节点**上发布，形态都是字符串 | 原判断方向成立：序列号通常拿得到，所以摘要脱敏是在做实事，而 `none` 只在真没号的时候出现。接口节点 11/11 都带号还多出一层含义——"只遍历接口节点"那条路径同样能拿到可关联的稳定标识，所以脱敏必须在那条路径上一视同仁，Stage 1 的对应断言不是冗余 |
  | 产品名是可选装饰 | `USB Product Name` 在**每个**节点上都有；接口节点的 registry name 甚至可以是 `http://help.vesa.org/dp-usb-type-c/` 这类可关联字符串。接口节点也带 `idVendor`/`idProduct` | "读取路径不看产品名"这条静态断言现在有了物证：泄露向量确实存在，而只遍历接口节点也必须能归因（否则可见设备被记成匿名设备，策略只能拒） |

- **第二轮取证测的是「归因入口应当从哪一端遍历」，因为 `MLUSBBusSnapshot` 只能照这一个事实写**。
  同一台机器、同一系统版本、同一次枚举：从 `IOUSBHostDevice` 的 10 个设备节点沿 `kIOServicePlane` 向下走 children，
  带 `bInterfaceNumber` 键的节点共 **16 个（唯一 id 也是 16 个，没有被两条路径重复计入）**；
  而 `IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOUSBHostInterface"))` 只返回 **11 个**，
  且这 11 个**全部**落在那 16 个里面——也就是说接口迭代器会**漏掉 16 个里的 5 个（31%）**，而不是「多给出一些不相干的节点」。
  16 个节点逐个沿 parent 方向数，**16/16 恰好只有一个 IOService 父节点**，且父节点自身不带 `bInterfaceNumber`
  （即它是设备，而不是接口的另一种拼法）。三个后果都写成了代码与门禁：

  1. 归因只允许**从设备节点向下**，接口迭代器不得当接口全集使用。漏掉的方向恰好是复合设备的那些面，
     而「扩展坞 = 存储 + 智能卡 → 整体拒绝」在少看一面时会退化成「先看哪一面就放行哪一面」。
     这条不是注释里的偏好：`scripts/usb-bus-snapshot-tests.py` 断言去注释后的源码里**不出现**
     `IOUSBHostInterface`/`IOUSBInterface`，并**反向**要求 `USBBusSnapshot.h` 的注释里保留这个类名与这组数字
     ——规则要读起来像一次发现，而不是一条禁忌。
  2. `MLUSBBusSoleParentID` 只在 parent **恰好一个**时才认这个归属：两个父节点是「归属有争议」，不是「多一个证据」。
  3. 「这张表是不是一张接口表」的判据是**键名** `bInterfaceNumber` 存在与否，值一律不看。
     看值的判据会被它所描述的那台设备的返回值改变，而复合设备的归因规则不能由设备自己挑选。

- **仍未观测的部分**：Apple 文档里出现过的 Data 形态标识符（`USB Vendor ID` 为 NSData 那一类）在本次取证的 21 个唯一节点上**一个都没出现**，本机既不能证实也不能证伪。`USB Vendor ID`/`USB Product ID` 本身一个节点都没有，所以"短键名全消失、只剩 Data 形态"那种总线本次也无法证实——它仍是推测，而实现按不利处理，不依赖它出现。实现**不接受** Data 形态，按不利处理成 `unread`，由身份门拒绝——也就是说：如果哪天在一台机器上只见到 Data 形态，症状是"看得见设备但身份不完整"，而不是把两个字节猜成厂商号。这一条留作观测记录，**不构成放宽解析的依据**。


## 3. 架构：分层交付，每层各自解锁下一层

```
Stage 0  决策与协商（纯本地、零设备访问）        ← 已实现
Stage 1  设备枚举可见性与诊断（只读，本机关）        ← 已实现（不含 UI）
Stage 2  语义旁路（新消息类型 + 能力位，需主机契约）  ← 客户端半边已实现（有意未接线，见 9.4）
Stage 3  设备直通（DEXT + 主机虚拟设备 + 签名公证）  ← 生命周期逻辑已实现（扩展本体受阻，见 9.5/9.6）
```

| Stage | 内容 | 前置条件 | 交付物 | 主要风险 |
|---|---|---|---|---|
| 0 | 策略引擎 + 能力协商 + 审计串 | 无 | `DeviceRedirectionPolicy`、门禁 harness、本文档 | 逻辑黑洞（顺序/绕过）；以门禁变异覆盖对冲 |
| 1 | 本机设备枚举、类别归因、"为什么被拒"的诊断串，以及把这三样摆给玩家看的面板 | Stage 0；`IOKit` 只读枚举（取证见 2.5） | **已交付**：`USBDeviceEnumeration`（身份 + 摘要令牌 + 诊断行）、归因入口 `USBBusSnapshot`、签名形态 `CodeSignatureProfile`、面板模型 `DeviceRedirectionPanelModel` 与 SwiftUI 的 `DevicesView`，各自带门禁 | 枚举信息进入日志造成指纹聚合 → 序列号只在读取处摘要，对象上不保留序列号字段，面板与每一行都不出现产品名（门禁断言真机输出）；UI 之所以此刻可以给，见 6 第一条的改正 |
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
| 构建纳入 | `Stream/DeviceRedirectionPolicy.m` 出现在 xcodebuild 的编译清单里：`source-membership-audit.py --build-log build-arm64.log` 报 130 个实现文件 / 0 个无归属 / 3 条有理由的排除。**`membershipExceptions` 不是纳入凭据**：那一个 exception set 没有挂到任何 target（工程文件里 `fileSystemSynchronizedGroups` 出现 0 次），它的 137 条目既不排除也不包含任何文件，所以「有没有被编译」只能问构建日志 |
| 取证回归 | `scripts/usb-registry-shape.py`（**不是门禁**，命名刻意向）：从解析器源码抽取候选键生成只读探针、在活总线上取证，并把每个形状与 Stage 1 已钉的 fixture 表比对；三种结论 covered / drift / not measured，无 IOKit 的机器上明说"这次没取证"且不打印 covered。`stale_pins()` 每次遍历整张 pin 表，所以删掉一条 fixture 会立刻红（8.1 记的六个植入缺陷全部被抓）。它的 `--self-test` 由 `usb-device-enumeration-tests.py` 调用，因此跟着现有门禁在两种 runner 上一起跑，不需要新 step。见 8 |
| Stage 2 断言 | `scripts/device-redirection-session-tests.py`：整个 `DeviceRedirectionSession` 被编译后由仓库内参考应答器驱动 **44 条**时序/判定断言（serverinfo 负向矩阵、bind/state/item 的顺序与畸形应答、超时与拒答的区分、槽位消耗、首因保留）；**10 个植入缺陷全部被抓**；另断言源码里不存在 `NSDate`/`CACurrentMediaTime`/`clock_gettime`/`gettimeofday`/`NSUserDefaults` |
| Stage 3 断言 | `scripts/driver-lifecycle-tests.py`：整个 `DriverLifecycle` 被编译后驱动 **39 条**断言（安装超时回落、卸载超时不得谎称已卸载、崩溃预算、orphaned 租约只能超时失效、重插不复用、"相位 + 租约"双条件可用性）；**10 个植入缺陷全部被抓** |
| 签名门禁 | `scripts/driver-extension-signing-audit.py`：树里出现 `.dext`/DriverKit 源码/`OSSystemExtensionRequest`/DriverKit entitlement，而 workflow 缺 Developer ID 签名、hardened runtime、`notarytool`、`stapler staple` 任一项 → 红。`--self-test` **10 条**含"完整签名必须判绿"，避免一个只会红的门禁 |
| 由谁执行 | macOS 每个 build 的 `scaling-output-evidence-tests.py` step 调用本 gate；`constraints-audit.py` 的 `DRIVEN_BY` 记录了这条依赖并校验"driver 确实是 CI step 且确实调用它"。原因：该 gate 需要真 clang 与 macOS SDK，Ubuntu audits job 跑不了，而新增 step 需要带 `workflow` scope 的凭证，当前推送凭证没有 |
| Stage 1 门禁 | `scripts/usb-device-enumeration-tests.py`：把 `USBDeviceEnumeration.m` 与 Stage 0 的 `DeviceRedirectionPolicy.m` 作为**同一翻译单元**用真 clang + `-Wall -Werror` 编译（摘要实现只有一份，不复刻第二套），输入是注入的 registry 属性字典，**不链接 IOKit** |
| Stage 1 断言 | 行为断言在编译出的二进制里执行，条数由二进制自己打印（当前那次运行 23 条），harness 拒绝低于下限的用例清单——用例被悄悄删掉时，只有那个数字会发现不对。覆盖的形状：数值/十六进制文本/`0x` 前缀/无标识符/过长文本/半个十六进制/4 字符的半十六进制、候选键名、接口与 protocol 的三种配对、**真机节点形状**（短键名 + 单数值 + 每接口一个节点 + 设备与接口节点都带序列号 + 每节点都有产品名）、Data 形态与数组形态的标识符一律不读、只遍历接口节点也要能归因、重复接口节点不得折叠、复合设备以分离节点到达时 whichever-face-first 都被拒、诊断行不含序列号与产品名、摘要令牌一对一。另有 6 条静态断言（不链接 IOKit、除摘要外只 import 一个系统头、枚举自身无日志出口、读取路径不看产品名、`Moonlight.entitlements` 未新增 usb） |
| Stage 1 变异 | 11 个，全部被抓：序列号写出、序列号丢弃使所有设备同形、超长文本仍按标识符解析、半个十六进制被采信、一个 protocol 字节摊给两个接口、候选键名被删一个、归并只取第一个节点、只从"非接口节点"取标识符、把重复接口折叠成一个；另有本轮补的两个——把一坨字节读成厂商号、把数组读成它的第一个元素。第 4 个只有 4 字符输入才能抓到——长度护栏会掩盖它，所以那条断言是补上的缺口，不是装饰；中间三个是 2.5 实测之后补的，它们各自对应一条真实总线会让 4.5 静默失效的归因错误；最后两个钉的是"真机今天没有但文档里出现过"的形状，它们的存在由 8.1 的负向验证证明不是装饰 |


**剩余 gate**：枚举脱敏（禁止序列号与设备名进入日志）已由 Stage 1 门禁覆盖；剩下的两处随各自的交付走——UI 落地时新诊断文案必须过 `l10n-audit.py`，Stage 2 的协商 gate 必须让未知能力位、缺字段、版本偏斜全部落`host-unsupported`。

## 6. Stage 1 已交付的边界，与 Stage 2/3 的解锁条件

- Stage 1 的边界（已按此交付）：做枚举、归因与诊断串；不做网络消息、不打开设备。**UI 这一项本轮改正了**：
  原来的理由（第 3 节末尾）是「主机与签名两个前置到位之前，一份被拒列表只会把系统层面的不可用伪装成用户的设备问题」。
  它成立的不是「不能做 UI」，而是「不能只给一张被拒列表」。所以本轮交付的面板把四项前置放在列表**之上**：
  这个构建能否加载扩展（从正在运行的二进制自己的签名读出来，而不是从构建设置读）、DriverKit 与系统扩展两个 entitlement、
  主机是否宣告、总线是否真的被扫过。「伪装」这一条由此被拆掉：今天每一项拒绝都会先显示成 `build-adhoc`，
  而不是显示成一屏可疑的设备。仍然不做的还是网络消息与打开设备——那两项的前置确实没到位，面板上也照样写着没到位。枚举本身经 2.5 取证，不需要新 entitlement，因此它属于"能今天做完并锁进门禁"的那一类。
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


## 8. 附：2.5 那次取证的复现程序

2.5 的每个数字都来自一次探针运行。它不写任何东西、不打开任何设备、不需要 entitlement，
所以任何一台 Mac 上几十秒就能复核或推翻那张表——包括推翻之后该怎么改。

**探针不再是手写的，它由 `scripts/usb-registry-shape.py` 生成。** 这条规则本身是 2.5 那次改正的产物：
第一版取证程序里的手工键名清单把 `USB Serial Number` 写成 `USB SerialNumber`，于是"没有设备发布序列号"
这个结论被写成表格、写进 CHANGELOG、写进 harness 的用例文案，直到有人重新怀疑它。同一份程序还把每类匹配
截断到 8 个节点，那张表把 8 当成总线规模报告了出来。所以现在的生成规则是：

- **被查的键 = 解析器自己的候选键**，由 `key_lists()` 从 `Limelight/Stream/USBDeviceEnumeration.m` 的五组
  候选键里正则抽取；解析器如果重构到读不到这些键，工具直接 `SystemExit` 而不是安静地少问一个；
  工具还额外断言 `idVendor`/`idProduct` 仍在清单里——那正是上一版出错的地方。
- **节点数由探针自报**（`COUNT` 行），不再有"每类前 8 个"这种上限混进结论。
- **不打印任何值**：只报类型、长度、以及字符串是否呈十六进制形状。序列号是个人数据，而这份输出是要能贴进
  issue 的。

```bash
python3 scripts/usb-registry-shape.py --print-probe > /tmp/shape.c   # 看生成了什么
clang -Wall -Wextra -isysroot "$(xcrun --show-sdk-path)" \
      -framework IOKit -framework CoreFoundation /tmp/shape.c -o /tmp/shape && /tmp/shape
python3 scripts/usb-registry-shape.py                                # 生成 + 编译 + 归类 + 比对 fixture
```

最后那条命令只有三种结论：

| 结论 | 含义 |
|---|---|
| `covered` | 今天总线上的每个形状都有一条 Stage 1 用例钉住它 |
| `not covered: N shape(s)` + `DRIFT ...` | 出现了没钉过的形状，或某条 pin 指向的用例已从 harness 里消失。前者说该加哪条 fixture，后者说表被人缩小了 |
| `not measured: ...` | 这台机器没有工具链或没有 IOKit（比如 Ubuntu runner）。它明说这次没取证，**不打印 `covered`**，退出码 0。这一态由 self-test 用伪造的工具链验证（把 `apple_toolchain` 换成一个必定失败的对象），因为跑 self-test 的机器往往真有工具链，不伪造就永远测不到 |

`stale_pins()` 与 `verdict()` 是两件事，分开是必要的：`verdict` 只对"今天出现的形状"判漂移，
而一条今天没出现的形状对应的 fixture 仍然是承重的——如果删掉它可以等到那种设备真出现才变红，
那张表就能靠删目标悄悄缩小。所以每次运行都遍历整张 pin 表。

```
$ python3 scripts/usb-registry-shape.py            # macOS 27.2，本轮
measured IOUSBHostDevice=10, IOUSBHostInterface=11, IOUSBDevice=10, IOUSBInterface=11
  interface-class=number-per-node    11/IOUSBHostInterface nodes carry bInterfaceClass as number; ...
  interface-protocol=number-per-node 11/IOUSBHostInterface nodes carry bInterfaceProtocol as number; ...
  product=number                     10/IOUSBDevice ...; 11/IOUSBHostInterface ...
  serial=string                      7/IOUSBDevice nodes carry USB Serial Number as string; ...
  vendor=number                      10/IOUSBDevice ...; 11/IOUSBHostInterface ...
covered: every shape on this bus is pinned by a Stage 1 case
```

分类器本身在**没有 USB 设备的机器上**也要被验证，所以它带 `--self-test`（当前 19 条）：用伪造的总线记录驱动
`classify`/`verdict`/`stale_pins`，断言五组候选键确实能从真实源码抽出来，并伪造一个失败的工具链来验证
"这次没取证"那一态不会说成通过。这条 self-test 由
`usb-device-enumeration-tests.py` 调用，因此它跟着已有门禁在 macOS 与 Ubuntu 上一起跑——不必为它新增 CI step。

这个工具**故意不叫** `*-audit.py`/`*-tests.py`/`*-probe.py`：它是取证，不是门禁。若它是门禁，
一台没有 USB 设备的 runner 会让它"通过"，而那正是最危险的假绿。

### 8.1 这次改正是怎么被验证的

上一版的错就是"没人能反驳"，所以改正后的东西必须能反驳。六个植入缺陷逐个验证会被抓：
分类器永远返回"没有漂移"；解析器少问一个候选键；`idVendor` 从解析器清单里被删；
已经答上话的角色也被判成 absent；节点数被硬编码成 8（正是上一版那个截断错误的形状）；
从 harness 里删掉一条真机今天没出现过的 fixture；还有两个打在"没取证"那一态上的——`run_probe` 在无工具链时返回空记录而不是 `None`，以及把那条提示的措辞改成 `covered`。八个全部变红。

## 9. 不依赖任何外部配合的 Stage 2/3 推进计划

前提换掉一次：之前 6 的写法是"等主机契约落地"，这等于把进度抵押给别人的排期。本节改为**只推进我们能单方面验证的部分**，并把剩下两个物理前置写成"缺了就必须红"的形状，而不是"等别人"的形状。

### 9.1 先把"完成"定义改成不会说谎的版本

| 阶段 | 本节完成 = | 本节完成 ≠ |
|---|---|---|
| 2 | 客户端侧全部协商语义、消息状态机与兼容矩阵在 CI 里被验证，且验证者是一个**仓库内的参考应答器**（不需要真主机） | 与某台真 Sunshine 互通。那需要别人实现；本节不假装它发生了 |
| 3 | DEXT 生命周期、所有权、超时、崩溃回退、热插拔竞态这些**纯逻辑**被编译并被驱动；构建树里出现驱动类目标却没有 Developer ID 签名与公证步骤时**构建失败** | 设备真的能直通。那需要 Developer ID 证书与公证流水线，缺了就是缺了 |

把 ≠ 那一列写出来是重点：不写就等于用它骗自己完成。

### 9.2 批次与解锁判据

| 批次 | 内容 | 新增面 | 完成判据（各批独立可评审） |
|---|---|---|---|
| A | **已完成**。取证回归工具 `scripts/usb-registry-shape.py`：从解析器源码生成探针读活总线，把形状与已钉 fixture 表比对（见 8） | 一个非门控工具 + harness 里的两条新用例与一次 self-test 调用 | 三条判据逐一成立：三种结论都能被驱动（`not measured` 由伪造工具链验证、`drift` 由 self-test 验证、`covered` 由真机实跑给出）；pin 表整表遍历，删 fixture 即红（8.1）；无 IOKit 时明说没取证且不打印 covered。**超出判据的收获**：它一出生就抓到一个已发布错误——2.5 的序列号那一行是错的，改正见 2.5 与 8 |
| B | **已完成**。`MLDeviceRedirectionSession`：三段式的时序与判定，配仓库内参考应答器（见 9.4） | 一对 `Limelight/Stream/` 文件 + 一个门禁 | 44 条编译断言，10 个植入缺陷全被抓（含"只认 `1`"被反转、未知通道被跳过、重复键取第一个、文本槽位被 parse、槽位未知却放行上传、首因被覆盖、顺序检查反向、缺槽位读成满员、串台、花掉槽位仍放行第二个）；不读时钟由门禁断言源码中不存在这些符号来保证，超时以事件传入 |
| C | **已完成**。`MLDriverLifecycle`：生命周期、租约、崩溃预算与热插拔竞态（见 9.5） | 一对 `Limelight/Stream/` 文件 + 一个门禁 | 39 条编译断言，10 个植入缺陷全被抓，包括"安装超时仍停在 installing""卸载超时谎称已卸载""崩溃把设备直接归还""重插继承上次租约""只看租约不看相位"；设备一律用 Stage 1 的摘要命名，且断言该行不含该摘要 |
| D | **已完成**。`driver-extension-signing-audit.py`：把签名前置变成门禁规则（见 9.6） | 一个门禁 + 它的 `--self-test` | 10 条自测断言；负向五项——假 `.dext` 目标、DriverKit 源码、DriverKit entitlement 各报 4 条并退出 1，"目标 + 完整签名与公证"报 0 条并退出 0，被截断的 workflow 判红。规则单向：只拒绝"造出来却没人能加载"的组合 |

A→D 的顺序由风险决定：A 让后面几批的取证前提不会悄悄过期；B/C 是纯逻辑，错了可回滚；D 是防"无声放宽"，本身不引入能力。

### 9.4 批 B 交付了什么，以及它没有交付什么

`Limelight/Stream/DeviceRedirectionSession.{h,m}` + `scripts/device-redirection-session-tests.py`（编译出 **44 条断言**，**10 个植入缺陷全被抓**）。

**交付的是顺序与判定**：主机先在 serverinfo 上答 `1`，然后 bind、request state、upload；每步可被拒、可答得畸形、可不答。规则逐条落地——任何一步都不在前一步被接受之前发生；只有明确的 `1` 是"是"；同一个 tag 给出两个不同答案时不选边；未定义通道上的消息终结会话（跳过它会让下一条答复被读成对另一步骤的回答）；没答不等于"否"，`bind-unanswered` 与 `bind-refused` 是两个 stop，慢主机和满主机在日志里必须长得不一样；会话死掉的第一因保留到最后。

**没有交付线上格式**。契约 §4 的三个调用在 moonlight-common-c 和任何主机里都不存在，所以 `usbRedirectionBound`/`usbRedirectionSlots`/`usbRedirectionAccepted` 是**参考应答器用的名字**，源码里逐个注明哪个 tag 有契约依据（只有 `usbRedirection`）。因此它**不接 stream 启动路径**：没有对端时接线等于用猜测填协议。能被单方面定死的只有时序，所以定的是时序。

**形状表**（44 条）：缺字段、`0`、`"0"`、`"yes"`、空值、`2`、大小写错的 tag、同 tag 两次（一致/不一致）、未见过的未来字段、槽位写成文本、带小数、负数、128（超出 USB 能寻址的 127）、127、缺槽位、半程断连、槽位花完后的第三次上传、超时与拒答的区分。

**两个记录而非修饰的事实**：Foundation 无法区分 `@1` 与 `@YES`，所以"只认 1"必然同时接受 `@YES`，这条写成断言而不是愿望；USB 用 7 bit 寻址，127 是主机能描述的上限，超它更像编码错误而不是慷慨。

"状态机不读时钟"这件事不写在注释里，写在门禁里：`NSDate`/`CACurrentMediaTime`/`clock_gettime`/`gettimeofday`/`NSUserDefaults` 逐个断言源码中不存在——注释可以说任何话，断言不行。

### 9.5 批 C 交付了什么

`Limelight/Stream/DriverLifecycle.{h,m}` + `scripts/driver-lifecycle-tests.py`（编译出 **39 条断言**，**10 个植入缺陷全被抓**）。

批 C 断言的东西：安装请求超时**必须回落到 `not-installed`**并带 `install-unanswered`（停在 `installing` 就是一个永远不告诉玩家该重试的设置页）；卸载请求无应答时**不得谎称已卸载**（相位留在 `removing`，因为没有任何观测支持"它已经没了"这个结论）；崩溃计数累加到预算即 `held-back`，且 `held-back` 无法被"再请求一次安装"解除；崩溃时持有的租约变成 `orphaned` 而**不是**直接释放，orphaned 只能超时失效、不能被"归还"（归还它的进程已经死了）；**同一设备第二次插拔不复用旧可用性**——包括移除事件丢失/乱序时的那次竞态；`mayUseDeviceToken` 必须同时问"扩展在跑"和"这台设备被我们租出去过"两个问题，只问其一会把设备交给主机而另一个会话还持有它。

设备一律用 Stage 1 的摘要令牌命名，auditLine 里有断言检查该令牌不出现在行内——只数租约，不写它挂在什么硬件上。

### 9.6 批 D 交付了什么

`scripts/driver-extension-signing-audit.py`：`--self-test` **10 条**，另有真实树运行与 **5 项负向验证**。规则是**单向**的：树里出现 `.dext` 目标、DriverKit import、`OSSystemExtensionRequest` 或 `com.apple.developer.driverkit` entitlement，而 workflow 里没有 Developer ID 签名、hardened runtime、`notarytool`、`stapler staple` → 构建红，且每条缺口点名要改的文件与要敲的命令。

**它的自测必须能给出绿色**：一个只会红的门禁和一个从不会响的门禁一样没用，所以自测里喂进一份"扩展目标 + 完整签名与公证"的假 workflow，断言它通过；也断言"签名做了一半、缺公证"恰好报出一条缺口。负向验证：假 `.dext` 目标 → 4 条 error、退出 1；DriverKit 源码 → 4 条、退出 1；DriverKit entitlement → 4 条、退出 1；目标 + 完整签名 → 0 条、退出 0；被截断的 workflow → 红（读不到被检查的东西不能算通过）。

它不声称前置到位。它保证的是：**"设备能直通"这句话不会在扩展根本加载不了的时候被写进发布说明**。


### 9.7 批 E 交付了什么：一屏能说的话，必须能从二进制里证明

三件事同时落地，缺任何一件，这一屏就变成安慰：

- `Limelight/Stream/CodeSignatureProfile.{h,m}` + `scripts/code-signature-profile-tests.py`：
  用 Security.framework 的公开 API 读**正在运行的这个二进制**的签名，回答「这个形态能不能加载扩展」。
  实测 ad-hoc 构建返回的签名字典里根本没有 certificates/entitlements-dict/teamid/trust 这些键，
  第三方 Developer ID 应用则有 3 段证书链与 entitlement 字典，所以判定用**证书链 + leaf subject 前缀**
  （`Developer ID Application:` / `Apple Development:`），不去猜 flags 的位含义。
  `mayAttemptDriverExtension` 只有在 Developer ID **且** entitlement 键名前缀出现 `com.apple.driverkit` 授权时才为真
  （系统扩展那一项用精确键）。门禁用 openssl 现场生成三种 issuer 名的真证书喂进分类器：
  46 条 Python 断言、106 条编译断言、11 个植入缺陷全抓。类型守卫顺手抓到一次真实崩溃——
  数组元素被无条件桥接成 `SecCertificateRef`。
- `Limelight/Stream/USBBusSnapshot.{h,m}` + `scripts/usb-bus-snapshot-tests.py`：把 2.5 的第二轮取证变成代码——
  只从设备节点向下遍历、按「恰好一个父节点」归组、孤儿节点自成一组、判据只看键名。
  49 条 Python 断言、37 条编译断言、9 个植入缺陷全抓。隐私那一侧另做交叉验证：
  用 `ioreg -l -p IOUSB` 独立取到的 14 个产品名与序列号，逐个断言不出现在被测程序的输出里（checked 14, leaked 0）。
- `Limelight/Stream/DeviceRedirectionPanelModel.{h,m}` + `Limelight/macOS/ViewControllers/SettingsDevicesPane.swift`
  + `scripts/device-redirection-panel-model-tests.py`：面板的全部逻辑在 Objective-C 里，Swift 只渲染模型产出的字符串。
  90 条编译断言，另有源码与接线断言（模型进了桥接头、面板进了 target、面板被 tab 页引用、两种语言表都答得上面板要的每一句），
  18 个植入缺陷全抓，其中一个是「删除按钮删的是存储槽而不是玩家看见的那一行」。
  面板上每一条文案与日志用的是同一个拼写，所以截图和日志行说的是同一个障碍。
  面板的主机答案有四个状态而不是三个：没问过、问到了但不是、问到了且是、以及**根本没问着**。
  最初把最后一种并进「拒绝」，与 9.2 里 Stage 2 已经立下的「没答不等于否」直接矛盾——同一条原则
  在会话层写对了、在页面上写错了，而玩家被这句谎话支使去翻 PC 设置时，真正该查的是网线。
  现在 HTTP 失败、状态非 OK、以及 uuid 对不上（那台机器不是所选主机）一律走 `host-unreachable`，
  门禁断言两个状态永不共用拼写，并植入了「把无法联系写成拒绝」的缺陷。

**接线状态说清楚**：`DevicesView` 是这些 `auditLine` 的第一个生产调用方（此前它们一个调用者都没有，等于死代码）。
面板读写的是 `NSUserDefaults` 里 `moonlight.usbredirection.` 前缀下的四个键，而**没有任何一条流媒体路径读这些开关**——
在扩展存在之前开关授权不了任何东西，这是设计而不是待办。

**UNLOCK(stage3) 的集中清单**（`SettingsDevicesPane.swift` 顶部有同名标记，门禁同时断言两处都在：
占位注释能无声消失的话，它就不是占位，而是一个悄悄不再标注自己未完成的功能）：

1. DriverKit 驱动扩展目标进入 app 的两个 macOS job；
2. app 与该扩展用 Developer ID 身份 + hardened runtime 签名（面板第一张卡读的就是这一项的现状）；
3. `notarytool` 公证 + `stapler staple`，否则下载到的副本根本打不开；
4. helper 的安装/启用生命周期接到真实对象上（`DriverLifecycle` 已经把这套生命周期建模好，并且拒绝假装）。

主机侧那一半另有其位置：`+[MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:]`
要在真实连接建立处被问一次，今天问它的只有面板上那个「查询主机」按钮。问回来的字符串会先被裁掉空白再比对：
`ServerInfoResponse` 对同一份响应的**每一个** tag 都做了这件事，所以入库的 uuid 是裁过的，而面板一开始拿未裁的
应答去比裁过的 uuid，也拿未裁的应答去比 `"1"`——缺陷不在模型也不在传输层，在两者的接缝上，因此喂干净字面量的
测试永远看不见它。现在模型自己也会裁（不为调用方的自觉买单），并加了 4 条用例与 1 个植入缺陷，其中一条专门保证
裁空白不会把 `"10"` 裁成 `"1"`。同一个比较还有第二个洞：存库 uuid 缺失与应答缺失是两个「缺失」，可选值相等会
把陌生机器的能力位记到所选主机头上——现在没学到的身份谁也不匹配。四项各是一个可评审提交，不是一个「顺手做完」。

### 9.3 两个物理前置：缺时必须红，到位时按清单解锁

1. **真主机实现**（Stage 2 互通）：现状取证为 Sunshine 仓库无 USB 重定向议题、协议无设备通道（host-contract §1 #1/#2/#8）。到位判据 = 对端在同一能力位上答 `1` 且三段式消息双端跑通。**不接线到 stream 启动路径**是有意选择：我们没有对端，接线等于用猜测填协议，而猜错的代价是"看起来支持"。
2. **Developer ID + 公证**（Stage 3 加载 DEXT）：到位判据 = `codesign` 出 Developer ID 且 `notarytool` 返回 accepted，此后才允许出现 DEXT 目标。到位清单四项：DEXT 目标进 workflow 的两个 macOS job → 安装/卸载生命周期接到 helper（复用 `SMAuthorizedClients` 代码要求串的做法，见 2.3）→ 公证步骤进 release job → 崩溃与热拔插回退在真机上复测。四项各是一个可评审提交，不是一个"顺手做完"。
