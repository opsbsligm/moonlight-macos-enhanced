# 插帧强制开启开关（force frame interpolation）— 2026-10-01

## 背景与需求
用户反馈：本机 1920x1080@180Hz 面板串流 120 FPS 时，实测刷新率 179.82Hz 低于
120 FPS 所需的节奏余量门限，插帧被 cadence 门控拒绝。要求提供一个"强制开启"
开关，越过该门控。参照 UU远程的激进策略，但保留硬件/渲染器硬性约束。

## 设计决策
- force 开关**只绕过 cadence 门控**（`shouldUseFrameInterpolationForDisplayRefreshRate:`
  内的刷新率余量检查）。以下硬约束仍然生效，不做强制：
  - Metal renderer 可用性 / HDR 路径限制
  - VT 帧插值硬件能力检查
  - 刷新率未知（测量失败）时的保守拒绝
- 超分（super resolution）路径的拒绝全部来自硬件能力，本轮未加 force。
- 新状态 `MLVideoFrameInterpolationReportActiveForced`：cadence 拒绝被 force 越过并
  成功挂载时如实上报"强制激活"，徽章/详情提示存在卡顿/撕裂/延迟风险，
  不与普通 Active 混报。日志 `forced over cadence refusal`（LOG_W）。
- 配置链：SettingsStore → SettingsObjCBridge → StreamConfiguration.frameInterpolationForce
  → VideoDecoderRenderer。默认 OFF，不改变既有行为。

## UI
设置页视频面板，插帧 Picker 非 Off 时出现"强制开启插帧"开关：
- 当前刷新率无余量 → 提示强制后的风险（Force Frame Interpolation detail）。
- 当前已有余量 → 提示不强制也会插帧，保留可在实测抖动时跳过检查
  （no conflict detail）。
- cadence 建议文案在 force 开启时隐藏（不再劝导用户降帧率）。

## 改动清单（commit 4bfa2af8，14 文件）
- Limelight/Stream/StreamConfiguration.h/.m：新增 frameInterpolationForce 属性。
- Limelight/Stream/VideoDecoderRenderer.m：ActiveForced 报告枚举、force ivar、
  gate 分支、runtime detail key、LOG_W 日志、stage 成功段分叉上报。
- StreamViewController.m：从 prefs 写入 streamConfig。
- Swift 配置链 7 文件 + en/zh-Hans 文案 + scripts/frame-interpolation-status-tests.py。

## 验证
- scripts/frame-interpolation-status-tests.py：EXIT=0，含新负控制
  "forced-admission-reads-as-ordinary-success"（已知坏形状，能失败）。
- local-gates.sh：76 PASS / 0 FAIL。git diff --check 干净。
- build.sh --no-dmg：EXIT=0。CI run 36852660553（分支 integration/round74）。
- 部署：/Applications/MoonlightEnhanced.app 已原子替换并签名校验，
  新 sha255(MacOS)=48ed0e3ccd365488c771c368c6152db3ebc50b5d53487643fc67c00686f8aa33，
  回滚备份在 ~/.Trash/.MoonlightEnhanced-before-force-interp-*.app。

## 验收状态
- 已部署二进制内 force 配置链贯通：自动测试通过。
- **实机尚未验收**：串流中 120 FPS + 强制开关 → 徽章显示"强制插帧"、
  日志出现 forced over cadence、主观流畅度/延迟表现。用户当前占用会话，
  待空闲后补跑并逐项记录。

## 实机验收补记（2026-10-01 20:45，HOME-PC 120FPS 会话）
- **force 越过 cadence 门：实机 PASS。** 日志多次出现
  `frame interpolation forced over cadence refusal: display 180.00Hz below 180.00Hz
  needed for stream 120 FPS`（20:23:41、20:29:39、20:31:37），且设置页
  profile 确认 `frameInterpolationForce=True`。开关→配置→渲染器链路真实贯通。
- **实际插帧引擎：本主机环境下未挂载。** 全量日志（含 rotated/curated）中
  从未出现 `active=VTLowLatency` 的 INFO 上报；取而代之，每次会话均有
  `VT frame interpolation doesn't support source pixel format 0x34343476`（v444）。
  根因：当前 HOME-PC 会话使用 YUV444 编码，VT 低延迟插帧不接受 v444 源像素格式。
  运行时报告走 SourceFormatUnsupported 分支，UI 徽章语义应为"源格式不支持"，
  与 force 机制无关——这是 force 门控之外的独立限制。
- 结论：**force 开关机制实机 PASS；"强制后插帧真正运行"在当前 YUV444 配置下
  实机 FAIL（预期内的独立限制，非本轮引入）。** 要获得插帧实效：视频编码改为
  H.264/HEVC（4:2:0），或后续轮次实现 4:4:4→4:2:0 转换后再送插帧。
- 徽章挂载显示与主观流畅度：UNVERIFIED（会话已断开，且引擎本就未挂载）。

## 第二层根因与修复（2026-10-02，4:2:0 达成后池仍建不起来）

4:4:4 让步部署后实机确认：协商不发 444 位（`formats=0x101`）、解码缓冲
`format=0x34323076`（v206=4:2:0），源格式拒绝消除。但引擎仍未挂载，日志
`Failed to create VT frame interpolation output pool: -6682`。

**根因（探针实证，非猜测）**：
`VTLowLatencyFrameInterpolationConfiguration.destinationPixelBufferAttributes`
携带几何（Width/Height/ExtendedPixelsWidth 等）。旧代码用
`CVPixelBufferCreateResolvedAttributesDictionary` 合并该属性集与渲染器
preferred 属性，该 API 对此组合返回 -6660；fallback 只回 preferred 属性
（无宽高），`CVPixelBufferPoolCreate` 随即 -6682。结果：输出池永远不存在，
插帧在源格式问题解决后依然静默失败。

**修复**：`resolvedFrameProcessorAttributesWithPreferredPixelFormat:baseAttributes:`
改为手动 NSMutableDictionary 合并——base（配置）提供几何，preferred（渲染器）
的像素格式选择覆盖同名键。不再调用会拒绝该组合的 resolver。

**测试**：`scripts/interpolation-output-pool-tests.py`（已注册 CI）——从
VideoDecoderRenderer.m 提取真实 resolver+池方法编译运行：
- 真 1920x1080 配置建池成功（旧代码在此必须失败 ready=0，负控制）；
- 池实际吐出 1920x1080 BGRA 缓冲；
- 丢几何变异必须失败。
本地 EXIT=0。回归：source-format/status/sdr-10bit 全绿，git diff --check 干净。

**验收状态**：池修复后的实机挂载（`active=VTLowLatency` + UI 徽章 +
主观流畅度）**尚未验收**——需重新构建部署后补跑。

## 第三层根因与修复（2026-10-02 凌晨，池建起来了但每帧提交失败）

池修复部署后实机确认：`-6682` 消除、池存在、缓冲正常发出，但每帧
`VT frame interpolation failed: VTFrameProcessorErrorDomain Code=-19740
(NSUnderlyingError=-50)`（VTFrameProcessorProcessingError），且每帧
prewarm→fail→teardown 循环——一个插帧帧都没产出。

**根因（提交级探针实证）**：`/tmp/mle/fi-submit-probe2.swift` 对同一
已启动 session 提交三种目的缓冲：
- 目的=config 原生 attrs（420v）：**processed=ok**
- 目的=BGRA+extended：**-19740**
- 目的=BGRA 无 extended：**-19740**

即 **LLFI 目的缓冲的像素格式必须等于 configuration 自带的
destinationPixelBufferAttributes 格式（420v/0x34323076）**。第二层修复
让渲染器 preferred（BGRA）覆盖了同名键，池能建、缓冲能发、提交必死。
像素格式的权威是配置，不是渲染器偏好。

**修复**：合并时像素格式以 base（configuration）为准，preferred 仅在
配置未声明格式时兜底；Metal 兼容与 IOSurface 键仍由渲染器注入。呈现
路径本就支持 420v（解码帧即为 420v）。该方法同时被超分路径复用，行为
一致（本主机 LL SR factors=[]，超分不可用，如实记录）。

**测试升级**：`interpolation-output-pool-tests.py` 不再只看池的形状——
从生产池取缓冲、经真实 session 真提交并要求回调成功；目的格式断言从
BGRA 改为配置原生 0x34323076；新增"BGRA 覆盖"植入变异，必须精确复现
`ok=0 err=-19740`（旧缺陷的活体负控制）。旧 resolver/丢几何负控制保留。

**实机验收（2026-10-02 05:55，HOME-PC Desktop 会话，pid=71921）**：
- `YUV444 held back for forced interpolation` PASS（第一层保持）
- `formats=0x101`、解码 `format=0x34323076` PASS
- 全日志 `-6682`=0、`-19740`=0、prewarm 仅 2 次（无每帧循环）PASS
- `active=VT Low-Latency Frame Interpolation reason=display 180.00Hz
  provides cadence headroom over 120 FPS stream` PASS
- 统计条实机显示 `插帧 +32.3 fps`（绿色增量，帧真的在产出）PASS
- 主观流畅度：UNVERIFIED（无人为对比基线，自动化无法裁决）
