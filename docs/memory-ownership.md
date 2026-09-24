# 临时对象图的所有权：第一次把 `leaks` 跑在这条路径上

> English summary: running Apple's `leaks` against the Debug render-probe build — for the
> first time in this project — found a real retain cycle in first-party code.
> `TemporaryHost.appList` retains its `TemporaryApp`s (`TemporaryHost.h:41`) while
> `TemporaryApp.host` retains the host back (`TemporaryApp.h:20`), so the pair is garbage
> for anyone but itself. That matters because `-[DataManager getHosts]` builds a *fresh*
> graph on every call (`DataManager.m:175`) and `SettingsModel.hosts` is a computed property
> (`SettingsModel.swift:122`) with call sites counted in §13: each evaluation pins the graph
> it made.
> Flipping the back-pointer to `weak` is **not** safe by itself — `StreamViewController`
> holds an app and no host, and an asynchronous box-art path reads `app.host.uuid` — so this
> page records the measurement, the fix, and the one thing that has to exist before the fix
> is honest. No ownership change was made here, because the streaming path cannot be
> exercised on this machine. Section 13 (2026-09-25) removed the last guess in the chain:
> `getHosts` now counts its own calls, and the settings page measures one read per visit at
> its root, three for the stream pane, and none on dismissal -- so the growth rate that
> `leak-audit.py` reports is tied to the reads that cause it instead of merely sitting under
> a byte ceiling. Section 10 (same day) splits that blocker in two and measures the
> half that never needed a session: the Debug build now reports who keeps a host alive, three
> shapes with two controls, and the holder rule refuses a `weak` back-pointer while any
> assignment hands out an app without handing out its host. (That same rule corrected one row
> of the section 4 table: the box-art retriever does hold its host.) Section 11 corrects a
> measurement error that section 10 filed: a private `HOME` does not give a probe a private
> database — the support directory resolves out of the account, not out of `$HOME` — so the CI
> runner's ownership reading had been measuring the host the memory sweep planted a step earlier,
> and this laptop's real library had a probe's host in it. Probes now count the library by who
> wrote it and reap only what they can prove is theirs, and the two counts have to reconcile. Section 12 (next day) asks the question that left open -- where a
> deleted host's app records go -- and answers it by deleting a planted host and counting the rows:
> six to three, none orphaned. That is the model's `Cascade` measured rather than grepped, and it
> is reconciled on every push, because the reap on a runner deletes something every single time.

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
- `getHosts` 的调用点（口径与逐处清单见 §13）：生产代码 **16 处**（Swift 11 + ObjC 5），Debug
  探针里另有 6 处，其中多处就在设置页的取值路径上。

所以每求值一次，就多钉住一份图。探针那一次渲染只摊到几 KB，是因为测试账号的主机/应用少；
这台机器量的是**一次渲染**，不是长会话曲线（见 §6）。

## 4. 为什么不能顺手把 `host` 改成 `weak`

`weak` 子指针是标准解，但前提「没人只持有孩子」在这棵树上不成立。逐个持有方实测：

| 持有 apps 的地方 | 是否也持有 host | 结论 |
|:---|:---|:---|
| `AppsViewController.h:24` `strong TemporaryHost *host` | **是**（`self.host = newHost`，`:496`；并在 `:1592` 把 `app.host` 指回来） | 这条路径安全 |
| `StreamViewController.h:25` `strong TemporaryApp *app` | **否**（`StreamViewController.h` 里没有任何 `TemporaryHost` 属性） | 今天全靠这条环给 host 续命 |
| `AppAssetManager.m:58` → `AppAssetRetriever.app` | ~~**否**~~ **是**（2026-09-24 更正：`AppAssetRetriever.h:15` 就声明了 `TemporaryHost* host`，`AppAssetManager.m:59` 在赋 app 的下一行赋了它） | 异步 boxart 路径（`AppAssetRetriever.m:29` → `boxArtPathForApp:` 读 `app.host.uuid`）其实一直自己持有 host——**§5 的第 3 步这条路已经做完了** |
| `AppsViewController.m:246` 的 `NSArray *hosts` 等局部变量 | 方法返回即释放 | 不构成根 |

**这张表本轮被自己写的门禁更正了一行**：那条更正不是修辞，而是 §10 的门禁在扫全仓 `.app =` 赋值点时，
把 `retriever.app = app;` 与同一方法体内的 `retriever.host = host;` 配上了对，然后与这张表撞车。
表里那条「否」因此是**读代码读漏了一行**，而这条门禁存在的意义之一就是不让这种「读出来的一致」继续走。

`streamVC.app` 的唯一赋值点是 `AppsViewController.m:611-613`（`prepareForSegue:`）。串流开始后 apps 页是否还活着不由静态阅读决定——
而 `StreamViewController+Diagnostics.m` 里读 `self.app.host` 有 **21 处**（含 `activeAddress` 的写入与设置分桶读取）。
也就是说：**只改 `weak` 会把一个内存缺陷换成串流期的空指针**，那是行为变更，超出打磨模式的允许范围。

## 5. 修法（写清楚，等条件到位再做）

1. `TemporaryApp.host` → `weak`（ARC 下自动置零，部署目标 26.0）。
2. `StreamViewController` 增加 `strong` 的 host 属性，并在 `AppsViewController.m:611-613` 与 `app` 一起赋值。
3. 异步 artwork 路径按请求持有 host（`AppAssetRetriever` 加一个 strong host，`AppAssetManager.m:58` 处赋值），逻辑一字不改，只是续命显式化。
4. 验证：同一条 `leaks` 命令，`ROOT CYCLE: <TemporaryApp>` 的栈数 **6 → 0**（这是可红可绿的证据，不是推理）；
   再配一条门禁「给 `streamVC.app` 赋值处必须同时给 host 赋值」+ 植入反例，与「changelog 说某个 step 进了 workflow 而 workflow 里没有它」同形状。

**第 4 步的门禁已在 2026-09-24 落地**（`scripts/ownership-audit.py` 的 holder 规则：扫每一处 `X.app =` 赋值，
要求同一方法体内出现 `X.host =`；`weak` 之下有任何一条就判红，今天强指针之下则**新增**一条也判红，
并把现存的未配对点记在基线里）。它同时给出了 §10 的测量，把下面这条「阻塞」改成了一半能验证。

**阻塞条件（不是借口，是缺的那条证据）**：串流路径本地跑不起来（需要真主机 + 真会话）。
`leaks` 只能为设置页那条路径担保，为串流期不存在的空指针担保不了。
在能给出「串流会话中 `app.host` 不为 nil」的红→绿证据之前，这个改动不做——
本仓库自己定下的规矩就是：没测过的路径不写进规则，也不写进代码。

> **2026-09-24 的状态更新**：这句话里混着两个问题，本轮把它们分开了。
> **「谁持有谁」不需要会话**，§10 已经把它量出来了（三种形状 + 两条控制 + 头文件对账）；
> **「串流期会不会读到 nil」仍然需要会话**，而它现在改由源码侧的持有者规则担保：
> `weak` 一落地，任何「只把 app 交给持有者、没把 host 交出去」的赋值点都会判红。

> **2026-09-25 的登记（不编码）**：第 2 步与第 3 步的形状是「给 `StreamViewController` 与
> `AppCell` 各加一个 `strong` 的 host 属性并在赋值点配对」。它同时满足「新增属性」与
> 「改变 host 生命周期」两件事，**在打磨模式下属于登记项，不写代码**。
> 登记内容：需要一次带新形状的测量（cell ← app → host ← cell 会不会成环）＋
> `leaks` 的 ROOT CYCLE 6→0 ＋ §9 的增长速率不变，三者同时到位才算可提交；
> 门禁（holder 规则）已经在上膛状态，所以真做的那天它会自动把关，不怕被「只 flip 属性」绕过。
> 也就是说：`weak` 化的提交从此**必须先让 `streamVC.host`/`item.host` 这类赋值存在**才可能过 CI——
> 这条改动不再等一个跑不起来的会话，它等的是两个今天就能补上的属性。

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
  **这条在同一天做了**，见 §8：CI 从此有图可量，而「把扇出基线改对」变成了「把字节口径换掉」——
  上面那句「CI 的绿只担保没有新的一手类开始泄漏」到 §8 之后不再成立。
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
（2026-09-24 更新：这条的一半由 §10 的探针给出，另一半由 `ownership-audit.py` 的持有者规则从源码担保；
本门禁依旧只为「有没有多出一手泄漏」负责。）

**门禁的牙齿范围**（写清楚，免得被当成内存总闸）：能抓到的是「多出一类一手对象」与「同一张图多了一个持有者」
（扇出会翻倍，不是加一）；抓不到的是「每个主机多漏一个几十字节的对象」——那只占每主机字节的几个百分点，
而字节预算故意留了余量。

## 8. CI 上现在真有一张图：种主机，以及为此换掉的字节口径（2026-09-24）

§6 结尾留的那件事做了：**Debug 探针可以在没有局域网的机器上确定性地种出一张主机图**，
于是 `leaks` 门禁在 runner 上不再只能宣布「没有新的一手类开始泄漏」。

**种什么、怎么种**：`ML_RENDER_PROBE_SEED_HOSTS=<n>`，只在 Debug 且显式设置时生效，
内存扫描（`leak-audit.py` 的 `capture()`）设 1，视觉探针不设（它的像素断言是照空库写的）。
种的是 1 台主机 + 每台 3 个 app——3 是九次真实扫描量到的扇出，不是为了让基线好看；
地址落在 `192.0.2.0/24`（文档段，不通向任何机器），主机不配对、无证书。
写库走生产 `DataManager` 的 `updateHost:` + `updateAppsForExistingHost:`（与真机发现走的是同一条），
设置页再用生产 `getHosts` 读回来——**被测的仍是那条泄漏的所有权路径，不是被造出来的道具**。
库里已有主机就不种（否则量的就是种子而不是那台机器）；`ML_RENDER_PROBE_SEED_IGNORE_EXISTING`
只为了让「种」这条分支在**有局域网的机器上也能被跑到**——没有它，这段代码只有 runner 会执行，
等于读过但从未运行；本地实测用它抓到过 `status: seeded`（下面第二行）。

**探针必须自证**：`capture()` 现在在清目录之前读探针写下的 `report.json`，
没有报告 / `failures` 非空 / 没有 `seedHosts` 记录 / 状态不是 `seeded` 或 `existing-hosts` → 整轮直接 FAIL。
这条针对的是一种很特定的假绿：**旗号送到了构建里，构建不理它**，于是报告里满是系统块、一个一手对象都没有，
看起来和「干净」完全一样。四形状各有一条 fixture（`--self-test`），不靠临场运气。

**五张图，每主机一手字节都是 384**（1 个 `TemporaryHost` + 3 个 `TemporaryApp`）：

| 运行 | 一手 | 泄漏主机 | 每主机一手字节 | 总字节 |
| --- | --- | --- | --- | --- |
| 提交进仓库的 `scripts/leak-sample.txt` | 18 app / 6 host = 2,304 B | 6 | 384 | 11,792 |
| 本机扫描（`existing-hosts`） | 21 app / 7 host = 2,688 B | 7 | 384 | 13,744 |
| 本机扫描（`seeded`，开 IGNORE 开关） | 48 app / 16 host = 6,144 B | 16 | 384 | 21,712 |
| **CI runner arm64**（`seeded`，种 1 台） | 21 app / 7 host = 2,688 B | 7 | 384 | 24,416 |
| **CI runner x86_64**（`seeded`，种 1 台） | 18 app / 6 host = 2,304 B | 6 | 384 | 23,424 |

扇出每次都是 3.0。最后两行是 run `35987288683`：runner 上没有 mDNS 应答，所以 `status: seeded`、
库里就只有种下的那 1 台，两条判据第一次在 CI 上真的判到了（2,688 对 3,712、2,304 对 3,200）。**泄漏主机数不等于库里主机数**：库里 2 台时泄漏 16 张图——设置页每读一遍 `getHosts`
就留下每张主机的一份图，探针运行期间会读好几遍。这不改变两条比值判据（它们都按主机数摊），
但它解释了为什么主机计数从来不是代码的性质：库里台数取决于 mDNS 应答，读数取决于渲染轮次。

**字节口径因此换了，而且不是靠推算换的**：旧口径 `bytes_per_host=2500 + byte_floor=2000` 判的是**报告汇总的总字节**。
种下图之后，同一条 push 的两台 runner 各自报 24,416 与 23,424 总字节，旧预算分别是 19,500 与 17,000——
**两次都会红，而红的那两个数字里一个一手对象都不是**（一手只有 2,688 / 2,304）。这条实测记在
`observed.ci_runner.byte_budget` 里：换口径不是为了让门禁松，是因为旧口径在**有图之后**必然去拒绝机器。
所以规则改成判**一手对象的字节**：`first_party_bytes_per_host=512`（实测 384 + 三分之一余量）`+ first_party_bytes_floor=128`，
总字节只打印不判定。牙齿反而更利：同一张图多一个持有者时一手字节翻倍，768 > 512+128（主机数 ≥1 时成立）就红。
换口径这件事本身有回归：fixture 里写了一条「runner 形状」（1 张一手图 + 2,800 字节系统噪声），
**旧口径下它是拒绝，新口径下它是放行**，红证里也补了对称的两条——放大我们自己的块必红、放大 `CFString` 必放行。

**仍然没测到（别把 §8 当成总闸）**：
- 128 字节地板仍是占位：至今没有一次扫描漏过「不属于任何主机图」的一手对象，地板从没被量到过。
- runner 只覆盖到「无 LAN 的纯种子」这一种混合：种 1 台后渲染轮次是 6~7，本机开 IGNORE 时是 16，
  而「runner 上既有真实发现又有种子」这种形状构造不出来（runner 没有 LAN）。
  「种子被种进一个非空库」因此仍然是纸面推演，尽管那条分支本机已经跑过。
- ~~§5 的所有权修法照旧卡着~~ **2026-09-24 拆成两半**：「谁持有谁」由 §10 量出来了；「串流期读到 nil」依然没有真会话，但改由持有者规则在源码上拦住——`weak` 落地时任何未配对的 `X.app =` 都会判红，所以这一条不再是「等真机」，而是「先补两个 host 属性」。
- 替我们泄漏的**系统对象**（`CFString`/`NSMutableSet` 那 80%）没有任何一条规则盯着——
  一手类集合抓不到它们，一手字节预算也抓不到，这条边界与上一轮相同。

## 9. 每进出一次页面留下多少：增长速率，以及它容不紧的阈值（2026-09-24）

前八节全部建立在**一次访问**之上：打开页面、读一遍、关掉，然后看退出时还剩什么。
这种测法有一个盲区，而且正好是用户唯一在意的那个——**「每次运行漏一张图」和「每次访问漏一张图」
在单次扫描里长得一模一样**（退出时都在那里），但前者一整晚不变，后者一整晚在长。
本轮把这条变成有数字的东西。

**怎么测**：`ML_RENDER_PROBE_CYCLES=<n>`（Debug-only、env 门闩）在探针收尾前按生产顺序多跑 n 次
「present → 按页面自己的返回闭包关闭 → 让销毁落地」，并记录 `requested/completed/status/libraryEnd`。
`leak-audit.py --growth --growth-cycles <n>` 跑两次完整扫描（1 次访问与 n 次访问），
**两次各自先按原有 ceiling 判过**（否则一条听起来更强的门禁会偷偷变成更弱的），
再用「一手字节差 ÷ 多出的访问次数 ÷ 库里主机数」得到每访问每台主机的字节速率。

**结论：关闭页面并不回收这些图。**同一份构建、同一台机器、库中 2 台主机：

| 本机增长率（字节/次访问/主机） | 192 | 384 | 422 | 461 | 461 |
| --- | --- | --- | --- | --- | --- |
| 本机泄漏图数（1 次访问 → 6 次访问） | 20 → 25 | 19 → 31 | 19 → 31 | 21 → 31 | 19 → 30 |
| **CI 增长率（arm64 / x86_64）** | **230** | **307** | — | — | — |
| **CI 泄漏图数（1 → 6 次访问，库中 1 台）** | 9 → 12 | 9 → 13 | — | — | — |

每张图的字节在所有运行里**恒为 384**——所以多出来的是**整图**，不是变胖的对象。
这也是这条测量最重要的产出：**§5 的修法从此有了验收口径**——修好之后这条速率必须趋近 0，
而不是「每图字节变小」。在那之前，上面这张表就是那个循环的账本。

**分母必须是访问之后的库大小**：`seedHosts` 是在页面打开前记的，而 discovery 在进程活着的时候还在往里加主机。
用访问之前的数当分母，同一条未改的构建在两组各 5 次的测量里给出 230–499 的散布，
换成 `memoryCycles.libraryEnd` 之后是 192–461——**分母不是细节，是分母**。

**阈值因此容不紧，这是实测决定的，不是让步**：未改动的构建自己就散布在 192–499 之间，
所以把上限放在「一次访问每台主机一张整图」（384）会红在没人碰过的代码上——
与上一轮那个 18/6 绝对上限被九次实测否掉是同一件事。
最终 `growth_bytes_per_cycle_per_host = 1100`：
一张图/访问/主机（384）与两张（768）**放行**，三张（1152）**判红**。
「两张也放行」这条盲区**写进了 fixture**（`a visit orphans two graphs per host -- the measured blind spot`），
不是写在注释里——将来谁收紧它，必须先改掉那条 case。

**植入的可红性是量过的**：把 `growth_bytes_per_cycle_per_host` 人为压到 1 字节再跑红证，
红证立刻报 2 条并**以 1 退出**（1 张/访问与 2 张/访问两条本该放行的被拒）。
这一量还顺手抓到自己埋的一条假绿：growth 的植入原本写在 `failures = 0` 之前，
任何植入失败都会被抹成 0 退出——挪到赋值之后才真的能红。

**为什么抖**：一次访问里页面读几遍 `getHosts` 不由单一控制（`SettingsModel` 计算属性、设备页、
app 页各读各的），而每次读会遍历当时库里的全部主机。这条**没有测到根因**，只测到了它的幅度。
顺带记下：那些 `getHosts` 调用点（逐处清单见 §13）本身就是可优化的存量（同一页渲染内读 3 遍
同一个库）——§13 已经把「读几遍」从推测变成有门禁的读数；但**合并读取属于「行为可能变」的重构**，
本轮不动，登记在此。

**CI 上第一次跑到就落在同一个分布里**（run `36000138662`：230 与 307 字节/次访问/主机，
库中各 1 台，每图仍 384）。一个细节要记下：那两次扫描的**第一趟是种子先到、第二趟是发现先到**
（第二趟记成 `existing-hosts`）——种子与 discovery 谁先写进库不由本仓库决定，
这正是分母必须取「访问之后的库大小」而不是「种子写下的那个数」的原因。

**这条门禁抓不到什么**（与它抓得到同等重要）：抓不到「每次访问多漏一个几十字节的小对象」——
速度的抖动比那个信号大一个数量级；抓不到回收失败但字节不变形（例如图被换成了别的等量对象）。
它抓的是**倍增**，并且第一次给了 §5 一个能被证伪的目标值。


## 10. 谁在给 host 续命：把 §5 从「等真机」变成一次测量（2026-09-24）

§5 的理由一直是一句诚实的话：没有真串流会话，就没法断言 `app.host` 会不会在串流期变 nil。
但这句话里混着两个问题——**谁持有谁**（对象图的性质）与**串流期会不会读到 nil**（需要会话）。
前者从来不需要会话。本轮把它单独量了，于是 §5 从「等条件」变成「有一张能红能绿的表」。

**怎么问的**：Debug 构建里的 `ML_OWNERSHIP_PROBE` 造出 host 与 app，然后**只留 app 一个持有者**
——这正是 `prepareForSegue:` 交出串流时的状态（`AppsViewController.m:613` 只赋 `streamVC.app`）——
再问两个问题：只有 app 被持有时 host 还活着吗？两个都不再被持有时，它们还活着吗？

**三种形状，每种挡的是一种会骗人的方式**：

| 形状 | 它排除的是什么 |
|:---|:---|
| `productionGraph` | app 直接取自 `-[DataManager getHosts]`（就是那张泄漏过的图），读数不能赖成「fixture 自己搭的形状」 |
| `handBuiltGraph` | 同一形状手工再搭一遍，**唯一用途是与上一行一致**；不一致就说明图之外还有人在持有，这份报告里所有读数都不再描述 app |
| `backpointerOnly` | 只有 `app.host`、没有任何东西反向指向 app。它**必须**能被回收；它若活着，说明探针在持有自己声称在观察的对象 |

**实测**（本机真实库 2 台主机，被选中的那台带 3 个 app；`scripts/ownership-sample.json` 是这次运行留下的记录，只替换了主机 UUID）：

| 形状 | 只有 app 时 host 活着 | 无人持有还活着 | `appList` |
|:---|:---|:---|:---|
| `productionGraph` | 是 | 是 | 3 |
| `handBuiltGraph` | 是 | 是 | 1 |
| `backpointerOnly` | 是 | **否** | 0 |

- 第三行是这份报告能成立的唯一原因：**harness 没有持有被测对象**，
  所以前两行的「无人持有还活着」是 app 自己的循环——`leaks` 那句 ROOT CYCLE 从此有了进程内部的对应物。
- 第一行与第二行一致，说明图之外没有别人在拿着它。
- 「只有 app 时 host 一定活着」这一条，正是 §4 那张表所说的「今天全靠这条强反向指针续命」——现在它是量出来的，不是读出来的。
- 形状定义写进 `shape_contract`：手工形状若悄悄变成「只有反向指针」，两条图的一致就退化成同一种形状自己跟自己一致，所以 `appListCount` 不对就整轮拒绝。

**CI 第一次跑到的读数**（run `36015387603`，arm64 与 x86_64）：两条 arch 报出**逐字相同**的三行
——production `appList 3` / hand-built `1` / back-pointer `0`，前两行 yes+yes、第三行 yes+no——
以及同样的「3 个赋值点、1 个已配对」。**这一节当初把它的来源写错了**：它记成 runner 自己
`seeded` 了一台，而真机打印（run `36019606141`）两条 arch 都是 `existing-hosts`。
抄错的原因是同一个作业里前一步内存扫掠的 `seeded` 被当成了这一步的读数，
而真相是三步共库：runner 上那 1 台 host 是**上一步种的**，不是这一步种的。详见 §11。
本节其余推论不受影响——`appList 3` 无论是种子还是真库给的，三形状读数的**一致性**都成立。
门禁因此把来源打在绿字里（`N host(s) in the library, seed status …`）：
「量的是自己种的图」与「量的是别人的库」是两个不同的断言，而日志的读者没法去摸那台机器。

**门禁判什么**（`scripts/ownership-audit.py`；CI 里三条 step：audit 作业跑 `--self-test` 与 `--red-team`，两个 macOS 作业跑真机测量）：

- 两条控制任一不成立 → 整轮拒绝。控制不是警告，因为第三个读数全靠它们；
- **头文件与观测对不上账 → 拒绝**，尤其是「头里写 `weak`、host 却还活着」——那不是修好了，那是有个看不见的持有者；
- 声明说这里有循环（两边都 strong）却什么都没漏 → 拒绝：那说明实验自己没造出图；
- 期望写在 `scripts/ownership-baseline.json` 的 `profiles` 里，**键是它写下时所依据的声明**。
  于是「改所有权却没先写下预期」本身就是拒绝；修好之后那一份也提前写好了：任何形状都不许在无人持有时活着，
  也不许只靠 app 把 host 留住；
- 红证改的是**真记录**（`ownership-sample.json`）而不是照自己的正则造的数。最要紧的一条植入是「声明说有循环，可什么都没漏」——那正是坏掉的实验会报出来的样子，不是修好了的样子。

**另一半（`weak` 之后谁来持有 host）改由源码担保**：探针不构造任何 view controller，
所以它看不见串流会话。于是同一份门禁去扫全仓 `X.app = ` 赋值点，要求同一方法体里出现 `X.host = `：
`weak` 之下留一条就判红一条；今天 strong 之下**新增**一条也判红（因为它就是 `weak` 化那天会炸的地方）。
扫出来的事实：

| 赋值点 | 是否同时给了 host | 说明 |
|:---|:---|:---|
| `AppAssetManager.m:58-59` `retriever.app/.host` | **是** | §5 第 3 步这条路早就做完了（§4 的表格在这里读漏了一行，已更正） |
| `AppsViewController.m:613` `streamVC.app` | 否 | `StreamViewController.h:25` 只有 app，没有 host 属性 |
| `AppsViewController.m:724` `item.app` | 否 | **本轮新发现**：`AppCell.h:20` 只存 app，而 `AppCell.m:129` 读 `self.app.host.uuid` 去查 artwork 变暗设置 |

这条规则**由它看守的那个改动来上膛**：今天 strong 之下它只做「记录 + 不许新增」，
所以它不会去逼一个测不了的行为变更；`weak` 一落地它自动变成硬门，
于是「只 flip 属性、不给持有者补 host」这种提交**在 CI 里过不去**，而不是等真机串流炸出来。
配对是**按持有者名字**判的——`otherVC.host = host;` 不能给 `streamVC.app` 续命，这条也有一条 fixture。

**仍未测到**：
- 真串流会话里 `self.app.host` 的实际读数照旧没有（这需要真主机 + 真会话）。现在拦它的是源码侧的持有者规则，不是运行时证据；
- 探针种下的主机走的是生产 `DataManager` 写路径，但**不经过 discovery**，所以「mDNS 应答拼出来的 host 与其 appList 的所有权」依旧没测；
- `AppCell`/`StreamViewController` 补上 host 属性之后会不会引入新的循环（cell ← app → host ← cell？）没测——
  这条在补的那一轮必须一起量，量法就是本节这张表加一条新形状。

## 11. 「自己的 HOME」不是自己的库：一次把 CI 记录纠正过来（2026-09-25）

§10 那份 CI 记录里写着一句「runner 自己 `seeded` 了 1 台」。它是错的，而且错得有价值——
顺着它查下去，撞到的是这条路径上**每一个探针都当作前提**的一件事。

**实测（一步定死）**：把 `HOME` 指向一个**空的**临时目录，启动 ownership 探针，
它报出 `2 host(s) in the library` ——本机的真库。
原因写在 `DatabaseSingleton.m:100`：`URLsForDirectory:NSApplicationSupportDirectory
inDomains:NSUserDomainMask` 从**账号记录**解析，不看 `$HOME`。
所以「给探针一个私有 HOME，于是它有私有的库与偏好」这句话在 render-probe 的注释里、
在两个审计的 `rmtree` 注释里都成立过，其实一次都没成立过；
审计删掉的那个 HOME 目录，从来就不是它写数据的地方。

**两条后果**：

1. **CI 里三步共库**。扫掠那一步没有 LAN，于是它 `seeded` 1 台；紧接着的 ownership 那一步
   打开同一个文件，看见这 1 台，判成「这是别人的库」→ `existing-hosts`，
   然后**把上一步留下的图当作生产图量了一遍**。它没有量错形状（形状就是那张形状），
   但它对「这一步种了什么」的陈述是假的——而这正是那一节要区分的两个断言。
2. **本机真库被污染**。第一条 reap 报 `mixed`：2 台里有 1 台带种子前缀，
   是更早某次扫掠在「HOME 会隔离」的信念下写进去的。

**处置**（全部 Debug-only，生产行为一字未动）：

| 东西 | 作用 |
|:---|:---|
| `MLProbeHostUuidPrefix` | 种子 uuid 的前缀只剩一个定义：播种、按来源计数、回收三处必须说同一种话 |
| `MLCountLibraryHosts` | 把库按**谁写进去的**分开数：库里几台、其中几台是探针种的 |
| `ML_PROBE_REAP_OWN_HOSTS` | 播种前先回收**只属于探针**的 host，走生产 `-[DataManager removeHost:]` 并回读校验。整库皆探针 → `reaped`；库空 → `empty`；库里没有探针的 → `kept`；**混着别人的 → `mixed`，判红** |
| `ML_PROBE_REMOVE_OWN_HOSTS` | 第二把旗号，只由人对自己机器按下：删掉带前缀的那些，不碰别人的。本机那 1 台就是这么清掉的（清完剩 1 台，是真机） |

`mixed` 之所以是红而不是「跳过」：**猜错的代价是把某人的 GameStream 主机从列表里删掉**。
默认路径不许猜；要清库存，得有人明确按下第二把旗号。

**顺手抓到一个我自己上一轮写的 bug**：形状循环在选中第一台带 app 的 host 后 `break`，
而「库里几台是探针种的」那段计数就长在同一个循环里 → 计数被 `break` 截断。
真机当场露馅：`probeOwnedHosts = 0` 与 reap 的 `probeOwned = 1` 并排出现。
于是门禁加了一条**经播种量对齐**的一致性规则：
`测量时探针自有数 == 回收后剩余自有数 + 本轮播种数`，对不上即红——
两个数取自同一进程对同一个库的两次看，本不可能不一致。

**门禁现状**：31 条 fixture、红队 12 条，其中红队现在读**两份真记录并各自核对期望**：
本轮记录必须被**接受**，`36019606141` 那份必须**只**因缺 `reapedHosts` 被拒——
且**补齐该字段后必须转绿**（否则那记拒绝就是在拒绝形状，而不是在拒绝缺失的证据）。

**CI 侧的实测**（run `36029410301`，两条 arch 逐字相同）：
`1 host(s) in the library (1 planted by a probe), seed status seeded, reap status reaped`，
三形状读数与本机一致。也就是说 **ownership 在 runner 上第一次量到了自己种的图**——
§10 当初想要的「seed 分支终于被执行」，隔了一天才真成立。
同一次作业里内存扫掠自己打印的三行是 `seeded` / `existing-hosts` / `existing-hosts`：
同一件事的另一面——第一遍扫掠种下，后面的扫掠沿用同一份库。
growth 判的就是这一份库上的两遍扫掠（正是它要的），但**「沿用别人留下的图」这件事从此必须说出来**，
不许再冒充「这是别人的库」。

**清理后的实测**：reap `kept`(found 1 / probeOwned 0)、seed `existing-hosts`、
三形状逐字同于前一日（production 3 / hand-built 1 / back-pointer 0，yes+yes / yes+yes / yes+no）；
`leak-audit` 重跑 **0 failure**，增长 **384 B/visit/host**、扇出 **3.0**，
即「谁持有谁」被改口了，而「每进出一次付多少」一分未变。

**没测到 / 盲区**：
- `removeHost:` 删的是 host 记录；种子挂在 host 上的 **app 记录是否随之消失**，取决于 Core Data 的删除规则，本轮没量（回收后的回读只数 host）；
- HOME 隔离失效同样意味着**在本机上**，render-probe 与内存扫掠一直是**在真实库上**跑的。已核对其断言不依赖空库（它们要的是「页面画出来了」「我们的对象没多漏」），但「私有 HOME」这句话以后不许再写；
- 同一句话在**配对私钥**上同样成立：`CryptoManager.m:211` 用 `NSDocumentDirectory` 解析路径，也是从账号而不是从 `$HOME`。目前没有任何探针走到配对写入，所以这条只是给后来人的护栏——**别把会写 Documents 的旗号交给「有私有 HOME」的脚本**；
- 真串流会话里 `self.app.host` 的读数照旧没有；被 reap 掉的 host 其 `appList` 是否连带释放，也没测。

## 12. 删一台 host 时它的 app 记录去哪了：把上一节的盲区量掉（2026-09-25）

§11 留了一句「`removeHost:` 删的是 host 记录，种子挂的 app 记录是否随之消失，取决于 Core Data
的删除规则，本轮没量」。本轮去问了。

**先读**：当前模型由 `Limelight.xcdatamodeld/.xccurrentversion` 指定为 `Moonlight v1.6.xcdatamodel`
（树里一共 **9 个模型版本** —— 读错版本等于读一份 app 永远不会打开的模型），里面写着
`Host.appList` 的 `deletionRule="Cascade"`、`App.host` 是 `Nullify`。
读到这里还不能算：声明是声明，**store 实际怎么执行是另一件事**（迁移过库的机器尤其如此）。

**实测（真删一次，两侧计数）**：
用现成的 `ML_RENDER_PROBE_SEED_IGNORE_EXISTING` 在真库上种 1 台探针 host（带 3 个 app，走生产
`updateAppsForExistingHost:`），app 记录从 3 变 **6**；再用 `ML_PROBE_REMOVE_OWN_HOSTS` 删掉它 →
app 记录 **6 → 3**，`orphanAppRecordsAfter = 0`。
⇒ **`Cascade` 是量出来的**：删 host 连带带走它的 3 条 app 记录，库里不留任何「没有 host 的 app 行」。

这条为什么值得当成一件事：**一条 host 已不存在的 app 行，生产代码再也看不见它**
（`getHosts` 只能顺着 host 走到 app），于是既列不出来也删不掉，而 store 一直为它付空间。
它比一个泄漏对象更糟，因为泄漏对象至少在 `leaks` 里看得见。

**计数为什么新开一个 context**：`DataManager` 跑在自己的 private-queue context 上，
`DatabaseSingleton` 又对外暴露另一个 context，两者都不保证无 refresh 就看见对方已提交的行 ——
用旧 context 数出来的「3」可能是某个更早时刻的 3，**那种数恰好会跟模型声明对得上，从而永远绿**。
所以新开一个绑在同一 `NSPersistentStoreCoordinator` 上的 context，读 SQLite 里已提交的内容。

**门禁把「声明」与「实测」对上账**（`scripts/ownership-audit.py` 读 `.xccurrentversion` 指向的那个模型）：

| 情形 | 判定 |
|:---|:---|
| 模型说 `Cascade`，删完 app 行数没少 | **红**：store 跑的不是这个模型，或那些 app 从没挂上去 |
| 模型说的不是 `Cascade`，可删完行数与孤儿都没变 | **红**：store 做了模型没描述的事 |
| 删完出现「没有 host 的 app 行」 | **红**（无论规则是什么，这种行都删不掉） |
| 删了但两侧没计数 / store 拒绝回答孤儿问题 | **红**：不许宣称「删干净了」 |
| 读不到当前模型或删除规则 | **红**：读不到前提，就没资格下结论 |

**CI 每次都真跑到**：runner 上没有 LAN，扫掠那一步种 1 台（带 3 个 app），紧接着 ownership 的
reap 把它删掉 —— 所以这张对账表**不是本机专属**，每次 push 都在两 arch 上执行一次真实删除。

**测试**：fixture 43 条（新增 9 条，其中「非 Cascade 规则下行数照消失」这类靠**注入模型**来测，
测的是对账而不是某个具体模型），红队 18 条（新增 3 条：级联失效 / 没计数 / 清理谎报完成）。
入档真记录四份，各自在 baseline 里声明期望：新记录必须被接受，
而上一轮那份清理记录**如实改成必须被拒**（它删的时候 app 计数还不存在），
并且「按种子扇出补齐计数后必须转绿」——拒绝的仍是缺失的证据，不是形状。

**没测到**：孤儿判定依赖 `host == nil` 谓词在该 store 上的行为；若 store 拒绝这个谓词，
探针记 `appRecordProblem` 并判红，不猜。真串流会话里 `self.app.host` 的读数照旧没有。


## 13. 一次进设置页到底读了几遍库：把最后那个猜测量掉（2026-09-25）

### 为什么这仍属于正确性，而不是性能

§9 交付的增长速率是 `bytes / visit / host`。它有一个从未被检验的前提：**一次 visit 会读几遍
库**。`-[DataManager getHosts]` 每次调用都为库里每一行造一套全新的 `TemporaryHost`/`TemporaryApp`
图（`DataManager.m:210`），于是

```
一次 visit 泄漏的图数 = 这次 visit 读库的次数 × 库内 host 数
```

读库次数不是常数的时候，「速率」就只是恰好观测到的字节数。§9 那条字节阈值自己也承认：同一份
未改动的代码，五轮跑出 192 / 384 / 422 / 461 / 461 字节，脚本当时的注释写着「一次 visit 到底
读几遍库，不是这个仓库能控制的数字」。**这一轮就是把那句话作废。**

### 先更正旧口径：调用点不是 17 处

§1 与 §2 里的「17 处」是 §1 那轮的估数。这轮按明确口径重数：排除 `DataManager.h:29` 的声明、
`DataManager.m:210` 的定义、纯注释行，以及名字相近但无关的 `forgetHosts`。

| 口径 | 数量 | 位置 |
|:---|:---|:---|
| 生产代码调用点 | **16** | Swift 11：`HostSidebarViewModel.swift:74`、`SettingsModel.swift:127/1031/1126`、`SettingsModel+DerivedValues.swift:220`、`SettingsModel+RiskAssessment.swift:42`、`SettingsObjCBridge.swift:50/791`、`SettingsAppPane.swift:193`、`SettingsDevicesPane.swift:504`、`SettingsStreamPane.swift:174`；ObjC 5：`AppsViewController.m:246`、`AppsWorkspaceViewController.m:98`、`HostsViewController.m:554`、`DiagnosticsReportBuilder+Live.m:250`、`AppDelegateForAppKit.m:1956` |
| Debug 探针调用点 | 6 | `AppDelegateForAppKit.m` 的 714 / 873 / 927 / 972 / 1174 / 1583（ownership 与 render 两个探针自己数库用） |

记一笔：`AppDelegateForAppKit.m:1956` 一行里写了 `performSelector:@selector(getHosts)` 和
`[dm getHosts]` 两个调用表达式，最坏情况读两遍。这是登记，不是本轮要改的。

### 实测读数

计数器是 `#if DEBUG` 下的一个 `atomic_ullong`，由 `getHosts` **自己**在入口以 `relaxed` 自增
（`DataManager.m`），不是外面套的包装，所以「调用了却没被记到」没有藏身之处。跑法是同一份二进制
跑三次（1 次 3 个 cycle、2 次 6 个 cycle），对着本机那 1 台真 host：

| 读数 | videoPane | appPane | streamPane | 设置根页（cycles） |
|:---|:---|:---|:---|:---|
| present 期间读库 | 1 | 1 | **3** | 1（每个 cycle 都是 1） |
| dismiss 期间读库 | 0 | 0 | 0 | — |
| 三次运行是否一致 | 一致 | 一致 | 一致 | `readsPerCycle` 全是 `[1]` |

三个结论：

1. **`streamPane` 一次打开读 3 遍**，另两页各 1 遍。§9 记录里那个「扇出 3.0」到这里才算有了
   名字：被量的那一路就是串流设置页，它按分节各读一次，而不是每次 visit 读一次。
2. **关闭路径一次都不读**。这不是推出来的，是三次运行都为 0，于是它够格当门禁。
3. **每个 cycle 的读数与第几次无关**（全是 1）。也就是说现在没有「越开越慢」的形状——而这类
   问题只有多 cycle 才看得见，单 cycle 永远看不见。

### 门禁：读数不许偷偷变

| 断言 | 为什么是这个形状 |
|:---|:---|
| 每页 present 读数 `==` `HOST_READS_WHEN_OPENED`（1 / 1 / 3） | 读几遍由代码结构决定，不由机器、库大小或负载决定，所以写**精确值**而不是上限；给上限就等于允许一次翻倍藏进余量里。要改数，就得在改结构那个 commit 里连同这张表一起改，并说明理由 |
| dismiss 读数 `== 0` | 实测如此；teardown 期间的读是在页面正被释放时读，属于另一类错误 |
| `readsPerCycle` 必须全部相等 | 递增＝每进一次读更多＝用得越久越慢。这与「常数偏大」是两种病，修法不同，不该混进同一条阈值 |
| `readsUnattributedToCycles == 0` | 状态说所有 cycle 都完成了，就不该有落在 cycle 边界外的读；这条是「计数仍然自洽」的自检 |
| `libraryEndReads >= 1`（ObjC 侧与 Python 侧各判一次） | 数一次库本身就是一次 `getHosts`。若它记成 0，说明计数器根本没接在读路径上，**这份报告里所有读数都是假的 0** |
| 报告里没有 `readsPerCycle` | 判红：Release 编译，或探针被删。此时 growth 速率没有归因来源，只是一个带单位的巧合 |
| leak 侧：多出的泄漏图数 ≤ 读库次数 × visits × hosts | 把 §9 的字节阈值和读数接起来。字节阈值容得下一次翻倍（192→461 的实测散布），所以它**不该**是发现「同一张图的第二个创造者」的那条规则；读数才是：它说清了每台 host 有权被泄漏几个图，超出部分必须点名 |

### 测试

* 7 条红证（拿真报告注入污染）：streamPane 翻倍、某页变成 0、dismiss 去读库、`readsPerCycle`
  递增、边界外多一次读、计数器是死的、探针字段整块消失——逐条打出预期拒绝理由，全部命中；真报告
  自身 0 拒绝（绿）。
* `leak-audit --self-test` 新增：2 条 growth case（「泄漏图数超出读库有权解释的量」判红；「没有
  读数记录」不由这条判红，留给更 sharp 的那条），以及 4 条 `probe_problems` case（cycle flag
  到达无视它的 build / cycle 完成却没记读数 / 记了读数 / 中途停止）。全量 0 失败。

### 没测到 / 留给下一轮

* **真串流会话里 `self.app.host` 的读数**照旧没有——那需要能跑起来的主机，本机没有。
* **`streamPane` 那 3 次能不能合并成 1 次**：属于性能优化，且会改变「页面在什么时刻看到最新的
  库」这个语义（分节各自刷新 vs 一次快照），所以它是一次**独立决策**，登记在此，本轮不编码。
  真要动它，`HOST_READS_WHEN_OPENED` 会先变红，逼着把理由写清楚。
* 计数器只在 `DEBUG` 下存在，Release 没有读数——这是刻意的：门禁跑 Debug 二进制，而 Release 若
  被拿去跑 leak-audit，会因为「报告里没有 `readsPerCycle`」直接判红，不会静默变绿。
