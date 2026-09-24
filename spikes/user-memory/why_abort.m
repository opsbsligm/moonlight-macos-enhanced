#import <Foundation/Foundation.h>
int main(void) {
    @autoreleasepool {
        NSUserDefaults *d = [[NSUserDefaults alloc] initWithSuiteName:@"usermem.probe.1"];
        @try {
            [d setObject:@{ @"s": @3, @"v": [NSNull null] } forKey:@"k"];
            printf("no exception; objectForKey -> %s\n", [[d objectForKey:@"k"] description].UTF8String);
        } @catch (NSException *e) {
            printf("exception name=%s reason=%s\n", e.name.UTF8String, e.reason.UTF8String);
        }
    }
    return 0;
}
