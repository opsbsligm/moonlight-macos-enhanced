# CI 插帧闭包显式捕获修复

Run38124574418（head5339b64c）的静态分析步骤实际完成，但“Verify no finding was added”失败：VideoDecoderRenderer.m异步插帧结果发布块新增13处`-Wimplicit-retain-self`告警。完成job114431845272日志已通过GitHub API现场读取。不是下载失败、不是编译错误，不能通过重试或增大finding baseline解决。

修复：只将该worker结果发布段的成员访问标为`self->`，包括pending frame、metadata、active engine和forced cadence。异步任务已明确使用self调用方法及锁定状态，因此显式标注不新增强捕获、不改变处理器串行退休或引用所有权。没有改告警基线。

防复发：增强呈现原生FI回放的真实生产方法编译启用`-Wimplicit-retain-self -Werror`。生命周期场景和合法编译负变异仍必须通过。完整冷缓存本地analyze结果和CI最终结论在阶段记录中单列，不能把CI旧run当本修复的验收。

回滚本阶段视频提交恢复旧显式性，但旧CI将再次遇到新增告警；USB隔离修复为独立提交，可单独回滚。
