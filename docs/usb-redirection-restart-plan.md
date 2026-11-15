# USB 重定向重启方案

日期：2026-11-15。范围：只读评估 `/Users/<user>/code/moonlight-ci` 当前客户端仓与基地版为任务级只读浅克隆（上游 Moonlight macOS 增强分支 v1.3.9 RC8，HEAD `2c13fd6f46d1d83ca838dadae011116d0088260a`，评估后已按归属清理）；本报告不修改仓库。主仓评估时 HEAD `f27dead906ddea6cd536459cb4d746ed6579f8c0`，工作树另有 9 个设置相关未提交文件，评估期间未触碰。

标记：**源码已核**表示本次直接读了对应文件；**文档记载**表示沿用仓内文档对较早阶段的实测/CI描述，本次未重跑；**推断/未核**表示尚无主机端或真机证据。

## 1. 我们已有基线

### 已实现与未实现

- **源码已核**：`DeviceRedirectionPolicy` 是本地拒绝优先的决策层，含接口级类别、启动键盘/鼠标保护与显式规则；其头文件明确“不打开设备、不加载驱动、不发送字节”（`Limelight/Stream/DeviceRedirectionPolicy.h:5-13,24-80`）。
- **源码已核**：`USBDeviceEnumeration` 从 IORegistry 得到身份/接口，序列号只形成审计摘要，并将显示名与日志边界分开（`Limelight/Stream/USBDeviceEnumeration.h:8-19,28-49`）。`USBBusSnapshot` 负责设备节点与全部接口节点的归因，不能只取接口迭代器（`USBDeviceEnumeration.h:62-70`；设计文档 `docs/usb-redirection-design.md:84-99`）。
- **源码已核**：`DeviceRedirectionSession` 是可执行的会话状态机，限制 host advertise → bind → state → item 的顺序；文件注释说明 wire format 尚未协商，相关调用也未接入串流启动路径（`Limelight/Stream/DeviceRedirectionSession.h:7-24,31-55`）。它不是 USB/IP 数据通道。
- **文档记载**：设计基线称 Stage 0/1 已有门禁，策略、枚举、归因和诊断可离线验证；并记录 Stage 2 仅有客户端状态机/能力读取草案、无生产传输接线；Stage 3 的 DriverKit、签名公证、主机虚拟设备与热插拔回退仍未闭合（`docs/usb-redirection-design.md:14-25,159-173`）。本次未重跑文档提到的测试。
- **源码已核**：主仓 `rg -l 'RemoteUSB|USBIP' Limelight` 为 **0 个文件**。这是关键词口径；USB 策略/枚举/状态机文件使用 `DeviceRedirection` / `USBDevice` 命名，不能据此说“仓库没有 USB 代码”。当前 main 已有策略、枚举、总线快照、面板模型及无 wire 的状态机；没有基地版的 `RemoteUSBForwardingSession`、反向隧道、USB/IP helper/host wire 组件。
- **基线文档内部需要对齐之处**：设计文档开头仍称“没有 interface”（`docs/usb-redirection-design.md:7-10`），但后文记录面板已交付（`:159-166`）；报告以明确更新的后文与当前文件为准。host contract 中 `/serverinfo` 的 `usbRedirection` 和 bind/state/item 是**提案**（`docs/usb-redirection-host-contract.md:1-5,34-55`），不能把它当成已部署主机协议。其 Sunshine `virtualhid_input` 建议（`:59-64`）也不是可证明的通用 USB 设备总线实现。

### 方案上的关键差异

我们现有契约目标是受控的设备描述/会话交换，并明示尚无 USB 设备数据面；基地版则采用独立 USB/IP TCP 数据面和另一套 Foundation Sunshine API。两者不是“把类文件复制过来即可”：先要由我们和自家 Sunshine 主机端选定唯一 wire/认证/设备生命周期契约。将 USB/IP 套进剪贴板或输入消息不符合其流量与设备语义，也会与现有契约草案分叉。

## 2. 基地版实现剖析

### 架构与职责（本次源码已核）

1. **UI / ViewModel**：`RemoteUSBForwardingViewModel` 针对配对主机读取 Foundation 能力，调用 session 枚举设备，检查 enabled/available，再用 host、port、token、证书启动转发（`Limelight/macOS/ViewControllers/RemoteUSBForwardingViewModel.swift:15-60,64-89`）。UI 是控制面，不承载数据。
2. **ForwardingSession**：单例管理设备列表、状态与 helper 进程。`list --json` 读取 helper JSON；`serve --bind <busid> --listen 127.0.0.1:0` 启动本机 USB/IP exporter，解析 `READY <port>`（`Limelight/Network/RemoteUSBForwardingSession.h:15-56`；`.m:168-243,245-309`）。然后启动 ReverseTunnel；停止时关闭隧道、终止 helper、清理 ready 文件（`.m:382-439`）。
3. **ReverseTunnel**：客户端主动连接主机 TLS stream，以已配对客户端身份做 mTLS，并对服务端证书做精确 DER 比对；发 `{"op":"forward","token":...,"busid":...}`，只有收到 `ready` 才转发双向不透明 USB/IP 字节，分块 64 KiB、输出队列设 4 MiB 高水位（`Limelight/Network/RemoteUSBReverseTunnel.m:54-127,160-189,192-223,226-274`）。
4. **Exporter/helper**：独立 `moonlight-usbd` 使用 Apple IOKit `IOUSBLib` 打开设备/接口并服务 USB/IP。helper 链接的是仓内 `usbip_core` C 库和 Apple IOKit/CoreFoundation，不是第三方 `usbip-host` 库（`RemoteUSB/CMakeLists.txt:15-20`；`core/network/usbip-core/CMakeLists.txt:3-11`；`RemoteUSB/main.mm:1-8,26-29`）。C 核心是解析、请求追踪、限界等通用部分；平台 USB provider 在 Objective-C++ helper。
5. **提权现状与风险**：session 在非 root 下通过 AppleScript `do shell script ... with administrator privileges` 启动 `nohup ... --detach` helper，并以临时 ready 文件轮询 PID/端口（`.m:311-363`）。这属于基地版现有做法，不是建议照搬：脱离会话常驻进程与本任务生产规则冲突；自动化授权、ready 文件清理、崩溃回收及授权主体边界需要重做或采用受约束的 helper 生命周期，不能复制其 shell/AppleScript 方案。

### 对外 API 与主机接收机制

- macOS API 是 `refreshDevicesWithCompletion`、`startExporterForDevice`、`startForwardingForDevice:host:port:token:serverCert:completion:`、`stop`（`RemoteUSBForwardingSession.h:36-56`）；对外能力通过 Foundation `/api/v1/usb-forwarding?uniqueid=...` 取回版本、enabled、available、token、port（`Limelight/Network/HttpManager.m:659-720`）。token 仅保存在内存并校验 64 位十六进制（`:689-719`）。
- 数据路径：Mac 本地设备 → `moonlight-usbd` 的 loopback USB/IP listener → mTLS stream → 主机专用转发 listener → 主机侧 USB/IP importer/provider。主机先验证 client cert/token 和 `busid`，同意后返回 `ready`，之后 USB/IP 字节流交给主机 importer。客户端侧前半段由 `.m:88-127,160-189,192-223` 直接证实。
- **关键证据缺口**：提供的基地版只是 Moonlight client clone，没有 Foundation Sunshine 主机仓。故主机 `/api/v1/usb-forwarding` 路由、TLS listener、token 轮换/绑定、`forward` 校验、USB/IP import 落地与真实设备可见性，均不能仅凭客户端源码称为已核实。可证实的是客户端调用这些契约；“主机端已可用”来自任务背景，不是本次端到端复测。host contract 的 `/serverinfo` + `Li*` 提案与基地版 API/tunnel 并不兼容，必须确定自家 Sunshine 当前实现/契约后再接。

## 3. 差距与回吸路径

### 可借鉴与需改造

- **可直接借鉴概念/结构**：helper 与 SwiftUI/ViewModel 解耦；清晰的 exporter/session/tunnel 状态边界；loopback-only listener；配对证书校验与 token 绑定；固定长度/格式校验；背压上限；失败时停止并关闭两端；USB/IP wire 单元测试与限界测试。
- **不可原样吸收**：Foundation `/api/v1/usb-forwarding` 路由、token 字段/状态 JSON、`forward` JSON 握手、特定端口/mTLS stream，以及 host importer；它们需与我们自家 Sunshine 的认证、配置、运行状态及设备驱动契约对应。不得同时保留 docs 的新 Li 消息草案和另一套独立 TCP 通道，避免双协议事实源。
- **需本项目适配**：当前 USB 设置/菜单与输入路径已分叉，应把入口作为独立设备页/控制面，避免将普通 HID 手柄重新枚举/接管而破坏既有游戏控制。继续复用默认拒绝、复合设备完整归因、本地 boot-input 保留与脱敏策略；基地版 `MLRemoteUSBDevice` 包含原始 serial/manufacturer/product 字段的做法不能越过这些保护（基类 `RemoteUSBForwardingSession.m:62-100`）。
- **主机端是主依赖**：主仓 host contract 的虚拟 HID 建议无法自然承接 USB/IP 任意设备；需自家 Sunshine 定义且实现 USB/IP import/provider 或双方协议明确定义的另一种设备总线。无主机真实落地，客户端阶段只能做到 helper/wire 单元边界，不构成重定向。

### 建议阶段

| 阶段 | 改动对象 | 依赖与主要风险 | 验收判据 |
|---|---|---|---|
| A. 契约裁决与安全边界（离线） | 更新 `docs/usb-redirection-host-contract.md`、`docs/usb-redirection-design.md`；加协议图/状态/超时/拒绝码/并发与卸载语义 | 先只读核 Foundation Sunshine 对应路由/分支源码；确认沿用 USB/IP+mTLS 还是收敛至另一方案。风险是 host/client 双重契约 | 双端唯一协议、API schema、认证来源、失败行为、受支持类别及测试向量能被双方实现；未知/旧主机全拒绝 |
| B. 独立 USB/IP 核心与 wire 对接（离线） | 对应 `core/network/usbip-core/`、`RemoteUSB/USBIPHostWire.*`、CMake 与 tests | 可先吸收基地版纯协议解析/序列化与测试思想；不接设备、不引入提权。风险：ABI/协议包长、并发 URB、取消/热插拔时序 | 独立 C/C++ fixture 双端往返/负向/截断/超限/取消测试；无硬件结论 |
| C. 主机接收面（离线代码，运行环境后验） | 自家 Sunshine 的配置、server API、认证 listener、USB/IP importer/provider、设备策略/日志；配套 host tests | 主机 source/实际组件尚未读到，不能指定具体文件名或承诺已有 `virtualhid_input` 可复用。高风险：网络暴露、令牌重放、权限与设备劫持 | 非配对/过期 token/错误 busid/未启用全拒；仅 loopback/预期 TLS identity；host fixture 能收发受限 USB/IP 会话 |
| D. 客户端离线集成（先不启设备） | 本仓 `Limelight/Network` 新 session/tunnel/helper 接口，`SettingsInputPane.swift` 或合适独立 UI，`Moonlight.xcodeproj/project.pbxproj`/helper build；更新 UI 和本地化门禁 | 保留现有设置/键位/主路径契约；权限/entitlements/helper 签名边界；不可直接复制 AppleScript nohup。风险：串流生命周期停止/崩溃遗留、竞争设备访问 | mock host+helper 可证 state 顺序、失败恢复、停止回收、拒绝策略、token 不落盘；不宣称真机重定向 |
| E. 主机-客户端互操作（硬件可分层） | 双端集成/测试脚本与诊断 | 先虚拟 USB provider，再选获准的非 boot-input 设备；禁止默认放行任意类别 | 抓取两端证据：配对/TLS、attach、USB/IP URB 完整往返、设备在 host OS 枚举、detach 后释放；错误/拔线恢复 |
| F. 真机与发布路径（必须硬件/发行物） | 已签名 helper/app、真实 Mac + 自家 Sunshine 主机 + 明确测试设备；安装/更新/回滚文档 | 权限弹窗、设备被本地系统占用、休眠/重连、代码签名与发布渠道；物理设备测试可能影响本机输入 | 真实设备被 host 枚举/功能读写/停止归还；重启/重连/崩溃回收；更新与卸载不留进程/设备占用。当前 `hardware_validated=false` |

**风险边界**：DriverKit/DEXT 是原设计一条路径，但基地版用 IOKit USB host user client + 需授权的 helper；不应未经 SDK/签名/权限核实直接宣布“必须 DEXT”或“无需 DriverKit 就可发行”。源码说明其技术路径，不证明公开发行身份能运行，也不证明目标设备可被抢占。

## 4. 冻结项与离线推进

- 冻结的是“真实 USB 接管/重定向的真机验收”，不是安全设计、契约核对、解析器、状态机和 mock 测试。Stage A/B 可离线推进；C 可在读到真实 Sunshine 源码并具备受控测试环境后做代码，不开生产设备；D 可先做模拟端与生命周期测试。
- helper 对真实 IOKit 设备的打开/claim、设备类策略、主机 OS 枚举、真实 USB/IP URB 往返、插拔与释放、特权授权和发布签名必须由真机/目标构建验证。任何纯代码或 CI 只能标 `hardware_validated=false`。
- UI“设备列表/Forwarding”或 helper `READY`、TCP/mTLS 建连、双方返回成功都不等于设备已在主机可用。验收需要主机 OS 观察到正确设备并完成一次功能读写，随后 detach/stop 后本机设备恢复可用。

## 5. 最小可交付：首个可合并 PR

建议首 PR 定为 **“USB/IP 双端契约与 host 侧拒绝默认行为”**：先读实际自家 Sunshine 代码后，只加入协议说明、server capability 的禁用/缺省拒绝 schema、认证/握手状态机和纯内存/fixture 单元测试；不在客户端显示可点的 Forward，不打开 USB，不新增长期 helper/权限，不声称 USB 重定向完成。若 host 源码/可测试 harness 当前不可用，则最小首 PR 应收窄为**文档契约裁决 + 独立 USB/IP wire fixtures/解析测试**，并在 PR 描述列清 host 实现为后续依赖。合并门槛：明确唯一协议，测试覆盖缺字段、错证书/token、错 busid、未启用、乱序、截断与超限均拒绝；仓级安全/CI 符合项目门禁。

该 PR 不包含复制基地版 AppleScript+nohup 提权流程，不包括任意设备放行，不以已有菜单/界面/播放器件展示冒充传输验收。真实 USB 工作仍受冻结项约束：`hardware_validated=false`。
