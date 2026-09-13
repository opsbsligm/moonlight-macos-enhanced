//
//  AppDelegateForAppKit.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 10/2/18.
//  Copyright © 2018 Moonlight Stream. All rights reserved.
//

#import "AppDelegateForAppKit.h"
#import "DatabaseSingleton.h"
#import "AboutViewController.h"
#import "NSWindow+Moonlight.h"
#import "NSResponder+Moonlight.h"
#import "ControllerNavigation.h"

#import "MASPreferencesWindowController.h"
#import "GeneralPrefsPaneVC.h"

#import "AppsViewController.h"
#import "AppsWorkspaceViewController.h"
#import "TemporaryHost.h"
#import "Moonlight-Swift.h"
#import "DataManager.h"
#import <objc/runtime.h>

typedef enum : NSUInteger {
    SystemTheme,
    LightTheme,
    DarkTheme,
} Theme;

@interface AppDelegateForAppKit () <NSApplicationDelegate, NSWindowDelegate>
@property (nonatomic, strong) NSWindowController *aboutWC;
@property (nonatomic, weak) NSWindow *mainWindow;
@property (nonatomic, strong) NSWindowController *welcomePermissionsWC;
@property (nonatomic, strong) ControllerNavigation *controllerNavigation;
@property (weak) IBOutlet NSMenuItem *themeMenuItem;
@property (nonatomic, assign) BOOL didAttemptPermissionRepair;
@end

@implementation AppDelegateForAppKit

static const void *MoonlightOriginalMenuItemTitleKey = &MoonlightOriginalMenuItemTitleKey;
static const void *MoonlightOriginalMenuTitleKey = &MoonlightOriginalMenuTitleKey;
static const void *MoonlightOriginalToolbarLabelKey = &MoonlightOriginalToolbarLabelKey;
static const void *MoonlightOriginalToolbarPaletteLabelKey = &MoonlightOriginalToolbarPaletteLabelKey;
static const void *MoonlightOriginalToolbarToolTipKey = &MoonlightOriginalToolbarToolTipKey;

- (void)dealloc {
    [[NSNotificationCenter defaultCenter] removeObserver:self];
}

- (NSString *)hostUUIDFromViewControllerTree:(NSViewController *)viewController {
    if (viewController == nil) {
        return nil;
    }

    if ([viewController isKindOfClass:[AppsWorkspaceViewController class]]) {
        NSString *hostUUID = ((AppsWorkspaceViewController *)viewController).currentHostUUID;
        if (hostUUID.length > 0) {
            return hostUUID;
        }
    }

    if ([viewController isKindOfClass:[AppsViewController class]]) {
        NSString *hostUUID = ((AppsViewController *)viewController).host.uuid;
        if (hostUUID.length > 0) {
            return hostUUID;
        }
    }

    for (NSViewController *child in viewController.childViewControllers) {
        NSString *hostUUID = [self hostUUIDFromViewControllerTree:child];
        if (hostUUID.length > 0) {
            return hostUUID;
        }
    }

    return nil;
}

// Opt in explicitly to secure restorable state to avoid the system warning on some macOS versions.
- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app {
    return YES;
}

- (void)applicationDidFinishLaunching:(NSNotification *)aNotification {
    [self createMainWindow];
    self.controllerNavigation = [[ControllerNavigation alloc] init];
    [self refreshLocalizedChrome];
    [self showWelcomePermissionsIfNeeded];

    // Listen for the Swift welcome-window "Request Local Network" button tap.
    // The welcome screen can't call POSIX socket APIs directly easily, so it
    // posts a Notification and our ObjC side runs the actual UDP probe.
    // NOTE: We match the notification name by literal string (mirroring the Swift
    // constant MoonlightRequestLocalNetworkTriggerNotification) to avoid needing
    // a Swift-ObjC bridging header just for this one symbol.
    [[NSNotificationCenter defaultCenter] addObserverForName:@"MoonlightRequestLocalNetworkTrigger"
                                                      object:nil
                                                       queue:[NSOperationQueue mainQueue]
                                                  usingBlock:^(NSNotification * _Nonnull note) {
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();
            NSUserDefaults *d = [NSUserDefaults standardUserDefaults];
            [d setBool:YES forKey:kMoonlightLocalNetworkTriggeredKey];
            [d synchronize];
        });
    }];

    [self scheduleConnectionHealthCheck];
    [self addDiagnoseMenu];
}

- (void)addDiagnoseMenu {
    NSMenu *mainMenu = [NSApp mainMenu];
    if (!mainMenu) return;

    NSMenu *helpMenu = nil;
    for (NSMenuItem *item in mainMenu.itemArray) {
        if ([[item.submenu title] isEqualToString:@"Help"]) {
            helpMenu = item.submenu;
            break;
        }
    }
    if (!helpMenu) return;

    // Add separator + "Diagnose Connection" item
    [helpMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *diagnoseItem = [helpMenu addItemWithTitle:@"诊断连接问题…"
                                                   action:@selector(repairLocalNetworkPermission)
                                            keyEquivalent:@""];
    [diagnoseItem setTarget:self];
}

- (void)applicationWillFinishLaunching:(NSNotification *)notification {
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(languageChanged:) name:@"LanguageChanged" object:nil];
    [[LanguageManager shared] applyAppLanguage];

    [self applyThemePreference:[self currentThemePreference]];
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag {
    if (!flag) {
        [self createMainWindow];

        return YES;
    }
    
    return NO;
}

- (void)applicationWillTerminate:(NSNotification *)aNotification {
    [[DatabaseSingleton shared] saveContext];
}

- (void)createMainWindow {
    NSWindowController *mainWC = [NSStoryboard.mainStoryboard instantiateControllerWithIdentifier:@"MainWindowController"];
    mainWC.window.frameAutosaveName = @"Main Window";
    self.mainWindow = mainWC.window;
    [mainWC.window setMinSize:NSMakeSize(650, 350)];
    
    [mainWC showWindow:self];
    [mainWC.window makeKeyAndOrderFront:nil];
    [self localizeToolbarForWindow:mainWC.window];
}

// MARK: - Connection Health Check (CI/CD best practices — FULL REWRITE)
// Key fixes:
// 1. Gatekeeper spctl check removed — Apple Dev certs ALWAYS fail spctl --assess; it's normal, not an error
// 2. LocalNetwork permission MUST be actively triggered by a real network action (Bonjour/UDP won't pop dialog otherwise)
// 3. No double-popups: welcome window OR permission guide, never both at the same time
// 4. All permission operations are NON-DESTRUCTIVE on normal launch. tccutil reset = opt-in only.
// 5. Full diagnostics: any connection issue → "Help → 诊断连接问题" gives a complete report.

static NSString * const kMoonlightFirstLaunchKey = @"MoonlightFirstLaunchCompleted.v2";
static NSString * const kMoonlightLocalNetworkTriggeredKey = @"MoonlightLocalNetworkTriggered.v1";

// Send a single UDP broadcast packet to the GameStream discovery port (47989).
// This has two critical effects on macOS 12+:
//   a) Triggers the system LocalNetwork permission prompt the FIRST time it runs.
//   b) Serves as a fallback discovery probe for Sunshine/GFE hosts that don't respond to mDNS.
// Never blocks; runs on a background queue. Does not require any entitlement beyond NSLocalNetworkUsageDescription.
static void TriggerLocalNetworkPermissionPromptWithDiscoveryProbe(void) {
    @autoreleasepool {
        int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (fd < 0) {
            Log(LOG_W, @"[Connect] socket() failed for LocalNetwork trigger");
            return;
        }

        int one = 1;
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &one, sizeof(one));
        struct timeval tv = { .tv_sec = 0, .tv_usec = 200000 }; // 200ms send timeout max
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

        struct sockaddr_in sin;
        memset(&sin, 0, sizeof(sin));
        sin.sin_family = AF_INET;
        sin.sin_len = sizeof(sin);
        sin.sin_port = htons(47989);
        sin.sin_addr.s_addr = htonl(INADDR_BROADCAST); // 255.255.255.255

        // GameStream HTTP serverinfo payload fragment — anything works, we just need a
        // real datagram so the kernel reports us as "using local networking" to TCC.
        const char *probe = "GET /serverinfo HTTP/1.0\r\n\r\n";
        ssize_t n = sendto(fd, probe, strlen(probe), 0,
                           (struct sockaddr *)&sin, sizeof(sin));
        Log(LOG_I, @"[Connect] LocalNetwork trigger UDP probe sent: %zd bytes (errno=%d)",
            n, (int)(n < 0 ? errno : 0));
        close(fd);
    }
}

- (void)scheduleConnectionHealthCheck {
    self.didAttemptPermissionRepair = NO;

    // 1) Quarantine removal — fire-and-forget, non-destructive, safe every launch
    [self asyncRemoveQuarantine];

    // 2) LocalNetwork trigger — runs on a BG queue after UI is painted.
    //    This is the ONLY way macOS 12+ will show the LocalNetwork dialog.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.8 * NSEC_PER_SEC)),
                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        NSUserDefaults *d = [NSUserDefaults standardUserDefaults];
        BOOL everTriggered = [d boolForKey:kMoonlightLocalNetworkTriggeredKey];
        // Trigger on first launch AND every 24h so that users who previously denied
        // can still be re-prompted after a tccutil reset without changing bundle ID.
        if (!everTriggered) {
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();
            [d setBool:YES forKey:kMoonlightLocalNetworkTriggeredKey];
            [d synchronize];
        } else {
            // Even if already triggered, still send the probe so discovery has another shot.
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();
        }
    });

    // 3) Non-destructive diagnosis on background queue.
    //    Delayed 3.5s so welcome window has already been shown/dismissed — NO double-popups.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3.5 * NSEC_PER_SEC)),
                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        [self runPermissionDiagnosis];
    });
}

- (void)asyncRemoveQuarantine {
    @autoreleasepool {
        NSString *appPath = [[NSBundle mainBundle] bundlePath];
        if (appPath.length == 0) return;

        NSTask *task = [[NSTask alloc] init];
        [task setLaunchPath:@"/usr/bin/xattr"];
        [task setArguments:@[@"-d", @"com.apple.quarantine", appPath]];
        [task setTerminationHandler:^(NSTask *t) {
            Log(LOG_I, @"[Connect] Quarantine attr removal: exit=%d", t.terminationStatus);
        }];
        @try { [task launch]; } @catch (NSException *e) {
            Log(LOG_W, @"[Connect] xattr launch failed: %@", e);
        }
    }
}

- (void)runPermissionDiagnosis {
    @autoreleasepool {
        NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        BOOL firstLaunch = ![defaults boolForKey:kMoonlightFirstLaunchKey];
        if (firstLaunch) {
            [defaults setBool:YES forKey:kMoonlightFirstLaunchKey];
            [defaults synchronize];
            Log(LOG_I, @"[Connect] First launch (v2 marker)");
        }

        // ---- Intentionally NOT running spctl --assess ----
        // Apple Development-signed apps always FAIL spctl assessment. That is NOT an error
        // condition and it does NOT mean Gatekeeper blocked the app. Gatekeeper only blocks
        // unnotarized Developer ID apps or apps with broken signatures. Ad-hoc / Apple Dev
        // signed apps that the user launched via Right-Click → Open have already cleared the
        // Gatekeeper UX gating. Showing a "Gatekeeper BLOCKED" alert every launch is wrong.
        // We still log the signature info for diagnostics only.
        [self syncRunTask:@"/usr/bin/codesign"
                arguments:@[@"--verify", @"--verbose=2", [[NSBundle mainBundle] bundlePath]]
                completion:^(int exitCode, NSString *output) {
            Log(LOG_I, @"[Connect] Code-sign verify: exit=%d — %@", exitCode,
                output.length > 0 ? [output stringByTrimmingCharactersInSet:
                                     [NSCharacterSet whitespaceAndNewlineCharacterSet]] : @"(no output)");
        }];

        // If the welcome-permissions sheet has already been shown (or doesn't need to show),
        // and hosts are still offline after ~10s, we show ONE gentle permission-reminder alert.
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(8.0 * NSEC_PER_SEC)),
                       dispatch_get_main_queue(), ^{
            // Only show a guide if we don't have a welcome sheet up already.
            if (self.welcomePermissionsWC != nil) return;
            // Also skip if app is not active in foreground.
            if (NSApp.isActive == NO) return;
            // Read saved host count via DataManager (CoreData backed)
            DataManager *dm = [[DataManager alloc] init];
            NSArray *allHosts = [dm performSelector:@selector(getHosts)] ? [dm getHosts] : nil;
            if (allHosts.count > 0) {
                Log(LOG_I, @"[Connect] %lu saved hosts exist; skipping permission nag",
                    (unsigned long)allHosts.count);
                return;
            }
            // No saved hosts AND 11.5s into first use → single gentle guide.
            // NEVER auto-reset TCC; NEVER show this if user has already seen welcome sheet.
            [self presentPermissionGuideSingleTime];
        });
    }
}

// Show the permission guide AT MOST ONCE per launch. The original presentPermissionGuide
// still exists for explicit "diagnose connection" menu flows.
- (void)presentPermissionGuideSingleTime {
    if (self.didAttemptPermissionRepair) return;
    [self presentPermissionGuide];
}

// Manual repair action: resets LocalNetwork TCC permission, THEN re-triggers the prompt.
- (void)repairLocalNetworkPermission {
    NSString *bundleID = [[NSBundle mainBundle] bundleIdentifier];
    if (bundleID.length == 0) bundleID = @"std.skyhua.MoonlightMac2";

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        @autoreleasepool {
            // Collect full diagnostics FIRST so we always know what state things were in.
            NSMutableString *report = [NSMutableString stringWithString:
                @"===== Moonlight 连接诊断报告 =====\n"];
            [report appendFormat:@"Bundle ID: %@\n", bundleID];
            [report appendFormat:@"App path: %@\n", [[NSBundle mainBundle] bundlePath]];

            // Codesign
            [self syncRunTask:@"/usr/bin/codesign"
                    arguments:@[@"--verify", @"--verbose=4", [[NSBundle mainBundle] bundlePath]]
                    completion:^(int e, NSString *o) {
                [report appendFormat:@"\n--- Code Sign ---\nexit=%d\n%@\n", e, o ?: @""];
            }];

            // Quarantine attr
            [self syncRunTask:@"/usr/bin/xattr"
                    arguments:@[@"-l", [[NSBundle mainBundle] bundlePath]]
                    completion:^(int e, NSString *o) {
                [report appendFormat:@"\n--- xattrs (quarantine) ---\nexit=%d\n%@\n", e, o ?: @"(none)"];
            }];

            // TCC state is not queryable from our own process. tccutil implements
            // exactly one subcommand, "reset SERVICE [BUNDLE_ID]"; there is no
            // "dump" and no "list", and the database itself is protected by TCC.
            // The previous "tccutil dump" probe therefore always failed and the
            // report line it produced was pure noise. The only trustworthy signal
            // is what the UDP discovery probe actually observed, so record that.
            BOOL probeFired = [[NSUserDefaults standardUserDefaults]
                boolForKey:kMoonlightLocalNetworkTriggeredKey];
            [report appendString:@"\n--- TCC (LocalNetwork) ---\n"];
            [report appendString:@"Not queryable (tccutil has no read subcommand).\n"];
            [report appendFormat:@"Discovery probe already fired this install: %@\n",
                probeFired ? @"YES" : @"NO"];

            Log(LOG_I, @"[Connect-Diagnose]\n%@", report);

            // Now do the destructive reset + re-trigger
            Log(LOG_W, @"[Repair] Resetting LocalNetwork TCC for %@", bundleID);
            __block int resetExit = -1;
            __block NSString *resetOut = nil;
            // Real location is /usr/bin/tccutil. The previous /usr/sbin path does
            // not exist, so NSTask threw, syncRunTask swallowed it and reported
            // exit=-1: this reset silently never ran for anyone.
            [self syncRunTask:@"/usr/bin/tccutil"
                    arguments:@[@"reset", @"LocalNetwork", bundleID]
                    completion:^(int exitCode, NSString *output) {
                resetExit = exitCode;
                resetOut = output;
                Log(LOG_I, @"[Repair] tccutil reset LocalNetwork: exit=%d, out=%@",
                    exitCode, output ?: @"");
            }];

            // Clear the "triggered" marker so the UDP probe actually fires again and
            // macOS presents the permission prompt a second time.
            [[NSUserDefaults standardUserDefaults] removeObjectForKey:kMoonlightLocalNetworkTriggeredKey];
            [[NSUserDefaults standardUserDefaults] synchronize];

            // Re-trigger permission prompt
            TriggerLocalNetworkPermissionPromptWithDiscoveryProbe();

            dispatch_async(dispatch_get_main_queue(), ^{
                NSAlert *alert = [[NSAlert alloc] init];
                NSString *resetSummary = resetExit == 0
                    ? @"tccutil reset 结果：成功"
                    : [NSString stringWithFormat:
                       @"tccutil reset 结果：失败（exit=%d）。请手动前往系统设置关闭再开启本地网络开关。",
                       resetExit];
                [alert setMessageText:resetExit == 0
                    ? @"本地网络权限已重置，请允许访问"
                    : @"本地网络权限重置失败"];
                [alert setInformativeText:
                 [NSString stringWithFormat:
                  @"系统很快会弹出「Moonlight 想要访问本地网络」的对话框，请务必点击「允许」。\n\n"
                  @"如果对话框没有出现，请手动前往：\n"
                  @"系统设置 → 隐私与安全性 → 本地网络 → 开启 Moonlight。\n\n"
                  @"%@\n%@\n\n"
                  @"完整诊断已写入控制台日志（帮助 → 诊断连接问题 可随时重新运行）。",
                  resetSummary, resetOut.length > 0 ? resetOut : @""]];
                [alert setAlertStyle:NSAlertStyleInformational];
                [alert addButtonWithTitle:@"打开本地网络设置"];
                [alert addButtonWithTitle:@"知道了"];
                NSWindow *window = [NSApp mainWindow] ?: [[NSApp windows] firstObject];
                [alert beginSheetModalForWindow:window completionHandler:^(NSModalResponse rc) {
                    if (rc == NSAlertFirstButtonReturn) {
                        NSURL *u = [NSURL URLWithString:
                            @"x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"];
                        [[NSWorkspace sharedWorkspace] openURL:u];
                    }
                }];
            });
        }
    });
}

// Synchronous task runner. MUST be called on a non-main queue.
- (void)syncRunTask:(NSString *)launchPath arguments:(NSArray *)arguments completion:(void (^)(int exitCode, NSString *output))completion {
    NSTask *task = [[NSTask alloc] init];
    [task setLaunchPath:launchPath];
    [task setArguments:arguments];

    NSPipe *pipe = [NSPipe pipe];
    [task setStandardOutput:pipe];
    [task setStandardError:pipe];

    __block int exitCode = -1;
    __block NSString *outputString = @"";

    @try {
        [task launch];
        [task waitUntilExit];
        exitCode = task.terminationStatus;

        NSData *data = [[pipe fileHandleForReading] readDataToEndOfFile];
        if (data.length > 0) {
            outputString = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"";
        }
    } @catch (NSException *exception) {
        Log(LOG_W, @"[HealthCheck] Task %@ failed: %@", launchPath, exception);
    }

    if (completion) {
        completion(exitCode, outputString);
    }
}

- (void)presentPermissionGuide {
    if (self.didAttemptPermissionRepair) return;
    self.didAttemptPermissionRepair = YES;

    NSWindow *window = [NSApp mainWindow] ?: [[NSApp windows] firstObject];
    if (window == nil) return;

    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:@"Moonlight 无法发现游戏主机？"];
    [alert setInformativeText:@"找不到主机通常是因为本地网络权限没有开启。\n\n请完成以下步骤：\n\n"
     @"① 打开 系统设置 → 隐私与安全性 → 本地网络，开启 Moonlight\n\n"
     @"② 如果系统之前没有弹出过「本地网络」权限提示，可以点击 帮助 → 诊断连接问题\n\n"
     @"③ 也可以点击主窗口右上角「+」按钮手动输入主机 IP 地址直接添加。"];
    [alert setAlertStyle:NSAlertStyleWarning];
    [alert addButtonWithTitle:@"打开本地网络设置"];
    [alert addButtonWithTitle:@"知道了"];
    [alert beginSheetModalForWindow:window completionHandler:^(NSModalResponse returnCode) {
        if (returnCode == NSAlertFirstButtonReturn) {
            NSURL *url = [NSURL URLWithString:@"x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork"];
            [[NSWorkspace sharedWorkspace] openURL:url];
        }
    }];
}

- (void)showWelcomePermissionsIfNeeded {
    if (![WelcomePermissionsWindowObjCBridge shouldShowWelcomeWindow]) {
        return;
    }

    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.welcomePermissionsWC != nil) {
            return;
        }

        NSWindow *parentWindow = NSApplication.sharedApplication.mainWindow;
        if (parentWindow == nil) {
            parentWindow = NSApplication.sharedApplication.windows.firstObject;
        }
        if (parentWindow == nil) {
            return;
        }

        self.welcomePermissionsWC = [WelcomePermissionsWindowObjCBridge makeWelcomeWindow];
        self.welcomePermissionsWC.window.delegate = self;
        self.welcomePermissionsWC.window.frameAutosaveName = @"Welcome Permissions Window";
        [parentWindow beginSheet:self.welcomePermissionsWC.window completionHandler:^(__unused NSModalResponse returnCode) {
            [WelcomePermissionsWindowObjCBridge markWelcomeWindowShown];
            self.welcomePermissionsWC = nil;
        }];
    });
}

// Settings is a page inside the main window content region. There is no
// second window to position, no autosave name to keep in sync and no
// controller to rebuild: the presenter replaces the page in place and
// restores the toolbar and title on the way out.
- (NSWindow *)mainContentWindow {
    if (self.mainWindow != nil) {
        return self.mainWindow;
    }
    NSWindow *candidate = NSApplication.sharedApplication.mainWindow;
    self.mainWindow = candidate;
    return candidate;
}

- (void)showPreferencesForHost:(NSString *)hostId {
    NSWindow *window = [self mainContentWindow];
    if (window == nil) {
        return;
    }
    [window makeKeyAndOrderFront:nil];
    [SettingsWindowObjCBridge presentSettingsInWindow:window hostId:hostId];
}

- (IBAction)showPreferences:(id)sender {
    NSViewController *contentVC = [self mainContentWindow].contentViewController;
    [self showPreferencesForHost:[self hostUUIDFromViewControllerTree:contentVC]];
}

- (IBAction)showAbout:(id)sender {
    if (self.aboutWC == nil) {
        self.aboutWC = [[NSWindowController alloc] initWithWindowNibName:@"AboutWindow"];
        self.aboutWC.contentViewController = [[AboutViewController alloc] initWithNibName:@"AboutView" bundle:nil];
    }

    self.aboutWC.window.frameAutosaveName = @"About Window";
    [self.aboutWC.window moonlight_centerWindowOnFirstRunWithSize:CGSizeZero];
    
    [self.aboutWC showWindow:nil];
    [self.aboutWC.window makeKeyAndOrderFront:nil];
}

- (IBAction)filterList:(id)sender {
    NSWindow *window = NSApplication.sharedApplication.mainWindow;
    [window makeFirstResponder:[window moonlight_searchFieldInToolbar]];
}

- (IBAction)setSystemTheme:(id)sender {
    [self changeTheme:SystemTheme withMenuItem:((NSMenuItem *)sender)];
}

- (IBAction)setLightTheme:(id)sender {
    [self changeTheme:LightTheme withMenuItem:((NSMenuItem *)sender)];
}

- (IBAction)setDarkTheme:(id)sender {
    [self changeTheme:DarkTheme withMenuItem:((NSMenuItem *)sender)];
}

- (NSInteger)currentThemePreference {
    return [[NSUserDefaults standardUserDefaults] integerForKey:@"theme"];
}

- (void)applyThemePreference:(NSInteger)theme {
    Theme resolvedTheme = (theme >= SystemTheme && theme <= DarkTheme) ? (Theme)theme : SystemTheme;
    [self changeTheme:resolvedTheme withMenuItem:[self menuItemForTheme:resolvedTheme forMenu:self.themeMenuItem.submenu]];
}

- (NSMenuItem *)menuItemForTheme:(Theme)theme forMenu:(NSMenu *)menu {
    static NSUInteger menuIndexes[] = {0, 2, 3};
    if (menu == nil || theme > DarkTheme) {
        return nil;
    }
    return menu.itemArray[menuIndexes[theme]];
}

- (void)changeTheme:(Theme)theme withMenuItem:(NSMenuItem *)menuItem {
    NSMenu *menu = menuItem.menu ?: self.themeMenuItem.submenu;
    NSMenuItem *resolvedMenuItem = menuItem ?: [self menuItemForTheme:theme forMenu:menu];

    resolvedMenuItem.state = NSControlStateValueOn;
    for (NSMenuItem *item in menu.itemArray) {
        if (resolvedMenuItem != item) {
            item.state = NSControlStateValueOff;
        }
    }
    
    [[NSUserDefaults standardUserDefaults] setInteger:theme forKey:@"theme"];
    
    NSApplication *app = [NSApplication sharedApplication];
    switch (theme) {
        case SystemTheme:
            app.appearance = nil;
            break;
        case LightTheme:
            app.appearance = [NSAppearance appearanceNamed:NSAppearanceNameAqua];
            break;
        case DarkTheme:
            app.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
            break;
    }
}

- (void)languageChanged:(NSNotification *)notification {
    [self refreshLocalizedChrome];
}

- (void)refreshLocalizedChrome {
    [self localizeMenu:[NSApplication sharedApplication].mainMenu];

    for (NSWindow *window in NSApplication.sharedApplication.windows) {
        [self localizeToolbarForWindow:window];
    }
}

- (NSString *)localizedChromeString:(NSString *)key {
    if (key.length == 0) {
        return key;
    }
    return [[LanguageManager shared] localize:key];
}

- (NSString *)storedStringForObject:(id)object associationKey:(const void *)associationKey currentValue:(NSString *)currentValue {
    NSString *storedValue = objc_getAssociatedObject(object, associationKey);
    if (storedValue == nil && currentValue.length > 0) {
        storedValue = [currentValue copy];
        objc_setAssociatedObject(object, associationKey, storedValue, OBJC_ASSOCIATION_COPY_NONATOMIC);
    }
    return storedValue ?: currentValue ?: @"";
}

- (void)localizeMenu:(NSMenu *)menu {
    if (menu == nil) {
        return;
    }

    NSString *originalMenuTitle = [self storedStringForObject:menu associationKey:MoonlightOriginalMenuTitleKey currentValue:menu.title];
    if (originalMenuTitle.length > 0) {
        menu.title = [self localizedChromeString:originalMenuTitle];
    }

    for (NSMenuItem *item in menu.itemArray) {
        NSString *originalItemTitle = [self storedStringForObject:item associationKey:MoonlightOriginalMenuItemTitleKey currentValue:item.title];
        if (originalItemTitle.length > 0) {
            item.title = [self localizedChromeString:originalItemTitle];
        }

        if (item.submenu != nil) {
            NSString *submenuOriginalTitle = [self storedStringForObject:item.submenu associationKey:MoonlightOriginalMenuTitleKey currentValue:item.submenu.title];
            NSString *submenuKey = submenuOriginalTitle.length > 0 ? submenuOriginalTitle : originalItemTitle;
            if (submenuKey.length > 0) {
                item.submenu.title = [self localizedChromeString:submenuKey];
            }
            [self localizeMenu:item.submenu];
        }
    }
}

- (NSString *)toolbarLocalizationKeyForItem:(NSToolbarItem *)item originalValue:(NSString *)originalValue {
    if ([item.itemIdentifier isEqualToString:@"PreferencesToolbarItem"]) {
        if (@available(macOS 13.0, *)) {
            return @"Settings";
        }
        return @"Preferences";
    }
    return originalValue;
}

- (void)localizeToolbarForWindow:(NSWindow *)window {
    NSToolbar *toolbar = window.toolbar;
    if (toolbar == nil) {
        return;
    }

    for (NSToolbarItem *item in toolbar.items) {
        NSString *originalLabel = [self storedStringForObject:item associationKey:MoonlightOriginalToolbarLabelKey currentValue:item.label];
        NSString *originalPaletteLabel = [self storedStringForObject:item associationKey:MoonlightOriginalToolbarPaletteLabelKey currentValue:item.paletteLabel];
        NSString *originalToolTip = [self storedStringForObject:item associationKey:MoonlightOriginalToolbarToolTipKey currentValue:item.toolTip];

        NSString *labelKey = [self toolbarLocalizationKeyForItem:item originalValue:originalLabel];
        NSString *paletteLabelKey = [self toolbarLocalizationKeyForItem:item originalValue:(originalPaletteLabel.length > 0 ? originalPaletteLabel : originalLabel)];
        NSString *toolTipKey = [self toolbarLocalizationKeyForItem:item originalValue:(originalToolTip.length > 0 ? originalToolTip : originalLabel)];

        if (labelKey.length > 0) {
            item.label = [self localizedChromeString:labelKey];
        }
        if (paletteLabelKey.length > 0) {
            item.paletteLabel = [self localizedChromeString:paletteLabelKey];
        }
        if (toolTipKey.length > 0) {
            item.toolTip = [self localizedChromeString:toolTipKey];
        }

        if ([item.view isKindOfClass:[NSButton class]] && item.toolTip.length > 0) {
            ((NSButton *)item.view).toolTip = item.toolTip;
        }
    }
}


#pragma mark - NSWindowDelegate

- (void)windowWillClose:(NSNotification *)notification {
    if (notification.object == self.aboutWC.window) {
        self.aboutWC = nil;
    } else if (notification.object == self.welcomePermissionsWC.window && self.welcomePermissionsWC.window.sheetParent == nil) {
        [WelcomePermissionsWindowObjCBridge markWelcomeWindowShown];
        self.welcomePermissionsWC = nil;
    }
}

@end
