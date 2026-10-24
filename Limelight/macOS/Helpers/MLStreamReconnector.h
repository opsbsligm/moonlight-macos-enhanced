//
//  MLStreamReconnector.h
//  Moonlight macOS Enhanced
//
//  P2-2 重连退避状态机：把连接异常断开、握手阶段失败、用户主动 reconnect
//  三类触发统一调度 1s/3s/9s 退避，最多 maxAttempts 次后停止；"主机确认消失"
//  或用户取消立即停。
//
//  状态机只做决策（要不要重连、什么时候重连）。真正的拆链/重建仍复用既有的
//  attemptReconnectWithReason:，避免出现第二套重连执行路径 —— 那条路径已经
//  负责 HID 收键、全屏状态保持、generation 递增和临时告警抑制。
//
//  设计：
//    - 纯状态机：attemptCount + timer + 回调块，不持有 StreamViewController。
//    - 主线程构造 + 操作（与 StreamViewController 同一队列的事实）。
//    - 不 import UI/协议栈，可单独编译回放。
//
//  attemptCount 的生命周期（本轮踩过的坑）：
//    - 只有 recordSuccess（连接真的起来了）、用户取消、预算耗尽后才清零。
//    - 一次 attempt 交给调用方执行后必须保留计数，否则每轮都被清零 →
//      退避永远停在第一档 1s、maxAttempts 形同虚设。
//      resetForNextAttemptWithReason: 就是为此存在：只清 timer 与待办回调。
//

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, MLReconnectTrigger) {
    MLReconnectTriggerConnectionTerminated = 1,
    MLReconnectTriggerStageFailed          = 2,
    MLReconnectTriggerPayloadStall         = 3,
    MLReconnectTriggerNoFrameStall         = 4,
    MLReconnectTriggerUserMenu             = 5,
};

@interface MLStreamReconnector : NSObject

// attemptCount 已达该值时不再调度。默认 3。
@property (nonatomic) NSUInteger maxAttempts;
// 退避序列（秒），超出档数后沿用最后一档。默认 [1, 3, 9]。
@property (nonatomic, copy) NSArray<NSNumber *> *backoffSeconds;
// "host confirmed gone"：置位后不再调度，已有 timer 立即取消。
@property (atomic, readonly) BOOL hostConfirmedGone;
// 已消耗的 attempt 数。
@property (atomic, readonly) NSUInteger attemptCount;
// 是否已有一个 attempt 在计时（用于 coalesce 与 UI 提示）。
@property (atomic, readonly) BOOL hasPendingAttempt;

// 主线程安全。以下情况**不**调度，返回 NO：
//   - hostConfirmedGone == YES；
//   - 已有 timer 在计时（此时只更新待办 trigger/reason/回调，返回 YES）；
//   - attemptCount 已达 maxAttempts；
//   - 块 shouldReconnect 返回 NO；
//   - stall 类触发且距会话启动不足 startupGraceMs（冷启动属正常）。
// 返回 YES 表示已纳入退避调度。
- (BOOL)requestReconnectFromTrigger:(MLReconnectTrigger)trigger
                         withReason:(NSString *)reason
                     startupElapsedMs:(uint64_t)startupElapsedMs
                      shouldReconnect:(BOOL (^)(void))shouldReconnect
                    beginReconnectNow:(void (^)(MLReconnectTrigger trigger,
                                                NSUInteger attempt,
                                                NSString *reason))beginReconnectNow;

// 用户主动取消（退出/关窗/切换主机）：取消 timer 并清零退避预算。
- (void)cancelWithReason:(NSString *)reason;

// 一个 attempt 已交给调用方执行：清 timer 与待办回调，但保留 attemptCount，
// 让下一次触发继续往后退。
- (void)resetForNextAttemptWithReason:(NSString *)reason;

// 诊断确认主机不可达：停止一切后续重连。
- (void)markHostConfirmedGoneWithReason:(NSString *)reason;

// 连接建立成功：清零退避预算与 timer。
- (void)recordSuccess;

// 用户从菜单点 Reconnect：不消耗预算，立即 begin；返回是否已发起。
- (BOOL)requestImmediateReconnectFromMenuWithReason:(NSString *)reason
                                  beginReconnectNow:(void (^)(MLReconnectTrigger trigger,
                                                              NSUInteger attempt,
                                                              NSString *reason))beginReconnectNow;

@end

NS_ASSUME_NONNULL_END
