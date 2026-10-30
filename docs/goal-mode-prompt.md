# Moonlight macOS Enhanced — 目标模式提示词（2026-10-30 三次基点刷新：MR 1–31 全合并 + Wave G-1/G-2/G-3 上游回吸落地 + 门禁覆盖对等已建）

> 用途：续跑本仓库对标作战的"目标模式"提示词。所有续接会话先读 AGENTS.md、`docs/baseline-2026-10-22.md`、`docs/campaign-plan-2026-10-20.md`、本文件和 `docs/competitive-polish-roadmap-2026-10-20.md`，再核对 Git、源码、准确 SHA 的流水线。

## 1. 当前基点（截至 2026-10-30，MR 1–31 全部合并，MR 32 在途）

- 代码基点 main = `18ee83cd`（`Merge branch 'ci/wave-k2-merge-request-pipelines' into 'main'`）。
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
  之后 main 各基点的 `package-dmg` 已产出到 `build2036`（#789 job 4572）与
  `build2041`（#813 job 4788），但**这两个包都没做过包内三件套验收**，
  不得当作"已验证产物"引用。
  本机 `/Applications/MoonlightEnhanced.app` 实测为 **build2029**（`plutil` 读回），
  既不是 2021 也不是最新的 2041。
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

- 唯一事实源 GitLab `https://www.bsligm.com:8445`（源站 `172.16.130.6`，API `https://172.16.130.252:8445`），project id 6。
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

（2026-10-30 三次刷新）**代码层里程碑 0.1→P2 + K1.2 + Wave B/C/D/E/H/I/K 已全部在 main**；
MR 1–31 全合并，main 基点 `18ee83cd`；唯一在途是 MR 32（Wave G-3 RFI 丢帧诚实性
submodule bump `6e1aa0b1`）。`docs/common-c-drift-2026-10-26.md` 的"未取待定"四类中，
RFI 修复族已随 G-3 处置完，剩下的 `342b106`（control stream 就地加密）、
`f1cca2d`（pen event 批处理）、`7022b33`/`1fddbcb`（BSD socket 错误重构 / rswrapper 头泄漏）
仍未评估，不是遗漏就是待定，不得当作已完成。

1. **本文档自身的收口**：本 docs 分支 → 准确 SHA CI 到终态 → `liguangming` 审批合并 →
   回读 MR 状态 / 合并者 / main 新 SHA / 合并 pipeline 终态。
   `跨文件静态安全扫描` 在本环境 `allow_failure=true`，只能记为「已豁免」，不得计入通过。
2. **真机验收矩阵**（不阻塞代码侧）：装新 DMG（build 号以 main 合并 pipeline 的 `package-dmg`
   产物为准，≥ 2014；本机当前仍是 build1993）→ 串流 → 逐项取证：
   0.1 双手柄诊断分类 / 0.2 双手柄互不覆盖 / M1–M4 主机侧类型、震动、IMU、电量、触摸板 /
  K1.1 中文 + emoji / **K1.2 本地输入法组合（开 per-host 开关验 §15 契约）** /
   K2 SAS 拉起 / E1 单双屏边栏 / P2-1 绝对鼠标 / P2-2 断网退避与主机关闭 / P2-3a 三后端失焦静音 / P2-3b 后台手柄抑制。
3. **对标来源矩阵钉版本**：`docs/source-matrix-2026-10-25.md` 目前只有 moonlight-qt v6.2.0
   （快照 `de2467e4`）达到源码级；Parsec / UU / Horizon / Citrix / 深信服 / 锐捷仍是宣传级或未知，
   后续任何对标结论先回矩阵补版本与证据层级，不升级证据等级。
4. **上游按 commit 回吸**：`docs/common-c-drift-2026-10-26.md` 列 fork 点 `62687809` 之后的漂移与
   17 个交集文件冲突面；逐 commit 判断吸收/拒绝，不整支 rebase。
5. 每波开发分支、MR、准确 SHA CI、`liguangming` 凭据审批合并；`PUT /merge` 必须带 `sha=<head sha>`；
   审核未完成保留 MR，不得用 codex 凭据提权代批。
6. CI 排队已知事实：Mac runner 全局 `concurrent = 1`，多 pipeline 并发时 Mac job 会长时间
   `created/running`，属自愈排队，不是失败；不改 runner 配置、不绕门禁。

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
