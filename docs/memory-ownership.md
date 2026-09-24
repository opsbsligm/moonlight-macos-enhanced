# 临时对象图的所有权：第一次把 `leaks` 跑在这条路径上

> English summary: running Apple's `leaks` against the Debug render-probe build — for the
> first time in this project — found a real retain cycle in first-party code.
> `TemporaryHost.appList` retains its `TemporaryApp`s (`TemporaryHost.h:41`) while
> `TemporaryApp.host` retains the host back (`TemporaryApp.h:20`), so the pair is garbage
> for anyone but itself. That matters because `-[DataManager getHosts]` builds a *fresh*
> graph on every call (`DataManager.m:175`) and `SettingsModel.hosts` is a computed property
> (`SettingsModel.swift:122`) with 17 call sites: each evaluation pins the graph it made.
> Flipping the back-pointer to `weak` is **not** safe by itself — `StreamViewController`
> holds an app and no host, and an asynchronous box-art path reads `app.host.uuid` — so this
> page records the measurement, the fix, and the one thing that has to exist before the fix
> is honest. No ownership change was made here, because the streaming path cannot be
> exercised on this machine.

## 1. 实测结论

| 项 | 结果（本机，`8f63e1f`） |
|:---|:---|
| 被测对象 | Debug 构建 + `ML_RENDER_PROBE=1`（设置页渲染完即退出） |
| 工具 | `/usr/bin/leaks --atExit`（Debug 带 `get-task-allow`，无需 sudo） |
| 进程汇总 | **105 leaks for 10896 total leaked bytes** |
| 详列的栈 | 9 个：6 × `ROOT CYCLE: <TemporaryApp>`、3 × `ROOT LEAK: <NSArray>` |
| 引用树 | 每个 cycle 记 `17 (1.91K)` —— **这 6 个栈共享同一批对象，不能相加** |
| 一手帧 | 全部落在 `static SettingsModel.hosts.getter` → `-[DataManager getHosts]`（`DataManager.m:178`/`:182`）→ `-[TemporaryHost initFromHost:]`（`TemporaryHost.m:46`） |

## 2. 复现方法，以及两个会骗人的地方

```bash
H=$(mktemp -d) && O=$(mktemp -d) && \
HOME="$H" ML_RENDER_PROBE=1 ML_RENDER_PROBE_OUTPUT="$O" \
  leaks --atExit -- \
  build-render-probe/Build/Products/Debug/MoonlightEnhanced.app/Contents/MacOS/MoonlightEnhanced
```

- **`leaks` 的 `exit=1` 不是工具坏了**，是「发现了泄漏」的正常语义。把它当失败去重试，会重复劳动。
- **别用 `strings` 量主二进制**：Debug 的主二进制只有 38384 字节且被 strip，一手代码在包内的
  `MoonlightEnhanced.debug.dylib`。本轮先用 `strings` 量主二进制，得到「今日新增的字符串一个都没有」的
  假结论；正确的量具是 `Build/Intermediates.noindex/.../<File>.o`（那里能查到，且时间戳证明是本次重编）。

## 3. 环的形状

```
TemporaryHost ──appList(retain, TemporaryHost.h:41)──▶ TemporaryApp
      ▲                                                      │
      └─────────────host(retain, TemporaryApp.h:20)──────────┘
```

为什么它是累积而不是「退出前回收的一次性垃圾」：

- `-[DataManager getHosts]`（`DataManager.m:175`）**每次都 `alloc` 新的 `TemporaryHost`**，没有缓存；
- `SettingsModel.hosts` 是 `static var ... { }` 计算属性（`SettingsModel.swift:122`），同样没有缓存；
- `getHosts` 的调用点实测 **17 处**（Swift 11 + ObjC 6），其中多处就在设置页的取值路径上。

所以每求值一次，就多钉住一份图。探针那一次渲染只摊到几 KB，是因为测试账号的主机/应用少；
这台机器量的是**一次渲染**，不是长会话曲线（见 §6）。

## 4. 为什么不能顺手把 `host` 改成 `weak`

`weak` 子指针是标准解，但前提「没人只持有孩子」在这棵树上不成立。逐个持有方实测：

| 持有 apps 的地方 | 是否也持有 host | 结论 |
|:---|:---|:---|
| `AppsViewController.h:24` `strong TemporaryHost *host` | **是**（`self.host = newHost`，`:496`；并在 `:1592` 把 `app.host` 指回来） | 这条路径安全 |
| `StreamViewController.h:25` `strong TemporaryApp *app` | **否**（`StreamViewController.h` 里没有任何 `TemporaryHost` 属性） | 今天全靠这条环给 host 续命 |
| `AppAssetManager.m:58` → `AppAssetRetriever.app` | **否**，且 `AppAssetManager.m:34` 在异步路径里读 `app.host.uuid` 拼 boxart 路径 | 同上 |
| `AppsViewController.m:246` 的 `NSArray *hosts` 等局部变量 | 方法返回即释放 | 不构成根 |

`streamVC.app` 的唯一赋值点是 `AppsViewController.m:611-613`（`prepareForSegue:`）。串流开始后 apps 页是否还活着不由静态阅读决定——
而 `StreamViewController+Diagnostics.m` 里读 `self.app.host` 有 **21 处**（含 `activeAddress` 的写入与设置分桶读取）。
也就是说：**只改 `weak` 会把一个内存缺陷换成串流期的空指针**，那是行为变更，超出打磨模式的允许范围。

## 5. 修法（写清楚，等条件到位再做）

1. `TemporaryApp.host` → `weak`（ARC 下自动置零，部署目标 26.0）。
2. `StreamViewController` 增加 `strong` 的 host 属性，并在 `AppsViewController.m:611-613` 与 `app` 一起赋值。
3. 异步 artwork 路径按请求持有 host（`AppAssetRetriever` 加一个 strong host，`AppAssetManager.m:58` 处赋值），逻辑一字不改，只是续命显式化。
4. 验证：同一条 `leaks` 命令，`ROOT CYCLE: <TemporaryApp>` 的栈数 **6 → 0**（这是可红可绿的证据，不是推理）；
   再配一条门禁「给 `streamVC.app` 赋值处必须同时给 host 赋值」+ 植入反例，与「changelog 说某个 step 进了 workflow 而 workflow 里没有它」同形状。

**阻塞条件（不是借口，是缺的那条证据）**：串流路径本地跑不起来（需要真主机 + 真会话）。
`leaks` 只能为设置页那条路径担保，为串流期不存在的空指针担保不了。
在能给出「串流会话中 `app.host` 不为 nil」的红→绿证据之前，这个改动不做——
本仓库自己定下的规矩就是：没测过的路径不写进规则，也不写进代码。

## 6. 这次没测到

- ~~96 处泄漏未被归因~~ **已解决（2026-09-24 同日）**：那是 `leaks` 默认**树状报告**的性质，不是应用的性质。
  换成 `--list`（一块一行）后，同一份构建的 106 处泄漏逐块读全 106 块，落在 8 个类上，一手类仍是 18/6。
  这条差额因此变成了门禁的判据之一，见 §7。
- **MDNS / AppAsset 回调的 weak 化**：探针不走主机发现与 artwork 路径，所以「泄漏里没有它们」**不是**证据，那条登记项仍未验证。
- **长会话曲线**：没有跑「反复进出设置页 N 次」的累积测量，因此没有增长速率。
- **CI 里没有 `leaks` 门禁**：**这条在 2026-09-24 当天作废**——`scripts/leak-audit.py` 现在就是门禁。
  形状按本节原来的建议落（一手类**集合**不得扩大），但**每类实例数的绝对上限当天下午就被实测否掉了**：
  同一份 Debug 探针构建、同一台机器、无代码改动，连跑 9 次，泄漏的 `TemporaryHost` 分别是
  4、5、5、5、6、6、6、6、8，`TemporaryApp` 是 12、15、15、15、18、18、18、18、24——
  **比值每次都是 3.0**，总字节 6,176–15,696。设置页每看见一个主机就现造一张临时图，
  而「看见几个主机」取决于 `Limelight/Network/MDNSManager.m` 浏览 `_nvstream._tcp` 时收到几个应答，
  不是本仓库代码的性质。写死 18/6 的那版门禁当天下午就在没人改过代码的数字上红过两次。
- **所以门禁判的是形状不是计数**：一手类集合不得扩大；**扇出**（每个泄漏主机带几个 app）不得超过实测比值 + 每主机余量
  （基线：3 + 1）；总字节不得超过**每主机**预算（2,500/主机 + 2,000 地板，实测每主机 1,418–1,968）。
  主机数本身不受上限约束——那是 LAN 的数字。
  **runner 侧已实测（2026-09-24，run 35977080604，arm64 与 x86_64 各一次）**：GitHub 的 macOS runner 上 `leaks` 跑得起来，
  两次都发现 **0 个主机**、一手类**一个都没泄漏**，报告里是 287 / 288 个系统块、18,720–18,816 字节，
  门禁自己打出 note 说明「这次没建图，所以字节预算未判」。结论要写死在纸面上：
  **CI 的绿只担保一件事——没有新的一手类开始泄漏**；上面那个级别的循环在 CI 上没被复现，也就谈不上被它守住。
  真要让 CI 量到那张图，得让 Debug 探针在 CI 上确定性地种一个主机（连带 3 个 app）再渲染——
  那是 Debug-only 的代码改动，值得单独一轮，且同一条 commit 里要把扇出基线改对。
  **仍然没测到**：地板值 2,000 依旧是占位（CI 恰好是 0 主机的运行，字节预算未判，地板因此也没被量到过）；
  「有 app 没主机」判红这条只在红证里被量到，真实运行还没出现过那个形状。

## 7. 读不到就是红：判定形状与红证（2026-09-24）

内存门禁有一种别的门禁没有的失败方式：**读不到泄漏=绿**。`leaks` 的报告格式一旦在读取器下面变了，
计数归零，门禁高高兴兴地过了——它看起来和「真的没有泄漏」一模一样。本轮把这条从推理论证变成了实测：

- **实录的假绿**：`leak-audit.py` 第一次被指向的报告是默认**树状**报告。它的汇总行写着 105 处泄漏，
  正文是一张只详列 9 个块的图。读取器读到 0 个块，于是输出 `first-party classes: none`，
  还附了两条 note 说预算里的两个类「这次没泄漏」，**退出码 0**——脚下是 18 个 `TemporaryApp` 与 6 个 `TemporaryHost`。
- **新增判据**：报告自己的汇总说有几块，读取器就得读到几块，**两个方向都对不上就红**。
  少读=报告形状不对（树状图），多读=文件被改过或两份报告被拼在一起。宁可不判，也不把「没读到」判成「没泄漏」。
- **红证（`--red-team`）**：拿一份真实抓取的报告逐条破坏，看每条破坏是否都被拒、且拒得有理：
  扇出越界 / 冒出没预算的类 / 每主机字节越预算 / 汇总行被截掉 / 块被删而汇总留着 / 只剩 app 没有主机 /
  真的修好了一类（这条必须**放行**并给 note）。7 条破坏 7 个正确答复；
  对着上面那份树状报告跑时，红证**拒绝运行**而不是给出假绿。
- **红证的素材是实测不是仿写**：`scripts/leak-sample.txt` 是设置页一次 `--atExit --list` 抓取的真实报告，
  只把泄漏字符串里本机的 host GUID 与 IPv6 地址抹掉、地址归一化，类名/大小/块数都是 `leaks` 自己写的。
  用真实报告而不是 fixture 做红证的原因就在这：fixture 是照读取器的正则写出来的，读取器格式漂移时它照样全绿。

**红证证不了什么**：它证明读取器还在读，不证明上限数字是对的（数字的正确性靠上面那 9 次实测）；
也不证明 §5 的所有权修法可以做——那条仍卡在「串流会话里 `app.host` 不为 nil」这条本地给不出的证据上。

**门禁的牙齿范围**（写清楚，免得被当成内存总闸）：能抓到的是「多出一类一手对象」与「同一张图多了一个持有者」
（扇出会翻倍，不是加一）；抓不到的是「每个主机多漏一个几十字节的对象」——那只占每主机字节的几个百分点，
而字节预算故意留了余量。
