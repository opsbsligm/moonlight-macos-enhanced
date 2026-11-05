# 超分与插帧提交压力修复 — 2026-10-11

## 改动与依据

`VideoDecoderRenderer.m` 原先在超分、纹理转换完成后才申请 GPU 在飞额度。
额度满时，主线程的昂贵计算已经发生，随后整帧退出。现在先申请额度，
不足时保留最新源帧状态，在后续 CVDisplayLink 刷新重试。

额度成功申请后，所有未提交的返回路径统一通过 `@finally` 归还。
成功提交则由 GPU 完成回调归还本次捕获的信号量，而不是读取 renderer
可能已经更换的信号量。额度限制和非阻塞等待沿用现有设置。

插帧生成期间标记源帧 sequence，draw 暂不提交该源帧，避免源帧超越中间帧。
VT 完成后同时核对 buffer 身份、sequence 与源帧提交状态；过期结果释放。
清理 staging 只允许清理自己的 sequence，避免旧回调解除新帧的等待。

每次刷新可以重试中间帧或源帧；成功提交的源帧不再重复超分/转换/呈现。
保持最新源帧覆盖策略，不增加 FIFO，过载时仍可能丢弃尚未呈现的旧配对。
本轮没有把该策略误当成必须补齐旧帧的要求，否则会增加串流输入延迟。

## 验证与边界

- `scripts/enhanced-presentation-tests.py` 编译实际使用的 C 策略，重放
  staging → 中间帧多次提交失败 → 中间帧成功 → 源帧成功 → 空闲刷新，
  并覆盖 decode 超越 VT、stop、插帧失败/预热中的源帧路径。
- 5 个变异必须编译成功并在重放中失败；11 个接线断言核对实际 renderer。
- CI 全量变异回归捕获了旧纹理缓存测试的缩进锚点失效；锚点已改为适配
  实际缩进，另验证 4/8 空格与实际源文件共 3 个布局。单项实植回归被
  正确拒绝，失败项为“a drawn frame holds its own reference to the texture cache”。
- 新测试由已有 `constraints-audit.py` 调用，进入现有 CI 入口。
- 本地 Debug Xcode build 成功，build-warning-audit 无一方源码警告。
- 合法 90FPS/180Hz 会话的持续帧率、主观蜂蜜感、720p 超分耗时仍需实机证据。
  测试版已启动，HOME-PC 在线已配对；computer-use 原生通道随后断开，两次
  尝试均返回 `Sky Computer Use native pipe closed before response`，未完成串流。
- VT 插帧仍在解码回调同步处理，VT 超分仍在 draw 同步处理。异步化需独立
  处理 processor/session 的串行所有权、取消、buffer 生命周期与过期结果，
  本轮没有宣称该工作已经完成。

## 回滚

回滚本轮提交即可；无设置迁移、无数据库变化。

## 呈现接口边界

Apple 文档将 `afterMinimumDuration` 定义为上一 drawable 的最短显示时长，
不是实际二倍输出率的验收证据。后续需采集实际 drawable 呈现时间，区分
提交完成、真正显示和节拍波动。来源：
https://developer.apple.com/documentation/metal/mtlcommandbuffer/present%28_%3Aafterminimumduration%3A%29?language=objc
