// What the permission section of the diagnostics report can honestly say.
// A bare command-line tool holds no screen-recording grant, so it is a natural
// sample of the "never asked" branch that the report currently prints as "not granted".
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <IOKit/hidsystem/IOHIDLib.h>

static NSString *hid(IOHIDAccessType t) {
    switch (t) {
        case kIOHIDAccessTypeGranted: return @"granted";
        case kIOHIDAccessTypeDenied:  return @"denied";
        default:                      return @"undetermined";
    }
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        printf("preflight screen recording : %s\n", CGPreflightScreenCaptureAccess() ? "yes" : "no");
        printf("AXIsProcessTrusted          : %s\n", AXIsProcessTrusted() ? "trusted" : "not trusted");
        printf("CGPreflightListenEvent      : %s\n", CGPreflightListenEventAccess() ? "yes" : "no");
        printf("IOHID listen / post         : %s / %s\n",
               hid(IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)).UTF8String,
               hid(IOHIDCheckAccess(kIOHIDRequestTypePostEvent)).UTF8String);

        // The exact call the app makes in isWindowInCurrentSpace.
        NSApp = [NSApplication sharedApplication];
        NSWindow *w = [[NSWindow alloc]
            initWithContentRect:NSMakeRect(0, 0, 200, 120)
                      styleMask:NSWindowStyleMaskTitled
                        backing:NSBackingStoreBuffered
                          defer:YES];
        [w setReleasedWhenClosed:NO];
        [w orderFront:nil];   // on-screen without activating or stealing the session
        for (int i = 0; i < 20 && w.windowNumber <= 0; i++) {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }
        int mine = (int)w.windowNumber;

        CFArrayRef all = CGWindowListCopyWindowInfo(
            kCGWindowListOptionAll | kCGWindowListOptionOnScreenOnly, kCGNullWindowID);
        NSArray *windows = (__bridge_transfer NSArray *)all;
        NSUInteger count = windows.count;
        BOOL sawOwnNumber = NO, sawAnyName = NO, sawOwnName = NO;
        for (NSDictionary *d in windows) {
            NSNumber *num = d[(__bridge NSString *)kCGWindowNumber];
            NSString *name = d[(__bridge NSString *)kCGWindowName];
            if (name.length > 0) { sawAnyName = YES; }
            if (num.integerValue == mine) {
                sawOwnNumber = YES;
                if (name.length > 0) sawOwnName = YES;
            }
        }
        printf("CGWindowListCopyWindowInfo  : %lu window(s)%s\n", (unsigned long)count,
               windows == nil ? " (NULL)" : "");
        printf("  own window number         : %d\n", mine);
        printf("  own number visible        : %s\n", sawOwnNumber ? "YES" : "no");
        printf("  own name visible          : %s\n", sawOwnName ? "YES" : "no");
        printf("  any name visible at all   : %s\n", sawAnyName ? "YES" : "no");
        printf("  --- verdict for the report ---\n");
        if (sawOwnNumber) {
            printf("  isWindowInCurrentSpace works WITHOUT a screen-recording grant\n");
        } else {
            printf("  isWindowInCurrentSpace is BROKEN without the grant (count=%lu)\n",
                   (unsigned long)count);
        }
        return 0;
    }
}
