# 实际 drawable 呈现观测 cp3

既有 rendered/interpolated/scaled 计数在 command buffer 提交路径更新，不足以证明实际到屏。此次保留既有数据兼容性，新增独立观测，不能将两者混用。

## 采集与读数
- 在 present/commit 前向真实 drawable 注册一次 `addPresentedHandler:`，只读取回调参数的 `presentedTime`。
- 使用弱 renderer 引用；串流帧快照同时捕获观测 generation。clear/stop/切呈现路径重置状态，旧回调无法进入新会话。
- 0 是未呈现或丢帧，不记为成功；负值/NaN/Infinity 拒绝。没有回调不能据此确认丢帧总数。
- 固定 128 样本环，读数时按呈现时间排序，不假设回调到达顺序。相同呈现时间有歧义时不发布 FPS。
- FPS 为 `(样本数-1)/(最后-首个呈现时间)`；P95 帧时来自相邻呈现时间差。样本不足、超过两秒没有新呈现或时钟读数不一致时，读数 unavailable，UI 显示 --。
- Present Wait 是 `presentedTime - CACurrentMediaTime(提交前)`，仅有效非负样本进入 P95。不是解码/网络/输入到光子总延迟。
- 性能条新增独立“实际呈现”行，按窗口宽度换行，不扩展出两侧边缘；tooltip 解释窗口/新鲜度/旧计数边界。
- 每秒至多一条 Actual drawable 日志，含 FPS、P95、有限样本数与已观测帧类别计数，无设备名称/凭据。

## API 与边界
[Apple presentedTime](https://developer.apple.com/documentation/metal/mtldrawable/presentedtime?language=objc) 定义它为 drawable 显示到屏幕的 host time，0 表示未呈现或帧被丢弃；[addPresentedHandler](https://developer.apple.com/documentation/metal/mtldrawable/addpresentedhandler(_:)) 提供回调。

观测只覆盖 Enhanced Metal drawable 路径；Native/Compatibility 无此观测时显示 --，不捏造数据。这不是外部光学测量，也不能证明输入延迟、实际 VT 画质或长期稳定性。当前未完成自动真实串流采样；插帧异步与 USB 真接管仍是完整目标的一部分。

## 测试与回滚
共享 C 实际读数代码回放覆盖 180Hz、回调乱序、0/非法/重复时间、generation、两秒新鲜度、128 容量环绕与无有效等待数据；六个可编译变异必须被行为测试拒绝。接线断言验证捕获 generation、注册时机、真实 presentedTime、弱引用与 UI 新鲜度门限。测试不等同实际面板样本。

撤销 cp3 提交恢复旧统计显示；未改用户设置、协议、正式安装或驱动。
