// Which CGWindowListCopyWindowInfo option set actually contains the calling app's own
// window. isWindowInCurrentSpace asks for kCGWindowListOptionAll|OnScreenOnly, and a window
// that is merely created is not the same thing as a window the window server has mapped.
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>

static const char *seen(NSWindow *w, CFArrayRef all) {
    NSArray *windows = (__bridge_transfer NSArray *)all;
    BOOL own = NO, anyName = NO;
    for (NSDictionary *d in windows) {
        if ([(NSNumber *)d[(__bridge NSString *)kCGWindowNumber] integerValue] == w.windowNumber) own = YES;
        if ([(NSString *)d[(__bridge NSString *)kCGWindowName] length] > 0) anyName = YES;
    }
    static char buf[128];
    snprintf(buf, sizeof buf, "count=%-3lu own=%-3s name=%s",
             (unsigned long)windows.count, own ? "YES" : "no", anyName ? "visible" : "hidden");
    return buf;
}

int main(void) {
    @autoreleasepool {
        NSApplicationActivationPolicy policy = NSApplicationActivationPolicyAccessory;
        [NSApp setActivationPolicy:policy];
        printf("activation policy: Accessory (no Dock icon, still a GUI app to WindowServer)\n");
        NSWindow *w = [[NSWindow alloc] initWithContentRect:NSMakeRect(120, 120, 260, 160)
                                                 styleMask:NSWindowStyleMaskTitled
                                                   backing:NSBackingStoreBuffered defer:NO];
        [w setTitle:@"perm-spike-probe"];
        [w setReleasedWhenClosed:NO];

        struct { const char *name; NSWindow *w; BOOL mapped; } stages[] = {{"created only", w, NO}};
        (void)stages;

        printf("\n-- before the window is on screen --\n");
        printf("  number=%ld visible=%s\n", (long)w.windowNumber, w.isVisible ? "YES" : "no");
        printf("  All|OnScreenOnly : %s\n", seen(w, CGWindowListCopyWindowInfo(kCGWindowListOptionAll | kCGWindowListOptionOnScreenOnly, kCGNullWindowID)));

        [w makeKeyAndOrderFront:nil];
        [NSApp activateIgnoringOtherApps:YES];
        for (int i = 0; i < 40; i++) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
            if (w.isVisible) break;
        }
        printf("\n-- after makeKeyAndOrderFront + a runloop --\n");
        printf("  number=%ld visible=%s\n", (long)w.windowNumber, w.isVisible ? "YES" : "no");
        printf("  All|OnScreenOnly : %s\n", seen(w, CGWindowListCopyWindowInfo(kCGWindowListOptionAll | kCGWindowListOptionOnScreenOnly, kCGNullWindowID)));
        printf("  OnScreenOnly     : %s\n", seen(w, CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)));
        printf("  All              : %s\n", seen(w, CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID)));
        printf("  ExcludeDesktop   : %s\n", seen(w, CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID)));
        return 0;
    }
}
