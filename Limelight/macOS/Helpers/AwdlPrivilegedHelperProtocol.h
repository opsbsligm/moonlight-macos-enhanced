#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@protocol MLAwdlPrivilegedHelperProtocol

- (void)queryAwdlStateWithReply:(void (^)(BOOL present, BOOL up, NSString *stderrText))reply;
- (void)runIfconfigArgument:(NSString *)argument
                  withReply:(void (^)(BOOL success, NSString *message))reply;

@end

NS_ASSUME_NONNULL_END
