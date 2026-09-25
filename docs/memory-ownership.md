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
> a byte ceiling. Section 14 (same day) followed those reads to a defect they exposed: a
> server-info response with no `uniqueid` matched a paired host by the code's own fall-back rule and
> wrote the missing id over the stored one, after which the next look at the device list deleted the
> host and -- `Host.appList` being `Cascade` -- the applications the user had added to it. Measured
> at 2 hosts to 1 and 6 app records to 3 for one response missing one tag; fixed by the nil guard
> that method already applies to every neighbouring field. Section 15 (same day) applies the same
> promise to the second field that was written bare -- the name -- and records why the third one,
> `customName`, must stay unguarded: the rename sheet clears that field with nil, and `populateHost:`
> never assigns it, so a guard there would make a custom name impossible to unset. Section 10 (same day) splits that blocker in two and measures the
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
一次 visit 造出的图数 = 这次 visit 读库的次数 × 库内 host 数
```

> **2026-09-25 修正（§16）**：这个等式讲的是**造出**多少图，不是 `leaks` 在退出的那一瞬间
> **数到**几张图还活着。后者是快照，同一份代码实测在 6/8/9 之间浮动。把等式当成泄漏计数的
> 判据写进门禁之后，它在一天之内把正确的代码判红了三次（CI 两个 arch ＋ 本机一次）。

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
   名字：被量的那一路就是串流设置页。**3 遍的来源用一次性插桩（打印 `callStackSymbols`，跑完
   即回滚、未提交）测到，不是推测**：
   * 每个 present 区间里都有 1 次来自 `SettingsOverlayPresenter.init` → `SettingsModel.init`
     → `static SettingsModel.hosts.getter`（§1 说的那个 computed 属性，在这里被求值）；
   * `streamPane` 另有 2 次来自 `StreamView.body` 里两个不同的 `onAppear`（栈上夹着
     `FormSection.init(title:content:)`），链路逐条读代码核对过：
     `SettingsStreamPane.swift:199` → `refreshConnectionCandidates()`
     （`SettingsModel+DerivedValues.swift:216`，在 220 行自己 `getHosts`）与
     `SettingsStreamPane.swift:694` → `refreshSunshineDisplays(force:)`
     （`SettingsModel.swift:1130` → `currentTemporaryHost()` 1123 → `getHosts` 1126）。
     两条链读的是**同一个语义**（当前选中那台 host），却各自重读一遍全库；
   * 探针自己数库的那些读（`MLRunRenderProbeAndExitIfRequested`）落在 present/dismiss 区间
     之外，不进这三行读数。
   本轮做的是**栈归因 + 代码链路核对**，没做逐次时间对齐（那需要阶段标签），也没有改任何调用
   点——见下面「顺带撞见的风险」。
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
| ~~leak 侧：多出的泄漏图数 ≤ 读库次数 × visits × hosts~~ **已被 §16 换成斜率规则** | 接法是对的（字节阈值容不下「同一张图的第二个创造者」，读数才说清是谁造的），错在把它当成**计数**而不是**速率**判：泄漏图数是快照，短窗口下差值实测 3–7 而配额恒为 5，于是它在正确代码上判红。现在判的是「超出读数配额 1.6 倍」且窗口必须 ≥ 10 次额外访问 |

### 测试

* 7 条红证（拿真报告注入污染）：streamPane 翻倍、某页变成 0、dismiss 去读库、`readsPerCycle`
  递增、边界外多一次读、计数器是死的、探针字段整块消失——逐条打出预期拒绝理由，全部命中；真报告
  自身 0 拒绝（绿）。
* `leak-audit --self-test` 新增：2 条 growth case（「泄漏图数超出读库有权解释的量」判红；「没有
  读数记录」不由这条判红，留给更 sharp 的那条），以及 4 条 `probe_problems` case（cycle flag
  到达无视它的 build / cycle 完成却没记读数 / 记了读数 / 中途停止）。全量 0 失败。
* **这批 growth case 中的图数那条在当天就被 §16 推翻并重写**：断言的形状从「超出配额即红」变成
  「斜率超出 1.6 倍即红 ＋ 窗口不足 10 次访问即红」，并把 CI 那次误判的真形状
  （6→12 图 / 配额 5）原样钉成一条 case。

### 顺带撞见的风险：一次「读」列表会先写库删行

`SettingsModel.hosts`（`SettingsModel.swift:122`）是 **static computed**，每次求值的头两行是：

```swift
let dataMan = DataManager()
dataMan.removeHostsWithEmptyUuid()   // 写操作，先于任何读
if let tempHosts = dataMan.getHosts() as? [TemporaryHost] { ... }
```

于是「打开设置页看一眼设备」这件事在生产路径上包含一次**删除**（`removeHostsWithEmptyUuid`
实测是 `deleteObject:` + `saveData`，`DataManager.m:227`，写 store 不是改内存）。单看它有道理：
空 uuid 的行是半成品，`hosts` 自己也会把它们过滤掉，留着只是让三条链反复遍历。但它和 §12 刚量到
的删除规则**复合**起来就不是清理了——模型说 `Host.appList = Cascade`，**删一台 host 会连带删掉
它的 app 记录**，而那些 app 记录是用户自己配的。

「已保存的 host 会不会被写成空 uuid」没有留成猜测，链路是读出来的：

| 环节 | 位置 | 事实 |
|:---|:---|:---|
| 响应缺字段就赋空值 | `ServerInfoResponse.m:22` | `host.uuid = [[self getStringTag:TAG_UNIQUE_ID] trim];` —— 无守卫，缺 tag 即 nil/空 |
| 写回 store 时也没守卫 | `TemporaryHost.m:79` | `parentHost.uuid = self.uuid;` 无条件执行。**同一个方法里** `address` / `externalAddress` / `localAddress` / `ipv6Address` / `mac` / `serverCert` 全都写着 `if (self.x != nil)`，只有 `name` 与 `uuid` 是裸赋值 |
| 于是下一次读会删 | `SettingsModel.swift:126`、`HostSidebarViewModel.swift:73` | 两处都在读列表之前调 `removeHostsWithEmptyUuid` |
| 删 host 会连带删 app | §12 实测 | `Host.appList = Cascade`，删一台 host 时 app 行随之消失 |

一条不完整的主机信息响应（缺 `UNIQUE_ID`）就可能把一台已配对主机的 uuid 清成空，之后**任何一次
打开设置页或侧栏**都会把它和用户配的 app 一起删掉。**可达性**（真机上是否确有缺 `UNIQUE_ID` 的
响应）本机测不了——这里没有可连的主机，所以它是登记项，不是结论。

测法已经想好，能复用本轮与 §12 的全部机制：种一台 uuid 有值、挂 3 个 app 的 host → 走一次
`populateHost:` 喂一份**不含 `UNIQUE_ID`** 的响应 → 数 uuid 与两侧 app 记录。当前代码的**预期**是
uuid 被清空、随后 app 记录 3 → 0 且 `ML_PROBE_REMOVE_OWN_HOSTS` 也救不回来（行已经没了）；那正是
红证，红了之后修的是「同一方法里漏掉的守卫」，而不是新行为。本轮不编码，因为无论补守卫还是让删除
不级联，都是**行为改变**，属独立决策；而读库次数已经钉死，改动无法偷偷发生。

### 没测到 / 留给下一轮

* **真串流会话里 `self.app.host` 的读数**照旧没有——那需要能跑起来的主机，本机没有。
* **`streamPane` 那 3 次能不能合并成 1 次**：属于性能优化，且会改变「页面在什么时刻看到最新的
  库」这个语义（onAppear 再读一遍 vs 用 presenter 构造时那份快照），所以它是一次**独立决策**，
  登记在此，本轮不编码。真要动它，`HOST_READS_WHEN_OPENED` 会先变红，逼着把理由写清楚。
  两处 onAppear 读的是**同一个语义**（当前 host），已逐条核对过链路，所以合并的技术前提成立；
  真正没解的是「它们各自期望在什么时刻看到新 host」——这条留给下一轮连同上面那个删除风险一起判
  定，因为两者动的是同一段代码。
* 计数器只在 `DEBUG` 下存在，Release 没有读数——这是刻意的：门禁跑 Debug 二进制，而 Release 若
  被拿去跑 leak-audit，会因为「报告里没有 `readsPerCycle`」直接判红，不会静默变绿。


## 14. 一次缺 `uniqueid` 的响应，如何删掉用户配的 app（2026-09-25）

§13 登记的风险当天就测完了，因为它不需要真机——**代码自己就声明了这个场景会发生**。

### 链路：四个环节，每一环都是读出来的

| 环节 | 位置 | 事实（不是推测） |
|:---|:---|:---|
| 响应可以不带 id | `ServerInfoResponse.m:22` | `host.uuid = [[self getStringTag:TAG_UNIQUE_ID] trim];` 无守卫：缺 `uniqueid` 这个 tag，赋进去就是 nil |
| 代码**预期**它不带 | `DataManager.m:245` | `getHostForTemporaryHost:` 里有一段注释 `Fallback matching when UUID is missing`，改用 mac / address / name 去命中已存的那台。也就是说「uuid 缺失的发现响应」不是想象，是原作者按频次写进代码的常态 |
| 写回时没守卫 | `TemporaryHost.m:79` | `propagateChangesToParent:` 开头写着 `Avoid overwriting existing data with nil if we don't have everything populated`，并且 `address`/`externalAddress`/`localAddress`/`ipv6Address`/`mac`/`serverCert` 全部照这句话加了 `if (self.x != nil)`，**只有 `uuid` 是裸赋值** |
| 读列表先删 | `SettingsModel.swift:126`、`HostSidebarViewModel.swift:73` | 两处都在读之前 `removeHostsWithEmptyUuid`（`DataManager.m:227` 实测是 `deleteObject:` + `saveData`，真写 store） |
| 删 host 连带删 app | §12 实测 | `Host.appList = Cascade` |

**串起来的后果**：一台已配对主机只要被一次不带 `uniqueid` 的响应命中 fallback 匹配，它的 uuid 就被
抹掉；此后**任何一次打开设置页或侧栏**都会删掉这台主机，并顺着级联删掉用户自己添加的 app。不是
「等下一次好响应修好」，是「看一眼设备列表就没了」。

### 实测：修与不修各跑一次同一测量

新探针 `ML_PROBE_PARTIAL_HOST_INFO`（挂在 ownership 探针里，reap 之前）做的事与 app 自己做的完全
一致：种 1 台带 uuid 与 3 个 app 的 host → 把一份**除 `uniqueid` 外字段齐全**的 server-info 喂给
生产解析器 → 走生产 `updateHost:` → 再按设置页的方式读一次列表。两份真记录：

| 读数 | 修复前 | 修复后 |
|:---|:---|:---|
| `uuidAfterPropagate` | `<empty>` | `probe-host-partial` |
| `rowAfterPropagate` | `true` | `true` |
| hosts（读列表前→后） | **2 → 1** | 2 → 2 |
| apps（读列表前→后） | **6 → 3** | 6 → 6 |
| `cleanedUp` | `by-the-app` | `by-the-probe` |

修复前那份记录里 `probeOwnedBeforeCleanup` 也是 0：uuid 一被抹掉，**§11 那套「按 uuid 前缀认领探针
自己的 host」的归属判定就再也认不出它了**——被摧毁的不只是数据，还有"这是谁弄坏的"这件事本身。

### 修法：把方法自己声明的意图补到它漏掉的那个字段上

```objc
if (self.uuid != nil && self.uuid.length > 0) {
    parentHost.uuid = self.uuid;
}
```

`length` 也要判，因为 `<uniqueid></uniqueid>` 解析出来是空串，而空串在 `removeHostsWithEmptyUuid`
眼里同样是垃圾——写空与写 nil 删得一样干净。合法流程里不存在「把 host 的 uuid 置空」：读列表的代码
本来就把空 uuid 当成待删对象。

### 门禁

| 断言 | 理由 |
|:---|:---|
| CI 用 `--require-partial` 索要这份记录 | flag 到达一个无视它的 build 时，缺记录必须红——与 reap 用的是同一类控制，否则"探针被编译掉"就是静默的绿 |
| `uuidAfterPropagate == plantedUuid` | 守卫生效本身 |
| hosts 读前 == 读后 | 「看一眼列表」不许删东西 |
| apps 读前 == 读后 | 级联不许带走用户配置 |
| `parsedUuid == "<absent>"` 且 name/mac 非空 | 前提：喂进去的必须真是那份缺 tag 的响应，且 fallback 真是靠它命中的 |
| `plantedUuid` 必须带 `probe-host-` 前缀 | 不许拿真人的 host 做这个实验 |
| `cleanedUp == "by-the-probe"` | 探针自己种的自己收走；若变成 `by-the-app`，说明测量把自己的研究对象删了 |
| `appRecordProblem` 存在即红 | 数不出来＝级联没被观测到，而不是没发生 |

**本地门禁抓住了一次 harness 的不一致**：第一版把 `ML_PROBE_PARTIAL_HOST_INFO` 写在 build.yml 的
step `env` 里、把 `--require-partial` 写在命令行里，而 local-gates 只复现**命令行**、不带 CI 的
step 环境——于是本地跑到这一步时探针压根没被要求做这个实验，审计却索要记录，报红。这类"开关与断言
分家"的错误只会被本地门禁抓到（CI 两处都有，反而永远绿）。修法与 reap 对称：**审计脚本要求什么，就
自己在子进程环境里给探针设什么**，build.yml 只留命令行。一条真相，一个主人。

**红队抓住了一次我自己的空洞**：第一版把这条规则写成"默认不要求"，于是「步骤悄悄没跑」那条注入
判定为**通过**——红队直接报 `this is a rule that does not bite`。这就是把 CI 口径变成强制的原因。
第二个坑也同类：填充函数一开始无条件覆盖，把注入的危险记录洗成干净的，红队又报了一次不咬合。

### 测试

* `--self-test` **56 条**（+13：干净记录两种口径、uuid 被抹、列表删 host、级联带走 app、前提不成立、
  解析不出可匹配字段、种了真人 host、数不出 app、探针留下研究对象、status 没测、flag 到了无视它的
  build、没被索要时缺记录不算错）。
* `--red-team` **21 条全绿**（+3：真记录级别的「守卫关掉」注入、「步骤静默没跑」注入、新入档记录按
  baseline 声明被接受）。
* 入档第五份真记录 `scripts/ownership-sample-partial.json`（修复后那份）；**先前四份如实改成必须被
  拒**，且只因为缺这份记录被拒——把该记录补回去后它们重新转绿，证明拒的是缺失的证据，不是形状。
* `--require-partial` + reap 的最严口径在本机跑真 store：**0 failure**。

### 没测到 / 登记

* **真机上究竟有没有不带 `uniqueid` 的响应**：本机没有可连主机，测不了。但这条不必等真机——
  `getHostForTemporaryHost:` 的 fallback 分支就是原作者对该场景的表态；而**修复不依赖它是否常见**：
  写回守卫本来就是那个方法对每个字段的既定承诺。
* **`name` 同样没有守卫**（`TemporaryHost.m:77`），一次缺 `hostname` 的响应会把用户改过的主机名冲掉。
  后果比 uuid 轻（不触发删除），但同属"用 nil 覆盖已有数据"，登记待判。
* 修复改变了写库行为（少了一次覆盖写）。这是修 bug 必需的**行为变化**，不属于「接口与业务行为不变」
  的禁区：对外接口、页面、设置项都没动，动的是一条会让用户丢配置的写入。


## 15. 同族第二个字段：`name`；以及为什么 `customName` 必须继续裸着写（2026-09-25）

§14 之后，`propagateChangesToParent:` 里只剩 `name` 还是裸赋值。补上守卫的过程顺带回答了一个更重要的
问题：**这个方法的三个字段对「缺失」的语义并不相同**，把它们一起"加守卫"是错的。

### 三个字段的差别是可执行的，不是修辞

| 字段 | 谁会在响应里把它变成 nil | `nil` 有没有合法含义 | 该不该守 |
|:---|:---|:---|:---|
| `uuid` | 会（`populateHost:` 用 `uniqueid` 覆盖） | 无（读列表时空 uuid 一律当垃圾删） | **守**（§14） |
| `name` | 会（`populateHost:` 用 `hostname` 覆盖） | 无（服务器改名一定带着新名字来） | **守**（本轮） |
| `customName` | **不会**（`populateHost:` 从不赋这个字段；库里读出的 temp host 自带原值） | **有**：`HostsViewController.m:473` 就是靠 `nil` 表达「用户清掉了自定义名」 | **不许守** |

也就是说：给 `customName` 加守卫会直接**做坏一个功能**（自定义名再也清不掉），而它本来就没有被覆盖的
风险——因为覆盖它的那条路径不存在。这条判断写进代码注释，也写进门禁的措辞里，避免以后有人"顺手
统一风格"。

### `name` 的实际代价：比 uuid 轻，但同样有读数

`-[TemporaryHost displayName]` 在没有自定义名时退回 `self.name ?: @""`，所以名字被冲空的后果是
**设备列表里出现一行没有标签的机器**，而不是删数据。实测（新探针 `ML_PROBE_PARTIAL_HOST_NAME`，用
uuid 精确命中、不走 fallback，以免与 §14 那个实验混在一起）：

| 读数 | 加守卫前 | 加守卫后 |
|:---|:---|:---|
| `nameAfterPropagate` | `<empty>` | `Probe Host Named` |
| `displayNameAfterPropagate` | `""`（列表里是空标签） | `Probe Host Named` |
| hosts / apps | 2 / 3 → 2 / 3 | 2 / 3 → 2 / 3 |

最后那行是本轮最重要的读数：**它证明这个缺陷只是"难看"，不是"丢数据"**。规则照样判红，理由不是严重度，
而是那个方法自己的承诺——六个字段守、两个字段不守，那不叫承诺。

### 门禁

新增 `partialHostName` 记录，与 `partialHostInfo` 由同一个 `--require-partial` 索要（审计脚本自己在
子进程环境里打开两个探针开关，沿用 §14 学到的"一个主人"原则）。拒绝：

* 名字与种下的不一致（守卫失效）；显示名为空（用户看到空标签行）；
* 解析出来的 body 其实**带了**名字（前提不成立，测的是普通响应）；
* `appsAfter != appsBefore`——本轮判定这个形状"从未见过"，因为一次只是没带名字的响应不该动 app；
  真出现就说明写回做的事比覆盖标签更多；
* 记录缺失（flag 到了无视它的 build）、status 不是 `measured`、不是自己种的 host、数不出 app、
  探针留下自己的 host。

两个实验的记录**必须同时提交**：判定逻辑里两条规则对同一份记录一起判，所以"只带一半证据"的记录会被
点名——这正是我们想要的（避免 CI 上只跑了一个实验而另一个悄悄消失）。

### 测试

* `--self-test` **62 条**（+6：名字守住 / 名字被抹 / 空标签行 / body 其实带了名字 / 写回动了 app /
  name 步骤静默没跑）。
* `--red-team` **23 条全绿**（+2：真记录级「守卫关掉」注入、「name 步骤没跑」注入）。
* 入档记录重跑并覆盖：同一份 ownership 报告里 `partialHostInfo` 与 `partialHostName` 都在，reap 也在，
  最严口径（`--require-partial` + 本地真 store）**0 failure**。
* 先前四份记录的期望同步补上「缺 `partialHostName`」，依旧**只因为缺证据被拒**，补齐后转绿。

### 登记

* `ML_PROBE_PARTIAL_HOST_NAME` 测的是"响应缺 hostname"。另一条会让 name 变空的路径是用户自己把
  主机名改成空——那条走 `customName`/重命名面板，不在本探针范围内，且当前 UI 是否允许提交空名未测。
* 到这一步，`propagateChangesToParent:` 的九个字段全部有了明确归属：七个守、一个（`customName`）
  故意不守并写明理由、`pairState`/`serverCodecModeSupport` 是数值不涉及 nil。这个方法的"缺失语义"
  问题到此收口。

## 16. 门禁在正确代码上判红：泄漏图数是快照，不是累加（2026-09-25）

### 现象

`ad2d35a` 把 §13 的接法写成规则之后，第一次在 CI 咬合就红了两个 arch（run `36058010642`）：

| 扫描 | 1 次访问泄漏图数 | 6 次访问泄漏图数 | 差值 | 读库配额（1 读 × 5 visit × 1 host） |
|:---|---:|---:|---:|---:|
| CI arm64 | 6 | 12 | **6** | 5 → 判红 |
| CI x86_64 | 8 | 14 | **6** | 5 → 判红 |
| 本机（同一份代码） | 9 | 14 | 5 | 5 → 绿 |

本机绿、CI 两个 arch 同时红，且**上一轮同一份门禁在 CI 是 9→14（差值 5）绿的**——
这排除了「§14 的 uuid 守卫引入了第二个创造者」这条解释：守卫所在的
`propagateChangesToParent:` 在内存扫描里根本不会被调用（leak 扫描不设 `ML_PROBE_PARTIAL_*`，
也没有服务器可发响应）。

### 实测：快照计数本身的散布

把六个 CI 扫描与本机四轮摆在一起（库内恒 1–2 台 host、同一份未改动代码）：

| 来源 | 1 次访问的图数 | 5 次额外访问的差值 |
|:---|:---|:---|
| CI run `36000138662`（arm64 / x86_64） | 9 / 9 | 3 / 4 |
| CI run `36051089381`（arm64 / x86_64） | 9 / 9 | 5 / 5 |
| CI run `36058010642`（arm64 / x86_64） | 6 / 8 | 6 / 6 |
| 本机四轮（由字节 ÷ 384 B 反推，早于读数计数器） | — | 3 / 6 / 7 / 7 |

同一份代码，**1 次访问的绝对图数在 6–9 之间移动（±3）**，5 次额外访问的差值在 **3–7** 之间移动。
`leaks` 回答的是「进程退出的那一瞬间还有几张图没人认领」，而不是「一共造了几张图」：
一次 `getHosts` 造的图里，有多少在快照到达前已经被释放，取决于读发生的时机与之后排空过什么，
这些都不是本仓库能拥有的常数。§13 那条等式因此只在「造出」这一侧成立，不能直接当泄漏计数用。

### 改法：换成统计上成立的斜率规则，而不是把阈值调宽

1. **窗口先要够长**：两次扫描的额外访问数 `< growth_graph_rule_min_visits`（10）时**直接拒绝判定**，
   并说明原因（快照噪声是每次扫描约 ±3 张图的常数，与窗口长度无关，所以窗口越长它摊得越薄）。
   这条拒绝是硬失败：想调试就把 `--growth-cycles` 调大，而不是让门禁在短窗口上假装看得见。
2. **判斜率而不是判超额**：允许 `built ≤ ceil(读库次数 × visits × hosts × growth_graph_count_ratio)`，
   ratio 取 **1.6**。1.6 是量出来的：有史以来最大超额是 7 vs 配额 5（1.4），
   而 ±3 张图的快照噪声摊到 15 次额外访问只剩 0.2 斜率。
3. CI 的扫描因此从 `--growth-cycles 6` 提到 **16**（1 次 vs 16 次，额外访问 15 ≥ 10）。
   字节上限（`growth_bytes_per_cycle_per_host` 1100，约 3 图/visit/host）原样保留，两条规则互相独立。

**这不是放宽**，同一件事上净效果是收紧：旧规则在 5 次访问窗口下把「每次 visit 造两张图」
记为*已知盲区*（因为那时它连 1.2 倍都要误判），新规则在 15 次窗口下把 2 倍变成**拒绝**
（60 张 vs 允许 48 张）。新盲区是「在读数配额上加不到 60% 的第二个创造者」，
它被写成 fixture 里的一条 `ok` case（`the measured blind spot`），不是注释里的一句话。

### 顺带修掉的两个自身缺陷

* `--growth` 之前会先白跑一次完整扫描（`main()` 里那次 `capture()`），于是三次扫描里两次写同一个
  `build/leaks-sweep.txt`。这次排障时归档里那份报告就是被覆盖后的，**多出那 1 张图的证据（第二次扫描）
  从来没被上传**，只能靠日志数字反推一个多小时。现在 growth 模式不再预扫（省一次扫描 ≈ 70 s），
  artifact 改成 `build/leaks-sweep*.txt` 把两份报告都留下。
* 判红消息现在会打印 `entitled`/`allowed`/ratio，绿了也会有 note 说清是谁给这次增长归的因，
  不再出现「只给一个数字，理由要人自己反推」。

### 测试

* `leak-audit --self-test` growth 段整段重写为 15 次访问窗口，共 11 条：出厂形状、
  1 图/visit/host、**1.5 倍盲区（必须绿）**、**2 倍（必须红，且旧规则看不见）**、3 倍（两条规则同时红）、
  速率下降、速率持平、纯超额、无读数、无额外访问、无 host，**外加 CI 那次误判的真形状**
  （1 host、6→12 图、配额 5）必须被「窗口不足 10」拦住。全量 0 失败。
* 本机端到端复跑 `--growth --growth-cycles 16`：9 图 → 23 图（差值 14，配额 15、允许 24），**0 failure**。
* **新规则第一次上 runner（run `36066100563`，两 arch 全绿）**：arm64 10 → 22 图（差 12，配额 15）；
  x86_64 **8 → 24 图（差 16 > 配额 15）**。旧规则会在同一个 job 上第四次判红，而这次超额的
  「斜率」只有 1.07——所以这条记录同时证明两件事：旧规则错，以及新规则不是靠放宽过关的
  （16 仍在 `1.6 × 15 = 24` 之内；字节速率 307.2 / 409.6 都在 1100 之下；四趟扇出恒 3.0）。

### 登记

* ±3 张图的快照散布**没有**被解释到机制层面（不知道是哪一次释放的时机在动）。斜率规则容忍了它，
  但它是真实存在的观测现象；若哪天要把它解释清楚，入口是 `TemporaryHost initFromHost:`
  造图后由谁在什么时候放手，而不是把噪声当错误压掉。
* 短窗口拒绝这条规则依赖 `--growth-cycles ≥ 11`。CI 与 `local-gates.sh` 都由 build.yml 那一行取命令，
  所以想改窗口只有一处可改；把它改小会让门禁拒绝，而不是悄悄变绿。

## 17. 反向指针之外的手：把「配对能替它续命」从推断变成读数（2026-09-25）

### §10 量不到的那一半

§10 让「谁在给 host 续命」变成了一次进程内测量，但它的三个形状有一个共同前提：
**库外的持有者永远就是那个 app**（`productionGraph` 与 `handBuiltGraph` 都是 app 在持 host，
`backpointerOnly` 则是除 app 外无人持 host）。这个前提正是被研究对象本身，于是它没法回答
§5 的 step 2 与 step 3 真正依赖的那句话：

> 今天 `streamVC.app`、`item.app` 这些只拿到 app 的持有者能读到 host，是因为 app 里那条强反向指针
> 在替 host 续命；把 host 按名字交给持有者之后，就不需要它了。

前半句此前只从 `App.h` 的 `strong` 读出来，后半句从未被验证过——如果配对并不能续命，
§5 的修法本身就站不住。本轮补的形状就是为了让这两句各自有一个数字。

### 做法：切一刀，再从外面伸手

`Limelight/macOS/AppDelegateForAppKit.m` 的 `MLOwnershipMeasureHolderShape(holderKeepsHost,
severBackpointer)` 按 `-[TemporaryHost initFromHost:]` 留下的样子造好这一对，然后**手工**执行
`app.host = nil`——它不代表声明已经改成 `weak`，只代表「这条边的贡献」被固定住，
于是可以和保留这条边的形状并列比较。之后把对象交给一个库外的持有者（一个 `NSMutableArray`
充当 streamVC 的替身）：

* `severedBackpointerAppOnlyHolder`：holder 只装 app，等价于今天 `prepareForSegue:` 交给 stream 的状态；
* `severedBackpointerPairedHolder`：holder 同时装 app 和 host，等价于 step 2/3 要改成的状态。

holder 自己也被 `__weak` 见证：探针放手之后它必须死。**这是这两个形状唯一的控制**——
holder 若死不掉，下面所有 `yes` 都属于 harness，整轮作废（§10 的 `backpointerOnly` 是同一个道理）。

### 实测（本机，2026-09-25，与 §16 同一份库、同一次运行）

| 形状 | holder 持有什么 | 持有时 host 活着 | 持有时 app 活着 | 放手后 holder 活着 | 放手后 host 活着 |
|:---|:---|:---:|:---:|:---:|:---:|
| `severedBackpointerAppOnlyHolder` | 只有 app | **no** | yes | **no** | no |
| `severedBackpointerPairedHolder` | app + host | **yes** | yes | **no** | no |

两个 holder 放手后都死了（控制成立），两个形状里的 host 与 app 也都随 holder 一起消失，
所以这两行读数属于 holder，不属于探针。**唯一差别就是 holder 里多出来的那个 host，
而它决定了 host 活不活**——这就是配对的贡献，量出来的，不是论证出来的。

同一次运行里三个旧形状读数与前一天完全一致（`productionGraph` appList 3、`handBuiltGraph` 1、
`backpointerOnly` 0，`failures: []`，`seed: existing-hosts`，`libraryHosts: 1`），
这本身就是「加一个形状不会改变旧形状」的检查。

### 这两个形状能说什么，不能说什么

**能说**：反向指针被切断之后，只持 app 的持有者留不住 host；同时被给了 host 的持有者留得住。
因此 §5 登记里那两条推论——「今天全靠这条边续命」与「配对属性可以替它」——现在都是数字，
且**不需要真机串流会话**，也不需要先落地 `weak` 声明。

**不能说**：

* 它不构造 `StreamViewController`，也不构造 `AppCell`。真会话自己持有的引用不在这个进程里，
  所以「每一个只拿 app 的持有者都会被配上 host」这半边仍然只能由 `ownership-audit.py`
  从源码读的 holder 规则判定（把 app 交给持有者却没给 host 的站点，`weak` 之下直接拒绝）。
* 它不是「改完之后的构建」的读数：切边是手工的、且被 `backpointerSevered: true` 如实记录，
  读者不会把它误当成已经声明 `weak` 的那次运行。

### 接线：新读数不允许「读不到就是绿」

`scripts/ownership-audit.py` 里这批形状没有任何开关，所以**每次运行都必须出现**：

1. 两个形状缺任一 → 拒绝（`no severedBackpointerAppOnlyHolder` / `...PairedHolder`）；字段缺失同样拒绝。
2. **形状自身**：`backpointerSevered` 必须为真（没切边＝ graph 形状换了个名字）；
   `holderKind` 与形状名一致（写进 `shape_contract`，与 `appListCount` 同级）。
3. **控制**：`holderAliveWithNoHolder` 必须为假，否则整轮作废；`appAliveWhileHeldByHolder` 必须为真，
   否则「外面根本没有持有者」，两行的相等毫无意义。
4. **差值本身**：app-only 必须读不到 host（若读到＝存在 `app.host` 之外的隐藏持有者，
   整份报告关于「谁持有什么」的陈述都作废）；paired 必须读得到 host（若读不到＝配对不能续命，
   §5 的修法前提被否，直接拒绝而不是记录）。
5. `host.appList` 那类「声明与观测对齐」的环**不遍历**这两个形状（它们的字段名不同、
   观察对象不同），但 `profiles` 比对环遍历它们。两个 profile 期望**同一组读数**——
   因为切边是手工的，声明怎么改都动不了这个数；改期望等于改实验，所以两条路径写死成一样。
6. 通用洞：报告里出现审计不认识的形状名 → 拒绝（`does not know`）。否则将来加形状而漏写规则，
   就会变成「读不到就是绿」的另一个版本。

### 已归档记录被追认的拒绝

四份早于本轮的记录（`ownership-sample-cascade/-cleaned/-partial/-prereap.json`）各自多两条拒绝。
没有为了放进它们放宽任何规则：是「测量本身到来了」让旧记录变成不完整。
红队同时把这两个形状**填回**去（`with_filed_holder_shapes`，只在缺失时填、绝不覆盖已记录的），
四份记录随即转绿——这证明拒绝针对的是缺失，而不是它们的库、reap 或日期。
`ownership-sample.json` 则用本轮真记录重新归档（五个形状齐备），成为当前唯一一条什么都不引的绿基线。

### 测试

* `ownership-audit --self-test` **62 → 71** 全绿（新增 9 条：两形状缺失、没切边、holder 不死、
  holder 没接住 app、app-only 竟留住 host、paired 留不住 host、形状随 holder 泄漏、
  未知形状名、`holderKind` 与形状名不符）。
* `--red-team` 新增 7 条 mutation（上述破坏的真记录版本）＋ 5 份归档记录的期望，全绿。
* 真跑两个口径：默认与最严的 `--require-partial`，各 **0 failure**；绿线现在会直接打印
  `severed back-pointer, app-only: host held=no vs app+host: host held=yes`。

### 登记

* §5 的判定**没有**因为本轮改变：`app.host` 仍是 `strong`，`section5_status` 仍要求
  「翻转反向指针的那一次提交必须同时把 host 交给每一个持有者」。本轮改变的是那句话的证据等级。
* 仍然没有「真会话里 streamVC 读 `app.host`」的直接观测——这需要一次真实串流，
  在能跑真机会话之前，它由源码侧 holder 规则代管，这一边界在探针注释、baseline 与本文三处都写着。

## 18. 一次通知回调几遍：`viewDidAppear` 里的注册是乘数（2026-09-25）

### 现象

§13 把「一次进设置页读几遍库」量成常数之后，本轮在**应用页**（`AppsViewController`）发现另一条
与页面访问次数成正比的读库路径：它的 `-viewDidAppear` 里注册了三个通知观察者——
一个 block（`NSWindowDidBecomeKey`）与两个 selector（`NSUserDefaultsDidChange`、
`HostLatencyUpdated`）。那个 block 有前置撤销（注释写着实测「三个显示/隐藏周期里
`-viewDidAppear` 跑了三次」），**两个 selector 注册没有**——因为 token 撤不掉
中心按 selector 记的注册，上一次修复只能修掉它修得起的那一半。

### 实测：中心不做合并

两行程序量出来的（`/tmp/notify/main.m`，与仓库无关的独立记录）：

```
registrations=3 notifications-posted=1 callbacks=3
after removeObserver: callbacks=3
```

同一 observer/selector/name 注册三次 + 发一条通知 = **三次回调**。第二行同样重要：
`removeObserver:` 一次就清掉该 observer 的**全部**注册——所以修法必须按 name 精确撤销，
若在 `-viewDidAppear` 开头直接 `removeObserver:self`，会连带清掉 `-viewDidLoad` 里
那两个只该注册一次的（`LanguageChanged`、`HostAutoAddressSwitched`）。

### 代价

`HostLatencyUpdated → handleHostLatencyUpdate:` 会调 `-syncHostStateFromDatabase`，
而它读的是 `-[DataManager getHosts]`——正是 §13 逐台 host 计字节的那次整库构造。
第三次访问之后，一次时延更新会跑三遍整库读取、三遍窗口副标题、三遍 app 发现尝试。
`NSUserDefaultsDidChange → updateWindowSubtitle` 同样按访问次数放大。

### 修法

在注册之前按 name 撤掉本对象已有的注册（与同一方法里 block 那半完全同构）。
`AppsViewController.m:61` 那个 `hostLatencyObserver` 属性一并删除：它从未被赋值或读取，
selector 版注册本来就没有 token 可存，但这个名字摆在两个真 token 旁边，
等于告诉下一个读者「时延观察者是 token 管理的、重复注册无害」——正是让这个 bug 活下来的信念。

### 接线：这条形状不允许第三次出现

`scripts/ownership-audit.py` 新增 `observer_registration_sites()` /
`judge_registrations()`，与 §5 的 holder 规则一样**从源码读事实**（探针看不见它：
对象图在注册两次与一次时毫无区别）：

1. 扫 `-viewDidAppear`/`-viewWillAppear` 里的每个注册（selector 与 block 两类）；
2. 只承认**注册之前**的撤销：先注册后撤销只是把乘数短暂归一，随即又装回去；
   block 认它自己的 token，selector 认同 name 的 `removeObserver:name:object:`；
3. 经辅助方法撤销也算（串流页用 `removeStreamSettingsObservers` 一次撤五个 token，
   规则读进辅助方法体确认它撤的正是这个 token），否则它会因为写得干净而被判红；
4. 8 个站点全部记进 `notification_registration_sites`：新增未记录的注册要一并登记，
   记录里的站点消失了也要说明是哪次提交搬走的——只拒新增的规则，覆盖面能缩到零都没人发现；
5. **读不到就拒绝**：`appearance_bodies()` 只认 Objective-C 的方法声明。今天 `Limelight` 里
   没有任何 Swift 文件声明 `viewDidAppear`/`viewWillAppear`（扫描为空），但哪天有人用 Swift
   写一个页面并在里面注册通知，规则会读出 0 个站点、0 条记录、0 条抱怨——一个「关于它看不见的
   文件完全正确」的绿。`registration_blind_spots()` 把这种情形点名拒绝，并给出两条出路：
   把注册挪到规则读得到的地方，或者在同一次提交里让它认 Swift 声明；唯一不允许的是页面不被判定。

这条规则**每次 push 都 armed**，不像 holder 规则那样等 `weak` 翻转才生效：
它没有未来的触发条件，页面今天就能被打开第二次。

### 测试

* 独立程序量出「3 注册 + 1 通知 = 3 回调」（真记录，不是推断）。
* `ownership-audit --self-test` **71 → 84** 全绿：13 条新 case，覆盖 selector 前置撤销（绿）、
  完全没有撤销（红）、撤销写在注册之后（红）、block 用 token 撤销（绿）、
  block 无人保存 token（红）、辅助方法撤销（绿）、辅助方法撤的不是这个 token（红）、
  记录没提到的新注册（红）、记录里还在却已消失的注册（红）、 appearance 方法里没有注册（绿）。
  外加 Swift 盲点三条（Swift 页面在 appearance 方法里注册＝红；只在 `viewDidLoad` 里注册＝绿，
  因为拒的是 appearance 方法而不是语言；appearance 方法里不注册＝绿），fixture 是真的 `.m` 文本——
  规则是源码阅读器，用字典搭 fixture 只能测到它的数据结构。
* `--red-team` 新增 4 条真树 mutation：出厂树（绿）、删掉应用页那两行撤销（必须点名**两个**注册）、
  把注册从页面里删掉而不更新记录（必须拒绝）、往真树里注入一个会在 appearance 方法里注册的 Swift
  页面（必须拒绝）。全绿。
* 真跑 `--require-partial` 0 failure，绿线多一条 note：`8 registration(s) are made in an
  appearance method, 8 of them withdrawn before re-registering`。

### 登记

* Swift 那条拒绝**今天不拒任何东西**——仓库里没有 Swift 页面注册通知，所以它是给未来的门；
  它的红证来自 fixture 与红队注入的假页面，不是真页面被拒。真页面出现那天它才开始承重。
* 应用页的这条放大**没有**产品探针能测：`render-probe.py` 只呈现设置页，没有通往 `AppsViewController`
  的导航，也没有真 host 与 app 列表可喂给它，所以红证来自独立程序加静态规则，而不是运行期读数。
  若哪天要把它做成读数，入口是给探针加一条「导航进应用页并重复显示 N 次，再发一条
  `HostLatencyUpdated`，数 `getHosts` 计数器」的路径。
* 串流页 5 个 block 注册的保护来自早先一轮的实测修复（窗口两次 hide/show 使
  `-viewDidAppear` 送达两次，当时测到一次设置变更打到副标题两遍、一条日志行进浮层两遍），
  本轮只是把它的撤销方式认下来，没有改动它。

---

## 19. 读方法的边界：门禁自己也会误绿（2026-09-25）

§18 立了「看不见必须抱怨」这条元规则，本轮用它反查**门禁自身**，在读方法
`appearance_bodies()` 里找到一处违反它的实现。

### 缺陷

它用「某一行只有一个 `}`」当作方法结尾，也就是 `text.find("\n}\n", start)`。
这不是方法的结尾，只是方法**通常**的结尾，两种不通常的情形都量过：

| 交给读方法的文本 | 站点读数 | 后果 |
|:---|:---|:---|
| 注册后面跟一个顶格 `}`（合法可编译代码） | 1 个体，注册**不可见** | 静默绿 |
| 注册在被交给的最后一段文本里（无收尾 `}`） | 0 个体 | 静默绿 |

第一行才是真漏洞：一个长 block 字面量把闭合花括号顶到第 0 列是很常见的排版，
而 `find` 会命中那个**内层**花括号，于是方法体在它那里被截断，写在它后面的注册
对门禁彻底隐形。隐形注册加上没登记它的 baseline，得到的正是 `problems = []`
——一个「关于它没读到的东西完全正确」的绿，和 §18 用 `registration_blind_spots()`
堵掉的 Swift 盲区是同一类，只不过这次盲区在读方法内部。

第二行（`find` 返回 -1 便 `continue`）是同一猜想的另一种失败：整个方法被丢弃，
同样一句抱怨都不发。上一轮的红证用的是没有 `@end` 的合成片段，那编译不过，
说服力不足，所以本轮把它降级为「读方法的健壮性」用例，主证换成第一行。

### 修法

边界改成**能指着说的东西**：下一个顶格声明，或关掉这段 `@implementation` 的 `@end`，
两者先到为准；都没有就读到文本末尾。抽成 `method_text(text, start)`，
`appearance_bodies()` 和 `helper_removes_token()` 共用——后者原本也按花括号读
辅助方法体，`find` 落空时把整个体当空，方向偏保守（误红不误绿），但同一处猜法
不该留两份。

### 验证

* 两条新形状在**旧读方法**下都让注册不可见：`bodies=1/registration INVISIBLE`；
  新读方法下两者都 `READ`。
* `--self-test` **84 → 88** 全绿，新增 4 条：顶格 `}` 之后未登记的注册（必须红）、
  同一页面把撤销写在注册之前（必须绿）、无收尾花括号段落里未登记的注册（必须红）、
  它的撤销版（必须绿）。用 monkeypatch 把旧边界装回去复跑，**恰好这 4 条失败**，
  证明它们咬的是这次改动，不是装饰。
* `--red-team` 新增 1 条真树注入：`TailPage.m` 唯一的注册藏在顶格 `}` 之后，
  撤销写法与出厂页面一致、且不在记录里。新读方法下站点 **8 → 9**、
  报 `a new notification registration appeared`；旧读方法下站点仍是 8、
  `problems = 0`，即这条红队用例在修复前会直接放行。
* `--require-partial` 真跑：真树读数**不变**，仍是 `8 registration(s) are made in an
  appearance method, 8 of them withdrawn before re-registering`、0 failure。
  也就是说边界修正没有改变对现有代码的判断，baseline 无需改动——这既是好消息也是
  本轮的局限：仓库里目前没有页面真的踩到那条排版，所以这条修复的价值在于
  门禁不再可能因为排版而闭嘴，而不在于它今天拦下了什么。
* `workflow-audit` 25 规则通过；`local-gates.sh` **47 passed / 0 failed / 12 need CI artefact**。

### 登记

* 边界仍是**启发式**，不是 ObjC 解析器。它假设方法与 `@end` 顶格（本仓库的排版如此），
  假设没有列 0 的 `@end` 字符串字面量。真要摆脱启发式，得换成能数括号的可信解析，
  那是新功能，不在打磨模式里做，只登记。
* 未解释事项照旧：`leaks` 快照图数 ±3 散布仍无机制层解释（§16 以速率容忍）。

---

## 20. 同一个依赖的第二条路径：规则不该看换行（2026-09-25）

§19 把「读方法的边界」换成能指着说的东西，并写下原则：**答案不该取决于作者在哪里换行**。
本轮拿这条原则去查它自己的另一半——`observer_registration_sites()` 是**逐行**扫方法体的，
而 `REGISTER_SELECTOR` 里的 `\s` 本来就吃换行，也就是说这个模式**能**匹配跨行调用，
逐行扫描却**不给**它跨行的机会。两条后果都量了：

| 交给读方法的方法体 | 逐行扫描的读数 | 性质 |
|:---|:---|:---|
| selector 调用折成 4 行 | `sites=0` 注册**不可见** | 静默绿（最坏） |
| block 调用折行、token 写在首行 | `kind=block-untokened` | 误红（冤枉一个已受保护的页面） |

第一行和 §19 是同一类缺陷：一个折了行的 selector 注册对门禁彻底隐形，
只要 baseline 里也没有它，`problems` 就是空。第二行方向相反，但根子相同——
`TOKEN_ASSIGN.findall(line)` 在**注册所在的那一行**找 `self.xxxObserver =`，
而折行时赋值和 `addObserverForName:` 不在同一行，于是把**受保护**的页面判成
「没人持有 token」这一最重罪名。

### 修法

方法体当**一段文本**扫，不再当**行列表**：

* `REGISTER_SELECTOR.finditer(body)` / `REGISTER_BLOCK.finditer(body)` 取代逐行循环；
* 「撤销必须写在注册之前」改成 `earlier = body[:match.start()]`，
  语义与原来的「本行之前的所有行」一致，但不再被行边界切断；
* token 从**执行这条注册的语句**里取：
  `body[body.rfind(";", 0, match.start()) + 1 : match.start()]`，
  即上一个 `;` 到注册起点之间的那段。

顺手删掉一个只为规避缩进而写的 `for ... in [(...)][0]` 构造——整段重写之后没有理由留它。

### 验证

* 两条形状修复前后对比：折行 selector 从 `sites=0 INVISIBLE` 变成
  `kind=selector withdrawn=False`；折行 block 从 `block-untokened` 变成
  `kind=block withdrawn=True`（token 跨行仍然认账）。
* `--self-test` **88 → 90** 全绿。用 `git show HEAD:` 把**旧扫描器**取出来
  `exec` 回当前模块再复跑，**恰好这 2 条失败**（一条报「no longer made」即理由错误，
  一条把已保护的页面判红），其余 17 条不动。
* `--red-team` 新增 1 条真树注入 `WrappedPage.m`：一个折行的 selector 调用，
  撤销写法与出厂页面一致、且不在记录里。新扫描器站点 **8 → 9** 并报
  `a new notification registration appeared`；旧扫描器 **8 站点 / 0 problems**，
  即这条用例在修复前会放行。
* `--require-partial` 真跑读数**不变**：`8 registration(s) ... 8 of them withdrawn`、
  0 failure，baseline 无需改动。
* `--red-team` 本轮共 36 条全绿（此后 §21 到 37 条、§22 到 38 条，当前数以 §22 为准）；
  `workflow-audit` 25 规则通过；`local-gates.sh` 见本节末。

### 登记

* 真树里**目前没有**任何折行的注册（专门比对「整段匹配数」与「逐行匹配数」，
  129 个一方文件 0 差异），所以这条修复同样是**预防性**的：它买的是「排版不再能决定
  门禁是否看见」，不是「今天拦下了什么」。这一条必须写清楚，否则会被读成又修了一个真 bug。
* 语句窗口用 `;` 切分，仍是启发式：如果一条语句里嵌了带 `;` 的东西
  （块字面量、`for` 循环），窗口会偏窄，可能漏掉赋值而把受保护的 block 判成 untokened。
  方向是**误红**而非误绿，且真树未触发；要彻底摆脱就得要真正的 ObjC 解析器，属新功能，只登记。
* token 的持有写法只认点号形式：`TOKEN_ASSIGN` 是 `\w+\.(\w*[Oo]bserver\w*)\s*=`，
  也就是 `self.xObserver = ...`。用 ivar 直接持有（`_xObserver = ...`）的页面会被判成
  `block-untokened` 这一最重罪名——**误红**。扫过全部 129 个一方文件的 appearance 方法，
  这种写法 0 处，所以今天不可达，本轮因此**不改规则**，只登记；真有人改用 ivar 时它会以红
  的形式自己冒出来，不会静默。
* 规则只认 `viewDidAppear` / `viewWillAppear` 两个方法名。为确认没有别的「每次访问再执行」的
  方法在偷偷注册，按 viewDidLayout / viewWillLayout / windowDidResize / windowDidBecomeKey /
  updateView / refresh* / reloadData / applicationDidBecomeActive 扫了同一批文件，
  这些方法体里的注册数是 0，所以今天没有漏网项。把它们做成可配置清单是**新增规则能力**，
  不在打磨模式里写，只登记入口。

---

## 21. 从猜边界到数括号：一次同族扫描与它顺带照出的自己（2026-09-25）

§19/§20 之后，把「静默误绿」这条元规则拿去扫**所有读源码的门禁**，结果分三部分，
三部分都记下来，因为其中两部分是否证。

### 扫别人：其余门禁在失败处都大声报错

`enhancement-engine-resolution-tests.py` / `frame-interpolation-status-tests.py` /
`held-modifier-keyboard-pair-tests.py` 的 `enum_block()` 在 `find` 落空时
`raise SystemExit`；`workflow-audit.py` 的 `${{` 未闭合会追加 WF016；
`constraints-audit.py` 找不到 `[NSTimer` 会追加一条 problem；
`assertion-battery.py` 与 `stream-menu-addressing-tests.py` 找不到锚点也 `raise`。
**结论：ownership-audit 是例外而不是通例**——因为那两处正是我前两轮自己引入的。

### 否证的两条假设

* 「列 0 被注释掉的方法声明或 `@end` 会提前截断方法」：**不成立**。边界要求行首是
  `- (` 或 `@end`，`//` 前缀不匹配，实测 `READ`。
* 「同一文件多个 `@implementation` 的同名 appearance 方法在字典里互相覆盖」：**不成立**。
  扫全部 129 个一方文件，同名 appearance 方法 0 处。

### 成立的那条：块注释里的列 0 `@end`

```objc
- (void)viewDidAppear {
/*
@implementation OldView
- (void)deadCode {
}
@end
*/
    [[NSNotificationCenter defaultCenter] addObserver:self …];
}
```

合法可编译，且「把旧实现整段注释掉留在原地」是常见改法。`/*@end*/` 里那行 `@end`
在列 0，命中「下一个列 0 声明或 `@end`」这条边界 → 方法在它那里结束 →
其后的注册 `sites=0`，无登记、无抱怨 = 静默绿。实测：`INVISIBLE -> unjudged`。

### 修法：数括号，并且认出「括号只在看起来像括号时才算」

本仓库其实**已有**先例：`stream-menu-addressing-tests.py:method_body` 用深度计数找配对花括号。
但**不能直接照抄**——它不跳注释和字符串，实测 `// }` 会让朴素深度计数把方法提前结束
（`INVISIBLE -> would be wrong`），于是把「猜边界」换成另一种「猜括号」。
所以 `method_text()` 现在数括号，并先经 `past_noise()` 跳过 `//`、`/* */`、
`"…"`/`@"…"`（含 `\` 转义）与字符字面量；声明行没有 `{` 时（换行放在下一行的排版）
返回剩余全文，**过读而不过漏**。

### 验证

* `--self-test` **90 → 93**。`git show HEAD:` 把旧实现 exec 回当前模块复跑，
  **恰好 1 条失败**（被注释掉的 `@implementation`），即本轮真正关闭的是它；
  另 2 条新用例（注释里的 `}`、字符串里的 `{}`）在旧实现下也通过——它们不是红证，
  是**新匹配器自身风险**的护栏，用例注释里写明了这一点，不能混作「又抓到两个真 bug」。
* `--red-team` **36 → 37** 全绿：真树注入 `CommentedPage.m`（块注释 + 其后一个未登记注册），
  旧实现 `sites=0 / problems=0` 放行，新实现报 `a new notification registration appeared`。
* `--require-partial` 真树读数**不变**：`8 registration(s) … 8 of them withdrawn`、0 failure。
  方法体尺寸也从「整份文件」回到正常量级（`viewWillAppear` 750、`viewDidAppear` 2971 字符），
  这本身就是边界正确的证据。
* `workflow-audit` 25 规则通过；`local-gates.sh` 见本节末。

### 这条改动怎么把自己照出来的

第一版 `method_text` 取声明行时写成 `text.rfind("\n", 0, start)`，而 `start` 就是声明行
结尾换行的下一字符，于是 `rfind` 命中的是**同一个**换行，切片为空 →
`"{" not in declaration` 恒真 → **每次走「过读」分支**，括号逻辑从未执行。
`--self-test` 当时照样 **93/93 全绿**（过读让所有注册都「看得见」，而 fixture 只有一条注册，
顺序判断也恰好不受影响），`--red-team` 也照样通过。
把它照出来的是**真树读数**：`viewDidAppear` 的 3 个注册被同时算进 `viewWillAppear`，
`AppsViewController.m` 立刻冒出 3 条「未登记的新注册」。
教训写在这里而不是只写在 commit 里：**过读在 fixture 上是绿的，只有拿真文件读才会露出形状**；
所以「真树读数不变」这一条从 §19 起就不是走过场，它这几轮已经拦下两次我自己写的错。

### 登记（更新前两节的口径）

* **已关闭**：§19 的「边界是启发式、需要能数括号的解析」——本轮就是它，
  除了声明行不含 `{` 的排版（选择过读，安全方向）。
* **仍然开着**：§20 的 `;` 语句窗口（嵌套 `;` 会切窄，方向偏误红）；
  ivar 形式的 token 写法（今天 0 处，误红方向）；
  appearance 方法名只有两个（其他「每次访问再执行」的方法今天 0 注册）。
* **新登记**：`past_noise()` 不认预处理拼接、也不认 ObjC 特有的 `@"…"` 之外的
  字符串前缀（如 `u"…"`、原始字符串在本仓库无对应物）；真树 129 文件实测未触发。
* `stream-menu-addressing-tests.py` 的朴素深度计数**不在本轮射程内**：它只读自己
  控制的一个出厂方法，今天成立；若哪天让它读任意页面，必须复用 `past_noise()`。

---

## 22. 撤销写在注册之后，helper 路径原来照样放行（2026-09-25）

### 缺陷

`helper_removes_token(text, body, token)` 在**整个方法体**里找 `[self remove…Observers]` 调用，
只要找到了、且该 helper 自己确实移除这个 token，就给「已撤销」记账。
它不看**调用出现在注册的哪一边**。于是：

```objc
- (void)viewDidAppear {
    self.logObserver = [[NSNotificationCenter defaultCenter] addObserverForName:…];
    [self removeFixtureObservers];   // 注册之后才撤销
}
```

实测判成 `withdrawn=True via='removeFixtureObservers'` ——**静默绿**。
而 selector 路径从 §18 起就有「撤销写在注册之后必须判红」的用例
（`LATE_WITHDRAWAL_BODY`）。同一个规则，直接撤销看顺序、走 helper 撤销不看顺序，
这条不对称就是漏洞本身。

### 为什么值得修

串流页的 5 个 block 注册**全部**靠这一个 helper 撤销（实测 5 个站点
`via=removeStreamSettingsObservers`）。也就是说这个规则今天最重的责任，
正好压在最弱的那条记账路径上：谁把 `[self removeStreamSettingsObservers]`
挪到 5 行注册之后（重构里很常见），门禁会绿着放行一次 `NSUserDefaultsDidChange`
打到副标题 5 遍的放大。出厂代码的顺序是对的（692 行的调用在 693+ 的注册之前），
所以**产品里没有真实放大 bug**，本轮修的是规则判定不完备。

### 修法

记账范围从 `body` 收窄到 `earlier`（该注册之前的文本），与直接撤销同一条边界。
一句话：**给撤销记账的依据是它写在注册之前，而不是它写在方法里。**

### 验证

* `--self-test` **93 → 94**：新用例「helper 在注册之后调用」必须判红；
  `git show HEAD:` 把旧实现 exec 回来复跑，**恰好 1 条失败**，其余 22 条不动。
* `--red-team` **37 → 38**：注入方式不是造新页面，而是**改造真实串流页**——
  只把那一行 helper 调用挪到它 5 个注册之后，注册、helper、token 一个字符都没改，
  站点键也不变（仍在记录里），所以唯一还能抱怨的就是顺序。
  新规则：`5 notification registration(s) are made in a method that runs again`；
  HEAD 规则：`problems=0`。这组数字才是「洞曾经敞开」的量化证据。
* 真树读数**不变**：`8 registration(s) … 8 of them withdrawn`、0 failure，
  其中 5 个仍由 helper 记账——收紧没有冤枉出厂页面，它是靠顺序挣来的记账。
* `workflow-audit` 25 规则通过；`local-gates.sh` **47 passed / 0 failed / 12 need CI artefact**。

### 这条改动里我自己写错的两处（记下来，都是流程问题）

1. 红队用例第一版注入的是一个**新页面**，旧规则也会因为「未登记的注册」报红，
   于是它**根本不隔离本次修复**；而我给它的注释写的是「页面在记录里」，与事实相反。
   红队用例的合格标准不是「新规则会报红」，而是「**旧规则必须放行**」——
   这条标准写进 §19 之后第一次被我自己违反，靠把用例改造成真树 mutation 才满足。
2. 改造函数返回的是**页面文本**，而用例列表要的是**整棵树**，红队跑到那条用例时
   `AttributeError` 中断。暴露它的是 `^ok` 计数从 38 掉到 33——
   **门禁自己的输出计数也是信号**，一次「变少的绿」和一次红同样值得追。

### 登记

* helper 内部**按条件**撤销（`if (self.x != nil) { removeObserver:self.x; }`）仍然算撤销——
  规则只问 helper 体里有没有那句移除，不问它在什么条件下执行。今天出厂 helper 正是这种形状，
  所以这条宽松是必需的；但它也意味着「helper 里有那句」不等于「运行时真的执行了」。
  要证执行只能靠运行期读数（§18 已登记入口：给探针加一条重复显示页面 N 次再数回调的路径）。
* helper 若实现**在别的文件**（分类、父类），`helper_removes_token` 在单文件文本里找不到定义，
  于是不给记账 → **误红**方向，安全；真树今天 0 处（5 个站点的 helper 都在同一个文件里）。

### 规则的严格之处今天不产生误红（量过）

收紧判定会引入两类「合法但被判红」的可能，都实测过发生率：

* **整体撤销**：`[center removeObserver:self]`（不带 `name:`）确实会清掉旧注册，
  但 `REMOVE_BY_NAME` 要求 `name:`，所以不给它记账。真树里出现在注册之前的整体撤销
  **0 次**，也就是说这条严格今天不冤枉任何页面。将来真出现，方向是误红，
  报错信息会直接说清是「注册未撤销」，改法显然（要么按名撤销，要么把那句挪到注册之前）。
* **只在离开时撤销**：若某页面在 `viewWillDisappear` 撤销、`viewDidAppear` 注册，
  任意时刻也只有一个注册，放大并不存在，但本规则看的是 `viewDidAppear` 之前的文本，会判红。
  实测两个相关页面（应用页、串流页）都**没有**实现 `viewWillDisappear` / `viewDidDisappear`，
  清理只在 `dealloc`，所以今天没有这种页面。要支持它需要跨方法读（把 disappear 方法的撤销
  也算进该访问周期的账），属于**新增规则能力**，按基线只登记入口，不在打磨轮里写。

---

## 23. 配对记录是谁写的：一个从没被测过的阅读器（2026-09-25）

§18 的元规则（**看不见就必须抱怨；断言来的记账等于没测**）这轮拿去查 §5 的 holder 规则，
命中三处，外加一处结构性缺口。结构性缺口最要命：

`pairing_self_test()` 喂给 `judge_pairing()` 的是 `site()` 造的合成站点，
`pairedWithHost` **由 fixture 直接写死**。也就是说 §5 规则打分的依据，
从来没有人问过 `app_assignment_sites()` 从源码里读得对不对。
评分可以一直全绿，而阅读器和「配对」这件事毫无关系。

### 三处缺陷（方向都是危险的）

`pairedWithHost` 决定的是：**将来 `app.host` 转 `weak` 时，哪些 holder 免改。**
读错的后果不是误红，而是被免改的 holder 手里没有 host → 串流中途 nil 解引用。

1. **比较被当成赋值。** `HOST_ASSIGNMENT` 是 `\b[A-Za-z_]\w*\.host\s*=`，
   而 `\s*=` 会吃掉 `==` 的第一个等号。于是
   `if (retriever.host == nil) { … }`、`NSCAssert(retriever.host == nil, @"wired")`
   都记成「这个 holder 已经拿到自己的 host」。实测两个形状都 `paired=True`。
2. **注释里的配对也算数。** 判定直接在原始文本上做，
   方法体里留一段 `/* … retriever.host = host; … */` 死代码就足以换来免改资格。
3. **`method_span()` 的两个反向猜测。** 它取「最近的列 0 `- (`」作起点、
   「下一个列 0 `}`」作终点，且**找不到终点时一路读到文件末尾**——
   那时文件里任何靠后的 `.host =` 都会给前面的 holder 配上对。
   §19/§21 为这两条猜测付过两轮代价，而 §5 这里猜错的方向更坏。

### 修法

* `HOST_ASSIGNMENT` 捕获**主语**并加 `(?!=)`：`\b([A-Za-z_][\w.]*?)\.host\s*=(?!=)`；
  判定改为「body 里存在主语以该 holder 结尾的赋值」。
* 新增 `code_only(text)`：把注释与字符串**抹成空格**（等长、行数不变，偏移仍可索引原文），
  站点定位与配对判定都在它上面做。这是 §21 那条「括号只在像括号时才算」用到判定层。
* `method_spans(text)` 改为**前向走**：跳噪声后在列 0 认出方法头，复用 `method_text`
  的括号匹配定尾；`method_span` 退化成「在 spans 里查包含 offset 的那一段」。

### 本轮我自己引入的回归（第三次被真树读数抓住）

新写的 `METHOD_HEAD` 是 `[+-]\s*\([^)]*\)\s*[A-Za-z_][\w:]*\s*\{$`，
只吃**无参**选择器；而本仓库最常见的是带参声明
`- (void) retrieveAssetsFromHost:(TemporaryHost*)host {`。
结果 `AppAssetManager.m` 里 `retriever.app`（58 行）与 `retriever.host`（59 行）明明同方法相邻两行，
却读成 `paired=False`——**真树唯一那个配对项被冤枉**，门禁当场从
`1 of them also give it a host` 掉成 0。
修法是把声明尾部放开到 `{`：`[+-]\s*\([^)]*\)\s*[^{;{}]*\{$`。
（§19、§20、§22 之后这是第四次：fixture 全绿不等于读对了真文件。）

### 验证

* `--self-test` **94 → 105**，新增的 11 条全部跑真阅读器 `app_assignment_sites`：
  同方法配对（True）、只给 app（False）、`==` 比较（False）、断言比较（False）、
  别人的 `.host =`（False）、比较兼赋值（True）、块注释里的配对（False）、
  行注释里的配对（False）、被注释掉的 `.app =` 应当**不产生站点**（0 站点）、
  配对写在别的方法里（False）、**带参数的声明**（True，就是上面那个回归）。
* `git show HEAD:` 把旧的 `HOST_ASSIGNMENT` / `method_span` / `app_assignment_sites`
  装回来复跑：**恰好 4 条失败**，全部是危险方向的假配对（比较、断言、两种注释）。
* 真树读数**不变**：`3 site(s) hand an app to a holder and 1 of them also give it a host`、
  0 failure；红队 38 条全绿，其中「唯一配对 holder 被悄悄取消配对」仍然咬。
* `workflow-audit` 25 规则通过；`local-gates.sh` **47 passed / 0 failed / 12 need CI artefact**。

### 登记

* 本轮对今天的树**没有行为改动**（新旧读数一致），价值在关掉「假配对」这条危险方向，
  以及把阅读器的判定从断言变成实测。这条必须写明白，否则会被读成又修了一个线上 bug。
* `(?!=)` 只挡 `==`。`.host <= ` / `.host >= ` 这类写法在属性上不可能出现（`<=` 前必有空格与运算符），
  真树 0 处；`!=` 本来就不匹配（`.host` 后是 `!`）。
* `code_only()` 仍不认预处理续行，继承 §21 的上限。
* `APP_ASSIGNMENT` 只认 `^\s*(\w+)\.app\s*=` 这种**裸主语**写法，
  `self.store.app = …`、`items[0].app = …` 一类读不到。
  实测把源码里所有 `.app =` 出现处与规则登记的站点比对，**真树 0 处漏网**；
  将来若出现，方向是漏登记者 → 报「新 holder」→ 误红，安全。


## 24. `= nil` 也是赋值：配对阅读器补上的第三个洞（2026-09-25）

### 触发点

§23 把 `pairedWithHost` 从 fixture 断言换成真阅读器，末尾登记了一条「`(?!=)` 只挡 `==`」。
本轮顺着它问了一句：**挡掉比较之后，`HOST_ASSIGNMENT` 还承认什么？**
答案是它承认 `retriever.host = nil;`——一行**真赋值**，`(?!=)` 自然放行。

### 为什么这是危险方向，不是瑕疵

这条 verdict 只有一个用途：决定 **`app.host` 转 `weak` 时哪些 holder 免改**（§23）。
只会把 host 清空的页面，在反指变弱那天读到的正好是 nil——它是最该被点名去补的 holder，
却因为「body 里有一行 `.host =`」拿到了免改资格。方向和 §23 那三处同源：**该红不红**。

实测 HEAD 的实现：

| 页面形状 | 旧读数 | 应当 |
|:---|:---|:---|
| `retriever.host = nil;` | `paired=True` | False |
| `retriever.host = NULL;` | `paired=True` | False |

### 修法

* `HOST_ASSIGNMENT` 多捕获一个**右值**：`\b([A-Za-z_][\w.]*?)\.host\s*=(?!=)\s*([^;]*)`；
* 新增 `NO_HOST_ASSIGNED = ("nil", "NULL", "0")` 与 `hands_a_host(receiver, value, holder)`，
  配对条件从「主语以该 holder 结尾」变成「主语以该 holder 结尾**且值不是空指针的三种写法**」；
* **读不出的右值保留记账**：既不因此免改，也不额外报红。理由见下方登记。

### 验证

* `--self-test` **105 → 111**，新增 6 条全部跑真阅读器 `app_assignment_sites`：
  只清空（False）、`NULL` 写法（False）、先清后给（True）、把来路的 host 交回去（True）、
  清空的是别人的 host（False）、真配对旁边留了一行被注释掉的清空（True）。
* 红证（标准仍是「**旧实现必须放行**」）：`git show HEAD:` 把旧 `HOST_ASSIGNMENT` 与
  旧 `app_assignment_sites` 装回当前模块复跑，**恰好 2 条失败**，都是「只清空却被记成已配对」。
* **真树读数不变**：`3 site(s) hand an app to a holder and 1 of them also give it a host`、
  0 failure。真树里唯一的 `.host = nil` 在 `AppDelegateForAppKit.m:1170`，那是探针**手工切断反指**
  的形状，不在任何 `.app =` 站点所属的方法里，因此不参与这条判定——§19 起那条「真树读数不变」的闸
  第五次派上用场：它这一轮守的是「别把探针的切断读成业务的清空」。
* 红队 38 条全绿（含「唯一配对 holder 被悄悄取消配对」）；`workflow-audit` 25 规则通过；
  `local-gates.sh` **47 passed / 0 failed / 12 need CI artefact**。

### 登记

* 本轮对今天的树**仍然没有行为改动**：真树 0 处「只清空不给值」的 holder，
  `streamVC.app` 与 `item.app` 两处所在方法里连 `.host =` 都没有。价值是把「免改资格」
  最后一个静默放行口关掉。这条要写明白，否则会被读成又修了一个线上 bug。
* `NO_HOST_ASSIGNED` 只认字面量 `nil` / `NULL` / `0`。`retriever.host = someEmptyVariable`、
  `(id)nil`、`nil ?: host` 一类读不出来，方向是**继续记账**（免改），与上一条同族；真树 0 处。
* 反向的过度收紧已被用例咬住：`nil` 与真赋值同时出现时仍是 True。**清空不是撤销配对**，
  `any()` 要回答的是「这个 body 有没有真给过 host」，把它写成 `all()` 会把正确配对的页面冤枉成
  待改 holder——那是一条误红，也是本轮刻意留下的一条守卫。


## 25. token 存在 ivar 里，就被判成「没人保留 block」（2026-09-25）

### 触发点

§24 关掉一个静默放行之后，同族还剩一类问法：**这条规则认几种写法？**
`observer_registration_sites()` 认 token 只认属性拼写：

* 赋值侧 `TOKEN_ASSIGN` 是 `\w+\.(\w*[Oo]bserver\w*)\s*=`，**必须有个点号**；
* 撤销侧 `REMOVE_TOKEN` 同样要求 `removeObserver:` 后面是 `xxx.`。

于是把 token 存在 ivar 里的页面（`_logObserver = [[NSNotificationCenter defaultCenter]
addObserverForName:…]`）读不出 token，直接落进 `kind = "block-untokened"` 那条分支——
也就是本规则措辞最重的判词「block registered and never kept」。

### 方向：误红，而且红在已保护的页面上

实测旧规则看一个**完全正确**的 ivar 页面：

```objc
if (_logObserver != nil) { [[NSNotificationCenter defaultCenter] removeObserver:_logObserver]; }
_logObserver = [[NSNotificationCenter defaultCenter] addObserverForName:@"LogDidAppend" …];
```

读数是 `kind=block-untokened, withdrawn=False` → 报「每次进入都会再注册一遍」。
这条不危险（不会放行任何东西），但它把「读不出」和「最坏情况」写成了同一句话，
而这条规则自己反复讲的原则是：**读不到要叫读不到，不能叫成缺陷**。

### 修法

* 两个 pattern 各加一个 ivar 分支：`(?<![\w.])(_{0,2}\w*[Oo]bserver\w*)\s*=` /
  `removeObserver:\s*(_{0,2}\w*[Oo]bserver\w*)`。`(?<![\w.])` 把属性访问挡在 ivar 分支外，
  一个名字不会被记两次；
* 分支变成两个捕获组后，`findall` 返回的就是带空的一半的配对——这正是 `first_group`
  在通知名上处理的同一个坑。新增 `token_names(pattern, text)` 统一取名，
  三处调用点（`helper_removes_token` 与站点判定两处）一起改，**不许拿元组和字符串比**。

### 刻意不折叠 `_logObserver` 与 `self.logObserver`

ObjC 里 property 的 backing ivar 通常就是 `_x`，折叠两个拼写看起来很自然。
本轮**不折叠**，并且写了一条用例把这个选择钉住：注册写 `_logObserver`、撤销写
`removeObserver:self.logObserver` 的页面**继续判红**。
理由是折叠等于允许「对另一个变量的撤销」释放「存在这个变量里的注册」——
那是**该红不红**的方向，与 §23/§24 修的是同一类错误。代价（合法混用会误红）登记在下方。

### 验证

* `--self-test` **111 → 115**，4 条 ivar 用例：ivar 自撤（绿）、ivar 经 helper 撤（绿）、
  helper 没被调用（红）、存在 ivar 却经 property 撤销（红，就是上面那条钉子的守卫）。
* 红证：`git show HEAD:` 装回旧的 `TOKEN_ASSIGN` / `REMOVE_TOKEN` 与**旧的两处调用点**
  （调用点必须一起装，否则新代码拿元组比字符串，测的就不是旧规则了），
  复跑 27 条注册用例 → **恰好 2 条失败**，正是两条 ivar 误红；
  两条「必须继续判红」的守卫在旧实现下同样判红，说明用例没有靠收紧来制造失败。
* **真树读数不变**：8 registrations、8 withdrawn、0 ownership failure。
  实测真树这 8 处**全部**是 `self.xxxObserver` 写法，没有一处 ivar 拼写。
* 红队 38 条全绿；`workflow-audit` 25 规则通过；`local-gates.sh` **47 passed / 0 failed / 12 need CI artefact**。

### 登记

* 本轮对今天的树**没有行为改动**（真树 0 处 ivar 拼写），价值是把「读不出」从最重判词里拆出来。
* `_x` 与 `self.x` 混用的合法页面会被判红 → 误红方向，真树 0 处。真要支持，
  得先能读出 property 的 backing ivar 名（`@dynamic`、自定义 getter 都要另算），属新增能力。
* `_{0,2}` 只认 0～2 个下划线前缀（含 Swift 桥接常见的 `__`）。更怪的名字读不到 → 同上，误红方向。
* 局部变量形式的 token（`id observer = [center addObserverForName:…]`）仍在**跨方法撤销**这条上限里：
  它的撤销几乎总是写在 `dealloc` / `viewWillDisappear`，需要跨方法读才认，本轮不碰。

## 26. 功能栏只认「指针已经逃逸」：一条与捕获模式无关的感应带（2026-09-25）

### 触发点

`StreamViewController+MouseCapture.m` 里展开 dock 的唯一入口是 `uncaptureFreeMouseForExitEdge:`，
而它只在 `freeMouseExitEdgeForEvent:` 判定成功时才被调用。那个判定的第一行就是
`if (!self.isRemoteDesktopMode || !self.isMouseCaptured) return None;` —— 于是**游戏模式
（相对指针）下 dock 永远不会被指针唤出**：指针被回中/钳制在 view 内，根本到不了边。
非捕获态只剩 `MLEdgeMenuButton` 自己的 `NSTrackingArea`（收起态只露 `VisiblePeek=30`），
要命中它得先知道 dock 停在哪条边的哪个位置。

### 定案：常驻感应带，两条入口，任一先到

| 量 | 值 | 为什么是这个数 |
|:---|:---|:---|
| 感应带宽度 | 24pt | 沿 dock 那条边整条，不要求命中按钮位置；比 `InteractionOutwardPadding=18` 宽、比 `VisiblePeek=30` 窄，不吞掉正常贴边操作 |
| 贴边阈值 | 2pt | 与 `freeMouseExitEdgeForEvent:` 里非 tight 的 `threshold = 2.0` 同一读数 |
| 持续 | 150ms | FPS 甩视角在边的法向上停留 <150ms；150ms 已是「按住不动」而非「掠过」 |
| 推压预算 | 30pt | 指针被钳制时用户仍能「往外顶」；30pt 是多次事件累计，单次最多计 6pt |
| 单事件封顶 | 6pt | 一次甩动可达 100pt+，不封顶就等于「掠边即出」 |

* 触发后**复用** `activateEdgeMenuDockForExitEdge:`（展开 + 临时释放 + `AutoCollapseDelay=0.82s` 收起），
  不新造第二套展开逻辑；释放走通用 `uncaptureMouseWithCode:@"MUC109"`，因此**成对恢复**
  沿用既有实现（`deactivateEdgeMenuTemporaryReleaseAndRecaptureIfNeeded:` 里 `captureMouse`）。
* **现有 free-mouse 路径优先**：`handleEdgeSensorSummonForEvent:` 在 `freeMouseExitEdgeForEvent:`
  判出非 None 时直接让路。老路（1pt 逃逸）比新带更激进，因此远程桌面模式的行为**逐字节不变**，
  新带只在老路不会触发的场合（主要是相对模式）起作用。
* 偏好键 `edgeSensorSummon`，**默认开**；关→ `handleEdgeSensorSummonForEvent:` 第一行返回，
  不建 timer、不记账、不改任何既有分支。每次 `captureMouse` 重读，设置页改完下次捕获即生效。

### 验证

* `scripts/edge-sensor-summon-tests.py`：把三个**出厂 C 函数**从 `MouseCapture.m` 里按括号配对抽出来，
  用 `cc -std=c11` 编译后驱动 → **27 条行为断言全绿**（四条边的法向读数、越界为负不外翻、
  带内与贴边分离、四个方向的朝外符号、单事件封顶、预算 5 个事件花完、回抽不退账、
  29.4+0.6 触发而 29.4+0.5 不触发、出厂常量与文案数字一致）。
* 同一脚本的接线断言 **0 gaps**：四个指针 handler 全部接入；释放+展开成对；dwell 是 one-shot
  且 `weakSelf`、有 `invalidate`；到期时要求「仍然贴边」才触发；收起 dock 即清账；
  重新捕获重读开关；声明落在 `MouseCaptureInternal` 而不是 `(MenuUI)`。
* 偏好链路 **0 gaps**：默认 true、桥接字典带 key、设置页有开关、中英双语文案都写着 24/2/150/30/6/0.82。
* `--self-test` 红证三类：拆掉单事件封顶 → **4 条行为断言变红**；拆掉开关短路 → 接线报 1 gap；
  拆掉收起时的清账 → 接线报 ledger gap。
* 编译：`xcodebuild`(Debug/arm64) **BUILD SUCCEEDED**，一方文件 **0 warning**。
  第一轮构建曾有 6 条 `-Wincomplete-implementation`（方法声明误落在 `(MenuUI)` 分类接口），
  已把声明移到 `(MouseCaptureInternal)` 并复验为 0。
* `l10n-audit.py` 0 failures（第一次写漏了 `.strings` 条目结尾分号，CoreFoundation 会在第一条
  无终结符处停止解析 → 该审计把两条 FAIL 直接顶了出来）。

### 登记

* **手感未实测**：150ms / 30pt / 6pt 是按「掠边与持住的读数差异」定的，需要一次真实串流
  （180Hz 魔兽场景）确认不误触、且贴边能唤出。数字改动的登记与本次表格里同源。
* 回抽不退账（`-50pt` 不减少已累计的 10pt）：来回小幅蹭边会累计到预算 → 误触方向，真机若出现
  就改成「带符号累计并下限为 0」，代价是甩视角的余量变小。
* dwell 用 one-shot timer 而非事件时间戳：相对模式下用户静止时**不再产生**鼠标事件，
  事件计时会永远不触发；timer 是这里唯一能覆盖「静止贴住」的形式。
* dock 停在哪条边由 `edgeMenuDockEdge` 决定，感应带跟着它走；拖动 dock 换边时感应带随之换边
  （`resetEdgeSensorSummonState` 在收起与重新捕获时都会清账，不会把旧边的账带到新边）。

## 27. 系统快捷键是谁的：一次「借」与六条「还」（2026-09-25）

### 触发点

* 目标第 2 项要求 F1–F12 在串流时直达被控端。已验证事实：`Limelight/Input/HIDSupport.m` 的码表
  从 `kVK_F1` 起一直排到 `kVK_F20`，但全仓 **0 个 `CGEventTap`、0 个 `NSEventTypeSystemDefined`
  处理** —— F3/F4 在 WindowServer 层就被调度中心/启动台吃掉，本端从来没看到过这两个键。
* 所以「码表里有 F 键」不等于「F 键能用」：缺的不是编码，是**借键**这一步。

### 修法

* **私有 API 只能运行时解析**：`nm` 在 macOS 的 dyld shared cache 上探不到
  `CGSSetGlobalHotKeyOperatingMode`，而项目此前**私有 API 用法为 0**，直接 `extern` 会因 `.tbd`
  缺符号而链接失败。改为 `dlopen` CoreGraphics + `dlsym` 两个入口
  （`CGSMainConnectionID` / `CGSSetGlobalHotKeyOperatingMode`），**故意不 `dlclose`**：两个指针
  只在镜像映射期间有效，而之后任意时刻都可能要回退方向。任一入口缺失 → 整对指针置 NULL，
  `MLSystemGlobalHotkeysSetEnabled` 返回 -1（不可用），状态机停在「没借过」。
* **arity 与错误码是实测出来的**：非法 connection id 返回 **1002**（`kCGErrorInvalidConnection`），
  非法 mode（99 / 0xFFFF）返回 **0**。前者说明第一个字确实是连接、调用确实是两参数；后者说明
  **mode 不做校验**，因此只允许传 0 和 1，绝不把用户输入或枚举越界值透传。
* **账本只信成功的调用**：纯 C 的 `MLSystemHotkeyStateAfter(error, want, was)` 规定
  只有 `CGError == 0` 才把「已抑制」记进 `systemHotkeysSuppressed`。记下一次没发生的抑制，
  就是串流结束后快捷键永久消失、而应用里再没有任何东西能归还它。
* **借一次，还六处**（全部挂在既有钩子上，**0 个新增 observer 注册**）：进入全屏、退出全屏、
  应用转为前台 → `updateSystemHotkeySuppression`；应用转后台、窗口即将关闭 →
  `restoreSystemHotkeySuppressionForReason:`；`tearDownStreamLifecycleObserversAndTimers`
  内再还一次 —— 这是串流仍可能占着屏幕时进程里的最后一句话。
* **归还不能写进 `removeStreamSettingsObservers` 本体**：`viewDidAppear` 会先调用它再重新注册，
  挂在那里等于每次设置页刷新都还一次键；实测放在 teardown 里，注册路径不再触发归还。
* **转后台必须还**：抑制的作用域是本进程，把用户按在串流窗口后面却没有调度中心，等于没有退路。
* 三态偏好 `systemKeyboardShortcutCapture`（Int，默认 0 跟随全屏 / 1 始终 / 2 从不）全链路落地：
  `SettingsStore` → `SettingsModel+DerivedValues` → `SettingsModel` → `+Persistence` →
  `SettingsObjCBridge` → `SettingsInputPane`，中英双语句 case 成对；越界值在
  `refreshSystemKeyboardShortcutCapturePreference` 与 Swift `didSet` 两侧都归一化回 0。

### 验证

* `scripts/system-hotkey-capture-tests.py`：**13 条行为断言全绿**（只有 error 0 能推进账本、
  被拒的调用保持原状态、不可用返回 -1 等）、接线 **0 gaps**（六个借键时刻都有归还配对）、
  偏好链路 **0 gaps**（三态出厂、双语命名一致）。
* 同一脚本 `--self-test` **四类红证全部变红**：账本相信被拒的调用 → 7 条红；teardown 不归还 →
  1 gap；忽略「从不接管」→ 1 gap；把归还挪到 `viewDidAppear` 先走的那条刷新路径 → 1 gap。
* `swift-typecheck.py` clean（33 files）、`l10n-audit.py` 0 failures、
  `xcodebuild`(Debug/arm64) **BUILD SUCCEEDED**、一方文件 0 warning
  （第一轮 Swift 里多写了一个右括号，被 swift-typecheck 当场抓住）。
* CI 步骤与本地聚合都跑它：`build.yml` 新增步骤，`constraints-audit.py` 用 `subprocess`
  真跑读数与 `--self-test` 两半（否则 parity 规则会报「CI 跑了本地不跑的 gate」）。

### 登记

* **真正要验收的那件事还没实测**：180 Hz 串流下调度中心是否真的不弹、退出串流后 Spotlight 与
  输入法切换是否真的全部恢复，都需要一次真实串流。数字与恢复路径目前只有代码级证据。
* **私有 API 的分发风险未评估**：`CGSSetGlobalHotKeyOperatingMode` 是私有符号，Developer ID
  签名 + 公证路径上会不会被拦、是否影响上架，仓库里此前没有先例，本轮没有凭据可测。
* **mode 不校验**：越界 mode 返回 0（成功）而不报错，意味着一旦把不可信值透传，
  会得到「调用成功但什么都没发生」的假绿灯 —— 故两侧入口都硬性只允许 0/1。
* **`NSEventTypeSystemDefined` 归一化未实现（目标第 2 项的第 2 子项）**：键盘被设为「当作媒体键」
  时，F3/F4 以系统定义事件到达，其字段没有公开文档，反推 F 键码会因键盘型号而异。
  本轮不猜表：需要一次真机按键读数（keyCode / subtype / data1）才能把映射写成事实。
* 设置页呈现期间是否仍抑制快捷键：当前实现按「窗口 + 前台 + 全屏/无边框」判定，
  **内嵌设置页呈现时同样保持抑制**，尚未按真机手感确认这是否 wanted。

## 28. 「双击左键连续发 C」：一次没复现的回归报告，和它照出的四个无闸读数（2026-09-26）

### 触发点

* 用户报告：**串流时快速双击鼠标左键，会连续发送 C 键**。这是行为缺陷报告，不是新功能。
* 仓库里能找到同名旧案：`HIDSupport.m` 的 `keyDown:` 上方留着一条注释，明说某些驱动会把垃圾值
  留在鼠标事件的 `keyCode` 字段里、其中一个正好撞上 `kVK_ANSI_C`(8)，而**读它就是当年
  "double-click sends C" 的成因**；引入这条注释的提交是
  `6292cb9 fix(input): remove the synthetic keydown detector that drops real keys`（2026-09-13），
  结论写得很硬：类型闸是完整修法，任何「按时间/按字符猜」的启发式都会吃掉真实按键。
* 因此本轮的定位问题不是「为什么会发 C」，而是**「闸还在不在，以及是否所有读数点都有闸」**。

### 排查（全部是已验证事实，非推测）

* 三个会向被控端发键盘事件的入口 —— `-[HIDSupport keyDown:]` / `keyUp:` / `flagsChanged:` ——
  在 HEAD 上**都带着 `event.type` 硬闸**；发往远端的唯一出口 `LiSendKeyboardEventCtx` 只有
  `HIDSupport*` 调用（全仓 0 个其他调用点）。
* 鼠标路径干净：`dispatchMouseButton:` → `-[HIDSupport mouseDown:withButton:]` /
  `sendMouseButton:...` 只调 `LiSendMouseButtonEventCtx`；本机 monitor 的鼠标 handler 只写日志；
  `CoreHIDMouseDriver.swift` 不含任何键盘发送；Swift 侧快捷键录制器用
  `switch event.type`，`default` 原样放行。
* 本机 `CGEventCreateKeyboardEvent` 只有两处（`CollectionView.m`、`NavigatableAlertView.m`），
  且 keyCode 是显式常量（方向键/Return/Delete），只由手柄导航触发；`OnScreenControls` 不在工程里
  （`project.pbxproj` 命中 0），不构成串流内的虚拟按键。
* **照出的真问题**：把「读 `event.keyCode` 的函数」全部列出来后（25 处读数、13 个函数），
  有 4 个函数**没有自证闸**，其中
  `shouldDeferCommandModifierForShortcutHandlingWithEvent:` 只在
  `StreamViewController_Internal.h` 里被声明、**全仓没有任何调用方** —— 一个已导出、只判 nil、
  直接读 `keyCode` 的方法，等于上膛的枪：哪天有人把它接到 flagsChanged 或鼠标路径上，
  旧案立刻回来。另三个是 `updateKeyboardPhysicalModifierStateFromEvent:`、
  `translateKeyCodeWithEvent:`、`performIntialSelectionIfNeededForEvent:`，它们靠调用方有闸。

### 修法

* 四个读数函数各自补上类型闸（`keyDown`/`keyUp`/`flagsChanged` 三选一或二，按各自语义）：
  今天能走到它们的事件类型不变，所以**行为零改动**；差别是它们不再依赖调用方记得检查。
  `translateKeyCodeWithEvent:` 用 0 拒绝 —— 那正是它的表「查不到」时已经给的答案，
  两个调用方都按「两边都忽略」处理，按下与抬起仍然成对。
* 新增 `scripts/key-code-read-site-audit.py`：**零宽容**审计。判定按函数、不合并同名函数：
  函数体自己出现 `MLIsKeyboardKeyEvent(` 或 `type [!=]= NSEventType…` 才算过。
  两条曾被用来「开后门」的宽松都删掉了 —— 「调用方有闸所以我也算过」（那是会腐烂的调用图）
  和「方法名叫 `keyDown:` 就按 AppKit 契约放行」（`HIDSupport` 的两个 `keyDown:`/`keyUp:`
  正是**非 responder 类里的同名方法**，事件是调用方给的，离驱动最近，最可能拿到未定义字段）。
* 匹配只认**事件形状**的接收者（`*event`/`theEvent`/`event`），不认 `shortcut.keyCode`：
  StreamShortcut 里的 keyCode 是普通整数，没有「未定义状态」问题，全匹配会对着每一处快捷键
  比较喊狼来了。
* 已接进 CI 步骤，并由 `constraints-audit.py` 用 `subprocess` 真跑读数与 `--self-test` 两半。

### 验证

* `python3 scripts/key-code-read-site-audit.py`：**13 个读数函数 / 13 个自证闸 / 0 findings**；
  读数地板 20（今天 25）。
* `--self-test` **三类红证全部变红**：拆掉 `-[HIDSupport keyDown:]` 的闸（同名函数在别的文件里，
  以前能互相掩护，现在不能）；拆掉 `-[StreamViewController event:matchesShortcut:]` 的闸
  （证明「靠调用方」不成立）；往 `-mouseDown:` 里塞一次 `keyCode` 读数。
* `xcodebuild -scheme "Moonlight for macOS"`(Debug/arm64) **BUILD SUCCEEDED**，
  `Debug/…/CollectionView.o` 时间戳证实本轮改动确实重编；一方文件 0 warning。

### 登记

* **没有复现，也没有在 HEAD 上找到能复现的路径**。这一节记的是「旧案的同类读数全部补闸 +
  规则变成门禁」，不是「已修好用户报的那个现象」，两件事不能混。
* 还需要用户给三样东西才能继续定位：跑的是**哪个构建**（2026-09-13 之前的构建确实带旧案）、
  C 出现在**被控端还是本机**、以及一次复现后的诊断日志导出（`[diag]`/`[input]` 足以指认发送点）。
* `shouldDeferCommandModifierForShortcutHandlingWithEvent:` 为什么是「已导出但零调用方」的
  死方法，本轮没查（只补闸不删）；删与不删留给一次专门的死代码轮。
* 审计只覆盖第一方 `.m`。Swift 侧的 `keyCode` 读数（`SettingsSharedControls.swift` 两处）今天
  靠 `switch event.type` 的 `default` 分支挡住，**没有纳入本门禁的强制范围**，这是已知缺口。
