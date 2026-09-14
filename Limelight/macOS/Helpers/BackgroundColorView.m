//
//  BackgroundColorView.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 19/6/2024.
//  Copyright © 2024 Moonlight Game Streaming Project. All rights reserved.
//

#import "BackgroundColorView.h"

@interface BackgroundColorView ()
@property (nonatomic, assign) CGColorRef backgroundCGColor;
@end

@implementation BackgroundColorView

- (instancetype)initWithCoder:(NSCoder *)coder {
    self = [super initWithCoder:coder];
    if (self) {
        self.wantsLayer = YES;
        _clear = YES;
    }
    return self;
}

- (void)dealloc {
    // The property starts NULL and CGColorRelease(NULL) is not defined, so only
    // release what updateLayer actually retained.
    if (_backgroundCGColor) {
        CGColorRelease(_backgroundCGColor);
        _backgroundCGColor = NULL;
    }
}

- (void)setClear:(BOOL)clear {
    _clear = clear;
    [self updateBackgroundColor];
}

- (void)updateLayer {
    // Take the new reference before dropping the old one, and never call
    // CGColorRetain or CGColorRelease with NULL: colorNamed: returns nil when the
    // name is missing, which used to reach both calls.
    CGColorRef named = [NSColor colorNamed:self.backgroundColorName].CGColor;
    CGColorRef replacement = named ? CGColorRetain(named) : NULL;
    CGColorRef previous = self.backgroundCGColor;
    self.backgroundCGColor = replacement;
    if (previous) {
        CGColorRelease(previous);
    }
    [self updateBackgroundColor];
}

- (void)updateBackgroundColor {
    self.layer.backgroundColor = self.clear ? [NSColor clearColor].CGColor : self.backgroundCGColor;
}

@end
