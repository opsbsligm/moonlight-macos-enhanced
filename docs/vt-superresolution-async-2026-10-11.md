# VT 超分异步处理 cp2

## 实现
- 低延迟与质量超分的 `processWithParameters` 均移到专用串行队列。
- 同一 renderer 只允许一个 CPU 处理任务在途；新源帧不会排入旧任务队列。
- draw 仅读取精确匹配帧的已处理结果，或提交一个不可变输入/PTS/处理器/池快照。
- 等待由既有 CVDisplayLink 刷新重试驱动；超过一个显示刷新周期，或旧任务占用额度时，本帧临时使用 MetalFX/基础空间缩放，不阻塞主线程。
- 临时退让不销毁处理中会话；结束会话排在同一处理队列，避免与 `processWithParameters` 重叠。停止/切模式递增 generation，不提前释放旧任务的在途槽。
- 结果需同时满足 generation、源序列、缓冲区身份、处理器身份及尚未提交；旧源、停止或已退让提交的结果不回插。
- 质量超分历史只更新自被采纳的输出；源与历史 PTS 随缓冲快照保留，非递增历史改 Random submission。
- 插帧前一源保存对应 PTS，插帧输出保存两源中点 PTS；超分不再读取下一次解码覆盖的 `_currentFramePresentationTimeStamp`。
- UI 将 CPU 繁忙/超预算退让与模型预热区分；不从 VT 模式选择直接发布 Active。

## 验证边界
共享 C 决策回放及变异用于验证过期结果和延迟预算。原生生命周期夹具抽取实际 renderer 方法，使用真实 CV 缓冲/池和 dispatch 队列，VT 后端为可控替身：验证单飞、停止中引用、结束顺序、过期/已提交结果丢弃和精确 PTS；不验证真实 VT 画质、硬件能力、处理耗时或面板帧时。

目前插帧本身仍同步在解码回调中；真实串流、GPU呈现时间、持续稳定性及 USB 真实接管仍属完整目标未完成项。单次构建或提交计数不得冒充这些验收。

## API 依据
[Apple VTSuperResolutionScalerParameters](https://developer.apple.com/documentation/videotoolbox/vtsuperresolutionscalerparameters?language=objc) 将上一源/输出定义为呈现时间顺序中的前帧；本文据此保留历史 PTS。后台串行队列、单飞与超预算退让是本项目策略，不是 Apple 自动保证的效果。

## 回滚
撤销 cp2 提交可恢复原同步超分路径。未改用户配置、正式安装、驱动或主机协议。
