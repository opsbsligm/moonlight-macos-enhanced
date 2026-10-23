//
//  StreamViewController+MouseCapture.h
//  Moonlight for macOS
//
//  Category header that owns the edge-sensor accessors. The primary class
//  StreamViewController_Internal.h no longer declares these methods, so the
//  compiler stops warning that the primary class has an unfulfilled promise
//  while the category quietly fulfils it (-Wincomplete-implementation and
//  -Wobjc-protocol-method-implementation). Callers in other categories
//  (MenuUI, MouseCapture itself, anything that asks for the clamped dwell /
//  band / auto-collapse values) import this header so the selector stays
//  visible without the primary class pretending to implement it.
//

#import "StreamViewController_Internal.h"

@interface StreamViewController (MouseCapture)
- (NSTimeInterval)edgeSensorDwellSeconds;
- (CGFloat)edgeSensorBandWidthPoints;
- (NSTimeInterval)edgeMenuAutoCollapseDelay;
@end
