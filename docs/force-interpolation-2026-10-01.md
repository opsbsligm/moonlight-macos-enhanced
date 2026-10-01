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
