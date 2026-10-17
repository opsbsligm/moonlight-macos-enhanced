//
//  HostCell.m
//  Moonlight for macOS
//
//  Created by Michael Kenny on 22/12/17.
//  Copyright © 2017 Moonlight Stream. All rights reserved.
//

#import "HostCell.h"
#import "BackgroundColorView.h"
#import "NSApplication+Moonlight.h"
#import "HostCellView.h"
#import "NSView+Moonlight.h"
#import "GlassOverlayContainer.h"
#import "Moonlight-Swift.h"

#undef NSLocalizedString
#define NSLocalizedString(key, comment) [[LanguageManager shared] localize:key]

@interface HostCell () <NSMenuDelegate>
@property (weak) IBOutlet BackgroundColorView *imageContainer;
@property (weak) IBOutlet NSView *labelContainer;
@property (nonatomic) id languageObserver;
// The cell's own glass, behind every piece of content in the cell.
@property (nonatomic, strong) GlassOverlayContainer *glassCard;

@end

@implementation HostCell

- (void)viewDidLoad {
    [super viewDidLoad];
    
    self.imageContainer.backgroundColorName = @"HostSelectionBackgroundColor";
    
    self.imageContainer.wantsLayer = YES;
    self.imageContainer.layer.masksToBounds = YES;
    self.imageContainer.layer.cornerRadius = 10;

    // One glass card for the whole cell -- artwork, name and status together -- on the
    // same system glass the settings cards and the stream panels use. The old look was
    // a bare icon floating on the page wash with the name and status loose under it:
    // nothing bounded the cell, so a grid of hosts read as a pile of parts. The card
    // is built by hand rather than edited into the xib because the xib's image
    // container carries fixed constraints (180x156, centerX) that no IBOutlet route
    // can add a bottom-covering subview past. The card frame is a static snapshot of
    // the xib geometry, taken once: the xib sizes the cell, so nothing moves later.
    self.glassCard = [GlassOverlayContainer containerWithCornerRadius:10.0];
    NSRect art = [self.view convertRect:self.imageContainer.bounds fromView:self.imageContainer];
    NSRect status = [self.view convertRect:self.statusLabel.frame
                                  fromView:self.statusLabel.superview];
    // Everything the cell draws, plus an even margin: the artwork is widest, the status
    // row sits lowest, so their union is the content the card has to cover.
    NSRect content = NSUnionRect(art, status);
    NSRect card = NSInsetRect(content, -6.0, -6.0);
    self.glassCard.frame = card;
    self.glassCard.autoresizingMask = NSViewMinYMargin;
    [self.view addSubview:self.glassCard positioned:NSWindowBelow relativeTo:self.imageContainer];
    // The artwork sits on the glass, so the old flat selection fill behind it goes
    // clear for good; what it sits on is the card.
    self.imageContainer.clear = YES;
    self.labelContainer.wantsLayer = YES;
    self.labelContainer.layer.masksToBounds = YES;
    self.labelContainer.layer.cornerRadius = 4;
    
    self.statusLightView.wantsLayer = YES;
    self.statusLightView.layer.masksToBounds = YES;
    self.statusLightView.layer.cornerRadius = self.statusLightView.bounds.size.width / 2;
    self.statusLightView.backgroundColor = [NSColor systemGrayColor];
    self.statusLightView.alphaValue = 1.0;
    self.statusLightView.layer.borderWidth = 1.0;
    self.statusLightView.layer.borderColor = [[NSColor separatorColor] CGColor];
    
    ((HostCellView *)self.view).delegate = self;

    __weak typeof(self) weakSelf = self;
    self.languageObserver = [[NSNotificationCenter defaultCenter] addObserverForName:@"LanguageChanged" object:nil queue:[NSOperationQueue mainQueue] usingBlock:^(NSNotification * _Nonnull note) {
        [weakSelf updateHostState];
    }];
    
    [self updateSelectedState:NO];
}

- (void)dealloc {
    if (self.languageObserver != nil) {
        [[NSNotificationCenter defaultCenter] removeObserver:self.languageObserver];
        self.languageObserver = nil;
    }

    @try {
        [_host removeObserver:self forKeyPath:@"pairState"];
        [_host removeObserver:self forKeyPath:@"state"];
    } @catch (NSException *exception) {
        NSLog(@"Observer not registered: %@", exception);
    }
}

- (void)setHost:(TemporaryHost *)host {
    if (_host != host) {
        // Remove old observers
        @try {
            [_host removeObserver:self forKeyPath:@"pairState"];
            [_host removeObserver:self forKeyPath:@"state"];
        } @catch (NSException *exception) {
            NSLog(@"Observer not registered: %@", exception);
        }

        // Assign the new host
        _host = host;

        if (_host) {
            // Add observers for the new host
            [_host addObserver:self forKeyPath:@"pairState" options:NSKeyValueObservingOptionNew context:nil];
            [_host addObserver:self forKeyPath:@"state" options:NSKeyValueObservingOptionNew context:nil];
        }

        [self updateHostState];
    }
}

- (void)observeValueForKeyPath:(NSString *)keyPath
                      ofObject:(id)object
                        change:(NSDictionary<NSKeyValueChangeKey,id> *)change
                       context:(void *)context {
    if ((object == self.host) && ([keyPath isEqualToString:@"pairState"] || [keyPath isEqualToString:@"state"])) {
//        NSLog(@"Coofdy: %@ changed state", self.host.name);
        [self updateHostState];
    } else {
        [super observeValueForKeyPath:keyPath ofObject:object change:change context:context];
    }
}

- (void)prepareForReuse {
    [super prepareForReuse];
    
    // Remove observers for the old host
    @try {
        [_host removeObserver:self forKeyPath:@"pairState"];
        [_host removeObserver:self forKeyPath:@"state"];
    } @catch (NSException *exception) {
        NSLog(@"Observer not registered: %@", exception);
    }

    _host = nil;
}

- (void)updateSelectedState:(BOOL)selected {
    // Selected: the card's own glass takes a tint of the accent the list already uses.
    // The old expression of selection -- a solid pill behind the name, white text on it
    // -- is gone: over a tinted card it stacked two "this one" signals, and the pill was
    // the older of the two. The name keeps its ordinary colour, which the tinted card
    // still leaves with full contrast (measured on the render probe).
    self.glassCard.tintColor = selected ? [NSColor.selectedContentBackgroundColor colorWithAlphaComponent:0.35] : nil;

    self.labelContainer.backgroundColor = [NSColor clearColor];
    self.hostName.textColor = [NSColor textColor];
}

- (void)setSelected:(BOOL)selected {
    [super setSelected:selected];
    
    [self updateSelectedState:selected];
}

- (void)mouseDown:(NSEvent *)theEvent {
    if ([theEvent clickCount] == 2) {
        [self.delegate openHost:self.host];
    } else {
        [super mouseDown:theEvent];
    }
}

- (void)menuWillOpen:(NSMenu *)menu {
    [self.delegate didOpenContextMenu:menu forHost:self.host];
}


#pragma mark - Host Updating

- (void)updateHostState {
    if (![NSThread isMainThread]) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [self updateHostState];
        });
        return;
    }

    NSColor *statusColor;
    NSString *statusText;

    switch (self.host.state) {
        case StateOnline:
            if (self.host.pairState == PairStateUnpaired) {
                statusColor = [NSColor systemOrangeColor];
                statusText = NSLocalizedString(@"Online, but not paired", @"Online, but not paired");
            } else {
                statusColor = [NSColor systemGreenColor];
                statusText = NSLocalizedString(@"Online, and paired", @"Online, and paired");
            }
            break;
        case StateOffline:
            if (self.host.pairState == PairStateUnpaired) {
                statusColor = [NSColor systemGrayColor];
                statusText = NSLocalizedString(@"Offline, and not paired", @"Offline, and not paired");
            } else {
                statusColor = [NSColor systemRedColor];
                statusText = NSLocalizedString(@"Offline, but paired", @"Offline, but paired");
            }
            break;
        case StateUnknown:
        default:
            statusColor = [NSColor systemGrayColor];
            statusText = NSLocalizedString(@"Unknown", @"Unknown");
            break;
    }

    // Update UI elements
    self.statusLightView.backgroundColor = statusColor;
    self.statusLightView.alphaValue = 1.0;
    self.statusLabel.stringValue = statusText;
}

@end
