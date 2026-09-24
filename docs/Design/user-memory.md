# 跨会话用户记忆 / 偏好系统 —— 设计（评审稿）

范围：只做设计。本文件与 `spikes/user-memory/README.md` 是本次唯一的两处新增，未改动任何既有文件。
spike 源码与复现命令在 `spikes/user-memory/`（已入库，本文附录的输出就是它跑出来的），本文引用的全部输出都是该机实测结果。第 10 节的输出在评审时被当前源码重算过一遍：`spike_migration.m` 现为 29 条断言，早先粘贴的 26 条版本已被替换。

## 0. 阅读约定

本文每一条断言都带下面三个标记之一，未标记的句子是待评审的主张而不是事实：

- 〔实测〕：本次或本仓库既有脚本在同一台机器上跑出来的，附出处。
- 〔未验证〕：看起来合理但没有证据，评审时应当当作问题而不是前提。
- 〔推理〕：从已实测的事实推出的结论，写明推理链，不复现实验不采纳。

**运行环境（spike 全部在此环境产出）**：macOS 27.2（Build 26B5091g）、arm64、
Xcode clang `/Applications/Xcode.app/.../usr/bin/clang` + SDK `MacOSX27.0.sdk`、Python 3.14.7。
换机器/换 macOS 主版本需要重跑，本文不声称跨版本成立。

---

## 1. 现状：先量一遍再设计

### 1.1 键名风格已经有六套并存（实测）

`git grep -n -E "NSString \* *const +[A-Za-z_]*(Defaults|Key)[A-Za-z_]* *= *@\"" -- Limelight` 与
`git grep -n -E "@AppStorage\(|UserDefaults\." -- '*.swift'` 的结果整理如下（每套给一条真实出处）：

| 风格 | 例子 | 出处 |
| --- | --- | --- |
| `moonlight.<domain>.<key>` | `moonlight.usbredirection.rules` | `Limelight/Stream/DeviceRedirectionPanelModel.m:15` |
| `settings.<pane>.<key>` | `settings.input.mouseAdvancedExpanded` | `Limelight/macOS/ViewControllers/SettingsInputPane.swift:19` |
| 裸 camelCase | `autoDiscoverNewHosts`、`selectedMicDeviceUID` | `SettingsAppPane.swift:43`、`MicrophoneManager.swift:31` |
| 裸 kebab-case | `selected-settings-pane` | `macOS/ViewControllers/LiquidGlass/LiquidGlassSettingsView.swift:42` |
| 大驼峰 + 内嵌 `.vN` | `MoonlightFirstLaunchCompleted.v2` | 见 1.3 |
| `<前缀>.<hostId>` 动态拼接 | `manualEndpoints.<hostId>`、`<hostId>-moonlightKeyboardTranslationRules` | `ConnectionEndpointStore.m:16-25`、`SettingsModel.swift:87-89` |

另有第三方保留键 `MASPreferences Selected Identifier View`（含空格）与系统键 `AppleLanguages`
（`LanguageManager.swift:37-41` 直接改写它）。

计数口径要说清楚：`git grep -n "standardUserDefaults" -- Limelight | wc -l` = **44**；
`git grep -n "stringForKey\|objectForKey" -- Limelight | wc -l` = **56**，但这 56 条里大部分是
`NSDictionary` 的 `objectForKey:`（例如 `Limelight/macOS/Helpers/Functional/F.m` 一整片），
真正的 defaults 读写要少得多。**这两个数只能当"改动面"的量级参考，不能当"偏好键数量"**。

### 1.2 已经存在的三个好习惯（设计要沿用，不是另起一套）

1. **坏数据被计数并上报，而不是跳过**〔实测，仓库既有〕：
   `scripts/device-redirection-panel-model-tests.py:375-377` 断言五条脏记录里"两条真的是规则、
   三条读不懂的被数出来"（`unreadableStoredRuleCount == 3`）。本文的 `unreadable` 计数直接继承这个惯例。
2. **偏好模型不自建 suite，由调用方注入**〔实测，仓库既有门禁〕：
   同脚本 `:632` 断言 `initWithSuiteName` 不出现在生产实现里，注释写明 "a caller supplies one"。
   本文 API 因此把 `NSUserDefaults` 作为注入依赖，不做单例。
3. **模型自己没有任何日志出口**〔实测，仓库既有门禁〕：同脚本 `:624`、
   `code-signature-profile-tests.py:424` 都断言实现里既无 `NSLog` 也无 `printf`。
   本文第 6 节的"日志白名单"建立在这条之上。

### 1.3 版本化不是新问题，但现在的做法不可复用（实测）

`MoonlightFirstLaunchCompleted.v2`、`MoonlightLocalNetworkTriggered.v1`（`Limelight/macOS/AppDelegateForAppKit.m:965-966`）说明"改键名当迁移"已经发生两次：
旧键留在磁盘上变成垃圾，新键从零开始，用户的第一次启动体验被重置。〔实测〕键名如此；
"用户体感被重置"是〔推理〕，因为没有测量过这两次改名影响了哪些可读状态。

### 1.4 一条真实的隐私暴露面（实测 + 推理分开写）

- 〔实测〕`SettingsModel.swift:88` 是 `"\(hostId)-moonlightKeyboardTranslationRules"`，
  `ConnectionEndpointStore.m:16-25` 是 `manualEndpoints.<hostId>` —— **主机标识被明文拼进偏好键名**。
- 〔实测〕`ServerInfoResponse.m:22` 说明 `host.uuid` 来自服务器响应的 `TAG_UNIQUE_ID`。
- 〔推理〕该字段在很多主机实现里由网卡地址或安装 ID 派生，因此键名可能等价于一个稳定设备指纹。
  这一点**没有**在本仓库验证（未抓取过任何真实主机的 `TAG_UNIQUE_ID`），列为待查而不是前提。

---

## 2. 目标与非目标

### 2.1 要跨会话记住的（按现在的代码归属划分）

| 域 | 内容 | 现状出处 |
| --- | --- | --- |
| `input` | 键鼠映射方案、鼠标加速/高精度、控制器驱动选择 | `SettingsModel+Persistence.swift:76`（`Data` 值）、`SettingsInputPane.swift:19-21` |
| `stream` | 分辨率/帧率/HDR/编解码/码率 | `SettingsModel+DerivedValues.swift:1047-1057` |
| `ui` | 选中的设置面板、折叠状态、上次选中的主机 | `LiquidGlassSettingsView.swift:42`、`SettingsModel.swift:146` |
| `redirection` | USB 重定向开关与规则 | `DeviceRedirectionPanelModel.m:12-15` |
| `diagnostics` | 日志级别、诊断开关 | `SettingsModel.swift:78-82` |
| `discovery` | 自动发现、手动端点、默认连接方式 | `DiscoveryManager.m:26`、`ConnectionEndpointStore.m:16-25` |
| `workflow`（新增） | 用户自行标注的工作流标签（例如"这台主机=剪辑机"） | 目前不存在，本设计为它留出命名空间 |

### 2.2 明确不记的（写进门禁，见第 7 节）

凭据与配对着陆物（PIN、证书、私钥、p12）、主机配对状态本身、`TAG_UNIQUE_ID` 原文与任何由它派生的
明文键名后缀、麦克风/网络授权的系统状态（`MicrophoneManager.swift:718-723` 已经在存授权枚举与
"最后一次错误字符串"，后者是本文要求逐步搬走的对象）、序列号与设备产品名
（依据 `usb-device-enumeration-tests.py` 顶部说明的既定口径：序列号在读到时即摘要，产品名不存不暴露）、
以及**任何会被日志抓走的东西**——第 6 节给出可判定的规则，而不是一句"注意脱敏"。

一句话概括非目标：**这不是"记忆系统"，是"有版本号的偏好存储层"**。用户行为预测、云端同步、
多设备一致性、"AI 记住我的习惯"都不在本设计内，理由见第 9 节。

---

## 3. 为什么不引入现成库

五个维度各 1–5 分（5 最好），**分数只用于表达取舍顺序，不是度量**：

| 候选 | 依赖体积 | 签名/公证影响 | 沙盒与 entitlement | 可审计性 | 崩溃原子性 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 原生 `UserDefaults` + 本文手写 envelope | 5（零新增） | 5（零影响） | 5（现在就没有沙盒） | 5（纯仓库内源码，现有 78 个脚本能读） | 3（单键安全，复合值不安全，见 4.4 实测） | **采用** |
| Keychain（仅敏感项） | 5（系统框架） | 5（`Security` 已被 `CodeSignatureProfile.m` 引用） | 4（ad-hoc 下访问组/entitlements 行为〔未验证〕） | 4 | 4 | **仅作为例外通道**，且默认不用 |
| SQLite（裸 `libsqlite3`，不用 GRDB） | 3（系统 dylib，无需打包） | 4（不新增 Mach-O） | 5 | 3（schema 迁移代码要自己写门禁） | 5（WAL 下事务原子） | 备胎：只有当偏好量级到千条或需要查询才考虑 |
| GRDB / SwiftData | 2（SPM 目标 + Swift 版本门槛） | 2（新增动态库需重签，见下） | 4 | 2（迁移逻辑在库里，仓库读不到） | 5 | 不采用 |
| MMKV | 2（C++ 静态库 + libc++） | 3 | 4 | 1（预编译二进制，本仓库的审计脚本一律读不到内部） | 5 | 不采用 |

**决定性理由不是分数，是三条项目事实：**

1. 〔实测〕`Moonlight.entitlements` 里**没有** `com.apple.security.app-sandbox`，
   因此"必须换存储才能拿到文件权限"这类理由不成立；`~/Library/Preferences` 与
   `Application Support` 今天就可写。
2. 〔实测〕`scripts/codesign-bundle.sh` 的签名目标由一个 `find` 决定：
   只有 `Contents/{Frameworks,PlugIns,Libraries}` 下的 `*.framework|*.dylib|*.xpc|*.bundle`
   和 `Contents/Library/LaunchServices` 下的可执行文件会被逐个体签，最后整体签 `.app`。
   由此：静态库（`.a`）不产生独立 Mach-O，**不需要**任何改动；把 MMKV/GRDB 做成动态 xcframework 落进
   `Contents/Frameworks` 则会被现有循环自动 ad-hoc 重签，**不会**立刻红，但 `--force --sign -` 之前会
   先 `--remove-signature`，即上游签名被抹掉、由 ad-hoc 身份接管——这与仓库现在的 vendored
   xcframework 处理方式一致〔实测：`xcframeworks/` 下已有 FFmpeg/Opus/SDL2/OpenSSL 四个〕。
   至于新增 framework 会不会撞 `dmg-audit.py`：〔实测〕`grep -i framework scripts/dmg-audit.py` 无匹配，
   即该门禁对 framework 集合没有断言。
3. 〔实测〕本仓库对"读不懂的东西"的容忍度极低：`credential-scan-audit.py`、`assertion-battery.py`
   这类门禁全部靠读源码文本工作。一个预编译二进制存储层会直接减少可断言的面积。

**Keychain 的定位要说清楚**：它是"凭据的存放地"，而第 2.2 节已声明本设计不存凭据，所以 Keychain 在这里
**不该被顺手引入**。真正需要 Keychain 的东西（配对私钥）现在由 `CryptoManager` / `PairManager` 持有，
搬动它属于另一个设计。〔未验证〕"ad-hoc 签名下 Keychain 访问组是否可用"没有实测，故本文不依赖它。

---

## 4. 数据模型与命名空间

### 4.1 键规则

```
moonlight.<domain>.<key>            单一标量/数组
moonlight.<domain>.<entity>.<key>   按主机分区的值，<entity> 必须是摘要，不得是原文
moonlight.schema                    域级 schema 版本（整数）
```

- `<domain>` 白名单（编译期枚举，见 5.2）：`input stream ui redirection diagnostics discovery workflow`。
- `<entity>` 取 `h<8hex>`，即 `SHA256(hostUuid)` 前 8 位十六进制。
  〔推理〕`CommonCrypto` 已在链接闭包内（`CryptoManager.m`、`HttpManager.m:960` 均使用），
  因此摘要不引入任何新依赖；实现前需实测确认（见第 8 节 Stage 0 判据）。
- 现有六套旧键**不改名**，只登记为"只读来源"（Stage 0 的清单），新键一律走上面的规则。
  理由：改名就是第 1.3 节那个错误的第二次表演。

### 4.2 记录形状（envelope）

每个键存一个 dictionary：`{ "s": <schema 整数>, "v": <值> }`。

为什么不是"一个域一个 blob"：4.4 的实测说明复合 blob 会被多持有者覆盖；为什么不是"完全不带版本"：
第 1.3 节已经证明改键名当迁移的代价。**每键自描述**是这两者之间唯一不需要额外协调协议的选择。

### 4.3 读取与写入的策略（本文的核心约定）

读取返回 `(value, source)`，`source` 有六个互不相同的名字〔实测：spike 断言了六者名字不重复〕：

| source | 触发条件 | 返回值 | 是否写回 |
| --- | --- | --- | --- |
| `default` | 键不存在 | fallback | 否 |
| `stored` | `s == current` | 原值 | 否 |
| `migrated` | `oldest ≤ s < current` 且每步都有规则 | 迁移后的值 | 允许，写时升版本 |
| `tooOld` | `s < oldest` | fallback | 否，且**不删除原记录** |
| `tooNew` | `s > current` | fallback | 否，**且拒绝本次写入** |
| `unreadable` | 无 envelope、版本不是整数、payload 形状不认识 | fallback | 否 |

"未知版本按不利处理"落成三条可判定的话：不猜字段含义、不用猜测值覆盖磁盘、把拒绝计入 `unreadable/tooOld/tooNew`
三个**各自独立**的计数器。第三条不是形式主义——〔实测〕spike 里把 `tooNew` 折叠进 `unreadable` 的变异被断言抓住了，
因为诊断问的是"我读不懂"还是"这文件是新版写的"，这两个答案给出的处置完全不同。

### 4.4 四条平台事实（全部来自本次 spike，直接决定上面的形状）

1. 〔实测〕**单键写不存在半值**：8 线程 × 每键 3000 次写，并发读回并按 payload 自校验，
   `3349 / 520 / 255` 等多次运行累计数千次读，**0 次**读到非完整写入值。
   所以"单键原子性"不需要额外锁。
2. 〔实测〕**复合值的 read-modify-write 稳定丢更新**：两个持有者各自 `dictionaryForKey` 读一次、
   之后反复保存自己那份（这正是"面板加载时读、控件变化时写"的形状），
   最终记录里只剩一个字段——4 次运行 4 次复现。
   结论：任何复合偏好**必须只有一个写者**，或者拆成每字段一键。
3. 〔实测〕**同进程两个 `NSUserDefaults` 实例互相可见，无需 `synchronize`**；
   加 `synchronize` 不改变结果。所以第 2 条是"副本过期"问题，不是缓存问题，也就**不能靠 synchronize 治**。
4. 〔实测〕**乐观 CAS（写前比 revision、写后读回校验）不是保证**：24 轮 × 4 次运行，
   两个字段都保住的轮数为 22 / 22 / 23 / 21，重试次数只有 1–2 次。
   即"读回校验"几乎检测不到冲突（因为读的是自己那个实例的缓存），却确实会丢。
   所以设计上**不提供 CAS**；要么单写者，要么分键。

另有三条与存储层直接相关的平台行为：

5. 〔实测〕**写入非法值直接终止进程，不是异常**：往 `NSUserDefaults` 写 `NSNull` 得到 SIGABRT，
   崩溃栈为 `CoreFoundation _CFPrefsValidateValueForKey → abort`
   （`~/Library/Logs/DiagnosticReports/why_abort.bin-2026-09-24-062835.ips`），`@try/@catch` 抓不住；
   以 `fork+execv` 独立进程复现，观察到 `signal 6`。
   → 写前必须自己做 property-list 类型校验（spike 的 `IsStorableValue`），
   "清除一个偏好"必须走 `removeObjectForKey:` 而不是塞 `NSNull`。
6. 〔实测〕**磁盘上的 plist 是滞后子集**：一次运行结束后，`defaults read <suite>` 看到 25 个键，
   而 `~/Library/Preferences/<suite>.plist` 只有 22 个键，`plutil -lint` 合法。
   → 导出/诊断快照只能走 API（`persistentDomainForName:` 等），**禁止**读 plist 文件；
   macOS 27.2 上 `defaults synchronize <domain>` 已不是有效子命令（实测打印用法并退出）。
7. 〔实测〕**整域损坏表现为"空域"**：往Preferences 里塞垃圾文本、以及把合法 plist 截断一半，
   两种情况下 `defaults read` 报 `Domain ... not found`，ObjC 侧 `objectForKey` 返回 nil、
   `volatileDomainForName:` 返回 0 键，且**不崩溃**。
   → 损坏是静默的：域级自检必须自己写（"上次记住了 N 个键、这次读到 0 个"必须能报警），
   这正是第 4.3 节三个计数器存在的另一半理由。

---

## 5. API 形状

### 5.1 现状的病因不是"用了 UserDefaults"，是"键名是字符串"

〔实测〕`SettingsModel+DerivedValues.swift:1047-1057` 同时读 `defaultDisplayMode`（Int）和
`autoFullscreen`（Bool）来推断同一件事，两条键都没有类型说明。拼错一个键名不会有任何编译提示，
只会变成"设置看起来没生效"。

### 5.2 ObjC 侧

键名不散落靠**一道门禁**而不是靠类型系统（类型系统只能保证"是个枚举值"，不能保证"这个调用点想要哪把键"）：

```objc
// Limelight/Preferences/MLPreferenceKeys.h   （Stage 1 才落地，本文不实现）
typedef NS_ENUM(NSInteger, MLPrefKey) {
    MLPrefKeyStreamResolution,
    MLPrefKeyInputStreamMouseSpeed,
    MLPrefKeyUISelectedSettingsPane,
    ...
};
FOUNDATION_EXPORT NSString *MLPrefKeyName(MLPrefKey key);        // 唯一拼写处
FOUNDATION_EXPORT NSString *MLPrefEntityName(NSString *rawID);   // h<8hex>，摘要在此发生

@interface MLPreferenceStore : NSObject
- (instancetype)initWithDefaults:(NSUserDefaults *)defaults;     // 注入，沿用 1.2 第 2 条
- (nullable id)valueForKey:(MLPrefKey)key fallback:(nullable id)fallback
                     source:(MLPrefReadSource * _Nullable)source;
- (BOOL)setValue:(nullable id)value forKey:(MLPrefKey)key;       // nil → removeObjectForKey:
- (MLPrefStats)unreadableCounts;                                 // tooOld / tooNew / unreadable 分开
@end
```

### 5.3 Swift 侧

```swift
let store = MLPreferenceStore(defaults: .standard)
let pane: MLSetting<String> = store.setting(.uiSelectedSettingsPane, fallback: "stream")
// 面板里：pane.wrappedValue 读写，pane.projectedValue 给 SwiftUI 当 Binding
```

要求与待验证项：

- `MLSetting` 用 `@propertyWrapper` 实现，**必须**提供 `projectedValue: Binding`，
  因为现役代码大量是 `@AppStorage`（〔实测〕9 处，分布在 8 个文件）并依赖它驱动刷新。
  〔未验证〕自定义 wrapper 与 `@AppStorage` 在外部改值（例如另一面板写了同一键）时的刷新时机是否等价，
  Stage 1 第一条判据就是拿一个真实面板做双写观察，不通过就退回"枚举键名 + 显式 get/set"。
- 迁移期允许 `@AppStorage` 与新 API 共存，但**新增** `@AppStorage("` 与 `UserDefaults.standard.set(`
  由 Stage 0 的门禁拦下（第 7 节），存量记入清单不阻塞。

### 5.4 为什么不做"字符串键 + 命名规范文档"

因为第 1.1 节六套风格本身就是这种方案在同一个仓库里失败六次的记录。

---

## 6. 隐私与日志

### 6.1 三条可判定的规则（不写"注意脱敏"）

1. **值不进日志，键名可以**。_store_ 自身禁止出现 `NSLog`/`printf`〔实测：仓库对同类模型已有此断言〕，
   要报就是计数与 source 名，两者都不含用户数据。
2. **禁止 `description`/`%@` 打印整个 domain**。〔实测〕第 4.4 第 6 条说明整域快照只有一行 API 就能拿到，
   所以"顺手 dump 全部偏好"是极容易写出来的日志，必须是门禁级禁止项。
3. **含 `<entity>` 的键只允许输出摘要形态**。即 `moonlight.input.h1a2b3c4.mouseSpeed` 可以进日志，
   而 `...-moonlightKeyboardTranslationRules` 这种带主机原文的键名不可以——
   〔实测〕后者是今天的现实形状（`SettingsModel.swift:88`）。

### 6.2 与既有门禁的冲突点（实测，含解法）

| 冲突 | 证据 | 解法 |
| --- | --- | --- |
| 键名常量化会让现有门禁变红 | `device-redirection-panel-model-tests.py:626` 断言实现文本里含 `"moonlight.usbredirection.` | Stage 0 **不搬**这四把键，只登记；Stage 1 若要搬，必须同一提交里改该断言为"经 `MLPrefKeyName()` 生成"，并把这条写进 Stage 1 验收 |
| 正则扫字面量的门禁会漏扫 | `l10n-audit.py` 用正则扫 `Limelight/` 内的字符串字面量（`:244`、`:371`、`:651`），改枚举常量后扫不到 | 键名集中到 `MLPreferenceKeys.m` 单文件后，门禁改为"该文件内字面量全集 ⊆ 白名单"，反而比散扫更强；本地化键不受影响（〔实测〕l10n 只扫 `Limelight/`，不扫 docs 与 spikes） |
| 凭据扫描的形状误伤 | `credential-scan-audit.py` 的 `quoted-credential-assignment` 规则匹配"凭据样式名 + 引号 + ≥24 字符值"，扫描对象是 `git ls-files` 全集（含文档） | 文档与测试里的样例一律写成拼装形态（该脚本自己就是这么做的，见其 `_joined`），行内豁免用官方 `credential-scan-audit:allow` 标记 |
| 新增测试必须进 CI 才叫门禁 | `local-gates.sh` 的清单来自 `.github/workflows/build.yml`（`gate_commands()`），不在 workflow 里的脚本等于没跑 | Stage 1 提交必须同时加 workflow 步骤，否则该门禁本地绿、CI 不存在 |

---

## 7. 门禁与变异计划

新增 `scripts/user-memory-store-tests.py`（Stage 1），照现有惯例：真 clang 把
`MLPreferenceKeys.m` + `MLPreferenceStore.m` 编成独立 harness、不链 IOKit、注入临时 suite，
`MIN_STORE_CHECKS` 作为 harness 自报 case 数的地板。

15 个植入缺陷已在 spike 上跑过（`spikes/user-memory/run_mutants.py`，结果见第 10 节）：
**14 个被抓，1 个无法区分**。表内"失败表现"就是实测输出的首条 FAIL：

| # | 植入的缺陷 | 失败表现（实测） |
| --- | --- | --- |
| 1 | 未来 schema 照样读 | `FAIL a record from a newer build answers the fallback and says tooNew` |
| 2 | 允许本版本覆盖新版本写的记录 | `FAIL this build refuses to write over a key a newer build owns` |
| 3 | 所有旧 schema 都当作可迁移 | `FAIL a schema older than the migration floor is refused rather than guessed` |
| 4 | 版本写成字符串被强转成数字 | `FAIL a schema version written as a string is not coerced into a number` |
| 5 | 迁移步骤把自己不认识的 payload 原样返回 | `FAIL step 1 refuses to migrate what it has no rule for` |
| 6 | 无 envelope 的裸值被当作可信 | `FAIL a bare unversioned value is called unreadable and the fallback answers` |
| 7 | 读不懂的记录不计数（静默跳过） | `FAIL and the refusal is counted, the way the panel counts unreadable rules` |
| 8 | `tooNew` 折叠进 `unreadable` | `FAIL the tooNew case is counted on its own, not folded into unreadable` |
| 9 | 写前不再校验值类型 | `FAIL a non-property-list object is refused for the same reason` |
| 10 | 拒绝时返回 nil 而不是 fallback | `FAIL a record from a newer build answers the fallback and says tooNew` |
| 11 | 每次写都自称 schema 1 | `FAIL a value written by this build reads back as stored, not migrated` |
| 12 | 清除偏好改成写 `NSNull` | 进程 `SIGABRT`（`exited -6`），harness 非零退出 |
| 13 | 读侧不再校验自己读到什么 | `FAIL the reader really ran its checker once per read: a check that stopped being called would otherwise report a clean run forever` |
| 14 | 并发值的自校验摘要算错 | `FAIL no reader ever observed a value that was not one whole write` |
| 15 | 去掉复合写的 `@synchronized` | **未被抓**（见下） |

第 15 条要说实话：去掉锁之后测试仍然通过，因为在同一进程里"每次写前重读"的两个线程本来就收敛
（4.4 第 3 条）。按 `code-signature-profile-tests.py` 的既有态度——"a mutation nobody can tell apart is noise"——
这条**不进正式门禁**，并且留下一条禁令：**不得写"实现里必须出现 `@synchronized`"这种字面量断言**，
那只会制造假证据。真正被证明有效的是"别让两个持有者各存一份副本"（4.4 第 2 条）。

两个变异在补强断言之前也漏抓过，记录以免被误当成一直成立：
"迁移步骤透传"最初漏抓，原因是迁移地板为 2 时那行分支**不可达**，于是补了直调 `Migrate()` 的三条断言才抓住；
"读侧不再校验"最初漏抓，原因是被破坏的正是检查器本身，于是补了"检查器每读必调用一次"的计数断言
（思路来自 `l10n-audit.py` 的 `scan_health()`：不许把空扫描读成干净树）。

---

## 8. 分阶段落地

### Stage 0 —— 只做两件事：键名常量化 + 只读迁移清单

- 新增 `MLPreferenceKeys.{h,m}`，把散落的键名收进枚举与唯一拼写处；**不改变任何一次读写的行为**，
  不引入 envelope，不动现有四把 `moonlight.usbredirection.*`。
- 产出一份"现网键清单"（键名、类型、写入者、是否有第二处读者、是否含主机标识），进设计文档或 `docs/` 附表。
- 验收判据：
  1. 〔可判〕全仓 `standardUserDefaults` / `UserDefaults.standard` 调用点数量不增加；
  2. 〔可判〕新增门禁断言"键名字面量仅出现在 `MLPreferenceKeys.m`"；
  3. 〔可判〕第 6.2 表中第 1 行的门禁保持绿色（证明没有提前搬键）；
  4. 〔待实测〕`CommonCrypto` 摘要在**不含 `Limelight/Crypto`** 的独立 harness 里可编译可运行
     —— 这条不过，第 4.1 的 `<entity>` 摘要方案就不能用，必须先解决它。
- **不可跳过的理由**：envelope 一旦上线，"同一个键被两个不同 schema 的代码读"就成了兼容性问题；
  先把键名收敛到一处，才谈得上给每把键钉版本号。此外 Stage 0 是唯一"零用户可感知风险"的阶段，
  用来验证第 6.2 那四条门禁冲突会不会咬人。

### Stage 1 —— 版本化读写层（含 spike 里的全部拒绝语义）

- 新增 `MLPreferenceStore.{h,m}`、`MLSetting`（Swift）、`scripts/user-memory-store-tests.py` 并登记进 workflow。
- 新键一律 envelope；旧键走"只读回落到 `unreadable`/`default`"，**不批量改写**。
- 验收判据：
  1. 〔可判〕第 7 节 14 条变异全部被抓，第 15 条不存在；
  2. 〔可判〕`unreadable / tooOld / tooNew` 三个计数各自可达且各自只被对应场景增加；
  3. 〔可判〕写 `nil` 等价于 `removeObjectForKey:`，且写非法类型的值**不可能**到达 `CFPrefs`；
  4. 〔待实测〕`MLSetting` 的双向绑定在真实面板里与 `@AppStorage` 行为一致（两个面板改同一键）；
  5. 〔可判〕store 自身无日志出口，且没有任何一条 API 返回"整个 domain 的字典"。
- **不可跳过的理由**：Stage 2 的导出格式必须以 schema 为前提。先做导出再做版本化，
  等于把今天这套六风格键名+无版本记录永久固化成一种文件格式，之后再没有便宜的重来机会。

### Stage 2 —— 导出 / 导入（跨设备仍然不做）

- 导出走 API 取域快照〔实测依据：4.4 第 6 条，读 plist 文件会拿到滞后子集〕，
  导出内容含 schema 版本；导入按第 4.3 的策略逐键判定，`tooNew` 一律不覆盖。
- 验收判据：导出→清空→导入后三个计数器均为 0；把导出版本号改大一位后导入，
  全部键落到 `tooNew` 且磁盘原状态逐字节不变。
- **跨设备同步不在 Stage 2**：〔实测〕本仓库 ad-hoc 签名且无沙盒，
  iCloud 键值同步需要带 identity 的 provisioning，而 ad-hoc 下拿不到；
  〔未验证〕具体错误形态没有测过。因此"跨设备"在拿到 Developer ID 之前是纯讨论。

---

## 9. 风险与被高估的东西

明确说**不需要**这套东西也能满足的诉求，避免为了架构而架构：

1. **绝大多数现有偏好不需要 envelope**。分辨率、帧率、面板选择、日志级别——
   今天 `@AppStorage` 一行就能表达，加 envelope 只换来"以后能迁移"。这笔交易只有在确实要改
   某把键的含义时才回本，所以 Stage 1 是"新键走 envelope，旧键不批量改写"。
2. **"跨会话记忆"这个词被高估**。第 1.1 的六套键名已经跨会话记住了所有需要的东西；
   真实缺陷是**键名拼写漂移**与**改含义即丢数据**，两者分别由 Stage 0 和 Stage 1 解决，
   都不需要新存储引擎。
3. **不需要并发保护框架**。〔实测〕单键写不需要锁；需要防的是"两个持有者各存一份副本"
   （4.4 第 2 条），那是所有权问题，加锁、加 revision、加 CAS 都治不好它
   （4.4 第 3、4 条实测）。**唯一有效的动作是让复合偏好只有一个写者**。
4. **不需要 Keychain**。它属于凭据，而凭据不在本设计范围内（第 2.2、第 3 节）。
5. **不需要 SQLite/MMKV/SwiftData**。理由见第 3 节三条项目事实。
6. **需要立刻修的只有一件**：第 1.4 那条主机标识明文进键名。它跟"记忆系统"无关，
   是一个已经在发生的暴露面，可以单独提一个小改动（先确认 `TAG_UNIQUE_ID` 的真实形态再动）。

其余风险：spike 结论绑定 macOS 27.2〔实测〕，跨版本未测；`MLSetting` 的刷新等价性未验证；
`<entity>` 摘要依赖 `CommonCrypto` 可用性的 Stage 0 判据；CI runner 的 macOS 版本与本机不同
（〔推理〕行为差异风险，故 Stage 1 门禁必须在 CI 上先跑绿再合）。

---

## 10. 附录：spike 原始输出（原样粘贴，未删行）

复现：`spikes/user-memory/README.md` 给出脚本位置与命令。环境同第 0 节。

### 10.1 spike 1 —— schema 版本迁移 + 未知版本按不利处理（29 checks 全绿）

```
clang: /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang
sdk:   /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX27.0.sdk
== spike 1: schema versioning on macOS Version 27.2 (Build 26B5091g) ==
ok   an absent key answers the fallback and says it was absent
ok   a value written by this build reads back as stored, not migrated
ok   the record on disk carries its own schema version
ok   a bare unversioned value is called unreadable and the fallback answers
ok   and the refusal is counted, the way the panel counts unreadable rules
ok   the refusal left the foreign value on disk instead of erasing evidence
ok   a v2 pair migrates to the v3 string and reports that it was migrated
ok   reading does not rewrite the record: migration is a write-layer decision
ok   the migrated value may be written forward
ok   and the write advances the stored schema
ok   a schema older than the migration floor is refused rather than guessed
ok   the old record survives the refusal so a newer build can still read it
ok   a record from a newer build answers the fallback and says tooNew
ok   the tooNew case is counted on its own, not folded into unreadable
ok   this build refuses to write over a key a newer build owns
ok   and the future record is byte-for-byte the one that was there
ok   a v2 record whose payload is not a pair is refused instead of formatted as "(null)x"
ok   a schema version written as a string is not coerced into a number
     a separate process writing [NSNull null] exited with signal 6
ok   measured: NSUserDefaults aborts a process on a null payload, it does not raise
ok   step 1 refuses to migrate what it has no rule for
ok   a step beyond the current schema is refused too
ok   the one real step still works
ok   a stored zero is a stored value, not a missing one
ok   the six read sources have six distinct names
ok   a null value is refused by the write layer instead of reaching CFPrefs
ok   and nothing was stored on the way to the refusal
ok   a non-property-list object is refused for the same reason
ok   a nested property-list value still passes
ok   writing nil removes the record rather than storing a null

RUN PASSED (29 checks, 0 failures)
```

### 10.2 spike 2 —— 并发写（16 checks 全绿，一次完整运行）

```
== spike 2: concurrency on macOS Version 27.2 (Build 26B5091g) ==
     (520 reads, 0 of them did not verify)
ok   no reader ever observed a value that was not one whole write
ok   the reader really ran its checker once per read: a check that stopped being called would otherwise report a clean run forever
ok   the reader really was running beside the writers
ok   after the writers stop, each key holds a value its own thread wrote
     two holders that never re-read: final record keys = rev,right
ok   measured: two holders each saving their own copy of one record lose one of the two settings, which is why a composite preference needs one writer
ok   serialising the read-modify-write keeps both fields
     compare-by-read-back over 24 rounds: both settings survived 22, one was lost 2, retries 1
ok   every round was counted exactly once, so the two numbers above are the whole story rather than the rounds that happened to be interesting
ok   the second instance agreed the key was empty to begin with
ok   measured: inside one process a second instance sees a write the first made, without any synchronize
ok   and synchronize changes nothing about that, which is why the lost setting above is a stale-copy problem and not a caching one
ok   the driver found its own path, so it can start real peers
ok   every peer process wrote and exited of its own accord
     an instance created after the peers ran saw 6 of 6
ok   a newly created instance sees what the peer processes stored
     the instance that already existed saw 6 of 6 before -synchronize
     the same instance saw 6 of 6 after -synchronize
ok   the stale instance catches up once it synchronizes (the before-count is printed, not asserted, because it is a caching choice the platform is free to make)
     peers that synchronized: 3 of 3 visible; peers that did not: 3 of 3
ok   a peer that synchronized is visible, as expected
ok   measured: a peer that never called -synchronize is just as visible, so -synchronize is not the cross-process visibility switch
suite: usermem.concurrency.80897
RUN PASSED (16 checks, 0 failures)
```

CAS 那一节重复三次的结果（说明它是概率现象，因此本文没有把它写成保证）：

```
compare-by-read-back over 24 rounds: both settings survived 22, one was lost 2, retries 2
compare-by-read-back over 24 rounds: both settings survived 23, one was lost 1, retries 2
compare-by-read-back over 24 rounds: both settings survived 21, one was lost 3, retries 1
```

### 10.3 植入缺陷是否被抓（15 个：14 抓、1 不可区分）

```
== planted defects: does the spike notice? ==
clang: /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang
sdk:   /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX27.0.sdk
ok   the migration spike compiles and passes its own checks
ok   the concurrency spike compiles and passes its own checks
ok   caught: a schema from the future is read anyway              | FAIL a record from a newer build answers the fallback and says tooNew
ok   caught: this build writes over a newer build's record        | FAIL this build refuses to write over a key a newer build owns
ok   caught: every old schema is treated as migratable            | FAIL a schema older than the migration floor is refused rather than guessed
ok   caught: a version written as text is coerced to a number     | FAIL a schema version written as a string is not coerced into a number
ok   caught: a migration step returns what it did not understand  | FAIL step 1 refuses to migrate what it has no rule for
ok   caught: an unversioned bare value is believed                | FAIL a bare unversioned value is called unreadable and the fallback answers
ok   caught: an unreadable record is not counted                  | FAIL and the refusal is counted, the way the panel counts unreadable rules
ok   caught: tooNew is folded into unreadable                     | FAIL the tooNew case is counted on its own, not folded into unreadable
ok   caught: the write layer stops vetting value types            | FAIL a non-property-list object is refused for the same reason
ok   caught: a refusal answers nil instead of the fallback        | FAIL a record from a newer build answers the fallback and says tooNew
ok   caught: every write claims schema 1                          | FAIL a value written by this build reads back as stored, not migrated
ok   caught: clearing a preference stores a null instead          | exited -6
ok   caught: the reader stops checking its reads                  | FAIL the reader really ran its checker once per read: a check that stopped being called would otherwise report a clean r
MISS not caught: the composite write drops its lock                 | the spike still passed
ok   caught: a peer's value is renamed so readers disagree        | FAIL no reader ever observed a value that was not one whole write

14 caught, 1 missed of 15 planted defects
  missed: the composite write drops its lock
```

### 10.4 非法值写入为什么会终止进程（崩溃报告摘要）

```
signal: SIGABRT
   libsystem_kernel.dylib __pthread_kill
   libsystem_pthread.dylib pthread_kill
   libsystem_c.dylib abort
   CoreFoundation _CFPrefsValidateValueForKey.cold.2
   CoreFoundation _CFPrefsValidateValueForKey
   CoreFoundation createDeepCopyOfValueForKey
```

### 10.5 域损坏与落盘滞后（两条命令级实测）

```
$ printf 'this is not a plist at all {{{ >>' > ~/Library/Preferences/usermem.corrupt.328.plist
$ plutil -lint ~/Library/Preferences/usermem.corrupt.328.plist
/Users/liguangming/Library/Preferences/usermem.corrupt.328.plist: (Unexpected character t at line 1)
$ defaults read usermem.corrupt.328.plist
Error: Domain 'usermem.corrupt.328' not found.
$ ./corrupt_probe.bin usermem.corrupt.328
stringForKey -> (nil)
objectForKey -> (nil)
volatileDomainForName -> 0 keys
persistentDomainForName -> (nil)

（另一形态：把合法 plist 截断一半）
$ plutil -lint ~/Library/Preferences/usermem.trunc.10475.plist
/Users/liguangming/Library/Preferences/usermem.trunc.10475.plist: (Malformed data byte group at line 1; invalid hex)
$ ./corrupt_probe.bin usermem.trunc.10475
stringForKey -> (nil)
objectForKey -> (nil)
volatileDomainForName -> 0 keys
persistentDomainForName -> (nil)

（落盘滞后：API 视角与文件视角键数不一致）
$ defaults read usermem.concurrency.81413 | grep -c '='
25
$ python3 -c "import plistlib,os;d=plistlib.load(open(os.path.expanduser('~/Library/Preferences/usermem.concurrency.81413.plist'),'rb'));print('keys:',len(d))"
keys: 22
$ plutil -lint ~/Library/Preferences/usermem.concurrency.81413.plist
/Users/liguangming/Library/Preferences/usermem.concurrency.81413.plist: OK
$ defaults synchronize usermem.concurrency.81413      # 打印用法并退出：macOS 27.2 无此子命令
```

### 10.6 跑不出来 / 没跑的部分（如实）

- **MMKV、GRDB、SwiftData 的体积与签名影响没有实测**：没有真的把它们接进构建。
  第 3 节的分数是取舍顺序，其中"静态库不需额外签名""find 会自动接管动态库签名"两条
  来自 `codesign-bundle.sh` 的文本〔实测〕，"引入后 CI 各审计仍绿"属于〔未验证〕。
- **`TAG_UNIQUE_ID` 的真实形态没有测**：没有抓取过任何真实主机的响应，所以第 1.4 的指纹风险是〔推理〕。
- **ad-hoc 签名下 Keychain 访问组的行为没有测**：第 3 节标为〔未验证〕。
- **复合偏好丢更新在真实 UI 路径上的复现没有做**：spike 用的是两个线程各自持有一份 dictionary 的
  最小形状，与"两个 SwiftUI 面板各持一份 SettingsModel"是否同形，属于〔推理〕，Stage 1 判据 4 会去证实它。
- **`@propertyWrapper` 的刷新时机没有测**：见第 5.3。
