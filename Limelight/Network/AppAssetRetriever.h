//
//  AppAssetRetriever.h
//  Moonlight
//
//  Created by Diego Waxemberg on 1/31/15.
//  Copyright (c) 2015 Moonlight Stream. All rights reserved.
//

#import "TemporaryHost.h"
#import "TemporaryApp.h"
#import "AppAssetManager.h"

@interface AppAssetRetriever : NSOperation

@property (nonatomic) TemporaryHost* host;
@property (nonatomic) TemporaryApp* app;
/// Weak, like every other back-reference in this tree. A retriever sits in somebody's
/// queue, so held strongly it kept the page that asked for the artwork alive until the
/// download finished -- and the artwork answer then arrived at a page nobody is looking at.
@property (nonatomic, weak) id<AppAssetCallback> callback;

@end
