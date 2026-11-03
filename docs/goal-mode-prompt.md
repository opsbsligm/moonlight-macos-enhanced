# Moonlight macOS Enhanced — 目标模式提示词（2026-11-04 二十一次基点刷新：Wave AJ 收尾批）

## 0. Wave AJ 目标模式（当前执行窗口，2026-11-04）

> 本节是本轮唯一执行契约。Wave AI 已收口（MR 56，head `c4d8a95c`，合并提交
> `dd21f09d`，合并者 `liguangming`，`merged_at=2026-11-03T17:46:32Z`）。本波
> 只收尾巴，不开新能力。

**标的**：五处未收口——(a) MR 56 合并触发的 main pipeline **#1157**（`dd21f09d`）
终态未落；(b) GitHub 镜像 main 停在 `1efe4a37`（pipeline 1128 的 `publish-github`），
等 #1157 的 publish 才会推进到 `dd21f09d`；(c) 分支卫生欠账：远端 21 个已合入
源分支 + 悬分支 `update/round77-readme-audit`（其 MR 已不存在，Wave AH §0 已裁定
"已被取代"）未删，本地已合入分支 `wave-ai-doc-refresh` 未删；(d) §1 基点停在
`1efe4a37`，MR 56 未刷新；(e) 本机 build2097 用户启动确认 + 真机验收矩阵
（用户项，不阻塞代码侧）。

**完成边界（四条全绿才算完成，第五条是用户项）**：
1. **#1157 终态 success**：16 job 全绿；读 `publish-github` job 输出 JSON 的
   `result` 字段确认不是 `superseded`，主机侧 `6.last-success.json` 回读
   `pushed=true`、`pipeline_id=1157`、`updated_refs` 含 `refs/heads/main`、
   `full_source_equal=true`；镜像 main SHA = `dd21f09d35`。
2. **分支卫生**：远端删除上述 22 个分支后 `git ls-remote --heads` 只剩 `main`
   （删除前每个分支都过 `git merge-base --is-ancestor` 确认已含入 main；
   `update/round77-readme-audit` 按 Wave AH §0 第 2 条的裁定删除，不另立 MR）。
   本地 `git branch -d wave-ai-doc-refresh`（ancestor 检查保安全）；
   `docs-goal-mode-refresh-b65db5fb` 未合入，保留不删。
3. **§1 基点刷新**：基点更新到 `dd21f09d35`（MR 56 合并记录 + #1157 终态 +
   镜像回读证据），`docs/gitlab-ci.md` 若因 #1157 出现新的 battery COST 实测值
   且与既有 200min 上限叙述冲突则同步；否则不动。
4. **`hardware_validated=false` 保留**：本波 docs-only，不触碰
   `.m`/`.swift`/`.h`；不动任何设置默认值；不解冻冻结项
   （USB 真重定向 / Developer ID 公证 / 自动更新）。

**不做**：不收 build2097 用户确认（用户项）；不跑完整 assertion battery
（`--all`）；不把 #1157 的 `allow_failure` job 状态当绿色，点名豁免项；
不替用户裁定 `docs-goal-mode-refresh-b65db5fb` 的去留。

**审批执行细则（沿用 Wave AH）**：开发用 `pat`（codex），审查与合并用
`review-pat`（user id=1 liguangming）；批准绑定精确 head SHA；合并后回读
MR state、merged_by、目标分支新 SHA 与合并 pipeline 终态。

---

## 0. Wave AH 目标模式（当前执行窗口，2026-11-03）

> 本节是本轮唯一执行契约。Wave AE 已收口（MR 53 → merge `c0b74bc2`，合并者
> `liguangming`，main pipeline #1090 16/16 success，battery job 7281 实测
> 8893s / 153/153 / 336 免证）；其目标模式顺延到 §0 之后的旧节，保留供追溯。

**标的**：五处未收口，全部是"做完的尾巴"而非新能力——超时上限还停在投影值、
README 债务分支悬着、合并后的源分支与本地 38 个陈旧分支没清、CHANGELOG 欠
Wave Z-3 之后的批次账、可装产物停在 build2097。本波不收新功能、不动设置面板
任何默认值、不解冻任何冻结项。

**完成边界（五条全绿才算完成）**：
1. **AG-2 上限落地**：`wave-ag-battery-ceiling-200`（head `9b3ea1c6`）经 MR 54
   走 liguangming 审批合并；本次 SHA 的 pipeline 全绿（`mutation-battery` 不出现
   于该 ref 的 pipeline 属规则使然，不视为缺口）。合并后远端源分支删除。
2. **README 债务裁定**：`update/round77-readme-audit`（`38c96e1d`，10-18 旧工作，
   author opsbsligm）逐文件对照 main 后裁定：README/README.en 重写已含入 main
   更晚版本；`liquid-glass-audit.py` 的两条 segmented 规则已被 main 上更新的
   `native_segments` 判定覆盖（main 版本是它的演进形态，不是缺失）；其余 183 文件
   diff 是 main 向前推进的方向。裁定 = 已被取代，close 不合并，远端分支删除。
   裁定证据写进本节，不另开文档。
3. **分支卫生**：远端 `wave-ae-battery-meta-trim` 删除（已含入 main，head
   `fc7bf2fe` ancestor of main 已验证）；本地 `git branch -d` 只删已合入项，
   未合入的本地分支一律保留不删（`git branch -d` 的 ancestor 检查保证安全）。
4. **CHANGELOG 补账**：`[Unreleased]` 补 Wave Z-3 / AC / AD / AE 四条门禁条目
   （AA 与 AB 此前已有条目；每条写清做了什么、门控名、判据来源），放在既有
   `### Added` 小节内；不重写既有 155 条历史。
5. **文档与产物收尾**：§1 基点更新到 Wave AH 合并后的 main SHA；`docs/gitlab-ci.md`
   的 battery 上限说明随 200min 同步；本机 build2097 待用户启动确认无回归
   （用户项，不阻塞代码侧）；`hardware_validated=false` 继续保留。

**审批执行细则（本波新增，后续波次沿用）**：开发用 `pat`（codex），审查与合并
用 `review-pat`（已核验 user id=1 liguangming，2026-11-03）。批准必须绑定精确
head SHA；合并后回读 MR state、merged_by、目标分支新 SHA 与合并 pipeline 终态。
不再走 Rails 建临时 token（那次方案已被本次的常驻 review-pat 取代）。

**不做**：不动 `342b106` 上游回吸（等真机窗口）；不触发完整 battery 再测
（8893s 的 COST 行就是本波上限的来源）；不合并任何 settings 默认值改动；
不替用户点 build2097 的"确认无回归"。

---

## 0. Wave AE 目标模式（当前执行窗口，2026-11-03）

> 本节是本轮唯一执行契约。Wave AC 与 Wave AD 已随 MR 52 一起收口（head
> `8b7f6b46`，合并提交 `18921771`，`merged_at=2026-11-02T18:59:45.861Z`，合并者
> `liguangming`），其目标模式与展开证据见 §0.AC 与 §0.AD；Wave AB 见 §0.AB。

**标的（2026-11-03 实测重述）**：电池共 153 条变异，其中 107 条经聚合审计
`constraints-audit.py`（77 条走默认 gate、30 条显式命名，按 `MUTATIONS` 表逐条载入
核对）。聚合每次都跑四个自证门控，而它们的判定形态（读树那一半）本来就在同一进程
里读完了同一棵树。CI 未优化基线（pipeline 1075 job 7141，正在跑的 main）实测
**56 条聚合用例均值 157.4s**，跑到 147.4min 时完成 89/153，投影 315min，
超 180min 上限——所以这个作业不是"再等等就能过"，是结构上跑不完；
该 run 已在 147min 处取消（它给不出总耗时，只给得出散落的 TIME 行）。

**净收益按快照逐条算，不折算**：四门控快照秒数合计 88.5s
（defaults 38.2 + presentation 30.9 + interrupt 15.1 + hardware 4.3）。对 107 条
聚合用例逐条判定可得档位分布 `{19.4s: 6, 42.5s: 1, 50.3s: 73, 57.6s: 1, 88.5s: 26}`，
均值 **57.8s/条**——不是每条都省满 88.5s，defaults 门控 `os.walk(Limelight)`
使 23 条 HIDSupport.m 变异只能省一部分。由此得两个投影：**178min**（省的秒数按
绝对秒计）与 **124min**（争用按比例放大工作量），夹住 180min 上限，
算术无法裁决——所以本波把 job 的 timeout 一次性抬到 240min 换真实数字，
作业自己打印 `COST` 行（总耗时 + 聚合/轻用例两个均值 + 免证次数），
下一提交按实测回落，而不是按投影许愿。

**本机绝对耗时不可作为依据（本轮踩到）**：这台 Mac 就是 `macos` runner 本体，
电池在跑时同机测速必然被污染——一次 `constraints-audit.py` 挂 34min 墙钟、
只用 1.8s CPU，阻塞在 `dmg-audit.py --self-test` 派生的 `hdiutil create` 上。
因此本节凡是"省了多少秒"的结论只取快照与变异表的算术，凡"总共跑多久"
只取作业自己的 `COST` 行；旧的"本机 103.1s / 106.4s / 20.6s"三个数字
是本机与 runner 争用时的读数，只能当量级参考。

**设计原则**：跳过不等于删除，判定形态永不受影响；无标记（push / MR /
`local-gates.sh`）时一项都不跳。读取面不再手写，由 `battery-scope-probe.py`
用 `open` + `os.walk` + `subprocess.Popen` 三个 audit hook 实测生成快照
`battery-self-proof-scope.json`——手写清单实测漏掉 222 个读取路径（defaults
门控实际 `os.walk(Limelight)` 遍历整棵树），漏记即静默消音，是危险方向。
探针在 Mac 上跑（GitLab `audit:python` + GitHub `analyze` 双端各一行），因为
两个门控要编译 harness，无 Apple 工具链时读取面会缩到近乎为空。

**完成边界（全绿才算完成）**：
1. 探针双端各跑一次且 `0 problem(s)`：快照必须覆盖实测读取面（窄=失败），
   并拒绝快照命名仓库里不存在的文件（`scope.missing_subjects()` 已接线，
   2026-11-03 前它无任何调用方＝空头承诺）。
2. 范围匹配时自证仍然执行：越界文件跳全部四项，落在 defaults 读取面内的文件
   必须仍然跑 defaults 自证（按快照档位可判：19.4s 档只跳 hardware+presentation
   +interrupt，省不掉 38.2s 那一项）。
3. 本地 `local-gates.sh` 0 failures（裸跑不跳任何门控）。
4. 本次 SHA 的 GitLab 流水线全绿，`mutation-battery` 在 240min 内跑完，
   且作业打印的 `COST` 行给出总耗时与免证次数；拿到该数字后把 timeout
   回落到实测值 + 一条收尾记录。硬件验证保持 false。
5. `COST` 行必须在**被杀掉的运行**里也存在：作业超时是 SIGTERM，处理器
   恢复工作树后以默认处置自杀，`atexit` 与循环后的摘要都不会执行——
   只在摘要里打印的总耗时，恰恰是撞上限那次拿不到的那个。
   `scripts/battery-cost-report-tests.py` 把真实 `restore_pending` 与
   `restore_and_return` 注入子进程，弄脏文件后发 SIGTERM，同时要求
   工作树复原**且**子进程 stdout 里出现总耗时；反向变异删掉恢复路径里
   的 `if report: report_cost()` 后，子进程安静死去并被本门控拒绝。

**已验证事实（2026-11-03）**：
- 探针 4 门控全部 `0 uncovered read(s)`，`battery scope probe: 0 problem(s)`；
  它打印的"每次聚合调用免掉约 83s"是**本机实时读数**（本轮 15/35/29/3s），
  档位算术一律取已提交快照的 15.1+38.2+30.9+4.3=**88.5s**，两者差值是
  本机争用，不作依据
- 反向证明：把 hardware 快照清空 → 探针 FAIL 1 处；清空 defaults 的 dirs →
  FAIL 222 处未声明读取；还原后 0 problems
- `missing_subjects()` 双向有效：注入不存在路径 → 报 2 条；真实快照 → 空
- `battery-cost-report-tests.py`：正向 1 项 ok，self-test 2 项 ok；
  `gate-coverage-audit.py` 收录该门控（列 source-of-truth only），
  `ci/test_pipeline.py` 18 tests OK
- `local-gates.sh`：**126 passed / 0 failed / 16 skipped**（跳过项均为需构建产物、
  需 Debug/CI 制品、完整电池 `--all`，或 render-probe 自建 Debug 二进制，
  与本轮改动无关）
- CI 未优化基线：job 7141 在 147.4min 完成 89/153，聚合 56 条均值 157.4s，
  153 条投影 **280～315min**（视剩余用例轻重）
- 免证这句话只有一个来源：`battery_scope.EXCUSED_LINE`，四处 print 与
  电池计数共用它，计数不会与输出各自漂移

---

## 0.AC Wave AC 目标模式（已完成并合并：MR 52 → head `8b7f6b46` / merge `18921771`，合并者 `liguangming`；保留供追溯）

> Wave AC 已随 MR 52 收口，本节保留完整证据供追溯。Wave AB 已收口（MR 51 →
> `60ddce2c`，合并者 `liguangming`，head pipeline #1051 success），见 §0.AB。

**标的**：渲染探针把**"从未测到"**报成**"测得一片平坦"**，而它判读器自己的 `--self-test`
形态从来不在任何管道定义里 —— 于是一句描述 CI 环境故障的红色被读成应用渲染回归，
且这条判读视觉主张的门（51 条变异）自身的可失败性从未被任何管道或本地扫描跑过。

**已验证事实（本机实测与 CI 日志，非估计）**：
- `MLProbeCaptureView`（`Limelight/macOS/AppDelegateForAppKit.m:70`）在两种情况下返回
  `nil`：SCShareableContent 列表里找不到自己的窗口，或 `captureImageWithFilter` 回不到图像。
  `MLProbePixels`（同文件 `:139`）拿到 `nil` rep 走的是空采样路径，返回
  `mean/stddev/distinctColours/sampled` **全 0** —— 与"页面真的画成一片纯色"在报告里不可区分。
- 判读侧因此说谎两次：`scripts/render-probe.py:296` 只看 `stddev >= 0.02`，报
  "the page drew no variation at all"；ObjC 侧 `:1885` 同一条规则报
  "the settings page rendered as flat"。两句都断言了页面**被看过**并且平坦。
- 探针其实**知道**自己没拿到画面：CI job 6840 的 trace 里有 7 行
  `[render-probe] own window capture failed: 音频/视频捕捉失败，无法开始流播放`。
  这句话只进 stderr，报告字段不携带，判读器只能从 0 反推。
- A/B 实测见 `moonlight-ci-evidence/20261102-audit-deep-display-ab/`：
  显示器熄灭 `sampled:0 / stddev:0 / failures:["...rendered as flat..."]`；
  显示器常亮 `sampled:85878 / stddev:0.0730 / 275 colours / failures:[]`。
  第三份 `report-display-race.json` 才是决定性的一条：同一轮里 `initialPixels` 正常
  （`sampled:1517`、`stddev:0.353`）而 `settingsPagePixels` 全 0 —— 这是**逐次捕获的
  暂时性通道故障**，"整机熄屏"解释不了它，所以重试与"环境"话术都得按逐次通道来写。
- 判读器的 `--self-test` 本机实测 **0.12–0.16 秒**（51 条变异 + 2 个良性通过点，
  其中 3 条是本波新增的"红色话说对了"话术断言），
  但 `scripts/gate-coverage-audit.py:96` 把 `render-probe.py` 登记为 `class=deep` 且**没有**
  `self_test` 字段，于是 `--emit-commands --class=deep` 只发射需要 20 分钟构建的全形态；
  `scripts/local-gates.sh:426` 又把任何含 `render-probe` 的命令一律 skip。两条路径合起来：
  这个门从未在事实源管道、merge-request 管道或本地扫描里跑过它的判定形态。
- **同一类谎言的第二处，且更彻底**（执行中发现，不在最初的七条边界内）：
  `MLProbeBlockAnalysis`（同文件 `:247`）的遍历范围来自视图 bounds 而不是图像，
  所以拿到 `nil` 图像时它照样走完每一块，而 `[nil redComponent]` 返回 0。
  `report-display-off.json` 里因此写着 `behindPageBlocks: {blocks: 1305, flat: 1305,
  meanBlockStddev: 0}`、`backdropBlocksBeforePresent` 同样是 `blocks: 1305, flat: 1305` ——
  这不是"采了 0 个点"，而是**把一页从未捕获的像素逐块数完并判定整页平坦**，
  比 `sampled: 0` 更像一次真测量。`MLProbeTranslucentRegions`（`:291`）同时把
  `consideredBlocks: 0` 配上 `readThroughPageWhere: "no block changed ... (expected while
  the page base is opaque)"` —— 把一个没发生的比较写成一条已验证的设计结论。
  判读侧不消费这三块（只 `print` 那句 `readThroughPageWhere`），所以修在探针侧即可，
  不需要判读器同步；这也是它一直没被发现的原因。

**完成边界（七条全绿才算完成，缺一不算）**：
1. **没测到就不给数值**：捕获不可用时，像素测量不携带 `mean/stddev/distinctColours`，
   改为携带捕获失败的原始句子；`sampled` 一类的"我采了 0 个点"不得伪装成测量结果。
   同一规则覆盖分块统计与读透比较（执行中发现的第二处）：`blocks/flat/meanBlockStddev`
   与 `changedBlocks/consideredBlocks` 在未捕获时一律不出现，那句"expected while the page
   base is opaque"的设计结论也不得在未测量时给出。
2. **判读器分得开两种红色**：未测量 → 说"捕获通道不可用"并附探针给的那句话；
   真的平坦 → 保留现有的渲染回归话术。把未测量重新读成平坦的变异必须被 self-test 拒绝。
3. **阈值一分不放松**：真机亮屏那组数字（0.0730 / 275 colours，以及历史上更紧的
   0.0702 / 53）必须继续通过；`0.001/2` 与 `0.012/44` 两个 fixture 必须继续被拒。
   0.02 与 40 的下限不因本波改动。
4. **判定形态进事实源**：`render-probe.py` 在 registry 里登记为 selftest 类并给出
   `self_test` 与 `full_form`，`--emit-commands --class=selftest` 发射它，
   `local-gates.sh` 不再把它一律 skip（0.12 秒，快速扫描就该跑）。
5. **三方一致**：`.gitlab-ci.yml`、镜像 workflow、registry 三者对同一个门不再互相矛盾，
   `gate-coverage-audit.py --verify` 绿，deep 类仍只发射全形态给 tag/main。
6. **探针侧与判读侧同步**：ObjC 那条 `stddev/distinct` 断言在未测量时不得再说
   "rendered as flat"，它必须说没拿到画面 —— 两处话术不一致就是下一次误判的起点。
7. **真机基线复现**：本机用盘上已有的 Debug 产物跑一次全形态，拿到 `sampled > 0`
   且判定为绿，作为"阈值没被放松"的实证；同时把捕获失败形态跑一次，确认红色话说对了。

**本波明确不做**：不改任何设置面板默认值，不动 `NSSegmentedControl role=.tabs`；
不解冻 USB 真重定向/Developer ID 公证/自动更新；不为让 `audit:deep` 转绿而放宽阈值、
把"未测量"算作通过，或给探针加删除/植入数据的开关（该探针读写真实 store，
见本文件顶部说明）；`hardware_validated` 保持 `false` —— 本波让红色**说实话**，
不宣称真机验收通过。

**已知非本波红色（如实记录，不计入通过）**：`audit:deep` 在显示器熄灭的槽位上仍会是红的，
这是环境事实而非应用回归；本波的产出是让它在日志里说"捕获通道不可用 + 探针原话"，
而不是让人去 diff 一个从没改过 `.m`/`.swift` 的提交。承接方是本机 Mac runner
（launchd `com.user.gitlab-runner`，实例 id 8）。

---

## 0.AD Wave AD 目标模式（已完成并合并：MR 52 → head `8b7f6b46` / merge `18921771`；保留供追溯）

> Wave AD 的目标：让"文件不在盘上"这个事实从报告里被诚实记录，而不是被生产者和判读器各说各话，更不要让读者被引向一个不存在的文件。
> 与 Wave AC 的关联：AC 只修了"从未测到"的话术，但没有修"测到了但没落盘"的话术，也没有让三处文件名调用共用同一判据。

**标的**：渲染探针在两种情况下不声称文件名——捕获通道拒绝（Wave AC 已修）和编码器/卷拒绝写入（Wave AD 新增）。任何调用者都不再单独判断 `rep != nil`，统一用 `MLProbePixelsHaveArtefact()`。判读器 `verify_panes` 把"未测量"、"测了未落盘"、"沉默（两个问题都不答）"、"自相矛盾"四种新故障各说各话。

**已完成（门禁验证，非估计）**：
- ObjC 生产者 `MLProbePixels()` 现在先采样、后写盘，写盘失败记 `captureWriteFailure`；`MLProbePixelsHaveArtefact()` 作为唯一入口供三处 `initialCapture`/`scrolledCapture`/`capture` 使用。
- 判读器 `artefact_absence()` 返回 `(类别, 原句)`，`verify_panes` 根据类别各说各话：`no-capture` → "never captured to disk"；`no-artefact` → "artefact was never written, so its numbers cannot be reopened"；沉默 → "cannot say whether the pane was ever drawn"。
- self-test 从 45 条增至 51 条，含 6 条新断言（写盘失败话术、沉默话术、自相矛盾话术、测了不给文件名话术、无 capture 也不无故障话术、有 measurements 但无文件名话术）。
- 变异测试证明 3 场人为删改全部被拦截：`no-capture` 分支摘掉后拒绝写盘失败；两种故障合并后话术混淆；沉默 pane 被放过。还原后 0 failures。
- `gate-coverage-audit.py` 登记更新：45 → 51 条变异。
- `scripts/render-probe.py --self-test` 实测 0.05–0.08 秒（51 条变异 + 2 个良性通过点）。

**未完成边界**：
- `hardware_validated=false`：没有编译或运行产物验证过。
- `artefact_absent_reason`/`artefact_absence` 在判读器里只读 JSON 字段，未经任何 CI 管道验证——需要 pipeline 跑过 `render-probe.py --self-test` 才算 CI 闭环。
- 旧二进制（wave AC build）仍包含 AC 的旧逻辑（未落盘时只报 `captureFailure`，没有 `captureWriteFailure` 字段）；新二进制需要 build 验证 `MLProbePixelsHaveArtefact()` 三处调用全部走同一判断。
- 三处调用点之外，`MLProbePixels` 在 `:1812`/`:1912`/`:1955` 还有额外调用，但它们不写文件名到报告里（只读像素数据），不受本波影响——需要确认没有新调用点遗漏。

**门**：
1. ObjC 编译通过（Release build）
2. `render-probe.py --self-test` 0 failures
3. CI pipeline 包含 `render-probe.py --self-test` 且 pass
4. `gate-coverage-audit.py --self-test --verify` 全绿

## 0.AB Wave AB 目标模式（已完成并合并：MR 51 → `60ddce2c`，合并者 `liguangming`；保留供追溯）

> Wave AA 已收口（MR 50 → `d16497a4`，合并者 `liguangming`，
> `merged_at=2026-11-02T05:27:39Z`），其目标模式见 §0.A。

**标的**：设置字典 → `StreamConfiguration` 对象**这一跳**从来没有任何审计看过，
于是"面板有开关、持久化有键、导出字典有行、渲染器也真按它动作"四项全齐的字段，
仍然可以永远读作零值。

**已验证事实（本机实测，非估计）**：
- `shortQueueOnDoubledCadence` 就是这一形状：`StreamConfiguration.h:90` 声明、
  `SettingsVideoPane.swift:580` 有开关、`SettingsObjCBridge.swift:283` 导出该键、
  `VideoDecoderRenderer.m:3028` 读取它并在 3146 按它少排一帧——
  而 `StreamViewController.m` 的装配区**没有**赋值行，ObjC 零初始化使它恒为 `NO`。
- 上一波的 `settings-usage-audit.py` 抓不到它，而且**不是缺陷**：该审计问"有没有人动作"，
  渲染器确实动作了。断链在下一跳。补上装配行后该审计立即由绿转红
  （`STALE shortQueueOnDoubledCadence`），这是它设计上的诚实反应，必须随之
  退场账本条目并把钉死判据改钉 `consumed`——删除钉死项是错的，那会让装配行
  再次丢失时无人报警。

**完成边界（六条全绿才算完成，缺一不算）**：
1. **判定来自源码文本**：对头文件声明的每个属性回答"有没有人赋值"，
   当前 68/68 已装配、债务账 `stream-config-assembly-baseline.json` 为空。
2. **接收者身份**：只认树里声明为 `StreamConfiguration *` 的标识符。
   `Connection.m` 的 `_streamConfig` 是同名 C 结构体成员，算作写入就会让真空缺永久藏住；
   `SCStreamConfiguration`（ScreenCaptureKit）靠词边界排除，不靠运气。
3. **三类假信号必须被拒**：`==` 比较不算写入；注释里的点号路径不算；
   日志格式串里的 `streamConfig.width` 不算。这三条都是第一版真踩过的坑。
4. **self-test 五个变异各只移动它该移动的判据**（装配行删除、写错对象、
   比较当写入、注释吃掉装配行、未使用字段误判为已读），另加头文件重命名的
   负对照与三条钉死判据；良性基线必须同时成立。
5. **接缝在事实源**：`.gitlab-ci.yml` 与镜像 workflow 各含判定 + self-test 两形态，
   `constraints-audit.py` 内跑判定形态（实测 0.4s；self-test 2.6s，
   电池 153 条变异中 107 条以本聚合为判读门，故 self-test 不入聚合），
   `local-gates.sh` 并集发现到 135 条命令，`gate-coverage-audit` 报 41/95/95。
6. **本次改动自身的红色必须清零**：装配行补上后，`settings-usage-audit.py`
   裸审计与 self-test 两形态同时转绿，`constraints-audit.py --no-battery` 0 failures。

**本波明确不做**：不改任何 `.swift`/`.m` 的运行时行为，除那一行装配；
不改设置面板默认值与 `NSSegmentedControl role=.tabs` 外观；不解冻 USB 真重定向/
公证/自动更新；`hardware_validated` 保持 `false`——装配行让开关**能够**生效，
"拨动它真的改变画面"仍需真机取证。

**已知非本波红色（如实记录，不计入通过）**：`audit:deep` 的 render-probe 在
`d16497a4`（main 自己的流水线 #1041，job 6840）报"设置页渲染为平面：stddev 0.000，
0 distinct colours"、多个 pane 截图缺失；本机 `leak-audit --growth` 同症状。
已核对 `e2334917`（上一次 `audit:deep` 绿）到 `d16497a4` 之间**没有任何 `.m`/`.swift`/`.h`
改动**，全部是脚本与文档，故这不是应用回归；`c73596cc` 只是把原本的 `TypeError` 崩溃
改成说得清的一句话。承接方是本机 Mac runner（launchd `com.user.gitlab-runner`，实例 id 8），
属 CI 环境故障，须单独修，不得为使其转绿而放松判据。

---

## 0.A Wave AA 目标模式（已完成并合并：MR 50 → `d16497a4`，合并者 `liguangming`；保留供追溯）

> 本节是本轮唯一执行契约。Wave Z-3 已收口（MR 49 → `9e914350`，合并者 `liguangming`，
> head pipeline #1010 success），其目标模式见 §0.0。这一波的标的不是又一处客户端缺陷，
> 而是**验收的另外一半从来没有人看过**：`hardware-acceptance-check.py` 判的是"报告与观测者
> 声明是否同意同一场会话"，两半都出自本仓，主机从没被问过。

**目标**：让"客户端通告了某种手柄，而主机根本模拟不了"成为**门禁级可见事实**，
判定依据必须是主机自己的话，不是本仓的推断。

**为什么这一波值得做**：通告与主机能力不符时，本仓一切指标都是绿的——手柄出现、按键有响应、
诊断报告与声明一致。玩家要等到游戏问起一个主机从没模拟的功能（DS5 的陀螺仪、触摸板）才发现
问题。这与 Wave S 修掉的 P1 是同一形状：生产者与消费者从未相连，只是那一次连的是本仓两侧，
这一次要连的是**网络对面的另一台机器**。

**已量化事实（2026-11-02 WinRM 实采 `192.0.2.1`，非估计）**：
- 主机是 Sunshine `v2026.925.152547.杂鱼`（版本串含非 ASCII，采集器必须原样保存，
  转码即丢失真机身份）；ViGEmBus `Running`（`ViGEmBus.sys`）→ Xbox 360 仿真可用。
- `gamepads.ds5_manifest = true` 而 `ds5_sidecar_installed = false`；主机日志原话：
  `Warning: Gamepad ds5 is disabled due to gamepads.ds5-sidecar-not-available`，
  switch 一路同理 `motion-server-not-available`。**清单在而载荷不在，不算已安装。**
- 客户端报告里 slot 0 通告 `ps`，与主机自己的拒绝直接冲突 →
  `advertised-versus-host = BLOCKED`。

**完成边界（五条全绿才算完成，缺一不算）**：
1. **判定来自主机快照**：五个结论（`host-identity` / `xbox-360-emulation` /
   `ds5-emulation` / `switch-emulation` / `advertised-versus-host`）全部从实采快照与
   原始 WinRM 转写派生；无快照时不产出能力结论（silent pass 即缺陷）。
2. **时序诚实**：启用戳早于拒绝戳不为永久否决，拒绝戳早于启用戳才说明主机后来改了主意；
   两者顺序颠倒必须转红。
3. **主机的拒绝压过客户端的宣称**：载荷已装但主机日志仍在拒绝，仍判 BLOCKED。
4. **self-test 覆盖八类削弱**，每一类由其归属检查转红（缺主机版本、无 ViGEmBus、
   WinRM 运行失败、清单缺载荷、启用戳早于拒绝、拒绝戳早于启用、"改主意"两份快照仅差在
   哪个文件上取戳、采集器转码主机版本）；良性基线必须同时成立，否则变异是被"全红"而非"被抓住"。
5. **接缝在事实源，且不为门禁拖垮流水线**：判定形态 + self-test 形态进
   `.gitlab-ci.yml` 与镜像 workflow，本地聚合跑判定形态；`gate-coverage-audit` 证明两处都在。
   本地聚合是变异电池的默认判读门（#1006 trace 实测：120 个变异中 81 个由它判读，每次
   130–180 秒），故 6.3s 的 self-test 形态**不**入聚合——换算代价是 +8.5 分钟，
   而那个 job 已经用满过 3 小时上限。只留 0.04s 的判定形态；这条取舍是实测决定的，不是偏好。

**本波明确不做**：不改任何 `.swift`/`.m` 运行时行为，不改设置面板默认值与
`NSSegmentedControl role=.tabs` 外观，不解冻 USB 真重定向/公证/自动更新，
**不安装 DS5 sidecar / motion server**（那是主机侧变更，须 owner 决定），
`hardware_validated` 保持 `false`——本节记的是主机状态的证据，不是真机验收通过。

**完成边界自证（2026-11-02 实测，逐条对应上节五条）**：
1. 判定来自主机快照：`--snapshot scripts/fixtures/home-pc-host-snapshot.json --report
   scripts/fixtures/home-pc-claim-report.txt` 产出五行结论，与 `--expect` 钉死的
   `OK/OK/BLOCKED/BLOCKED/BLOCKED` 逐项相符，exit 0；`--parse-capture` 用原始 WinRM
   转写重解析，除主机版本一字段外与快照逐字段相同（该字段正是变异 (h) 的标的）。
2. 时序诚实：`enablement-older-than-refusal` 与 `refusal-older-than-enablement` 两个
   快照只在"戳取自哪个文件"上不同，各自转红自己该转红的一路。
3. 拒绝压过宣称：`installed-payload-still-judged-on-host-words` 证明 sidecar 已装
   而主机日志仍拒绝时，结论仍是 BLOCKED。
4. `--self-test` 实测 **8 个变异全部由其归属检查转红 + 良性基线成立**，最后一行
   `self-test ok`；缺主机版本、无 ViGEmBus、WinRM 失败、清单缺载荷、两枚时间戳互序、
   "改主意"配对、转写可解析、转码丢版本各一条。
5. 接缝：`.gitlab-ci.yml` `audit:python`、镜像 `build.yml`（新增独立步骤）各含判定 +
   self-test 两形态；`constraints-audit.py` 内跑判定形态；`gate-coverage-audit.py` 报
   **source of truth 40 gates / mirror 94 gates / 94 reachable**、exit 0，不再出现
   `host-side-evidence-audit.py: source-of-truth only` 那条 note。

## 0.0 Wave Z 目标模式（已完成并合并：MR 49 → `9e914350`，合并者 `liguangming`，head pipeline #1010 success）

> 本节已收口。Wave Y/Z-1/Z-2 在其之前收口（§0.2）。这一波不在默认值尺子上，
> 而是那把尺子的结论**被误读**所掩盖的另一类缺陷：审计对一个键写
> `unread by the stream (one value exists, so no fork is possible)`，这句话本身
> 没错，于是"这个键查过了"就被当成了"这个键没问题"。它只证明了两层不会分叉，
> **没有证明有人在读它**。

**目标**：让"设置面板里有开关、写进了持久化、运行时零消费者"成为**门禁级红色**，
并把现存实例登记成带可证伪条件的债务，绝不允许它继续以"已审计通过"的形态存在。

**已量化事实（2026-11-01/02 逐键读源码实测，非估计）**：
- 探针从 `SettingsStore.swift` 读出 **119 个持久化键**，对每个键在
  `Limelight/` 全部 `.swift/.m/.h/.mm`（排除设置层自身）里找消费者。
  判定结果：**110 个有实际消费者，9 个登记为债务**
  （6 个 `unwired-control` + 3 个 `unreachable-field`）。
- 匹配必须用**前缀**而非 `\b`：ObjC 访问器是 `settings.keyFor:` 形状，
  `\bkey\b` 在 `relativeMouseAsAbsoluteFor:` 处失配，会把**有消费者**的键
  误报成死开关（本探针第一版就是这样误报了 `relativeMouseAsAbsolute`，
  其真实消费点在 `Limelight/Input/HIDSupport_Internal.h:886`）。
- 还必须先解析**导出字典键的改名**：`enable10BitSdr` → `sdr10bit`
  （消费点 `Limelight/Stream/Connection.m:2702`）、`enableMicrophone` → `microphone`
  （`Connection.m:2553`、`Network/HttpManager.m:519/604`）；按 Swift 字段名 grep
  会把这两个**有消费者**的键误判成死开关。
- `unlockMaxBitrate` 也不是死开关：它的消费点在 pane 内部
  （`SettingsModel+DerivedValues.swift:1408`、`SettingsModel.swift:577/600` 用
  `bitrateSteps(unlocked:)` 决定滑块档位），"运行时文件里没有"不等于"没有效果"。
- **逐键手工复核后坐实的实例只有两个半**：
  1. `captureSystemShortcuts`：UI 在 `SettingsInputPane.swift:503`，访问器
     `SettingsObjCBridge.swift:1631 captureSystemShortcuts(for:)` **全仓无调用者**
     （`git log -S "captureSystemShortcutsFor:" --all` 零命中，从未有过调用者）。
  2. `emulateGuide`：UI 在 `SettingsInputPane.swift:575`，**连 `@objc` 访问器都没有**；
     Guide 仿真实际在 `Limelight/Input/ControllerEventBaseline.m:19-20` 无条件启用
     （Start+Select → Guide），与该开关无关。
  3. （半个）`absoluteMouseMode`：既无 UI 绑定也无消费者，真实决策走
     `HIDShouldUseAbsolutePointerPath(...)`（`HIDSupport+Pointer.m:608/913`）；
     它是**死字段**而非死开关，与上两类的处置不同。

**为什么这一波值得做**：用户能拨动一个不生效的开关，比没有这个开关更糟——它是对
行为的错误承诺。这与"默认值两层一致"是同一个产品的两面：那一半管"显示的值是不是
生效的值"，这一半管"生效的东西有没有人显示"。

**完成边界（六条全绿才算完成，缺一不算）**：
1. **消费者判定基于符号解析，不基于键名 grep**：必须解析 `@objc` 访问器的 selector
   名（含 `@objc(...)` 显式改名）与其 `For:` 调用形状，必须解析导出字典的
   `"<dictKey>": settings.<swiftName>` 改名映射，两类都要能证明"改名字不会漏判"。
2. **pane 内部消费算消费**：判定域是整个 `Limelight/`，不是"设置层之外的运行时文件"。
   `unlockMaxBitrate` 必须是绿；把它判成死开关的门禁视为坏的。
3. **只登记，不改行为**：本波**不得**接任何新功能、**不得**删除任何 UI 开关、
   **不得**改任何默认值——那三者都是产品决策，须 owner 逐项批准（见 §5 与本节末）。
   交付物是"红线 + 债务账 + 每一项的现状说明"。
4. **self-test 含正/负对照至少四条**：(a) 负向：给某已接线键的访问器调用点删掉 →
   该键必须报未接线；(b) 正向：把访问器调用改写成另一等价形状 → 保持绿；
   (c) 负向：把字典导出改名 → 必须仍能追到消费者（证明改名映射在读，不是硬编码）；
   (d) 负向：pane 内绑定删除 → 该键不得因"无人绑定"而从账上消失。
5. **既有性质不回退**：`defaults-consistency.py --self-test` 现 35 项
   （其中 8 项负对照）全绿、`0 divergent`、`0 new / 0 stale`；
   `mute-on-focus-loss-tests.py`、`background-gamepad-tests.py`、
   `battery-interrupt-tests.py` 各 0 failures；`bash scripts/local-gates.sh` 0 failed
   （skip 逐项列名）。
6. **接缝在事实源**：新门禁同时进 `.gitlab-ci.yml`、镜像 workflow 与
   `constraints-audit.py`（本地门禁）三处，并由 `gate-coverage-audit` 证明三处都在；
   `liguangming` 对精确 SHA 审批合并后回读 MR 状态/合并者/main 新 SHA/流水线终态。
   `跨文件静态安全扫描` 在本环境 `allow_failure=true`，只记「已豁免」不计入通过。

**处置须 owner 决策（本波不动手，只登记）**：`captureSystemShortcuts` 是接上
（串流全屏时吞掉 Cmd-Tab 等系统快捷键）还是撤掉开关；`emulateGuide` 是让它真正
门控 `ControllerEventBaseline.m` 的 Guide 仿真还是撤掉；`absoluteMouseMode` 死字段
是删还是接到 `HIDShouldUseAbsolutePointerPath`。三者都可能改变用户可见行为。

**本波明确不做**：不改任何 `.swift`/`.m` 运行时行为，不改设置面板默认值与
`NSSegmentedControl role=.tabs` 外观，不解冻 USB 真重定向/公证/自动更新，
`hardware_validated` 保持 `false`。

**完成边界自证（2026-11-02 实测，逐条对应上节六条）**：
1. 判定用符号解析：`--json` 119 键中 `relativeMouseAsAbsolute`/`wheelScrollSpeed`/
   `enable10BitSdr`/`enableMicrophone` 全部 `consumed`（前两个靠 `For:` selector 形状
   与 `.h` 内联 helper，后两个靠导出字典改名映射），证明不是键名 grep。
2. pane 内部消费算消费：`unlockMaxBitrate` = `consumed`。
3. 只登记不改行为：本波 diff 只含新审计脚本 + 基线 + 三处接缝 + 文档，
   无任何 `Limelight/` 运行时改动、无默认值改动。
4. self-test 7 个变异 + 16 条钉死判读，覆盖契约要求的四类
   （(a) `accessor-call-site-deleted` 转红；(b) `export-row-restated`、
   `accessor-selector-stated-explicitly` 保持绿；(c) `exported-key-read-removed`
   证明改名映射被真读；(d) `pane-binding-deleted` 后键仍以 `unreachable-field`
   留在账上，不消失）。实测 `7 mutations, 16 pinned verdicts, 0 failures`。
5. 既有性质不回退（本机实测）：`defaults-consistency.py --self-test` **35 项全绿**
   （含 8 项负对照）、判定 **94 evaluated equal / 1 ledgered / 6 unresolved /
   0 divergent**、债务 **0 new / 0 stale**；`mute-on-focus-loss-tests.py` **0 failures**；
   `background-gamepad-tests.py` **OK**；`battery-interrupt-tests.py` **0 failures**；
   `bash scripts/local-gates.sh` **118 passed / 0 failed / 13 skipped**。
6. 三处接缝齐全：`.gitlab-ci.yml` `audit:python`、镜像 `build.yml`、
   `constraints-audit.py`（本地门禁）各加判定形态 + self-test 形态；
   `gate-coverage-audit.py --verify` = **92/92 reachable**、exit 0。

## 0.2 Wave Y 目标模式（已完成并合并：MR 46 → `3a4f47f1`，合并者 liguangming，head pipeline 988 success）

> 本节已收口。Wave Z-1（MR 47 → `2012367a`，合并者 liguangming）继续跨过了
> 它登记的"私有 helper 委托不跨函数求值"那一层。

> 本节是本轮唯一执行契约。Wave X 已收口（§0.1），本波修的是同一把尺子上**另一个**
> 读数错误：Wave X 修的是"回退记到错误的键名下"，本波修的是"回退根本不在被搜索的
> 语法形状里，于是那个键连账本都不上"。

**目标**：让 `scripts/defaults-consistency.py` 对**以访问器尾部 `return` 表达默认值**
的键也必须在两层不一致时变红，并且在这类键无法判等时**必须报未证明**，绝不给"该键
不存在"这种沉默。

**已量化事实（2026-11-01 逐处读源码实测，非估计）**：
- `bridge_read_ranges` 只搜 `settings\.(\w+)\s*\?\?` 这一种形状，因此一个键要被审计
  看见，它的串流侧默认值**必须写成 `??`**。
- 实测有 **8 个键**被 ObjC 真实调用（`[SettingsClass keyFor:]`），其默认值却写成
  `if let settings = … { return … }` + **函数末尾 `return 默认值`**：
  `appArtworkDimensions`（`SettingsObjCBridge.swift:1365`）、`audioConfiguration`
  （`:1388`）、`controllerDriver`（`:995`）、`dimNonHoveredArtwork`（`:1373`）、
  `framePacing`（`:1475`）、`mouseDriver`（`:1000`，委托私有 helper）、
  `rumble`（`:987`）、`streamShortcuts`（`:1726`）。
  这 8 个键在 `compared / divergences / unresolved / unread` **四本账上全部不存在**
  （35 个被调用访问器中减去这 8 个 = 27，即当前 `bridge_stream_accessors` 的读数里
  它们全被静默丢弃）。
- **假绿的量法（决定性变异，同一棵源码树）**：把 `SettingsObjCBridge.swift:987` 的
  `return SettingsModel.defaultRumble` 改成 `return false` —— 界面侧仍是
  `SettingsModel+DerivedValues.swift:1065 defaultRumble = true`，即"设置窗口显示开启
  震动、串流实际不震动" —— 审计打印 `0 divergent`、exit 0，且 `rumble` 在整个返回值
  里一次都没出现。**这条对照必须固化进 self-test。**
- 界面侧对这 8 个键同样**没有** `??`：默认值来自 `loadDefaultSettings()` 的赋值
  （`defaults_assignments` 已能读到），但**字段名不一定同名**：`framePacing` 对应
  `selectedPacingOptions`、`audioConfiguration` 对应 `selectedAudioConfiguration`、
  `controllerDriver` 对应 `selectedControllerDriver`、`mouseDriver` 对应
  `selectedMouseDriver`（见 `SettingsModel+Persistence.swift:308/322/387/389` 的
  `selectedX = Self.getString(from: settings.<profileKey>, …)`）。因此界面侧默认值的
  键名映射也必须**从源码反查**，不得硬编码一张表。
- 已逐键核对运行时结论（用于校准，不作为"已修好"的依据）：`audioConfiguration` 两侧
  都落在 `audioConfigurations[0]="Stereo"`、`controllerDriver`/`mouseDriver`/
  `framePacing` 两侧都走同一张表或同一常量、`dimNonHoveredArtwork`/`rumble` 同名同
  常量、`appArtworkDimensions` 界面侧是 `nil`+placeholder(300×400) 而串流侧是
  `CGSizeMake(300, 400)`、`streamShortcuts` 两侧同调 `defaultShortcuts()`。
  **本波不预期出现真实分叉**；尺子的正确性由变异证明，不由"现在报红"证明。

**完成边界（六条全绿才算完成，缺一不算）**：
1. **尾部 `return` 归属**：只在通过 `bridge_stream_accessors`（同名 + ObjC 真实调用）
   的访问器体内，取**大括号深度 0** 的最后一个 `return` 表达式；表达式里含 `settings.`
   的不算（那是读到的值，不是缺省值）。guard / 闭包内的 `return` 不得被当作函数默认值。
2. **界面侧键名映射来自源码**：`<profileKey>` → 界面字段名从 `loadSettings()` 体内
   `field = Self.getString(from: settings.<profileKey>` / `field = MouseInputDriverStrategy(
   persistedRawValue: settings.<profileKey>` 反查；反查不到才退回同名。映射结果必须
   能在 self-test 里被改名突变打破。
3. **无法判等必须报未证明，不得沉默**：`mouseDriver` 这类"尾部 return 是委托表达式"
   （`mouseInputStrategy(for: key).rawValue`）的键，若求值不到字面量，**必须**进
   `unresolved`（进而进债务账），绝不允许回到"键不在账上"。`appArtworkDimensions`
   的 `CGSizeMake` 同理：求值不出就报未证明，**不得**为凑绿而特判成尺寸相等。
4. **self-test 至少四条，且含正/负对照**：
   (a) 负向（尺子会红）：`rumble` 访问器尾部改成 `return false` → 报该键分叉；
   (b) 正向（未过拟合）：把 `return SettingsModel.defaultRumble` 重述成 `return true`
       → **保持绿**（证明判的是值，不是常量名）；
   (c) 负向（不得沉默）：把某访问器名改成 ObjC 不再调用的名字 → 该键报未证明/新债务，
       **不得**从账上消失；
   (d) 负向（映射来自源码）：把 `loadSettings` 里 `selectedPacingOptions` 的读取键改名
       → 该映射必须失效并报错/报未证明，**不得**继续判等。
5. **既有性质不回退**：`--self-test` 原 24 项全绿，且 `mute-on-focus-loss-tests.py`、
   `background-gamepad-tests.py` 仍 0 failures；字典侧 87 键的 compared 数、5 项已受理
   债务不得因本波减少（新增未证明键须进基线，`0 new / 0 stale`）。
6. **接缝在事实源 + 本地门禁 0 failed + 本次 SHA 流水线到终态**：
   `bash scripts/local-gates.sh` 0 failed（skip 逐项列名）；`liguangming` 审批合并后
   回读 MR 状态 / 合并者 / main 新 SHA / 合并 pipeline 终态。
   `跨文件静态安全扫描` 在本环境 `allow_failure=true`，只记「已豁免」不计入通过。

**边界**：不改设置面板任何默认值与标签栏 `NSSegmentedControl` role=`.tabs` 外观；
**不改任何 `.swift`/`.m` 运行时行为**（本波只改 `scripts/` 下的尺子 + 债务基线 + 文档，
八个键的出厂运行时结果逐一不变）；不解冻 USB 真重定向 / Developer ID 公证 / 自动更新；
`hardware_validated` 保持 `false`。

**已知未建模面（诚实登记，不当已完成）**：私有 helper 委托（`mouseInputStrategy(for:)`）
内部的 `return MouseInputDriverStrategy.defaultStrategy` 本波**不**跨函数求值，该键按
未证明处理；跨函数求值需要调用图，留作独立一波，不在本波偷偷扩大尺子范围。

**验收判据**：`python3 scripts/defaults-consistency.py --self-test` 全 `ok`（含新负对照）；
`python3 scripts/defaults-consistency.py` 末行 `0 divergent` 且 `0 new / 0 stale` debt，
并且 `rumble` 等键**出现在账上**（`compared` 或 `unresolved`，不再是缺席）；
`bash scripts/local-gates.sh` 0 failed；本次 SHA 流水线到终态。

## 0.1 Wave X 目标模式（已完成并合并：MR 45 → `515dfcf9`，合并者 liguangming，head pipeline 968 success，main pipeline 973 success）

> 本节已收口：五条完成边界全部落地（归属按消费路径、导出面写死可见默认值、
> self-test 含"这把尺子会红"的正负对照、两个下游门禁升级、事实源接缝 + 本地门禁）。
> 它修的是**归属**读错；同一把尺子还有一处**语法形状**读错（只认 `??`），
> 那是 Wave Y（§0）的标的，见其"假绿的量法"一条。

### 0.1.1 Wave X 契约原文（保留供追溯）

> 本节是本轮唯一执行契约。Wave W 已收口（§0.1），本波修的是 Wave W 那把尺子自身的读数错误。

**目标**：让 `scripts/defaults-consistency.py` 在"两层其实不一致"时**必须变红**。
Wave W 把"界面显示什么、串流就用什么"变成机器可证的性质，本波证明这把尺子
**不会在同一个缺陷面前给出绿色**。

**已量化事实（2026-11-01 逐处读源码实测，非估计）**：
- 桥接层有**两条**把设置交给串流的路径：`getSettings(for:)` 组装的字典（ObjC 侧
  `prefs[@"key"]` 读，实测 **54 个键**）与 76 个 `@objc static func key(for key:)`
  单体访问器（ObjC 侧 `[SettingsClass keyFor:]` 读，实测 **46 个键**）。
  实测**没有任何键同时被两种方式读**，所以每个键在串流侧只有一个默认值来源。
- Wave W 落地的 `fallbacks()` 用 `settings\.(\w+)\s*\?\?` 搜**整个**
  `SettingsObjCBridge.swift`，于是 90 个访问器里的 `?? defaultX` 被记到同一个键的
  **字典导出**名下：**21 个键**多算了不属于自己的回退。
- 字典组装以 `compactMapValues { $0 }` 收尾（`SettingsObjCBridge.swift:315`），
  所以裸 Optional 为 nil 时**不是**导出 `NSNull`，而是**这个键根本不存在**；
  ObjC 读到 nil，`[nil boolValue]` 得 `NO`、`[nil intValue]` 得 `0`，**不报错**。
- 三个键正好踩在两处叠加面上并且**真的被字典读**：`muteOnFocusLoss`
  （`StreamViewController.m:375/488`）、`backgroundGamepad`（`:393/506`）、
  `matchDisplayResolution`（`StreamViewController+MenuUI.m:1845/2415/2457/2505`）。
  它们的 `?? defaultX` 只写在**没有任何调用者**的访问器里
  （`muteOnFocusLoss(for:)` 在 `Limelight/**` 的 `.m/.mm` 中零调用，唯一提及是一行注释）。
- **假绿的量法**（决定性对照，同一棵源码树，只换归属逻辑）：把导出面还原成修复前的
  裸 Optional，并把 `SettingsModel+DerivedValues.swift:1089
  defaultMuteOnFocusLoss` 抬成 `true` —— 此时设置窗口显示"静音"、串流因键缺失读成
  `NO` 不静音；旧归属逻辑报 **0 divergent / exit 0**，收窄后报该键
  `unresolved`（"到 ObjC 侧没有任何回退"）。这条对照本身已固化进 self-test。

**完成边界（五条全绿才算完成，缺一不算）**：
1. **归属按消费路径**：字典键的回退只在 `getSettings(for:)` 体内寻找；访问器键的回退
   只在**同名且 ObjC 真实调用**（注释不算）的访问器体内寻找。多键推导函数
   （如 `loadMoonlightSettings(for:)` 用它算分辨率宽高）的 `??` **不得记到键名下**。
   归属不上的回退留空 —— 让键报"未证明"进债务账，绝不让它报"一致"。
2. **导出面写死可见默认值**：三个真被字典读的键在导出出处显式
   `?? SettingsModel.defaultX`（`matchDisplayResolution` 用字面 `false`，与界面侧
   `SettingsModel+Persistence.swift:248` 同一写法）。对全新安装是恒等变换：
   `false`/`false`/`false` 三值与 nil→`NO` 的运行时结果逐一相同，改的是"出厂值即被审计的值"。
3. **self-test 必须证明这把尺子会红**：新增负/正对照 —— 导出面回退改成错值→报红；
   导出面回退删成裸 Optional→报未覆盖（不得读作一致）；多键推导函数里的 `??` 改动→
   **不得**记到键名下（负对照）；被归属的访问器回退改动→报该层内分叉；
   导出面命名的是常量本身，故抬高常量→**保持绿**（证明修复没有把值冻成字面量）。
4. **下游断言同步升级**：`mute-on-focus-loss-tests.py` 与 `background-gamepad-tests.py`
   原来精确匹配裸 Optional 字符串，升级后必须匹配"键在字典中**且**默认值就地命名模型常量"，
   并各自用植入裸 Optional 的反向证明确实会红（已实测各抓 1 条 FAIL）。
5. **接缝在事实源 + 本地门禁 0 failed + 本次 SHA 流水线到终态**：
   `bash scripts/local-gates.sh` 0 failed（skip 逐项列名）；
   `liguangming` 审批合并后回读 MR 状态 / 合并者 / main 新 SHA / 合并 pipeline 终态。
   `跨文件静态安全扫描` 在本环境 `allow_failure=true`，只记「已豁免」不计入通过。

**边界**：不改设置面板任何默认值与标签栏 `NSSegmentedControl` role=`.tabs` 外观
（本波三个键的运行时结果逐一不变）；不解冻 USB 真重定向 / Developer ID 公证 / 自动更新；
`hardware_validated` 保持 `false`。

**已知未建模面（诚实登记，不当已完成）**：`loadMoonlightSettings(for:)` 是字典与访问器
之外的**第三条**串流侧消费路径（它把十余个设置算成宽高后写入 `DataManager`）。
本波只保证它的 `??` 不被**误记**为某键的默认，**没有**把它纳入两层判等。

**验收判据**：`python3 scripts/defaults-consistency.py --self-test` 全 `ok`（含负对照）；
`python3 scripts/defaults-consistency.py` 末行 `0 divergent` 且 `0 new / 0 stale` debt；
`python3 scripts/mute-on-focus-loss-tests.py`（含 `--self-test`）与
`python3 scripts/background-gamepad-tests.py` 0 failures；`bash scripts/local-gates.sh`
0 failed；本次 SHA 流水线到终态。

## 0.1 Wave W 目标模式（已完成并合并：MR 44 → `1031a42a`，合并者 liguangming，head pipeline 952 success）

> 本节已收口：五条完成边界全部落地（`defaults-consistency.py` 求值判等、带可证伪条件的
> 债务账、改源码文本的 self-test、两处真分叉修复、接缝进事实源）。它给出的尺子在
> **归属范围**上读数错误 —— 那是 Wave X（§0）的标的，见其"假绿的量法"一条。

**目标**：让"同一个未写入的设置项，界面显示什么、串流就用什么"成为机器可证的性质，
而不是靠人记得在两个文件里写同一个默认值。

**已量化事实（2026-10-31 逐处读源码实测，非估计）**：
- 两层读的是**同一个对象的同一个 optional**：`SettingsObjCBridge.getSettings(for:)`
  （`Limelight/macOS/ViewControllers/SettingsObjCBridge.swift:103`）与
  `SettingsModel+Persistence.loadSettings()`（`…/SettingsModel+Persistence.swift:244`）
  都从 `Settings.getSettings(for:)` 取值再各自 `??` 回退。两处回退不等价，就等价于
  **界面显示一个值、串流层用另一个值**。Wave V 修的 `ignoreAspectRatio ?? true` 是这条的第一例。
- 把符号解析成真实值后复核，上一轮用字符串粗比得到的"19 处疑似分叉"里 **15 处是误报**
  （`defaultEdgeSensorBandWidthPoints = 0.0` 对 `0`、`defaultSystemKeyboardShortcutCapture
  = systemKeyboardShortcutCaptureFollowFullscreen` 对 `0` 这类同值不同写法）。
  粗比的危害不是误报本身，是它会给出**绿色的错误结论**：上一版草稿（未入库）的 self-test
  只改内存字典、不改源码文本，因此它"证明了三个变异会被捕获"这句话没有任何证据支撑，
  与 Wave U 刚修掉的"幽灵规则"是同一类病 —— 故本波不继承那份草稿。
- 真分叉 **2 处，都有行为影响**，触发条件都是"老 profile：该键 nil、但相关旧键已设置"：
  （a）`smoothnessLatencyMode`：Persistence 用 `derivedSmoothnessLatencyMode(…)` 按
  pacing/vsync/buffer/responsiveness 推导，无预设命中时得 `Custom`；Bridge 的
  `smoothnessLatencyMode(for:)`（`:1461`）直接用静态 `Balanced`。该键**被串流消费**
  （`Limelight/macOS/ViewControllers/StreamViewController.m:1502`），所以界面显示 Custom
  而流用 Balanced。
  （b）`timingResponsivenessBias`：Persistence 用
  `?? (timingPrioritizeResponsiveness ?? false ? 1 : 0)` 的 legacy 推导（`…Persistence.swift:535`）；
  Bridge（`:286`）用静态 `Off`。`timingPrioritizeResponsiveness=true` 且该键 nil 时，
  界面 Mild、流用 Off。
- 第三处 `enhancedAudioEQLayout`（Persistence 按 `enhancedAudioEQGains.count` 推断带数、
  Bridge 用静态 12-Band）**当前无行为影响**：全仓 `.m`/`.h` 无任何位置读该 dict 键。
  它是"今天无害"，不是"永远无害"，所以必须钉住它无害的**条件**，不能只钉结论。
- 两处修复对**全新安装是恒等变换**（已代入默认值核算）：全默认时
  `derivedSmoothnessLatencyMode` 命中第二个预设 → Balanced，与静态默认相同；
  `timingPrioritizeResponsiveness` 默认 false → legacy 推导 0 → Off，与静态默认相同。
  这是本波唯一允许的行为变更边界，且必须由门禁复算而非由本文声称。

**完成边界（五条全绿才算完成，缺一不算）**：
1. **门禁不做字符串粗比**：`??` 后的表达式用括号平衡抽取，再按符号表**求值**到字面值
   （`Self.defaultX` 传递解析、`getInt(from:in:)` 按列表下标求值、
   `xxxRawValue(for:)` 按 options 表求值）。求值不出来的键**不得当作一致**。
2. **求不出值的键必须有账**：每条 ledger 记录必须带**可证伪的条件**（例：
   `enhancedAudioEQLayout` 的条件写作"ObjC 侧没有任何地方读该 dict 键"，一旦有人开始读，
   条目自己变成 violation）；条件已不成立的陈旧条目本身是 violation。
3. **self-test 改的是源码文本，不是内存字典**，且必须含**负对照**：
   （i）把 Bridge 某回退改成错值 → 报红；（ii）把模型默认值改成错值 → 报红；
   （iii）删掉一处读取路径 → 该键落入"未覆盖"而不是静默消失；
   （iv）负对照：语义等价的改写（`0.0` → `0`）不得报红。
   缺负对照就是本波要修的病的原始形态，缺它则 self-test 通过不说明门禁有效。
4. **两处真分叉修复且行为边界可证**：Bridge 两处改为与 Persistence 同一求值路径；
   门禁同时钉住"全默认时推导值 == 静态默认值"这一条，使"修复对全新安装恒等"由 CI 复算。
5. **接缝在事实源 + 本地门禁 0 failed + 本次 SHA 流水线到终态**：经
   `gate-coverage-audit.py --emit-commands --class=fast` 下发，由
   `.gitlab-ci.yml:344` 的 `bash -eo pipefail -x < gates-fast.txt` 真实执行，
   镜像侧同步调用；`bash scripts/local-gates.sh` 0 failed（skip 逐项列名）；
   `liguangming` 审批合并后回读 MR 状态 / 合并者 / main 新 SHA / 合并 pipeline 终态。

**边界**：不改设置面板任何默认值与标签栏外观（本波改的是"未写入时读到什么"，
不是"界面默认选了什么"）；不解冻 USB 真重定向 / Developer ID 公证 / 自动更新；
`hardware_validated` 保持 `false` —— 本波把"两层是否读同一个值"变成机器可证，
真机验收仍按 §4 独立保留。

**验收判据**（2026-10-31 落地后按实际命令与输出校正过一次：初稿写的
`defaults-consistency-tests.py` 并不存在，落地文件名是 `defaults-consistency.py`，
自测输出是逐条 `ok <检查名>` 而非 `caught`）：
`python3 scripts/defaults-consistency.py --self-test` 全部 `ok`（含负对照）；
`python3 scripts/defaults-consistency.py` 末行 `0 divergent` 且 `0 new / 0 stale` debt；
`python3 scripts/gate-coverage-audit.py` = 0 violation；`bash scripts/local-gates.sh`
0 failed；本次 SHA 流水线到终态。

## 0.1 Wave V 目标模式（已完成并合并：MR 42 → `c1f0eeac`，合并者 liguangming）

**发现（源码级，非推测）**：`SettingsObjCBridge.swift:115` 写的是
`settings.ignoreAspectRatio ?? true`，而模型默认
`SettingsModel+DerivedValues.swift:1123 defaultIgnoreAspectRatio = false`，ObjC 侧
`StreamViewController.m:783` 缺省 `NO`。三层里只有 Bridge 这一层是 `true`：没有显式写入
偏好的用户，运行时读到 `true` → `if (!ignoreAspectRatio)` 分支不执行 → **窗口宽高比默认不锁**，
与模型自述的默认值相反。

**修复**：`?? true` → `?? false`（一个词）。**用户可见路径零变化** —— 改之前运行时就是不锁，
改之后仍是不锁；改的是"模型/ObjC/Bridge 三层说法一致"这件事本身。审计文档
`docs/wave-v-settings-bridge-audit-2026-10-31.md` 同时记录其余分叉：
`autoAdjustBitrate`（Bridge/Model 同为 true，ObjC 缺省 NO 不触发）、
`edgeSensorSummon`、`edgeSensorSummonOnArrival`（三层一致）—— 均无行为影响，未改。

**验证**：MR 42 的 head pipeline **#897 = success**（`lint:toolchain`/`audit:python`/
`download-deps`/`build-app`/`test-app`/`audit:sources`/`audit:gates` + 4 项必跑安全扫描
success；`跨文件静态安全扫描` `allow_failure=true` → **已豁免**，不计入通过）。
合并由 `liguangming` 完成，`PUT /merge` 带精确 `sha=f6b071fe…`，main 新 SHA `c1f0eeac`。
`hardware_validated=false` 维持：无行为改动，不需要真机验收，但也不因此宣称任何真机结论。

## 0.2 Wave U 目标模式（已完成并合并：MR 41 → `b7be1dec`，合并者 liguangming；保留供追溯）

> 本节已收口。完成判据的回读结果见下，Wave V（桥接默认值分叉修复）另见 §0.1。

**回读结果（2026-10-31 实测）**：
- `source-matrix-audit.py --self-test`：`rule inventory: 13 codes documented, emitted and
  proved` + 14 条变异逐条 caught（SM001–SM014 全部有实现、有文档、有变异证明会触发）。
- `source-matrix-audit.py`（verify 形态）：`source matrix: 0 violation(s)`。
- `bash scripts/local-gates.sh`：**112 passed / 0 failed / 13 skipped**（skip 逐项在日志里
  列名：`release-gate.py` 需 CI 计算的 tag、`render-probe.py` 自带 20 分钟 Debug 构建、
  `source-membership-audit.py --build-log` 需构建产物等）。上一轮那一格
  `scaling-output-evidence-tests.py` 在无并发完整复跑里 **0 failed**，判定为编译抖动，
  非真实缺陷。
- `python3 scripts/gate-coverage-audit.py --verify`：rc=0，0 violation。新门禁经
  `--emit-commands --class=fast` 下发，`.gitlab-ci.yml` 的
  `bash -eo pipefail -x < gates-fast.txt` 真实执行；镜像侧 `build.yml` 同时跑
  `--self-test` 与 verify。
- MR 41：`state=merged`，`merged_by=liguangming`，merge commit `b7be1dec`，
  合并后 main 的 pipeline #895 除 `mutation-battery`（verify stage，长任务）外全部
  success，其中 `跨文件静态安全扫描` `allow_failure=true` → 只记**已豁免**，不计入通过。

**目标**：让对标矩阵的每一格"证据层级"由仓库自己复算，而不是由写下它的人自证。
Wave S 把"报告生产者"和"判读消费者"连上了；同一类缺陷在对标侧还有一个：
矩阵是散文，证据是 `docs/evidence/*/README.md` 加快照文件，两者**可以互相矛盾而无人查证**。

**已量化事实（2026-10-31 实测，非估计）**：
- 写这个门禁时逐格核对，**四格与仓库不符**：Sunshine 格钉的 release
  `v2026.1018.5342` 根本不存在（tag 直探针 404，当时最新 stable 是 `v2026.914.233613`）；
  qt 格自述"快照未钉 commit"，而 `docs/evidence/qt-snapshot/README.md` 早已钉住
  commit `de2467e4` 与两个可被 `git hash-object` 复现的 blob SHA；common-c 格钉的
  子模块 SHA 当前检出已无；Parsec 的 SHA-256 被缩写成无法复核的形式。CI 全绿。
- **门禁本身也带同一个病**（本轮自查发现，三条都真实存在）：
  （a）`SM004` 写在规则清单里，代码里**没有任何 `add(findings, ...)` 会发出它** —— 幽灵规则；
  （b）`SM001`/`SM011` 有实现，但没有任何变异证明它们会触发；
  （c）**`SM001` 在实践中永远报不出来**：`SM011` 的实现会去 `read()` 那个刚被
  `SM001` 判定"不存在"的 README，`FileNotFoundError` 直接掀掉整个审计 ——
  失效的证据链接让工具**崩掉**而不是**报红**，而"崩掉没有结论"在流水线里读起来像"没跑"。
  这条只有在真的补上 SM001 变异之后才暴露，靠读代码读了两遍都没看见。

**完成边界（五条全绿才算完成，缺一不算）**：
1. **规则三集合相等**（`source-matrix-audit.py --self-test` 内置）：文档声明的 code 集合、
   代码真正 `add()` 出来的集合、被某个变异证明会触发的集合，三者必须完全相同。
   任一方向都能反证有效：塞一条只写在文档里的规则 → `rc=1 documented as a rule but never
   emitted`；塞一条有实现有文档但没变异的规则 → `rc=1 emitted but never proved to fire`。
2. **SM011 不再越界读文件**：只为确实存在的邻居 README 取 SHA-256，
   断链时必须报 SM001 而不是抛异常。
3. **矩阵逐格与仓库重算一致**：`source-matrix-audit.py`（verify 形态）0 violation，
   且四格旧值的失效方式（**过期** / **记错**）在格内留字不静默替换 ——
   门禁看得见"SHA 与 build 号不自洽"（SM012）和"钉的 commit 不在本历史线"（SM013），
   **看不见"自洽但已落后 main"**，那一格只能靠验证日期这个人工凭据。
4. **接缝接在事实源上**：新门禁经 `gate-coverage-audit.py --emit-commands --class=fast`
   下发，由 `.gitlab-ci.yml:344` 的 `bash -eo pipefail -x < gates-fast.txt` 真实执行；
   GitHub 镜像侧同时补 `fetch-depth: 0` —— 浅树（实测 712/18963 对象）会让 SM012/SM013
   只能按 fetch depth 记分，`SM014` 是它拒绝撒谎的方式，不是可选提示。
5. **完整本地门禁 0 failed**：上一轮 `111 passed / 1 failed / 13 skipped`，
   那一项 `scaling-output-evidence-tests.py` 单跑 0 failures，
   须在**无并发**的完整复跑里判定是编译抖动还是真实缺陷；判不出来就不许提交。

**边界**：不改设置面板任何默认值与标签栏外观；不解冻 USB 真重定向 / Developer ID
公证 / 自动更新；`hardware_validated` 保持 `false` —— 本波只把"对标结论可不可复核"
变成机器可证，真机验收仍按 §4 独立保留。

**验收判据**：`python3 scripts/source-matrix-audit.py --self-test` 打印
`rule inventory: 13 codes documented, emitted and proved` 加 14 条变异逐条 caught；
`python3 scripts/source-matrix-audit.py` = 0 violation；
`python3 scripts/constraints-audit.py --no-battery` = 0 constraint failures；
`bash scripts/local-gates.sh` 0 failed（skip 逐项列名）；本次 SHA 流水线到终态；
`liguangming` 审批合并后回读 MR 状态 / 合并者 / main 新 SHA / 合并 pipeline 终态。

## 0.3 Wave T 目标模式（已完成并合并：MR 40 → `bf055b23`；保留供追溯）

> 本节是本轮唯一执行契约。完成后按 §11 交回常规顺序，不得扩大范围。

**目标**：让事实源流水线证明"真机验收那七行判据，确实建立在导出的字节上"。
Wave S 把生产者与消费者连上了，但那条缝只验到"能解析 + 构建身份可定位"为止。
判读器真正依赖的是**另外的键名**：六参数、六个开关、指针、重连、两手柄槽位、能力位。
这些名字今天没有一处被报告字节钉住。

**已量化事实（2026-10-31 探针实测，非估计）**：
- 把 builder 里的 `ml.param.` 改成 `ml.params.`，`python3 scripts/diagnostics-report-tests.py`
  依旧 0 failures —— 端到端门禁只看 `parse_machine` + `build_identity`，两者都不读这些键。
  同一份报告交给 `grade()`，七行里 `edge-sidebar-params` 直接 UNKNOWN，理由是
  `machine block lacks 30 key(s)`。**CI 绿、验收静默失效**，与 Wave S 修掉的 P1 同一形状。
- 判读器 `SIDEBAR_PARAMS` 六个键名是**手抄**的（`scripts/hardware-acceptance-check.py:73`），
  来源是 `StreamViewController+Diagnostics.m` 的六个 label 折叠下划线；两处之间没有门禁。
- 七行里报告侧条件依赖的键共 41 个，harness 目前只断言了 `ml.param.edge_sensor_band.*`
  一族（1/6 参数、0/6 开关、0/6 其余）。

**完成边界（五条全绿才算完成，缺一不算）**：
1. **验收态报告进 harness**：driver 额外产出一份"七行的报告侧条件全部成立"的报告
   （六个参数含至少一个 off-default、六个开关全 on、`ml.pointer.absolute=yes`、
   `ml.reconnect.present=yes` 且 attempt≥1、两个已通告槽位、能力位齐），
   经 `canonicalReportBytesFromString:` + `writeReport:toURL:error:` 落到 `ML_ACCEPTANCE_DUMP`。
   走生产写入口，不手搓 `writeToFile:`。
2. **七行全 PASS**：Python 侧把**那份文件**交给判读器 `grade()`，配一份绑定其 `report_sha256`
   且每行 `observed`+非空 `note` 的声明，断言 `pass 7, unknown 0, fail 0`。
   行 id 与 `(row, id)` 配对从两处独立推导后对拍：判读器 `ITEMS`，以及人真机时照着做的
   `docs/hardware-acceptance-checklist.md` 表格首列。判读器加一行而清单没加、或清单少一步
   而判读器还在打分，都算这盏灯该灭（已实测：任一边改 id 立即变红）。
3. **键名漂移变异**（逐条要求"七行不再全 PASS"）：`ml.param.`→`ml.params.`、
   `ml.switch.`→`ml.switches.`、`ml.controllers.slot.`→`ml.controllers.slots.`、
   `ml.pointer.absolute`→`ml.pointer.is_absolute`、`ml.reconnect.attempt`→`ml.reconnect.attempts`
   五条，各自打中不同行；只要求"链路在把关"，不要求措辞。最后一条是**证明件**：driver 自己的
   断言不读这个键，改完之后生产侧自检全过，只有判读侧能发现行掉了。
4. **两处手抄对拍**：门禁从**导出报告的字节**里取出 `ml.param.*.effective` 的键名集合
   （报告由 builder 用六个 label 经同一折叠规则产出，因此这等价于从生产侧独立推导，
   而不是把两份手抄再抄一遍），与判读器 `SIDEBAR_PARAMS` 按集合比对；
   改名在**生产侧或判读侧任一边**发生都被抓住（已实测：两边各改一次，都立即变红）。
5. **地板与流水线**：`MIN_DRIVER_CHECKS` 随真实用例上移；`bash scripts/local-gates.sh` 通过；
   本次 SHA 的 pipeline 到终态 success。

**边界**：不改变任何用户可见行为、设置默认值、判定语义（`MISSING_READS_AS_SATISFIED`、
`ANNOUNCED_TYPES`、`build_identity` 规则都不动）；不把"七行全 PASS"当 `hardware_validated=true`
—— 那七行 PASS 需要**人**在真机上写观察记录，门禁证明的是"报告载得起那七行"，不是"有人观察过"；
不解冻 §5 冻结项；不动设置页原生控件。

## 0.4 Wave S 目标模式（已完成并合并：MR 39 → `71a62394`，pipeline 883 全绿；保留供追溯）

> 本节是本轮唯一执行契约。完成后按 §11 交回常规顺序，不得扩大范围。

**目标**：让事实源流水线自己证明"app 导出的那份文件，判读工具读得懂"。
今天报告的**生产者**（`DiagnosticsReportBuilder`）和**消费者**
（`scripts/hardware-acceptance-check.py`）各有一盏绿灯，中间那条缝从没连过：
builder 测试只断言"提交号这个字符串在报告里"，判读器 `--self-test` 只判读
**它自己维护的 fixture**。两端都绿，真实导出的报告依旧可以整张矩阵判 UNKNOWN。

**已量化事实（2026-10-30 实测，非估计）**：
- **P1 缺陷真实存在过**：`redactOpaqueTokensInString` 的
  `[A-Za-z0-9+/]{24,}={0,2}` 把 40 位十六进制 `ml.build.git_commit` 当不透明块删掉；
  判读器把该键当**整张矩阵的前提**（§4.1），于是一次真机验收的 7 行全部 `UNKNOWN`，
  而 CI 全绿。它只在手工把报告喂给判读器时暴露。
- **两端从未相连**：`grep -n hardware-acceptance-check` 在
  `scripts/diagnostics-report-tests.py` 里零命中；`.gitlab-ci.yml:251` 只有
  `--self-test`。`scripts/diagnostics-report-tests.py` 已经能把导出的字节落到
  `ML_CANONICAL_DUMP` 指定文件，Python 侧从没读过它。
- **判读器对字节形状敏感**：`parse_machine` 用 `str.splitlines()` 断行，
  `report_sha256` 覆盖文本模式读入再编码的字节；`MLIsLineBreak` 折叠 CR/VT/FF/FS/GS/RS/
  NEL/U+2028/2029 就是为了让"被 hash 的字节"和"被断行的行"描述同一个文件。
- 修复前的基线：`python3 scripts/diagnostics-report-tests.py` = **0 failures**
  （含 P1 修复的 7 个反向安全用例），但那条缝仍未相连；Wave S 改动（导出按钮 +
  canonical 落盘 + P1 修复 + 端到端门禁）在 `feat/wave-s-diagnostics-file-export`，
  **推送之前 main 上没有**。

**完成边界（四条全绿才算完成，缺一不算）**：
1. **两端在门禁里相连**：driver 把导出的字节落到文件，Python 侧把**那份文件**交给
   判读器的 `parse_machine`/`build_identity` 判读，断言可解析、身份可定位、
   且二进制打印的 SHA 与 Python 独立重算一致（两个读者偶然一致和故意不一致是同一个 bug）。
2. **行为变异**（进 `scripts/diagnostics-report-tests.py`，逐条 rc=1）：
   （a）摘掉 `maskBuildIdentityInString` 那次调用 → 判读器必须立刻定位不到构建身份；
   （b）把区块标题写出 `[machine]` 契约 → 判读器必须拒绝解析；
   （c）builder 单方面升 `ml.schema` → 判读器必须拒绝解析。
   三条都要求"链路真的在把关"，不是被路过。
3. **导出功能进入事实源**：`canonicalReportBytesFromString:` / `writeReport:toURL:error:`
   与设置页导出按钮合并进 main，导出走 `NSDataWritingAtomic`，
   空报告与不可写目标必须返回错误而不是静默留下半个文件。
4. **门禁计数随真实用例上移**：`MIN_DRIVER_CHECKS` 跟住二进制自己打印的检查数，
   留出余量但不允许长期落后 —— 用例清单悄悄缩水只能靠这个数字发现。

**已落地（2026-10-30 实测）**：四条边界都已实现 —— driver 经**生产写入路径**落整个报告，
Python 侧用 `importlib` 载入真实判读器判读**那份文件**，SHA 做"builder 打印 / 判读器
重算 / Python 独立重算"三方比对；三条端到端变异全部由消费侧拦住（去 mask →
`ml.build.git_commit is [redacted-blob]`；改标题 → `no [machine] block`；升 schema →
`schema '2' is not understood`），其中"升 schema"这条在修复前**生产者侧完全无感**，
只有判读器看得见；`MIN_DRIVER_CHECKS` 109 → **134**（driver 自报 134）；
`bash scripts/local-gates.sh` = **110 passed / 0 failed / 13 skipped**（13 项全是需要 CI
产物、`--all` 或真机的项，逐项理由见门禁输出）。

**验收判据**：`python3 scripts/diagnostics-report-tests.py` 0 failures 且日志里能看到
三条端到端变异各自 `the checker stops accepting the export when …`；
`bash scripts/local-gates.sh` 0 failed（skip 逐项列名）；本次 SHA 流水线到 success，
`publish-github` 核对本 ref 双端 SHA；MR 由 `liguangming` 审批合并后回读
MR 状态 / 合并者 / main 新 SHA / 合并 pipeline 终态。

**边界**：不把 `hardware_validated` 改成 true —— 本波只把"报告能不能被判读"变成机器可证，
真机验收矩阵（§4）仍独立保留；不动设置页原生控件与已验收默认值；
不签 Developer ID、不公证、不做自动更新（§5 冻结项）。

## 0.5 Wave R 目标模式（已完成并合并：MR 38 → `c8e959d0`；保留供追溯）

**目标**：让事实源流水线在发出 DMG 的那一刻审计这个镜像本身。今天 `package-dmg`
只负责"造出镜像"，没有任何一步读过造出来的东西；`dmg-audit.py` 存在、且在 GitHub
镜像侧的 release job 里真跑，事实源却只跑它的 `--self-test-checksums`。结果是
一条完整链路可以全绿发布一个用户装到手里才发现不对的包。

**已量化事实（2026-10-30 实测，非估计）**：
- **CI 发布出去的镜像确实缺翻译表**：从 GitLab job **5036**（pipeline 836，main
  `dd68e529`）的 artifacts 取回 `Moonlight-1.6.0-build2050.dmg`，只读挂载后
  `Contents/Resources` 下 `InfoPlist.strings` 数量 = **0**，`en.lproj`/`zh-Hans.lproj`
  里只有 `Localizable.strings`。Xcode 不为本工程写出该文件，于是包内 app 的权限提示
  对任何语言都只剩 Info.plist 里那一句 —— 仓库里那两份翻译表只在 git 里成立。
- **修复后的同一个 app 打包能带上表**：经 `codesign-bundle.sh` 处理的副本再打包，
  镜像内 `InfoPlist.strings` 数量 = **2**，中文读出"用于捕获高回报率鼠标输入…"，
  包内 `codesign --verify --deep --strict` 通过；打包前后输入 app 的
  `InfoPlist.strings` 数量都是 0，证明改动落在 staging 副本而不是用户的构建产物。
- **期望值在同一个 job 内就能拿到**：`sh Limelight/build-number.sh --print` = 2054，
  `python3 scripts/project_identity.py --print-version` = 1.6.0；而本地那份 app 的
  `CFBundleVersion` 是 **1720**（xcconfig 陈旧基线）。同一次构建里源说 2054、包自报
  1720 —— 这正是"审计必须拿源当期望值、不能拿 bundle 自证"的证据。
- **门禁登记的理由已经站不住**：`gate-coverage-audit.py` 把 `dmg-audit.py` 记成
  `selftest` 类，`full_form` 写"uncovered on the source of truth: package-dmg produces
  the image but the audit also wants the release body and sidecar layout the mirror's
  release job assembles"。而 `--version`/`--build` 都是可选参数、
  `--localizations-from` 默认就指本仓库的语言表 —— 该审计并不真的需要 release 正文。
- `spctl -a -t exec` 对本地 Release 包 **rejected**，`codesign --verify --deep --strict`
  rc=0。ad hoc 签名不满足 Gatekeeper 是既有事实，属 §5 冻结项，本波不动、也不声称修好。

**完成边界（四条全绿才算完成，缺一不算）**：
1. **修复进入事实源**：`scripts/package-dmg.sh` 在 `hdiutil create` 之前对 staging 副本
   装语言表并 seal，且**签名在表之后**（表装进 bundle 之前 seal，句子就不在签名覆盖内）。
   输入 app 不被改写 —— 这条要用打包前后的读回证明，不能只靠"看起来没写"。
2. **期望值来自源**：短版本号在仓库里只能有一个读者，新增 `marketing_version()` 与
   `release-gate.py` 的既有读取路径在 `--self-test` 里互相钉死（两个读者偶然一致，
   和两个读者故意不一致是同一个 bug）。CI 审计显式传 `--version`（源声明）与
   `--build`（本次 SHA 的 `rev-list --count`），二者都不从镜像里的 plist 读。
3. **事实源真跑全形式**：`package-dmg` 造完镜像在同一 job 内跑
   `python3 scripts/dmg-audit.py "$dmg" --version … --build …`，失败即 job 失败；
   `gate-coverage-audit.py` 里 `dmg-audit.py` 的登记随之改为 `fast`，那句
   "uncovered on the source of truth" 必须删掉 —— 留着它，这条覆盖缺口就还能匿名存在。
4. **行为变异**（进入 `scripts/assertion-battery.py`，`--self-test` 下逐条 rc=1）：
   （a）去掉本地化安装步骤 → 镜像审计必须拒绝，证明表真的被检查而不是被路过；
   （b）审计期望值改读 bundle 自报值 → 必须被拒绝，禁止 bundle 自证；
   （c）从 `.gitlab-ci.yml` 删掉审计步骤 → `gate-coverage-audit.py` 必须报错或指出
   登记过期，证明接线不能悄悄松掉。

**验收判据**：本波 SHA 的流水线产物下载后只读挂载，`InfoPlist.strings` 数量 = 2；
job trace 里能看到 `ok bundle MoonlightEnhanced.app version 1.6.0 build <本次计数>`；
`dmg-audit.py --self-test` 与 `--self-test-checksums` 均 rc=0；
`gate-coverage-audit.py` rc=0 且 `dmg-audit.py` 不再出现在 note 列表；
`bash scripts/local-gates.sh` 0 failed；本次 SHA 流水线到 success，`publish-github`
核对本 ref 双端 SHA。

**边界**：不签 Developer ID、不公证、不做自动更新（§5 冻结项）；不顺手改设置页控件与
已验收默认值；不把 `spctl rejected` 说成已解决；真机验收仍按 §4 独立保留。

## 0.6 Wave P 目标模式（已完成并合并：MR 36 → `dcad899d`；保留供追溯）

> 本节是本轮唯一执行契约。完成后按 §11 交回常规顺序，不得扩大范围。

**目标**：让凭据门禁能看见"硬编码口令字面量"这一类形状，并诚实处理它在本仓库
历史里的既成事实。当前 `RULES` 八条全部面向厂商 token（GitHub/AWS/Slack/Google/
Stripe/PEM/`api_key =`），对 Objective-C 里
`static const char *password = "...";` 这种形状完全盲视——`HttpManager.m`
的临时钥匙串口令正是以明文常量 shipped 了若干个 release，没有任何门禁报过。

**已量化事实（2026-10-30 实测，非估计）**：
- 当前 tracked 树命中 **0**（旧常量已在本次改动中移除，`git grep` 复核）。
- 全历史（`git rev-list --objects --all`，7682 个 blob）命中 **56 行 / 56 个 blob**，
  distinct 值 **只有 1 个**，`sha256:732dfa98275bb3b007c639b1f7a3cb2051b638faaf075cd7c370e1589f664b2e`
  （9 字符），首次可见路径 `Limelight/Network/HttpManager.m`。
- 该口令保护的临时钥匙串是 throwaway：每次导入前 `SecKeychainDelete` + 删除文件，
  明文常量只让每个 shipped binary 共享同一个秘密。

**完成边界（三条全绿才算完成，缺一不算）**：
1. **检测**：新规则 `hardcoded-credential-assignment` 进入 `RULES`，覆盖
   `*password*/*passwd*/*passphrase*/*p12key*` 标识符赋引号字面量；
   `PRESCREEN` 与 `ANCHORS` 同步扩为该规则的超集，`--self-test` 逐规则证明超集性质。
2. **历史诚实**：历史豁免只按**值指纹**生效，且仅当该值在当前树 0 命中时生效——
   同值回到当前代码必须立刻 FAIL，豁免不得成为后门。树扫描模式完全不查豁免表。
   豁免表须带可读理由（值已从 tip 移除 + 保护对象是 throwaway 钥匙串）。
3. **行为变异**：`scripts/assertion-battery.py` 至少新增两条可被拦截的变异——
   （a）豁免表在树模式也生效（后门化）；（b）规则改写后不再匹配旧常量形状。
   本地门禁 + 本次 SHA 的 GitLab 流水线到 success，`publish-github` 核对双端 SHA。

**验收判据**：`python3 scripts/credential-scan-audit.py --history --timeout 900`
在移除旧常量后仍为 `ok ... (9 rule(s) armed)`；把历史里那行原样贴回工作区副本必须
被拒绝；`--self-test` 报 9 rules armed。

**实测收口（2026-10-30，本机，非估计）**：
- `--self-test` → `9 rules armed, 6 clean samples, report stays redacted`，rc=0。
- `--history --timeout 900` → `ok 635 tracked file(s) carry no credential shape`，rc=0，
  约 24 秒（字节预筛生效，远未接近预算）。
- 豁免不是后门：把历史 `HttpRequest.m:109` 那行按原样插回工作区，树扫单独 rc=1、
  树+历史 rc=1 双双 FAIL；恢复原文件后树扫回到 rc=0。
- `MUTATIONS` 146 → 148，两条新变异（`history-exemption-leaks-into-the-tree`、
  `password-rule-narrows-away-the-shipped-name`）在 `--self-test` 下均 rc=1 被拦。
- 运行时一致性：临时钥匙串路径每次导入都是新 UUID 且先删旧文件，口令 `dispatch_once`
  进程内固定，所以 create 与 unlock 必然同值；`randomBytes` 走 `arc4random_buf`，
  `bytesToHex` 只产十六进制数字，UTF-8 字节数等于 `strlen`，注释里的长度前提成立。
- 编译审计 87/87；`bash scripts/local-gates.sh` 110 passed / 0 failed / 13 skipped。

**边界**：不改历史（不 filter-branch、不 force push）；不碰 §5 冻结项；
不顺手改设置页控件与已验收默认值；真机验收仍按 §4 独立保留。

> 用途：续跑本仓库对标作战的"目标模式"提示词。所有续接会话先读 AGENTS.md、`docs/baseline-2026-10-22.md`、`docs/campaign-plan-2026-10-20.md`、本文件和 `docs/competitive-polish-roadmap-2026-10-20.md`，再核对 Git、源码、准确 SHA 的流水线。

## 1. 当前基点（截至 2026-11-04，MR 1–56 全部合并，在途 MR = 0）

- 代码基点 main = `dd21f09d35`（`Merge branch 'wave-ai-doc-refresh' into 'main'`，
  MR 56，head `c4d8a95c`，合并者 `liguangming`，`merged_at=2026-11-03T17:46:32Z`；
  合并为 docs-only 单文件，未触碰任何 `.m`/`.swift`/`.h`）。合并触发的
  main pipeline **#1157** 终态见 Wave AJ 收口记录（§0）。上一基点
  `1efe4a3720`（`Merge branch 'wave-ah-ai-doc-refresh' into 'main'`，
  MR 55，head `882bf14d`，合并者 `liguangming`，`merged_at=2026-11-03T12:41:19Z`，
  merge pipeline **#1123 = success**；合并为 docs-only 单文件，未触碰任何
  `.m`/`.swift`/`.h`）。合并触发的 main pipeline **#1128** 为完整 main push 链
  （battery 200min 上限生效后的第二次全量首跑）。上一基点 `1ceea940`
  （`Merge branch 'wave-ag-battery-ceiling-200' into 'main'`，
  MR 54，合并者 `liguangming`，`merged_at=2026-11-03T09:47:31Z`，head pipeline
  **#1110 = success**；合并触发的 main pipeline **#1112** 为完整 main push 链，
  含按实测 8893s 收紧到 200min 上限后的 `mutation-battery` 首跑）。再上一基点
  `c0b74bc2`（MR 53，合并者 `liguangming`，`merged_at=2026-11-03T03:17:20Z`，main
  pipeline **#1090 = success**（16 job 全绿；`mutation-battery` 首测 153/153 /
  8893s / 336 免证，COST 行落进 trace）。上一基点 `d16497a4`（MR 50，
  合并者 `liguangming`，`merged_at=2026-11-02T05:27:39Z`，合并流水线
  **#1040 = success**（12 个 job 全绿，无 `allow_failure` 豁免项可记）。该合并**未触碰任何
  `.m`/`.swift`/`.h`**，全部是脚本、fixtures 与文档，故 `hardware_validated` 的判断不受影响。
  判读器本体在本机重跑复核：`--self-test` 报 9 个变异各自转红，快照＋真实报告形态
  报 `host-identity=OK, xbox-360-emulation=OK, ds5/switch=BLOCKED, advertised-versus-host=BLOCKED`，
  与 `--expect` 钉死的一致（evidence：`moonlight-ci-evidence/20261102-wave-aa-host-side-evidence/`）。
Wave AC+AD 是 MR 52（head `8b7f6b46`），合并进 main 的合并提交是 `18921771`，
`merged_at=2026-11-02T18:59:45.861Z`，合并者 `liguangming`（MR 51 是 Wave AB）。
Wave AE 已随 MR 53 收口（见本节首段）；Wave AH 收口批随 MR 54 收口（见 §0），
五项完成边界中代码侧四项已落地，`mutation-battery` 200min 上限首跑与
GitHub 镜像回读以 #1112 终态为准。
- 上一基点 `9e914350`（`Merge branch 'wave-z3-settings-usage-audit' into 'main'`，
  MR 49，合并者 `liguangming`，`merged_at=2026-11-01T19:45:09Z`，head pipeline
  **#1010 = success**）。**合并后的 main 流水线未全绿，两条红色都是基础设施**：
  **#1017（`9e914350`）** `audit:python` 在 `pip install pyyaml==6.0.2` 上因
  `SSLEOFError` 五次重试全败（job 6623，无一条门禁跑到）；
  **#1006（`e2334917`）** `mutation-battery` 用满 3h 上限被 `Terminated: 15`（job 6530，
  trace 里 `RUN` 120 条、`CAUGHT` 119 条、`MISSED` 0 条——第 120 条
  `membership-exceptions-attached-to-a-target` 刚开跑就被杀，**因此这一轮的电池是"未跑完"，
  不是"全过"**，已跑到的 119 条全部被抓住。两条红色均与代码无关，**但 #1006 直接约束本波**：
  电池的默认判读门就是 `constraints-audit.py --no-battery`：`assertion-battery.py` 的
  变异条目不带归属门时继承该默认（`gate = entry[4] if len(entry) > 4 else AUDIT_GATE`），
  #1006 的 trace 实测**120 个变异里 81 个由本聚合判读**，每次 130–180 秒——加进聚合的每一秒
  按 81 计息。因此 Wave AA 的 self-test 形态（本机实测 6.3s，≈ 加 8.5 分钟）只进两份流水线
  定义与 `local-gates.sh`，聚合里只留实测 0.04s 的判定形态。retry 后须回读终态，
  未计入通过前不得引用为绿。
- 上一基点 `2012367a`（Wave Z-1：读取一层委托 helper 求默认值，并停止把"无法证明"
  当作"不存在"），MR 47，合并者 `liguangming`。
- 上一波 Wave Z-3（分支 `wave-z3-settings-usage-audit`，基于 `e2334917`）——
  新增 `scripts/settings-usage-audit.py`：把"面板里有开关、写进了持久化、运行时零消费者"
  变成门禁级红色。本机门禁实测 **118 passed / 0 failed / 13 skipped**（skip 逐项是
  需要构建产物或 CI 计算变量的项，加完整变异电池与 render-probe），
  `gate-coverage-audit --verify` 报 **source of truth 38 gates / mirror 92 gates /
  92 reachable**。
  Wave AA 的装配缺口证明这一层问得没错、但问的不是最后一跳，见 §0。
  同一轮的门禁计数在 Wave AB 后是 **事实源 41 / 镜像 95 / 可达 95**，
  本地并集 **135 条命令**（旧数字保留是为了让"加了几条"可核对）。
- 上一基点 `0fc2faa2`（`Merge branch 'docs/goal-mode-refresh-c1f0eeac' into 'main'`，
  MR 43，合并者 `liguangming`，head pipeline **#900 = success**）。其上是 Wave V
  `c1f0eeac`（MR 42，head pipeline **#897 = success**，12 个 job，
  `跨文件静态安全扫描` `allow_failure=true` → **已豁免**，不计入通过）。
- 上一基点 `b7be1dec`（MR 41，Wave U 对标矩阵自证）对应 main 流水线 **#895**：
  `audit:deep`/`package-dmg`/全部必跑安全扫描已 success，`mutation-battery` 仍在跑，
  `publish-github` 排队；`package-dmg`（job 5580）产物为
  `Moonlight-1.6.0-build2063.dmg`，**该包未做过包内三件套验收**
  （`hdiutil verify` / `codesign --verify --deep --strict` / `CFBundleVersion` 读回），
  因此**不计入"已验证 DMG"**，不得当作已验证产物引用。
- 自基点 `18ee83cd` 以来的合并链（原提交 → merge commit，MR 号）：
  - Wave G-3 common-c submodule bump（RFI 丢帧诚实性）：`20c4739a` → `c1662eda`（MR 32）。
  - 五个待定上游 commit 的源码级结论：`1bc05087` → `4a9e3da9`（MR 33）。
  - Steam Controller 按 STEAM 而非 Xbox 通告：`0c6b93df` → `6bd3fad3`（MR 34）。
  - 能力矩阵按 main 纠偏 + 两份新证据快照：`2e049b5f` → `dd68e529`（MR 35）。
  - 硬编码凭据门禁 + 运行期随机临时密钥链口令：`8233424e` → `dcad899d`（MR 36）。
  - 诊断报告命名来源字节 + 验收判分：`cccbfde0` → `27e076fe`（MR 37）。
  - 出厂镜像自证内容：`805d0e2b` → `c8e959d0`（MR 38）。
  - 报告导出即判读器哈希的字节 + 双管线相连：`6d8e2680` → `71a62394`（MR 39）。
  - Wave T 七行验收判据建立在导出字节上：`fd3557fd` → `bf055b23`（MR 40）。
  - Wave U 对标来源矩阵自证（规则三集合相等 + 断链不崩审计）：`7bf5e2c6`/`544cad84`
    → `b7be1dec`（MR 41）。
  - Wave V 桥接默认值分叉修复（`ignoreAspectRatio ?? true` → `false`）：`f6b071fe`
    → `c1f0eeac`（MR 42）。
- 历史基点链（保留追溯）：main 曾为 `18ee83cd`（`Merge branch 'ci/wave-k2-merge-request-pipelines' into 'main'`）。
  该基点自身的 pipeline **#813** 到本文档刷新时仍为 `running`：
  `lint`/`deps`/`build`/`test`/`package`/`audit:deep` 已 success，
  `package-dmg` 产物为 `Moonlight-1.6.0-build2041.dmg`，
  `mutation-battery` 与 `publish-github` 未收尾。**该产物尚未做过包内
  `hdiutil verify` / `codesign --verify --deep --strict` / `CFBundleVersion` 读回，
  因此不计入"已验证 DMG"**，以 #813 终态 + 产物验收记录为准。
- MR 1–31 全部 merged（MR 5、MR 13 因被后继 MR 取代而 closed），在途 MR = MR 32
  （Wave L-1 common-c submodule bump，见下）。
  自基点 `a8412222` 以来的合并链（原提交 → merge commit）：
  - 本文档基点刷新（至 `a8412222` + Wave G 计划）：`f83cb534`（MR 24）。
  - Wave G-1 上游 `0405384` UTF-8 密集打包：`aca93699` → `a539c604`（MR 25）。
  - Wave G-2 子模块 bump 至 `abe83b8`（相对鼠标 delta latch）：`43c6e835` → `32421c28`（MR 26）。
  - Wave H 两套流水线定义的门禁覆盖对等（`scripts/gate-coverage-audit.py`）：→ `1d43c908`（MR 27）。
  - 标签栏 inspector 在 AX 环上不再崩死：→ `2b1a893a`（MR 28）。
  - Wave I 机器可读验收区块 + 可执行真机验收判分器
    （`scripts/hardware-acceptance-check.py`、`docs/hardware-acceptance-checklist.md`）：→ `639d38b2`（MR 29）。
  - 诊断 harness 编译改并行：→ `80f8632e`（MR 30）。
  - Wave K2 有 open MR 的分支只判一次（merge-request pipeline 去重）：→ `18ee83cd`（MR 31）。
  - 在途：MR 32 `6e1aa0b1`（submodule pin `abe83b8` → `093098f5`，Wave G-3 RFI
    丢帧诚实性）。`detailed_merge_status=security_policy_violations` 是 merge-preview
    未跑完的瞬时状态（MR 23 已实证过一次），等 #820 预览管线到终态再判，不要先改安全策略。
  审批与合并均由 owner（`liguangming`，user id 1）凭据完成，
  `PUT /merge` 必须带精确 `sha=`，否则 GitLab 19.5 拒绝。
  上一轮新增：MR 22（诊断功能生效态 `25a374c5` → `127b4eb2`）、
  MR 23（本文档基点刷新 `68f1b3e8` → `a8412222`）。
  MR 23 一度显示 `detailed_merge_status=security_policy_violations`，
  实测是 merge-preview 尚未跑完时的瞬时状态，预览管线转绿后同一 SHA 直接合并成功；
  遇到该状态先看 merge-preview pipeline，不要先去改安全策略。
- 上一基点 `27b1206e`（`ci/held-key-mutant-scope-and-diagnostics` 合并）对应 pipeline
  **#719 = success**，产物 `Moonlight-1.6.0-build2019.dmg`（arm64）。
- 自 2026-10-25 基点（`b65db5fb`）以来的合并链（原提交 → merge commit）：
  - K1.2 本地输入法组合：`5c0dbfa3` → `fa1c645c`（MR 6）。
  - SAS 门禁补进 GitLab 事实源：`58453614` → `c8e004d7`（MR 7）。
  - 目标模式提示词刷新：`02c8f645` → `8945676e`（MR 8）。
  - 对标来源矩阵（逐产品版本 + 证据层级 + 未知项）：`a8561ec0` → `7c4eedc7`（MR 9）。
  - Wave B 文档收敛（qt v6.2.0 快照钉版本 `de2467e4`、common-c 漂移审计、
    FramePacer 描述修正、Citrix ADMX 归属核实）：`55269ac6` → `b0db68f4`（MR 10）。
  - E1 Wave C：剩余三个手感常量参数化（召唤宽限 1–6s/默认 2.5s、甩动行程
    400–1200pt/默认 700pt、idle 把手厚度 10–20pt/默认 14pt），
    绘制与命中同用 `effectiveIdleThickness`：`6960b92c` → `6bf491c1`（MR 11）。
  - Wave D CI 硬化：GitLab 侧 `mutation-battery` job、镜像重试退避
    5/15/30/60/120s、单 runner 并发文档：`1e36aac5` → `27e03f92`（MR 12）。
  - Wave E-A 上游回吸（LI_CTYPE_STEAM / MODIFIER_EXTENDED strip /
    UTF-8→CTRL_CHANNEL_KEYBOARD / 双触摸板 TouchEvent2）：`e2ffee0c` → `98d68c5e`（MR 14）。
  - 变异电池移出发布路径（verify stage + `macos-battery` resource_group）：
    `4a692db1` → `b63f8d35`（MR 15）。
  - IME 组合判定改看 TIS source type 白名单，不再看本地化名字（实测
    macOS 27.2 上 285 个可选键盘源误判 127 个）：`34ccb922` → `d394d525`（MR 16）。
  - Wave E-B 子模块 bump 到 `ff18621`（自适应扳机哨兵消越界读 + 丢包统计
    BbPut32 + 断连拦截只对等校验）：`da21d787` → `b10a4065`（MR 17）。
  - 电池诚实性：编不出探针就不算捕获变异（`PROBE_BUILD_FAILED_MESSAGE` 哨兵 +
    `gate_failed()` 返回 unproved）、keyboard harness 同口径、审计前显式取子模块：
    `c078d6ee`/`7137d0ad`/`5a08b1e4` → `8fd474db`（MR 18）。
  - K1.2 客户端诚实性（退格按 grapheme cluster 删除、`setMarkedText:` 光标 clamp、
    `selectedRange`/`attributedSubstringForProposedRange:` 真实回读）：
    `f29cacb8` → `8f97ba8f`（MR 19）。
  - 目标模式提示词基点刷新（至 `8f97ba8f`）：`1bb6ae42` → `2fa306f6`（MR 20）。
  - 变异电池 held-key 变异体改为可编译 + 未证明可读（`unproved` 而非静默通过）：
    `5884c6db` → `27b1206e`（MR 21）。
  - 诊断报告「功能生效态」区块（六手感参数生效值 + 六开关 yes/unknown + 指针路径 +
    视频 codec/帧计数 + 重连退避实时状态；顺带修 `compile-audit.py` 生成头按
    configuration 折叠、`constraints-audit.py` 报告门禁 CI-only 豁免两处可信度问题）：
    `25a374c5` → `127b4eb2`（MR 22）。
- 审批边界（不变）：开发分支 → MR → 准确 SHA 的 CI → 实际审核者审批；
  开发用 codex 凭据，审批/合并只用 owner（liguangming）凭据，禁止为 403 提权、
  禁止借 VM root 或 Rails 代替他人审批。
- 镜像由 `publish-github` job 单向发布；只核对本 ref 的双端 SHA，
  不凭发布成功宣称全仓一致。
- 最新**已验证** DMG 仍是 `build2021`（main `127b4eb2`，pipeline #733 job 4047，
  8,310,145 B，SHA-256
  `0591500abb224fae7f6ab0e52a1bc9b7076150618a69421edf14c7dc4cae5676`，
  `hdiutil verify` VALID、包内 `CFBundleVersion=2021`、
  `codesign --verify --deep --strict` OK，ad hoc 签名）。验收记录见
  `moonlight-ci-evidence/20261028-wave-f-feature-state/release-verification.json`。
  之后 main 各基点的 `package-dmg` 已产出到 `build2036`（#789 job 4572）、
  `build2041`（#813 job 4788），最新到 `build2063`（#895 job 5580），
  但**这些包都没做过包内三件套验收**，不得当作"已验证产物"引用。
  本机 `/Applications/MoonlightEnhanced.app` 实测为 **build2029**（`plutil` 读回），
  既不是 2021 也不是最新的 2063。
  旧版回滚链保留在 `/Applications/MoonlightEnhanced.app.b{1933,1984,1993,2015}`。
- `hardware_validated=false` 保留：0.2/M1/M2/M3/M4/K1.1/K1.2/E1/P2-1/P2-2/P2-3
  全是代码层完成 + CI 绿 + 真机待取证。

## 2. 已完成（代码层；CI/产物验收；真机仍待）

| 编号 | 提交 | 状态 | 备注 |
| --- | --- | --- | --- |
| 0.1 控制器诊断 | `a85c5879` | 代码+CI+DMG 完成 / 真机待 | `Moonlight-1.6.0-build1933.dmg` |
| 0.2 per-device HID 状态 | `19b68a22`/`f42f4002`/`aa99a860`/`69eb84ef`/`85ac0008` | 代码完成 / 真机待 | 单手柄逐字节等价已录制 |
| M1 arrival/type/caps + 拔出清位 | `cd42716a` | 代码完成 / 主机侧待 | `LiSendControllerArrivalEventCtx` 已接 |
| M2 按号震动 + setControllerLED + rumbleTriggers | `81f404be`/`e8c943a0`/`b8925df5`/`6109b363` | 代码完成 / 真机待 | per-number 去重 + 单手柄基线 |
| M3 IMU + 电量 + 触摸板 | `75ed217d`/`f5f5520a`/`c0707e70` | 代码完成 / 真机待 | PS4/PS5 触摸板 12 位坐标状态机 |
| M4 Joy-Con 收口 | `7c5b687f` | 代码完成 / 真机待 | 单只 Joy-Con 057E:2006/2007 |
| K1.1 可打印 Unicode | `34e921a3`/`798050d9`/`08616a19` | 代码完成 / 真机待 | 与键码路径互斥 |
| E1 边缘栏参数化 | `622132b3` | 代码完成 / 真机待 | 感应带 8–16pt / 驻留 60–300ms / 收起 300–1000ms，默认值 = 现常量 |
| P2-1 自由鼠标走绝对坐标 wire path | `9426623b` | 代码完成 / 真机待 | 默认关闭；UI 纯新增；谓词三条件，5 秒绝对参考 |
| P2-2a 退避状态机（terminated/stage/menu）| `c5c87fd2` | 代码完成 / 真机待 | `MLStreamReconnector` 1s/3s/9s，host-gone wrapper 写出但当时无 production caller |
| P2-2b 诊断触发器 + host-gone 真 caller | `41477a83`（merge `3b5ae07c`）| 代码完成 / CI 全绿（#471/#473）/ 真机待 | connect-timeout / startup-no-payload / payload-stall 接入退避；graceful + unexpected-early trigger `markHostConfirmedGoneFromDiagnosticsWithReason:`；transient 错误码仍走退避 |
| P2-3a 失焦静音（三后端）| `4e6fba87` + `dc1135bc`（merge `b65db5fb`）| 代码完成 / CI 全绿（#482）/ 真机待 | `Connection.setAudioFocusMuted:` 单入口：LegacyQueue `kAudioQueueParam_Volume` / Enhanced `mainMixerNode.outputVolume` / Direct 渲染回调帧级静默；默认 false |
| P2-3b 失焦抑制手柄事件 | `26d20062` | 代码完成 / CI 全绿 / 真机待 | 6 个 controller-wire 入口 + MFi `updateFinished:` 加门；4 焦点观察者对称；默认 off；键盘/鼠标不挂门 |
| K1.2 本地输入法组合 | `5c0dbfa3` → merge `fa1c645c`（MR 6 已合） | 代码完成 / CI 绿 / 真机待 | `HIDLocalIME` NSTextInputClient；per-host `imeLocalComposition` 默认 off；uncapture 先 flush 再 end；`keyboard-ime-routing-tests` 双管线 |
| K1.2 客户端诚实性 | `f29cacb8` → merge `8f97ba8f`（MR 19 已合） | 本地门禁 102/0/15 / merge-preview #708 success（跨文件扫描 af=True 已豁免）/ 真机待 | 退格按 grapheme cluster 删除、`setMarkedText:` 光标 clamp、`selectedRange`/`attributedSubstringForProposedRange:` 真实回读 |
| SAS 预置规则 GitLab 门禁 | `58453614` → merge `c8e004d7`（MR 7 已合） | CI 绿 / 已合并 | `sas-preset-tests.py` 接进 GitLab test job；SAS 功能本体早在 `6968286d`（翻译规则预置） |
| E1 Wave C 剩余三常量参数化 | `6960b92c` → merge `6bf491c1`（MR 11） | 代码完成 / CI 绿 / 真机待 | 召唤宽限 1–6s（默认 2.5s）/ 甩动行程 400–1200pt（默认 700pt）/ idle 把手厚度 10–20pt（默认 14pt）；绘制与命中同用 `effectiveIdleThickness` |
| IME 组合判定改看 TIS source type | `34ccb922` → merge `d394d525`（MR 16） | 代码完成 / CI 绿 / 真机待 | 白名单按 source type 而非本地化名字（macOS 27.2 实测 285 个键盘源旧法误判 127 个） |
| Wave D CI 硬化 | `1e36aac5` → merge `27e03f92`（MR 12） | CI 绿 / 已合并 | GitLab 侧 `mutation-battery` job、镜像重试退避 5/15/30/60/120s、并发文档 |
| 变异电池移出发布路径 | `4a692db1` → merge `b63f8d35`（MR 15） | CI 绿 / 已合并 | verify stage + `macos-battery` resource_group，不再阻塞 DMG |
| 电池诚实性（编不出探针不算捕获） | `c078d6ee`/`7137d0ad`/`5a08b1e4` → merge `8fd474db`（MR 18） | CI 绿（#706 14/14）/ 已合并 | `PROBE_BUILD_FAILED_MESSAGE` 哨兵 + `gate_failed()` 返回 unproved；审计前显式取子模块 |
| Wave E 上游回吸 | `e2ffee0c` → merge `98d68c5e`（MR 14）；`da21d787` → merge `b10a4065`（MR 17） | CI 绿 / 已合并 | E-A 四项协议修复；E-B 子模块 bump `ff18621`（自适应扳机哨兵消越界读 + 丢包统计 + 断连拦截对等校验） |
| 诊断报告「功能生效态」区块 | `25a374c5` → merge `127b4eb2`（MR 22） | 本地门禁 103/0/15、全量 Release 构建成功 / merge-preview #732 success（跨文件扫描 af=True 已豁免）/ 真机待 | 六个手感参数报生效值并标 shipped-constant 或 overridden/clamped；六个开关仅 profile 真有值才给 yes/no，否则 unknown；指针路径取 input ledger 实况；视频 codec/帧计数/是否曾有流；重连退避实时状态。profile 只报 global/per-host 名称不含 UUID，全部值走既有 redaction |
| 变异电池 held-key 变异体可编译化 | `5884c6db` → merge `27b1206e`（MR 21） | CI 绿（#716/#717/#719）/ 已合并 | 变异体编不出探针时如实报 `unproved`，不再伪装成已捕获行为变异 |
| 诊断报告机器可读镜像（Wave I） | 本分支 | 本地门禁 105 checks / 0 failures（含 6 个新行为变异）/ CI 待 / 真机待 | `machineStateSectionWithState:snapshot:` 之前是死代码，无人组装；现接入 `currentReport`，与散文块共用同一次读取的 `DiagnosticsFeatureState` + inventory 快照。键名契约见 §4.1 |
| 真机验收判读器 + 操作单（Wave I） | 本分支 | 自测 7 项契约 + 2 个弱化判读器被拒 / 双管线已接线 / 真机待 | `scripts/hardware-acceptance-check.py` 把 §4 七行判据变成可执行判读：报告证明设置生效 + 观测者声明绑定该报告 SHA，两半缺一即 `UNKNOWN`；动作→键→期望值见 `docs/hardware-acceptance-checklist.md` |
| Steam Controller 按 STEAM 通告 | `0c6b93df` → merge `6bd3fad3`（MR 34） | 代码完成 / CI 绿 / 真机待 | 不再误判为 Xbox 类型 |
| 诊断报告来源字节命名 + 验收判分（Wave Q） | `cccbfde0` → merge `27e076fe`（MR 37） | 代码完成 / CI 绿 | 报告自带来源指纹，判读器可绑定 |
| 出厂镜像自证内容（Wave R） | `805d0e2b` → merge `c8e959d0`（MR 38） | 代码完成 / CI 绿 | DMG 内本地化与包内容自证 |
| 报告导出即判读器哈希的字节（Wave S） | `6d8e2680` → merge `71a62394`（MR 39，pipeline 883 全绿） | 代码完成 / CI 绿 | 生产者与消费者首次相连；`ml.build.git_commit` 不再被脱敏正则吞掉 |
| 七行验收判据建立在导出字节上（Wave T） | `fd3557fd` → merge `bf055b23`（MR 40） | 代码完成 / CI 绿 | 验收矩阵不再全 `UNKNOWN` |
| 对标来源矩阵自证（Wave U） | `7bf5e2c6` → merge `b7be1dec`（MR 41） | 代码完成 / CI 绿 | `source-matrix-audit.py`：规则三集合相等（13 codes）+ 14 变异逐条 caught + 断链报 SM001 不崩审计 |
| 桥接默认值分叉修复（Wave V） | `f6b071fe` → merge `c1f0eeac`（MR 42，#897 success） | 代码完成 / CI 绿 | `ignoreAspectRatio` 三层默认值统一为 false；用户可见路径零变化 |
| Wave AC 未捕获页声明缺口状态 | `cbaefdf3` → merge `18921771`（MR 52） | 代码完成 / CI 绿 / 真机待 | 未捕获渲染页不再 claim flat，判读器分得开「从未捕获」与「真的平坦」；`render-probe.py --self-test` 进事实源管道 |
| Wave AD 仅在磁盘存在时命名 artifact | `8b7f6b46`（同 MR 52） | 代码完成 / CI 绿 / 真机待 | `MLProbePixelsHaveArtefact()` 统一三处调用；判读器把未测量/未落盘/沉默/自相矛盾各说各话 |
| Wave AB 装配层审计 | `7721bcd6` → merge `60ddce2c`（MR 51） | 代码完成 / CI 绿（#1051）/ 真机待 | 设置字典 → `StreamConfiguration` 这一跳首次有审计覆盖 |

## 3. 待开工（按优先级，不依赖真机排期）

> 所有未开工项必须遵守：默认值 = 当前行为、UI 纯新增、门控先证明自己会失败再放开。

### 3.1 K2 Ctrl+Alt+Del（2026-10-25 复核：功能本体已存在）
- **SAS 能力本体早在 `6968286d`（2026-09-20）落地**：`KeyboardTranslationProfile.secureAttentionSequencePresetRule()`
  在设置 > 快捷键 > "Add Preset Rule" 提供预置翻译规则，Ctrl+Option+FwdDel（macOS 键位）→
  Ctrl+Alt+FwdDel（主机 SAS 键位），走已有 translation-rule 机制，`sas-preset-tests.py` 守护。
- 机制选择 = 发现性而非新机制：macOS 不像 Windows 吞 SAS，普通转发路径本就能送三键；玩家缺的是找到它的方式。
- **剩余缺口（已闭合，MR 7 已合并为 `c8e004d7`）**：该门禁此前只接在 GitHub workflow（镜像侧），
  GitLab 事实源缺跑 → 已补进 GitLab test job 必跑项。
- **真机验证仍待**：用户装新 build 串流 → 用预置规则（或默认 Ctrl+Alt+FwdDel 直发）→ 主机 SAS 是否拉起。
  拉不起 → 文档降级为"提示用主机端工具"，不虚报。

### 3.2 P2 对等补齐（各自独立小提交，可与 K2 并行）
1. ~~`LiSendMouseMoveAsMousePositionEvent`~~ —— 已落地于 `9426623b`（见 §2）。
2. 重连退避状态机：
   - ~~terminated + stage-failed + menu retry~~ —— P2-2a (`c5c87fd2`) 已收口（main 8/8 success）。
   - ~~connect-timeout + startup-no-payload + payload-stall 三个诊断触发点 + host-gone 真 caller~~ —— P2-2b (`41477a83`) 已收口（已合并，历史 pipeline #471/#473 success）。
   - 当前覆盖全部 5 类自动 trigger 与 menu retry；host-gone 仅在 graceful (0) 与 unexpected-early (-102) 触发；transient 错误码仍走退避。
3. ~~qt 对等项打包~~ —— 拆为 §3.2.1 三条独立计划。
4. **桌面档绝对鼠标默认关**（已写明：旧游戏兼容场景别开）。

### 3.2.1 P2-3 收口状态（2026-10-24 P2-2b / P2-3a / P2-3b 全部落地后复核）

- `playAudioOnHost` —— 已存在（xib checkbox → `playAudioOnPC` → launch URL
  `localAudioPlayMode=%d`）；roadmap 描述已修，不留 TODO。
- `muteOnFocusLoss` —— **三后端已收口并在 main**：LegacyQueue `4e6fba87`（#433）+
  Direct/Enhanced `dc1135bc`（merge `b65db5fb`，pipeline #482 8/8）。Enhanced 走
  `mainMixerNode.outputVolume`（mute 缓存当前值、regain 恢复 1.0）；Direct 因 output unit
  无公开 volume 参数（macOS SDK 下 `kAudioUnitParameters_Volume` 不存在，编译实证）改为
  渲染回调按 latch 帧级静默。StreamViewController 接线与 SettingsModel 均不变。
- `backgroundGamepad` —— **已收口**（commit `26d20062`，pipeline #434 = 8/8 success）。
  HID 6 个 controller-wire 入口 + MFi `updateFinished:` 同步加门；4 个焦点观察者对称
  （window/app resign 按 per-host pref 写 YES，window/app become 无条件恢复 NO）；
  默认 off 保留 shipped 行为；键盘 + 鼠标路径不挂新门。详见 §15 + baseline §15。

### 3.3 K1.2 marked text / 候选窗 / 输入法提交（依赖 K1.1 已收口）
- 已合并（MR 6 → `fa1c645c`）：`HIDLocalIME`（`MLLocalIMETextClient` + `MLLocalIMESession`）挂
  keyDown/keyUp/flagsChanged；per-host `imeLocalComposition` 默认 off；候选窗屏幕坐标；
  原始键码与文本所有权互斥；断流 uncapture 先 flush 再 end。
- 已合并（MR 16 → `d394d525`）：组合判定改看 TIS source type 白名单，不再看本地化名字。
  公开 TIS 属性读取，不把不透明输入源强转字典，不按语言白名单猜组合输入法。
- 已合并（MR 19 `f29cacb8` → `8f97ba8f`）：客户端诚实性——`doCommandBySelector:` 退格按 grapheme cluster 删除、
  `setMarkedText:selectedRange:` 光标 clamp、`selectedRange` /
  `attributedSubstringForProposedRange:` 真实回读（越界返回 `{NSNotFound,0}`）。
  这三处此前只有注释声称已实现，实为空壳；仅回放 `insertText:` 不构成真实输入法验收。
- 验收契约见 §15；真机中文注入（整串提交、候选窗锚点、退格可删、长按重复、失焦/断流取消）仍未取证。
- 键盘接收路径纪律不变：若 6 个键盘门禁脚本（keyboard-concurrency /
  keyboard-modifier-mapping / keyboard-shortcut-modifier / keyboard-source-quirk /
  keyboard-unicode-routing / held-modifier-keyboard-pair）任一无法转绿，**只保留 K1.1**，K1.2 关闭。

### 3.4 工具链 / 流程增量（与上述并行）
- **门禁纳入 GitLab 必跑项：已闭合（Wave H）**。原"复核有无遗漏"现在有可复跑的判据：
  `python3 scripts/gate-coverage-audit.py --verify` 解析两份定义并要求镜像调用的每个门禁在
  事实源可达。基点实测镜像调 `87` 个门禁、事实源只可达 `33` 个（54 条 `HC001`），当前
  `88` 全部可达、`violations=0`（`88` 含审计自身在两份定义里的调用）。M4.3/M4.4 的 `controller-device-table-tests.py` / `diagnostics-report-tests.py`
  等已在事实源显式调用，故不重复出现在 `--class=fast`（47 条） emission 中；未显式写出的门禁
  由 `audit:gates` 在运行时按类别取回并逐条执行（另 5 条 self-test 形态、2 条编译型走 tag/main 的
  `audit:deep`）。规则、豁免语义与两条已记录盲区见 `docs/gitlab-ci.md`「Gate parity across both
  definitions」。
- 已知 CI 教训：reconfigure 后 nginx :80 → SSL-only，runner URL/tag 必须回读；Mac runner 短暂失联+macos tag 丢失会让 job 落到 Linux（swiftlint 缺失）。
- 本波新增教训：`.gitlab-ci.yml` 的 plain scalar 里不能出现 `: `（`echo "fast gates: $(...)"`
  会让整份定义 YAML 解析失败）。判据本地就有——`scripts/ci/test_pipeline.py` 用与 GitLab 相同的
  解析器加载该文件，且已被 `local-gates.sh` 纳入，改 CI 定义后跑它就等于预检。

### 3.5 common-c 上游回吸：Wave G 移植结果（2026-10-29 逐 commit 源码复核）

> 本节 2026-10-28 首次核实时把 G-1/G-2 记为"待移植"，那是 submodule 仍在 `ff18621` 时的快照。
> 之后两项均已移植并合入，main 的 submodule pin 已推进到 `abe83b8`。以下 fork 侧行号
> 全部在 `moonlight-common/moonlight-common-c`（pin `abe83b8`）内 `grep -n` 复核，
> 不是照抄 `docs/common-c-drift-2026-10-26.md` 的旧建议，也不是沿用上一版本节的旧结论。

| 上游 commit | 内容 | fork 侧现状（已核实） | 处置 |
| --- | --- | --- | --- |
| `0405384` | `NV_UNICODE_PACKET` 密集打包：Sunshine 一包容多码点，且 Sunshine 分支跳过 GFE 专用 flush + 50 ms 等待 | **已在 main**：子模块 fork `5f777b4`（merge `d11100a`）→ 主仓 `aca93699` → merge `a539c604`（MR 25）。取证：`src/InputStream.c:613` `unicodeNeedsControlStreamFlush()`、`:621` `unicodeChunkLength()`、调用点 `:967`/`:982` | 无需动作。真机收益（中文长文本包数与 50 ms 阻塞消失）仍待 §4 取证 |
| `448b2c6` / `421bd74` | 相对鼠标 delta 先 latch 到局部变量再分包，避免输入线程被高速相对鼠标独占 | **已在 main**：子模块 `f740e75`（merge `abe83b8`）→ 主仓 bump `43c6e835` → merge `32421c28`（MR 26）。取证：holder 字段 `src/InputStream.c:74` 起、latch `:794`、button 事件结束批次 `:1367` | 无需动作。fork 侧网络 I/O 本就不在锁内，未重复搬"释放锁"的 hunk |
| `970b072` | 修复 queued controller packet 的 use-after-free（队列满 / 连接终止两条路径） | fork 侧**不存在** `currentQueuedControllerPacket`（input edge queue 重写已移除该全局缓存，`sendControllerEventInternal` 直接入队不复用 holder） | **不适用**：不硬套补丁，只在 drift 文档记录"上游修的风险面我们已不存在" |
| `41cedb8` | `ignoreDisconnectIntercept` 只对发给本 peer 的 ENet DISCONNECT 生效 | `src/ControlStream.c` 已含 peerID/sessionID/地址三重校验（Wave E-B `f65f5b3` 已吸） | **已在 main**，无需动作 |
| `62e0663` | 只在 RFI 真正启用时才上报 speculative 丢帧（否则等于对主机撒谎） | **已在子模块 master**（main 尚未取用，pin 仍 `abe83b8`）：子模块 fork `5340b26`（merge `093098f5`）→ 主仓 bump `6e1aa0b1`（MR 32 在途）。取证（子模块 `093098f5` 内）：`src/RtpVideoQueue.c:230` 预判分支已被 `isReferenceFrameInvalidationEnabled() &&` 收口 | 待 MR 32 合并。真机收益（弱网下不再向主机发无效 RFI）待 §4 取证 |
| `d85371c` | multi-block 帧损后必须复位 `reportedLostFrame`，且用实际包 `frameIndex` 而不是 `currentFrameNumber` 上报 | **已在子模块 master**：fork `c759034`（同一 merge `093098f5`）。取证（同上）：`src/RtpVideoQueue.c:672` 已用 `nvPacket->frameIndex`、`:677-681` 起带 NB 注释复位为 `false` | 待 MR 32 合并。弱网连续丢帧的 RFI 范围正确性待真机取证 |
| `be43885` | 丢掉「部分已处理的 IDR 帧」时必须重新要求 IDR，不能降级成 RFI | **已在子模块 master**：fork `49cfe3a`（同一 merge `093098f5`）。取证（同上）：`src/VideoDepacketizer.c:156` `dropFrameState()` 条件已含 `(nalChainHead && ctx->frameType == FRAME_TYPE_IDR)` | 待 MR 32 合并。IDR 半包丢弃后的花屏恢复路径待真机取证 |

等价性取证方式（G-3 按此执行，记为可复核事实）：`git cherry-pick` 法因冲突污染结构不可用；
改用提取上游与 fork 两侧 diff 的 `-/+` 文本流、归一化 fork 适配点
（`notifyFrameLostCtx(...)`/`ctx->frameType` 一类上下文形参）后逐一比对，
三组 `5340b26↔62e0663`、`c759034↔d85371c`、`49cfe3a↔be43885` 均
`removed_equal=True added_equal=True`，且 `git diff --name-only abe83b8 49cfe3a`
只有 `src/RtpVideoQueue.c`、`src/VideoDepacketizer.c` 两个文件，无夹带改动。
fork 侧 `notifyFrameLost()`（`src/VideoDepacketizer.c:1244`）保留为取全局上下文的薄封装，
不构成语义差异。

移植纪律（G-1/G-2 已按此执行完）：一次一个 commit 一个分支；先让门禁脚本证明能抓到
"Sunshine 路径没走密集打包"、"非 Sunshine 主机仍被密集打包"、"delta 未 latch 就发第一包"
三类变异，再放开；子模块先合（子模块 CI 到终态）→ 主仓只 bump submodule SHA 一条 MR；
`IS_SUNSHINE()` 判据不自己造，复用 `src/Limelight-internal.h:71`。

## 4. 待真机验收（独立保留，不阻塞下一波代码）

> 真机验收不阻塞代码侧下一波；但每波必须保留 `hardware_validated=false` 标签。

1. 装最新可装 build（见本节末）接入两块手柄（建议 PS5 + Xbox Series / 单只 Joy-Con + Pro Controller），开流并核诊断分类、会话驱动、通告状态、玩家编号。
2. `Sunshine` 与 `GFE` 双主机侧：虚拟手柄类型、按键图标、拔出时序、IMU/电量/触摸板事件。
3. 键盘 K1.1：主机端微信/浏览器输入法实测中文 + emoji + 全角字符 + 长按重复。
4. 全屏侧边栏参数化（E1 + Wave C 共六项）：单屏 + 双屏 + 全屏菜单栏遮挡场景，
   并验默认值手感与参数化前一致（未动滑块时不得有任何差异）。
5. K1.2（需先把 per-host `imeLocalComposition` 打开）：中文整串提交无重复字、候选窗锚点、
   退格逐字删除、断流/失焦丢草稿、开关 OFF 时恢复 shipped 直通。
6. K2/SAS：用预置规则或直发三键，看主机 SAS 是否拉起。
7. P2-1 绝对鼠标（桌面档 + 开关开启）、P2-2 断网/主机关闭退避、P2-3a 三后端失焦静音、P2-3b 后台手柄抑制。

- 当前可装产物：`Moonlight-1.6.0-build2019.dmg`（main `27b1206e`，pipeline #719）；
  main `127b4eb2` 的产物以 pipeline #733 的 `package-dmg` 为准。
  本机 `/Applications/MoonlightEnhanced.app` 实测 build2015，尚未替换到 2019。
- 验收取证方式（MR 22 之后）：每一盒验收都从 app 内导出一份诊断报告，
  报告的功能生效态区块给出六个手感参数生效值、六个开关 yes/unknown、指针路径、
  视频 codec/帧计数与退避状态；报告读不到该项就写 unknown/no stream window，
  不得用目测结果替代报告值，也不得把"报告里是默认值"当成"真机行为已验证"。

- 验收取证方式（Wave I 之后）：同一份报告末尾的 `machine` 区块可直接判读，
  不再靠人眼读散文。判读器 `scripts/hardware-acceptance-check.py`（自测已入双管线门禁），
  操作单 `docs/hardware-acceptance-checklist.md`（动作 → 导出 → 判据键 → 期望值）。
  判读规则见 §4.1；未测到的项一律 `unknown` 或
  `present=no`，**缺失键与值为 0 是两件事**，判读脚本不得把缺项当 0。
  一行判 PASS 需要两半：报告证明该设置本局生效，且观测者声明的 `report_sha256`
  绑定这份报告；只有其中一半只能是 `UNKNOWN`。

### 4.1 `machine` 区块键名契约（Wave I）

一行一键，`key=value`，key 内无空格；以 `#` 开头的行是注释（只有区块头那一行）。
`ml.schema=1` 是该契约的版本号，增删键语义时递增。

| 键 | 含义 |
| --- | --- |
| `ml.build.git_commit` | 产出这份报告的二进制来自哪个 commit；解析不到就是 `unknown`（源码包、或该键之前的构建）。判读器把它当**整张矩阵的前提**：非完整 40 位小写十六进制 ⇒ 全部行 `UNKNOWN` |
| `ml.build.version` / `ml.build.number` | bundle 自报的营销版本与构建号，用于把报告和已发布 DMG 对上；构建号是分支内单调计数，**不能**代替 commit 定位源码 |
| `ml.profile` | `per-host` / `global` / `unknown`，固定三词，可跨报告比对 |
| `ml.param.<snake_key>.{effective,shipped,range,written,state}` | 六个手感参数；`state` ∈ `shipped` / `override_of_<v>` / `clamped_below_<min>` / `clamped_above_<max>`，界值保留小数位 |
| `ml.switch.<key>` | `on` / `off` / `unknown`；`unknown` = 该 profile 从未写过这个开关 |
| `ml.pointer.{mouse_mode,path,absolute}` | 指针路径实况；未记录 = `unknown`，不推断为相对 |
| `ml.video.present=no` | 无视频计数；此时 `ml.video.*` 其余键**不出现** |
| `ml.video.frames.{received,decoded,rendered}` / `.fps` / `.jitter_ms` / `.bytes` / `.format` | `bytes` 是裸字节，不预除 MiB |
| `ml.reconnect.present=no` | 没有 reconnector 持有计数器；此时 `ml.reconnect.*` 其余键不出现 |
| `ml.reconnect.{attempt,max,pending,host_confirmed_gone}` | 退避实时状态 |
| `ml.controllers.present=no` | 无手柄会话快照 |
| `ml.controllers.{sessions,recording,driver,arrivals}` | 会话代数、是否在录、会话启动时记录的 HID 驱动、arrival 是否已发主机 |
| `ml.controllers.slot.<N>` | 主机被告知的玩家槽类型（`xbox`/`ps`/`nintendo`/`unknown`）——**验收按槽位数判断手柄数** |
| `ml.controllers.caps.{analog_triggers,rumble}` | 已通告能力逐项一键，未实现能力不得出现 |
| `ml.controllers.group_count` | VID/PID/family 身份分组数 |
| `ml.controllers.group_count_is_physical_devices=no` | 上一行的限制写成独立键：同型号两只会合成一组，**不得当物理手柄数** |
| `ml.controllers.group.<N>.{vid,pid,family,type_map,transport,battery_percent,nodes}` | 逐组身份；`battery_percent` 为裸数字或 `unknown`（`0` 表示真的空电） |

`type_map` 只是本地协议类型候选，不等于已向主机通告；通告与否看 `arrivals` 与 `slot.<N>`。

## 5. 冻结项（不动）

- USB 真实重定向通道、Developer ID 公证 / 正式签名、自动更新 → README 边界表如实保留，不自行解冻。
- 设置页原生外观（macOS27 `NSSegmentedControl` + `role=.tabs`）+ 既有手感默认值 → 不可撬动。
- 90FPS 插帧稳定性、29ms 队列延迟 → 单独排期，不因对标作战自动解冻。

## 6. CICD 标准（每轮执行，不可降级）

1. 改代码 → `bash scripts/local-gates.sh`（默认快速，完整变异电池仅 `--all`）→ 0 failed，skip 逐项列名
2. 新行为 → 新增门控脚本（必须含 self-test，证明自己会失败）并接入 CI
3. `git -c user.email="codex-agent@homelab.local" -c user.name="Codex Agent" commit`
4. `git push gitlab <branch>`，创建指向受保护 main 的 MR；push 后等 30s+ 再查准确 SHA 对应 pipeline，全绿才算通过；失败修复后重推，不绕过
5. GitHub（opsbsligm）由 `publish-github` job 单向镜像，只读，不手推
6. 每波写一份 `moonlight-ci-evidence/<日期>-<主题>/release-verification.json`，记录 commit / pipeline / DMG / SHA256 / `hardware_validated` / mirror refs

## 7. 对标范围（持续维护，不缩水）

- 来源矩阵（逐格版本/验证日期/证据层级）：`docs/source-matrix-2026-10-25.md`。对象：`moonlight-qt`（上游客户端）/ `moonlight-common-c`（协议 fork 点 `62687809`，当前 pin `ff18621`，Wave E-B）/ `Sunshine` + 基地版（主机）。
- 竞品矩阵：`Citrix` 与 `Horizon`（分别评估；旧 ADMX 证据需核对归属）/ `Parsec`（无证据，不断言）/ `网易 UU 远程`（宣传面，手机赛道不与桌面客户端直接对照）/ `深信服 aDesk` / `锐捷云桌面`（如需新增列入"待调研"）。
- 每格区分：源码 / 官方资料 / 实测 / 宣传 / 未知；既有文档未覆盖的产品继续列为"待调研"，**不编造**已完成全面对标。

## 8. 关键文件（修改前必须先读）

| 用途 | 路径 |
| --- | --- |
| 标签页 UI（系统原生 tabs） | `Limelight/macOS/ViewControllers/LiquidGlass/LiquidGlassTabBar.swift` |
| 帧节奏（已接入 VideoDecoderRenderer：6 处 `_pacer` 引用 + `MLFramePacerDelegate`，见 VideoDecoderRenderer.m:1546/1696/2124/3507/5952/6161/6209） | `Limelight/Stream/MLFramePacer.h/.m` |
| 真正生效的帧队列 | `Limelight/Stream/VideoDecoderRenderer.m`（desiredEnhancedDrawableDepth / desiredPendingFramesForDisplayRefreshRate） |
| 带宽追踪 | `Limelight/Stream/MLBandwidthTracker.h/.m` |
| 解码渲染核心 | `Limelight/Stream/VideoDecoderRenderer.m` |
| 串流控制栏 | `Limelight/macOS/ViewControllers/MLEdgeMenuUI.m` |
| 设置面板 | `Limelight/macOS/ViewControllers/` |
| USB 侧边状态 | `Limelight/Stream/USBMenuStatus.h` |
| 玻璃容器 | `Limelight/macOS/Views/GlassOverlayContainer.h/.m` |
| 快捷键 OSD | `Limelight/macOS/ViewControllers/StreamViewController+Diagnostics.m` |
| 控制器诊断 / HID | `Limelight/Input/HIDSupport+Inventory.m`、`Limelight/Input/MLControllerInventory.h/.m` |
| 诊断报告 | `Limelight/macOS/Helpers/DiagnosticsReportBuilder.h/.m` |
| 审计基线 | `scripts/analyzer-baseline.json` |
| GitLab 构建/镜像 | `.gitlab-ci.yml` |
| 镜像端补充审计 | `.github/workflows/build.yml` |
| 边缘栏手感常量 | `Limelight/macOS/ViewControllers/StreamViewController_Internal.h:100-162` |

## 9. 不可撬动的底层（与 `docs/baseline-2026-10-22.md` §1–§7 对齐）

- 唯一事实源 GitLab `https://gitlab.example.com:8445`（源站 `192.0.2.1`，API `https://192.0.2.1:8445`），project id 6。
- 提交身份固定 Codex Agent / codex-agent@homelab.local；不绕门禁。
- 设置页原生 `NSSegmentedControl` + `role=.tabs`（commit `00315f0f`）。
- 全屏侧边栏手感默认值：感应带 12pt / 驻留 0.12s / 收起 0.45s / 召唤宽限 2.5s / 甩动 700pt-0.25s / 把手 14-30-48pt / 点击余量 2pt；E1 只参数化其中三项，默认值 = 现常量。
- 协议诚实：未实现的能力不向主机通告；type-map ≠ 已通告；报告/UI 必须区分两者。
- 验证纪律：未真机一律 `hardware_validated=false`；"单手柄发包不变"必须用录制的逐字节对比证明；跳过的门禁逐项列名，skip 不算 pass。
- 新增设置项：默认 = 当前行为；UI 纯新增。
- 冻结项不自行解冻（USB 真重定向、Developer ID 公证/正式签名、自动更新）。

## 10. 历史计划（保留追溯；当前基点以上文 §1–§9 为准）

- 作战计划原文：`docs/campaign-plan-2026-10-20.md`
- 对标矩阵原文：`docs/competitive-polish-roadmap-2026-10-20.md`
- 输入映射证据：`docs/input-mapping-benchmark.md`、`docs/input-mapping-design.md`、`docs/input-mapping-review.md`

## 11. 下一步执行

（2026-11-01 六次刷新）**代码层里程碑 0.1→P2 + K1.1/K1.2 + Wave B/C/D/E/H/I/K/Q/R/S/T/U/V/W
已全部在 main**；MR 1–44 全合并，**在途 MR = MR 45（Wave X）**，main 基点 `1031a42a`。
`docs/common-c-drift-2026-10-26.md` 的"未取待定"四类中，RFI 修复族已随 G-3（MR 32）处置完，
剩下的 `342b106`（control stream 就地加密）、`f1cca2d`（pen event 批处理）、
`7022b33`/`1fddbcb`（BSD socket 错误重构 / rswrapper 头泄漏）仍未评估，
不是遗漏就是待定，不得当作已完成。

1. **本文档自身的收口**：本 docs 分支 → 准确 SHA CI 到终态 → `liguangming` 审批合并 →
   回读 MR 状态 / 合并者 / main 新 SHA / 合并 pipeline 终态。
   `跨文件静态安全扫描` 在本环境 `allow_failure=true`，只能记为「已豁免」，不得计入通过。
2. **真机验收矩阵（当前唯一的真实缺口）**：`hardware_validated` 自项目开始就是 `false`，
   Wave Q→V 五波都在给"验收能不能被机器复核"上地基，而验收本身一次没做。
   装 DMG（build 号以 main 合并 pipeline 的 `package-dmg` 产物为准；`b7be1dec`/`#895`
   job 5580 已产出 `build2063` 但**未做包内三件套验收**，装之前先补
   `hdiutil verify` + `codesign --verify --deep --strict` + `CFBundleVersion` 读回）→ 串流 → 逐项取证：
   0.1 双手柄诊断分类 / 0.2 双手柄互不覆盖 / M1–M4 主机侧类型、震动、IMU、电量、触摸板 /
  K1.1 中文 + emoji / **K1.2 本地输入法组合（开 per-host 开关验 §15 契约）** /
   K2 SAS 拉起 / E1 单双屏边栏 / P2-1 绝对鼠标 / P2-2 断网退避与主机关闭 / P2-3a 三后端失焦静音 / P2-3b 后台手柄抑制。
   判据用 `scripts/hardware-acceptance-check.py`（报告 + 观测者声明绑定报告 SHA，两半缺一即 `UNKNOWN`）。
3. **对标来源矩阵**：Wave U 之后每一格的证据层级由 `scripts/source-matrix-audit.py` 复算，
   但**门禁只能证明"写的和仓库里的一致"，不能把宣传级升成源码级**。Parsec / UU / Horizon /
   Citrix / 深信服 / 锐捷在拿到机制级来源前继续锁"仅宣传"，不升级证据等级。
4. **上游按 commit 回吸**：`docs/common-c-drift-2026-10-26.md` 列 fork 点 `62687809` 之后的漂移与
   17 个交集文件冲突面；逐 commit 判断吸收/拒绝，不整支 rebase。
5. 每波开发分支、MR、准确 SHA CI、`liguangming` 凭据审批合并；`PUT /merge` 必须带 `sha=<head sha>`；
   审核未完成保留 MR，不得用 codex 凭据提权代批。
6. CI 排队已知事实：Mac runner 全局 `concurrent = 1`，多 pipeline 并发时 Mac job 会长时间
   `created/running`，属自愈排队，不是失败；不改 runner 配置、不绕门禁。
7. **默认值一致性检查的可扩展面**（Wave V 的后续，Wave W 已收口）：本项原是一次性人工动作。
   现由 `scripts/defaults-consistency.py` 把守：90 个共享键求值到字面值后判等，
   两层各自 `??` 的回退必须解析到同一个值，求值不出的键进
   `scripts/defaults-consistency-baseline.json` 带可证伪条件的债务账（当前 5 条，
   新增/过期都算 violation）。self-test 17 项，其中 4 项是负对照（语义等价改写必须保持绿），
   改的是源码文本而非内存字典。
   接入面：`.gitlab-ci.yml` 与镜像侧各一次裸审计 + 一次 self-test，
   并由 `constraints-audit.py` 在进程内重跑两种形态，故 `local-gates.sh` 也会跑到。
   扩展方向（未做）：把"新增 `@Published` 设置字段但未在任一层给默认"也纳入检查。

## 12. 历史与现状的界限

历史 CI、DMG、应用安装版本与 refs 数量均注明原验证波次，可能随开发变化。当前交付必须重新读回准确 ref 的流水线与产物；跳过项不能算通过。硬件未验收继续保留 `hardware_validated=false`。

## 15. 本轮 review 与下一波验收契约（2026-10-24）

- 已撤下本轮未接入的 K1.2 草稿：存在输入源误判、组合范围丢失、候选窗坐标为零、提交函数缺输入准入门等问题。未发布，既有输入路径不变。
- 当前 §2 表示代码/历史 CI 状态；本轮未重新验证硬件、安装版本、DMG 哈希或全仓镜像，不将这些历史值作为当前验收结论。
- 首要交付：K1.2 默认关闭实验项，先建立真实方法回放与失败变异，再接生产入口。覆盖英文/游戏按键不变、组合提交/取消、AttributedString、重复键、同键切换路由、失焦/断流取消、候选窗屏幕坐标。
- 第二交付：统一真机验收矩阵：双控制器身份与隔离、主机能力通告/反馈、中文提交、全屏单双屏边栏、三音频后端焦点恢复、断网退避与主机关闭。
- 对标补证：moonlight-qt 与本项目源码上游分别列版本；Sunshine 与基地版明确仓库身份；Parsec、UU、Horizon、Citrix、深信服、锐捷分别列来源/平台/版本/验证日期/未知项。旧矩阵保留为历史，不把宣传升级为实测。
- AI Native 定位：诊断数据结构化、关键事件可订阅、验证结果回流知识库、自然语言动作可追溯；Agent-first OS 与 Agent Swarm 先作架构探索，不引入常驻代理或改变串流热路径。
- 发布边界：默认行为、原生设置 tabs、已验收边栏手感、协议能力诚实及冻结项均保持；每波交付准确 SHA、MR、CI、跳过清单与 `hardware_validated`。
