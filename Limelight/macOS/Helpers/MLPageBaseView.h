//
//  MLPageBaseView.h
//  Moonlight for macOS
//

#import <Cocoa/Cocoa.h>

/// The AppKit twin of SwiftUI's SettingsPageBase: an opaque base with two low-alpha
/// radial washes, so a glass card placed over it has something to refract. The washes
/// carry the token marker mme-page-wash-v1; the constraints audit refuses a page whose
/// marker drifted from the SwiftUI side's.
@interface MLPageBaseView : NSView
@end
