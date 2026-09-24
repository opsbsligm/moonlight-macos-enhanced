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

- **96 处泄漏未被归因**：`leaks` 汇总 105 处，只详列了 9 个栈，差额没有栈可查。
- **MDNS / AppAsset 回调的 weak 化**：探针不走主机发现与 artwork 路径，所以「泄漏里没有它们」**不是**证据，那条登记项仍未验证。
- **长会话曲线**：没有跑「反复进出设置页 N 次」的累积测量，因此没有增长速率。
- **CI 里没有 `leaks` 门禁**：故意的。泄漏计数随机器与时序浮动，计数型门禁会闪断；
  若将来要做，形状应是「出现在 `ROOT CYCLE` 里的**一手类集合**不得扩大」，且必须先在同一台 runner 上取基线。
