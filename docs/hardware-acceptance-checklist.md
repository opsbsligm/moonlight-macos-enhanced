# 真机验收操作单（Wave I）

这份文件把人要做的动作和 `scripts/hardware-acceptance-check.py` 的判据一一对起来。
判读规则的唯一来源是报告末尾的 `machine` 区块，键名契约见
[`goal-mode-prompt.md`](goal-mode-prompt.md) §4.1；这份文件只回答"做哪一步能让某一行变成
PASS"，不替代契约本身。

## 0. 一轮验收的固定三步

```bash
# 1) 串流中从 app 内导出诊断报告，保存为 report.txt
python3 scripts/hardware-acceptance-check.py report.txt --emit-declaration > decl.json
# 2) 编辑 decl.json：把 observed 改成 true，note 写你在主机侧真实看到的现象
python3 scripts/hardware-acceptance-check.py report.txt --declare decl.json
```

`decl.json` 里的 `report_sha256` 绑定具体那份报告：换一份报告，全部声明立刻失效，所以
不能拿上一轮的声明给这一轮盖章。七行全 PASS 时输出尾部打印 `hardware_validated=true`，
否则 `false` 且退出码为 1。

七行之上还有一道**前提**，它不是一行、也没有地方打勾：报告必须说得出这些字节是哪个
commit 编出来的。`ml.build.git_commit` 不是完整 40 位十六进制（`unknown`、截断、大写、
混入非十六进制字符都算），或者 `ml.build.version` / `ml.build.number` 是 `unknown`，
那么整张矩阵一律 `UNKNOWN`，观测者声明绑得再准也没用——因为"build 2050"只是某条分支上
第 2050 个提交的计数，两条分支会数到同一个数字，它带不动一句关于源码树的结论。

报告里读不到的键一律是 `unknown` 或 `present=no`。**缺失键和值为 0 是两件事**，判读脚本
不会替任何一项编造默认值；把键删掉也不会让那一行变成通过（自测里有一条专门盯这个）。

## 1. 七行的判据

| 行 | 要做的动作 | 报告里必须出现 | 期望值 |
| --- | --- | --- | --- |
| 4.1 `controllers-two-pads` | 开流后接入两只手柄 | `ml.controllers.present` / `.arrivals` / `.group_count_is_physical_devices` / `ml.controllers.slot.<N>` | `yes` / `yes` / `no` / 至少两行槽位 |
| 4.2 `host-side-controller-behaviour` | 在主机侧看手柄类型、按键图标、震动 | `ml.controllers.arrivals` / `ml.controllers.slot.<N>` / `ml.controllers.caps.rumble` | `yes` / 每行都是 `xbox`\|`ps`\|`nintendo` / `yes` |
| 4.3 `keyboard-unicode` | 主机端输入法实测中文 + emoji + 全角 + 长按重复 | `ml.video.present`、`ml.video.frames.received` | `yes`、> 0（汉字是否上屏由声明记录） |
| 4.4 `edge-sidebar-params` | 把六个手感参数各拖动一次再导出 | 六个参数的 `{effective,shipped,range,written,state}` 共 30 键 | 至少一个 `state` 为 `override_of_*` 或 `clamped_*` |
| 4.5 `local-ime-composition` | 打开该主机的 `imeLocalComposition` 后切中文输入法 | `ml.switch.imeLocalComposition` | `on` |
| 4.6 `secure-attention-sequence` | 用预置规则或直发三键，看主机 SAS 是否拉起 | `ml.video.present`、`ml.video.frames.received` | `yes`、> 0（SAS 是否弹屏由声明记录） |
| 4.7 `desktop-suite` | 桌面档开绝对鼠标；制造一次断网重连；开两个失焦行为 | `ml.pointer.absolute` / `ml.reconnect.present` / `ml.reconnect.attempt` / `ml.switch.muteOnFocusLoss` / `ml.switch.backgroundGamepad` | `yes` / `yes` / ≥1 / `on` / `on` |

一行要 PASS 需要两半同时成立：**报告证明该设置这局真的生效**，**观测者绑定这份报告声明
看到了对应行为**。只有报告、或只有声明，都只会得到 `UNKNOWN`。

## 2. 行与行之间容易踩的坑

- 4.1 数的是**主机被告知的玩家槽**，不是 `ml.controllers.group_count`。同型号两只手柄在
  group 那一层会合成一行，所以契约专门要求 `group_count_is_physical_devices=no` 在场；
  若出现两组身份却只有一个槽位，这一行直接判不通过，而不是"看起来还行"。
- 4.2 只通告真正实现的能力。`ml.controllers.caps.*` 缺 `rumble` 说明震动能力从未通告给
  主机，此时主机侧"有震动"不能记在本局账上。
- 4.4 六项全在出厂默认值上，只能证明默认值没被升级改掉，**不能**证明滑块起作用；判读
  要求至少一项离开默认值。
- 4.3 与 4.6 属于"报告只能证明会话存在"的两行：`ml.video.present=no` 或
  `frames.received=0` 时，任何主机侧说法都不给 PASS。
- 4.7 是一行里的四件事，任一没做整行不通过。绝对鼠标需要桌面档 + 开关同时开，
  `ml.pointer.path` 会以 `(absolute)` 结尾。

## 3. 验收完成后

把 `report.txt`、`decl.json` 和判读输出一起放进本轮 evidence 目录，并在收尾记录里写明
`hardware_validated` 的实际取值。七行没有全 PASS 之前，roadmap 上的行仍标
`hardware_validated=false`；单行通过就在收尾记录里点名是哪一行、绑定哪个 `report_sha256`。
