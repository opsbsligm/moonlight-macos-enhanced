# 插帧输出池回归夹具与断路器生命周期

完整constraints回归在HEAD30cf3f63发现原生输出池夹具编译失败：cp10生产方法新增
`_interpolationOverloadStrikes`与`_interpolationSuspended`，FakeRenderer尚未声明。
应用Debug构建成功不代表这条提取生产方法的回归也成功，故补齐测试字段，不修改生产代码。

## 实际运行的行为

使用shipping `ensureFrameInterpolationOutputPoolForConfiguration:`与真实VT配置/输出池：
- 无processor拒绝建池时保留已有暂停/strike；
- 新建池清零strike并解除暂停；
- 同源格式缓存池复用时保留暂停，不能每帧重开断路器；
- 源格式变化重建池时复位；
- 1920x1080、420v真实输出buffer提交VT成功。

三条新负变异（不清strike、不解除暂停、缓存也重建）均先编译成功，再由原生行为拒绝。
原resolver、缺失几何、强制BGRA三个反例继续验证，BGRA实际提交报-19740。

## 证据与限制

/tmp/ml-cp15-pool-final.log保留本机验证；此测试不是屏幕呈现、画质或90FPS/180Hz顺滑验收。
无工具链/无配置时现有skip说明仍不当作硬件成功。未放宽全量约束或CI阈值。
原完整审计session66499因已证实夹具编译失败主动SIGINT终止（exit130），未声称全量通过；
中断时工作区干净、尚未进入植入变异battery。不因观测超时而重启。
修复提交后重跑单项和约束，再启动新HEAD完整回归，保留原远端run不取消。
