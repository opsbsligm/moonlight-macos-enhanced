//
//  StreamViewController.h
//  Moonlight for macOS
//
//  Created by Michael Kenny on 25/12/17.
//  Copyright © 2017 Moonlight Stream. All rights reserved.
//

#import <Cocoa/Cocoa.h>
@class TemporaryHost;
#import "TemporaryApp.h"
#import "AppsViewControllerDelegate.h"

@protocol KeyboardNotifiableDelegate <NSObject>

- (BOOL)onKeyboardEquivalent:(NSEvent *_Nonnull)event;

@end

struct Resolution {
   int width;
   int height;
};

@interface StreamViewController : NSViewController
@property (nonatomic, strong, nullable) TemporaryApp *app;
// Strong snapshot of app.host: the app->host edge is weak, so the streaming
// view controller keeps the host graph alive for the whole session (and for
// the deferred reconnect state). Required pairing for the weak back-pointer.
@property (nonatomic, strong, nullable) TemporaryHost *host;
@property (nonatomic, weak, nullable) id<AppsViewControllerDelegate> delegate;
@property (nonatomic) BOOL hasSessionSunshineTargetDisplayOverride;
@property (nonatomic, copy, nullable) NSString *sessionSunshineTargetDisplayNameOverride;
@property (nonatomic, strong, nullable) NSNumber *sessionSunshineScreenModeOverride;

+ (struct Resolution)getResolution;
@end
