//
//  Localization.h
//  Moonlight for macOS
//
//  One macro for one question: "is this string meant for a user to read?"
//
//  Every Objective-C file that shows text asked that question its own way.
//  StreamViewController_Internal.h defined MLString, so only the stream files could
//  use it; HostsViewController #undef-ed NSLocalizedString and re-pointed it at
//  LanguageManager; ContainerViewController called
//  [[LanguageManager shared] localize:] inline, which is how one line ended up
//  localizing a string twice. The consequence was not stylistic: strings written in
//  the files without the macro were shipped as bare literals, so an English
//  interface displayed Chinese, and the localizability checker only reported the
//  ones it happened to see.
//
//  One header, one spelling, no per-file invention.
//

#ifndef Moonlight_Localization_h
#define Moonlight_Localization_h

#import "Moonlight-Swift.h"

// The comment is deliberately not passed on: LanguageManager keys on the English
// text alone, and taking the argument keeps the call sites compatible with
// NSLocalizedString so a translated string never needs a second table lookup.
#ifndef MLString
#define MLString(key, comment) [[LanguageManager shared] localize:key]
#endif

#endif /* Moonlight_Localization_h */
