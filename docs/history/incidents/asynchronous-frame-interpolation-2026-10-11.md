# VT 插帧异步关键路径（cp6）

## 变化
此前解码回调同步调用 VT `processWithParameters:`，下一次拉取/解码必须等计算返回。现在准入和配置检查后，向专用 serial 插帧队列提交一份任务，解码回调不等待 VT。

- 每个 renderer 最多一个计算任务在途；忙时放行最新源帧，不为每个输入建立计算 FIFO。
- 保留源/前源/pool 和 processor 的强快照；两源时间戳在同一锁内捕获，目标 PTS 是两源的中点。后台计算不读取可变 renderer 帧、pool 或 processor。
- generation、源序列、输入身份、processor 身份和源未提交条件，在运行前/结果发布时检查；旧结果不能插入新源或新会话。
- staging 等待预算为一个测得的显示周期（至少 1ms；整数毫秒向下取整），从解码发布源帧时计时。首次 draw 和 CVDisplayLink 重试都检查 deadline，超时只解除呈现等待，不释放仍在计算的任务槽。
- 计算超过预算不发布 midpoint；源帧可以继续呈现。任务结束才释放单飞槽。此策略优先避免蜂蜜般积压，而不是承诺每源帧都能得到插帧。
- stop/重配置先使 generation 作废、移除 renderer 所有权；endSession 排在同一队列上已执行的 process 后，禁止并发结束会话。暖机回调发布使用相同同步锁。
- 保留 paused MTKView、CVDisplayLink 驱动和既有整除 cadence / present hold。不把 processing 成功或请求开关当实际到屏证据；cp3 drawable 观测仍独立。

## 验证范围
原生回放插入生产 stage/copy/expire/retire 方法，CVPixelBuffer/pool 与 dispatch 队列真实，VT 后端和时钟确定性模拟：8 场景覆盖成功中点、超时、single-flight、stop、新解码、执行前作废、已呈现源、失败/未准入 deadline。三个合法编译的负变异覆盖 process 期间 endSession、重叠入队、无限 staging，必须被回放拒绝。

这不是实际 VT 性能、输入延迟、面板或完整串流验收。应以真实串流 Actual drawable FPS/P95 与响应和画面检查继续验收；USB 真接管仍未完成。

## CI 超时证据
旧 head 7fc72688 的 run 38122563239，在 Repository audits 的 Verify project constraints 步骤从 07:48:01 UTC 到 08:13:06 UTC 触及 job 25 分钟限额；最终 cancelled，构建步骤 skipped，汇总 build 因 skipped != success 失败。不是编译错误，不能作为 CI 已通过。审计预算提高至 60 分钟，保留完整 battery 和失败判定；下一 run 是否完成仍须现场查看。

## 回滚
撤销 cp6 提交可恢复同步插帧路径；没有改用户设置、正式安装应用、数据格式或设备驱动。
