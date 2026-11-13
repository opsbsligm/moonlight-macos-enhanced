//
//  AppDelegateForAppKit.h
//  Moonlight for macOS
//
//  Created by Michael Kenny on 10/2/18.
//  Copyright © 2018 Moonlight Stream. All rights reserved.
//

#import <Foundation/Foundation.h>

@interface AppDelegateForAppKit : NSObject

- (void)showPreferencesForHost:(NSString *)hostId;
- (void)applyThemePreference:(NSInteger)theme;
- (NSInteger)currentThemePreference;
- (void)repairLocalNetworkPermission;

@end

// The Debug render probe counts the writes the settings page's own selection
// binding receives, so a segment press can be judged by the page instead of by the
// control's claim. Declared here so the Swift bridge sees it; the definition and the
// counter it serves live in AppDelegateForAppKit.m. A Release build never records,
// so the symbol costs nothing in a shipping binary.
extern void MLProbeWriteChainRecord(NSInteger pane);
