# 超分/插帧四组帧时间基线（2026-10-15，真机采集）

采集环境：Mac 客户端（macOS 27.2，M 系列 8 核，内置 1920x1080@180Hz 显示器）
串流 HOME-PC(192.168.3.110)/Desktop，HEVC，局域网直连。
数据源 = App 日志行 `[video] Actual drawable present fps=… frameP95=…ms submitWaitP95=…ms … source=N interpolated=N scaled=N`
（128 样本滑动窗口，每 ~1.3s 一行）。原始日志见 `docs/evidence/frame-time-2026-10-15/`。

## 四组数据

| 组 | 配置 | 源分辨率 | n | 上屏 fps（中位） | frameP95（中位） | 提交后等待 P95（中位） | interpolated | scaled |
|---|---|---|---|---|---|---|---|---|
| native | FI关、SR不介入 | 1920x1080 | 148 | 31.88 | 44.444 ms | 16.893 ms | 0 | 0 |
| scaling-only | SR=MetalFX(画质)、FI关 | 1280x720 | 139 | 62.63 | 27.777 ms | 17.479 ms | 0 | 全窗口>0 |
| sr+fi | SR=MetalFX(画质)、FI=VT | 1920x1080 | 149 | 61.78 | 27.777 ms | 17.786 ms | 0 | 全窗口>0 |
| fi-only | FI=VT(强制开启)、SR关 | 1920x1080 | 123 | 31.97 | 38.888 ms | 17.469 ms | 0 | 0 |

## 结论（区分证据层级）

### 已验证（有日志/界面双证据）
1. **MetalFX 超分路径健康**：720p→1701x956 全程介入（scaled 计数=全部帧），上屏 ~63fps，
   frameP95=27.777ms（=180Hz 下 5 个刷新周期，即呈现节奏被显示器量化，无额外卡顿尾巴），
   提交后等待与 native 组同水位（~17.5ms）。超分不是"粘稠"的来源。
2. **VideoToolbox 低延迟插帧在本机当前场景实际未产出任何插帧帧**：
   四个组的 `interpolated` 计数全部为 0。设置页运行时状态给出直接原因：
   「**插帧因处理失败或过载已暂停，继续显示原生帧。更改串流配置或重新连接后重试。**」
   （AX 快照：`docs/evidence/frame-time-2026-10-15/settings-runtime-ax-dump.txt`）。
   即过载断路器（3 strikes → suspend + 退避探针）把 FI 整段关掉了，
   这正是用户投诉"画面粘稠如蜂蜜、卡得不可用"的最可能机制：
   引擎在"尝试处理→超预算→熔断→冷却→再试"之间循环，呈现节奏忽源帧忽回退。
3. **预算约束极紧是结构性风险**：staging 预算 =
   `floor(1000/max(显示器刷新率, 流帧率))`，180Hz 面板上仅 ~5.5ms；
   而 VTLLFI 1080p 单次处理耗时普遍超过该预算，熔断是常态而非偶发。

### 场景限制（本次采集的边界）
- 主机侧为 Windows 锁屏/静态桌面，源帧率实际只有 ~32fps（内容驱动编码），
  并非 90fps 满载动态画面；"用户实际游戏/视频场景下 FI 是否同样熔断"未在本次复现，
  但熔断状态本身与画面内容无关（strike 只计处理耗时）。
- native/sr+fi 组的 frameP95=44.444ms 与 32fps 源间隔一致，是源限制而非渲染瓶颈。
- 采集期间出现大量 `Audio underrun`（锁屏+高负载采集环境噪声），未观察到视频路径丢帧（Loss 0.00%）。

### 未验收（下一步）
- 动态内容（游戏/视频播放）下的 FI 帧时间与 interpolated>0 的正向证据；
- 修复方向裁决（见下）后的 A/B 复测。

## 修复方向（待实现，未裁决）
1. **预算自适应**：staging 预算不应盲目取 1/180Hz；FI 开启时按 `1/(2×源帧率)` 与
   显示周期取更大者，避免"结构上必超支"。
2. **熔断降级为半速探针**：suspend 期间不再整段关闭，而是每 N 帧允许一次
   异步处理（不阻塞呈现），把"熔断闪烁"的粘稠感收敛为稳定源帧节奏。
3. 强制开启（frameInterpolationForce）时给出更前置的警告：当前策略页只提示
   刷新率节拍，不提示"该硬件/分辨率组合可能处理不及"。

## 复现命令
```
# 采集（串流中，另开终端）
tail -f ~/Library/Logs/Moonlight/moonlight-debug.log | grep --line-buffered "Actual drawable" > /tmp/group.log
# 解析
python3 <本仓库>/scripts/frame-time-baseline-parse.py /tmp/group.log
```

## Addendum (same day): breaker fix verified on the acceptance machine

The baseline above captured the failure: every group showed interpolated=0
because the staging budget was one display period (~5ms on the 180Hz panel) and
VTLLFI calls cost 18-41ms on measured dynamic content, so the breaker opened on
the first three frames of every scene.

Three commits fixed the shape of the deadline:
- `fix(video): fund the interpolation deadline with a whole source frame` —
  the fixed window is one source frame (never below a display period, never
  below 8ms), and the trip logs its measured cost unconditionally, because the
  engine-change log swallowed the first reason.
- `fix(video): score only gross overruns and fund them with measurements` —
  a publish late inside two budgets charges nothing (the measured engine always
  pays it); only a call at twice the deadline scores. The window is raised by
  the EMA of finished calls, bounded at two source frames.
- `test(video): lift the working report from its own state label` — the status
  harness had started lifting the breaker sentence as the success text, which
  is what turned CI red after the diagnostic commit.

Real-client verification (same machine, same 1080p90 stream over VPN, VT FI,
MetalFX quality set, mouse drags for content motion):
- `interpolated=1396..1629` per 128-sample window — the interpolated path now
  produces and presents frames (was 0 in every baseline group);
- presented `fps≈55-61` with `frameP95=33.3ms`, i.e. the doubled 30fps source
  frames land at a whole-refresh cadence on the 180Hz panel;
- `breaker tripped: 0` lines for the session (was: every cooldown probe);
- evidence: `docs/evidence/frame-time-2026-10-15/post-fix-session.log`.

Two boundaries, stated plainly:

1. This stream negotiated 90 FPS but the host's locked screen sent ~30 FPS of
   real content, so the run proves the pipeline (VT produces, the renderer
   presents, the breaker stays closed) at the frame rate the source actually
   carried. Over a twenty-minute session the interpolated counter grew
   monotonically to 37225 at a steady ~58 FPS, so this is sustained behaviour,
   not one window. A 90 FPS stream with sustained host-side motion needs the
   host unlocked (owner-held PIN) and is recorded as not yet acceptance-tested,
   not as passing.
2. The design conclusion the numbers force: on this 180Hz panel at a 90 FPS
   stream, the cadence admits with k=1 -- the session logs `each frame held
   5.555ms on 180.00Hz display at 180 FPS output` -- so an interpolated frame
   gets one refresh period to be produced while the engine needs 18-41ms. The
   doubled cadence cannot be served no matter what the breaker allows: an
   interpolated frame arrives roughly seven refreshes late and is superseded.
   Interpolation on a high-refresh panel therefore pays off at source rates
   whose doubled cadence leaves several refreshes of room per frame (30 FPS on
   this display: 33.3ms of room, which is exactly where the measurement above
   landed), and the 90 FPS row of the settings page is a promise the panel, not
   the feature, cannot keep. That is the honest shape of the feature, not a
   defect the EMA can fund away.
