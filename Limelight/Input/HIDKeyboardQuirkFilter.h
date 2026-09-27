#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Session-scoped, main-thread observer. It never seizes devices or requests permission.
/// Only the measured AJAZZ pointer/C quirk is eligible; ordinary keyboards and
/// unrecognized composite-device macros remain normal keyboard input.
@interface HIDKeyboardQuirkFilter : NSObject
- (void)start;
- (void)stop;
- (BOOL)shouldDeferKeyCode:(unsigned short)keyCode timestamp:(NSTimeInterval)timestamp;
- (BOOL)isKnownPointerKeyCode:(unsigned short)keyCode timestamp:(NSTimeInterval)timestamp;
@end

NS_ASSUME_NONNULL_END
