# 审计层与 CI 的真实语义（2026-09-28）

侧边栏本体代码本轮零改动。本文记录 CI #290 audits job 的 5 项失败如何定位、
根因是什么、修完之后"绿"到底证明了什么。全部结论有命令输出支撑；未做的部分
写在最后。

## 一、CI #290 的 5 项失败（确切标签）

此前只知道"5 constraint failures"，GitHub MCP 的 job log 被截断。改用
`gh run view 36353108829 --log`（本地 gh 已登录 opsbsligm）取全量日志后，
标签是确定的：

1. `FAIL the edge summon gate failed its readings`
2. `FAIL the edge summon gate failed its red proofs`
3. `FAIL the interpolation readout gate failed its readings`
4. `FAIL the interpolation readout gate failed its red proofs`
   四项原因文本同为 `no usable clang and macOS SDK pair was found … tried
   xcrun (no clang) and Command Line Tools (no clang)`。
5. `FAIL assertion battery: 128/144 mutations caught`，其中 16 项是
   `mutations whose anchor is gone`（anchor 消失＝什么都没证明），
   missed 为 0。

## 二、根因

### 根因 A：两个需要 clang 的门禁被错放进了 ubuntu 的 aggregate

`edge-sensor-summon-tests.py`（把 MouseCapture.m 的把手/感应带编译出来跑）
与 `interpolation-readout-tests.py`（把 VideoDecoderRenderer.m 的发布器编译
出来跑）都需要 Apple 的 clang + macOS SDK 配对。7c33e3f 把它们接进 audits
job（ubuntu-latest）的 constraints-audit，等于要求一台没有该配对的机器回答
它答不了的问题。

constraints-audit 早就有处理这类门禁的机制：`CI_ONLY` 表——"脚本名 + 一个必须
仍留在脚本里、否则借口失效的标记"，并由同文件的可达性规则保证这些脚本仍在
workflow 里被执行。同类先例是 scroll-notch / relative-pointer-gain /
discrete-scroll-click / controller-mouse-emulation 四项（标记 macOS SDK）。
本轮把两个脚本按同样方式登记：

- `edge-sensor-summon-tests.py` → 标记 `edge_sensor_runtime_probe`
- `interpolation-readout-tests.py` → 标记 `clang_and_sdk`

证明没有丢失：build 矩阵本来就有这两步（"Verify the edge summon band lets go
only for a player who meant it"、"Verify the interpolation readout carries
measurements to the settings page"），可达性规则会拒绝删掉它们的 workflow。
本机直跑两个脚本仍为 PASS（2657 runtime edge checks / 0 gaps），因此 macOS 侧
证据继续存在，只是不再由 ubuntu 冒充。

### 根因 B：16 个 mutation 锚点在输入层重构后全部失效

anchor 消失不是 CI 环境差异：在**本机 committed tree** 上用只读探针复现，
同样是 16 项，路径集中在

- `Limelight/Input/HIDSupport.m`（keyDown/keyUp 已重写：抑制集合改为
  `physical` 变量、release 的守卫变成
  `if (!self.shouldSendInputEvents || (savedCode == nil && pending == nil))`、
  记录写成 `keyboardForwardedKeyDownKeyCodes[physical] = @(keyCode)`）
- `HIDSupport_Internal.h`（滚动计数改 `CGFloat limit` + 包内钳位）
- `HIDSupport+Pointer.m`（手柄指针改走 `HIDDrainRelativeDelta(&emulationResidualX, …)`）
- `ControllerSupport.m`（鼠标模式点击改走 `sendMouseButton:pressed:forController:`）

为什么之前没人发现：本地习惯只跑 `constraints-audit --no-battery`（约 13s），
而 `--no-battery` 恰好跳过 battery；CI 跑全套时 anchor 消失 → exit 1，但日志
截断让人以为只有"数字不对"。后果是这 16 项证明在提交树上静默失效——正是键鼠
回归最需要证据的四组路径。

修法是重新锚定（不是放宽断言）：逐项确认被守护的行为仍在、门禁仍读它，再把
anchor 换成当前形状，并让 anchor 说清"是哪一处"。例：keyDown 与 keyUp 都写
同一行 `removeObject:physical`，于是 `late-clear` 的锚点改成"守卫右括号 + 该行"
的两行上下文——断言从"出现 2 次"变成"我指的是这一处"，邻居一移动就立刻失效。

16 项重锚定后逐项验证（临时 harness 只在真实树上短暂种植再还原，不 kill）：
**16/16 CAUGHT**，失败信息各自命中对应规则文本，例如

- `the release path is not effective: expected exactly one line starting with 'if (!self…'`
- `a three-notch wheel event is worth three notches`
- `the stick path truncates a frame again, which is the shape that lost 45 per cent of a held deflection`
- `the mouse-mode click path records the edge it refuses, so the host is owed a release for a button it never took on`

### 根因 C：battery 把"门禁跑不了"读成"抓到了"

`assertion-battery` 的门禁判定原来只有 True/False。clang 类门禁在没有 clang 的
主机上非零退出，于是那些 mutation 在 ubuntu 上被记成 **CAUGHT**——CI #290 报
128/144 且 missed=0，其中一部分其实是环境给的假证明。现在 `gate_failed` 是三态：
缺 clang+SDK 配对时返回"未判定"，该 mutation 计入 UNPROVED 并在汇总里点名数量
与清单，既不算抓到也不算漏掉。判据引用 `apple_toolchain.NO_TOOLCHAIN_MESSAGE`
（拒绝的那句话由该工具自己拥有），不是脚本里另造的短语。

### 顺带恢复的一条真规则

`drop-release` 重锚定时发现：现规则只要求"消耗记录早于发送"，把消耗移进
swallow 分支仍然是绿的，而那时按键会整局失去（下一次 keyDown 看到记录仍在，
按重复处理直接丢弃）。因此 constraints-audit 增加一条顺序规则：release 路径的
记录消耗必须排在 swallow 守卫之前。`drop-release` 现在专门由它抓住。

## 三、本轮本机证据

- `constraints-audit.py --no-battery`：0 constraint failures
- `input-regression-suite.py`：45 passed, 0 failed
- `edge-sensor-summon-tests.py`：PASS（2657 项 runtime edge checks）
- `interpolation-readout-tests.py`：PASS
- `workflow-audit.py`：1 个 workflow 过 25 条规则
- `enhancement-report-tests.py`：PASS
- 重锚定的 16 项 mutation：16/16 CAUGHT
- `git diff --check`：干净

## 四、尚未完成 / 未验证

- 全套 battery（144 项，含未改动的 128 项）尚未在提交树上跑完一轮：单轮约
  30 分钟，放在提交后的干净 clone 里执行，结论回填本节。
- ubuntu 侧只能证明"没有 missed"；那 4 个 clang 门禁的 mutation 在 CI 上会
  显示为 UNPROVED，其真实证明由 macOS 矩阵承担。
- 侧边栏实机验收矩阵仍未回填（见 edge-sidebar-final 文档），本轮改动不改变
  其状态。锁屏/用户在场与否仍需现场确认。
