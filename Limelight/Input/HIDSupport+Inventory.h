//
//  HIDSupport+Inventory.h
//  Moonlight for macOS
//
//  Reading controller identity off the bus so `MLControllerInventory` can hold it, for the
//  diagnostics report and the controller arrival event to agree on. See that header for why
//  a report reads a record instead of enumerating devices itself.
//
//  This is the only reader of the bus for that purpose, and it reads through a manager this
//  class already owns: a report must not go hunting on the bus, because the player copying
//  one is usually the one whose device is already misbehaving.
//

#import "HIDSupport.h"

NS_ASSUME_NONNULL_BEGIN

@interface HIDSupport (Inventory)

/// Publish what this instance's manager sees now, and count one streaming session. Called
/// once per session, where the manager has just opened.
- (void)publishControllerInventoryForSessionStart;

/// Publish what this instance's manager sees now, without touching the session tally.
/// Called on controller arrival and removal, so an idle app's record stays current.
- (void)publishControllerInventoryChange;
@end

NS_ASSUME_NONNULL_END
