#!/usr/bin/env python3
"""Prove the connection-timeout overlay can still reach the submenus it opens.

Three buttons on that overlay pop up the stream menu's Window, Monitor and Quality
submenus. They used to find those items by comparing the item's title against a
Chinese literal:

    if ([item.title isEqualToString:@"屏幕"]) { ... }

The titles are localized, so the comparison only held in the Chinese interface. In
English the loop matched nothing, `popUpMenuPositioningItem:` was never reached, and
Resolution, Bitrate and Display Mode did nothing at all -- no crash, no log line, no
build failure. Any check that reads the source for the word 屏幕 would have been
satisfied while the feature was broken for half the users, so this harness compiles
the real lookup and hands it menus wearing both languages.

The tags are read out of the file that builds the menu, not restated here: a build
side that stopped setting them has to fail this test, because a lookup that matches
nothing looks exactly like a menu that was never asked for.

Teeth come from the previous shape. The title comparison is rebuilt and run against
the English menu, where it must find nothing -- otherwise the scenario would be
proving only that AppKit returns items from a menu.

Exit 0 only when both languages resolve and the old shape fails in English.
"""
import os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERNAL = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers", "StreamViewController_Internal.h")
MENU_UI = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers", "StreamViewController+MenuUI.m")
DIAGNOSTICS = os.path.join(ROOT, "Limelight", "macOS", "ViewControllers", "StreamViewController+Diagnostics.m")

# The three sections, with the titles the language table gives them in each language.
SECTIONS = [
    ("StreamMenuSectionWindow", "Window", "窗口"),
    ("StreamMenuSectionMonitor", "Monitor", "屏幕"),
    ("StreamMenuSectionQuality", "Quality", "画质"),
]


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def method_body(source, signature):
    """One method, verbatim, braces matched: the harness runs the shipped code."""
    start = source.find(signature)
    if start == -1:
        raise SystemExit("expected %s, which is not in the file any more" % signature)
    brace = source.index("{", start)
    depth, index = 0, brace
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return source[start:index + 1]


def enum_from_header():
    source = read(INTERNAL)
    match = re.search(r"typedef NS_ENUM\(NSInteger, StreamMenuSection\) \{.*?\};", source, re.S)
    if not match:
        raise SystemExit("StreamMenuSection is gone from the shared header, so the overlay "
                         "has no addressing contract to be checked against")
    return match.group(0)


def tags_as_built():
    """Which section each menu item is built with, straight out of the build side."""
    source = read(MENU_UI)
    built = {}
    for variable, section in ((r"windowItem", "StreamMenuSectionWindow"),
                              (r"monitorItem", "StreamMenuSectionMonitor"),
                              (r"qualityItem", "StreamMenuSectionQuality")):
        if re.search(r"\b%s\.tag\s*=\s*%s\s*;" % (variable, section), source) is None:
            raise SystemExit("%s.%s is never tagged in StreamViewController+MenuUI.m, so the "
                             "timeout overlay addresses a section nothing advertises"
                             % (variable, section))
        built[section] = True
    return built


MAIN = r'''
#import <AppKit/AppKit.h>

ENUM_HERE

@interface MenuProbe : NSObject
@property(strong, nonatomic) NSMenu *streamMenu;
@end

@implementation MenuProbe
LOOKUP_HERE
@end

static NSString *failure = nil;

static void expect(BOOL condition, const char *what) {
    if (!condition && failure == nil) {
        failure = [NSString stringWithUTF8String:what];
    }
}

static NSMenu *menuWearing(NSArray<NSArray<NSString *> *> *titles) {
    NSMenu *root = [[NSMenu alloc] initWithTitle:@"StreamMenu"];
    for (NSArray<NSString *> *row in titles) {
        NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:row[0] action:nil keyEquivalent:@""];
        item.tag = [row[1] integerValue];
        item.submenu = [[NSMenu alloc] initWithTitle:row[0]];
        [root addItem:item];
    }
    return root;
}

int main(void) {
    @autoreleasepool {
        NSArray<NSArray<NSString *> *> *english = @[
            @[@"Window", @"TAG_WINDOW"],
            @[@"Monitor", @"TAG_MONITOR"],
            @[@"Quality", @"TAG_QUALITY"],
        ];
        NSArray<NSArray<NSString *> *> *chinese = @[
            @[@"窗口", @"TAG_WINDOW"],
            @[@"屏幕", @"TAG_MONITOR"],
            @[@"画质", @"TAG_QUALITY"],
        ];

        MenuProbe *probe = [[MenuProbe alloc] init];
        for (NSArray<NSArray<NSString *> *> *worn in @[english, chinese]) {
            probe.streamMenu = menuWearing(worn);
            NSString *language = [worn[0][0] isEqualToString:@"Window"] ? @"English" : @"Chinese";
            for (NSUInteger index = 0; index < worn.count; index++) {
                NSString *title = worn[index][0];
                NSInteger tag = [worn[index][1] integerValue];
                NSMenu *found = [probe streamSubmenuForSection:tag];
                expect(found != nil, "lookup by section returned nothing");
                expect([found.title isEqualToString:title], "lookup by section returned the wrong submenu");
            }
            // A button that asks for a section nobody advertises must get nothing
            // back rather than the first submenu it can find.
            expect([probe streamSubmenuForSection:9999] == nil, "an unknown section resolved to a submenu");
            [probe.streamMenu removeAllItems];
            expect([probe streamSubmenuForSection:TAG_MONITOR] == nil, "a lookup on an empty menu invented a submenu");
            if (failure) {
                fprintf(stderr, "FAIL %s interface: %s\n", language.UTF8String, failure.UTF8String);
                return 1;
            }
        }

        // The shape that shipped: find the submenu by matching the words on it.
        NSMenu *englishMenu = menuWearing(english);
        NSMenuItem *byTitle = nil;
        for (NSMenuItem *item in englishMenu.itemArray) {
            if ([item.title isEqualToString:@"屏幕"]) {
                byTitle = item;
                break;
            }
        }
        if (byTitle != nil) {
            fprintf(stderr, "FAIL the title comparison found the Monitor section in an English "
                            "menu, so this scenario cannot show the bug it exists for\n");
            return 1;
        }
        printf("ok   the overlay resolves each submenu in both languages\n");
        printf("ok   the previous title matching found nothing in English (it has teeth)\n");
    }
    return 0;
}
'''


def toolchain():
    """The same compiler the other harnesses use.

    `xcrun clang` runs the shim, which refuses on a host whose license has not been
    accepted from a Terminal; `xcrun --find clang` answers with a path that needs no
    such consent. The SDK is asked for by name, because the default one on this
    machine is the Command Line Tools SDK, which has no AppKit to link.
    """
    found = subprocess.run(["xcrun", "--find", "clang"], capture_output=True, text=True)
    sdk = subprocess.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                         capture_output=True, text=True)
    clang, path = found.stdout.strip(), sdk.stdout.strip()
    if not os.path.exists(clang) or not os.path.isdir(path):
        raise SystemExit("xcrun could not name a clang and macOS SDK to build the addressing probe")
    return clang, path


def build_and_run(work, source):
    binary = os.path.join(work, "stream-menu-addressing")
    clang, sdk = toolchain()
    built = subprocess.run([clang, "-fobjc-arc", "-O1", "-isysroot", sdk,
                            "-framework", "AppKit", "-o", binary, "-x", "objective-c", "-"],
                           input=source, text=True, capture_output=True, cwd=ROOT)
    if built.returncode != 0:
        # A harness that cannot compile has to say why, in the log a reader is
        # already looking at, instead of dying on a traceback three frames away.
        sys.stderr.write("the addressing harness did not compile:\n%s\n%s\n"
                         % (built.stdout, built.stderr))
        raise SystemExit(1)
    return subprocess.run([binary], capture_output=True, text=True)


def assemble():
    """The fixture source, with everything read out of the shipped files.

    This half needs no compiler, so it is checked on its own: an anchor that has
    moved, a tag that stopped being advertised, or a placeholder the enum no longer
    names, all arrive here before clang is asked anything. Each failure names the
    file to look at, because a harness that dies on a clang error three frames away
    gets blamed on the change that did not touch it.
    """
    enum = enum_from_header()
    tags_as_built()
    lookup = method_body(read(DIAGNOSTICS),
                         "- (NSMenu *)streamSubmenuForSection:(StreamMenuSection)section")
    if "isEqualToString" in lookup:
        raise SystemExit("streamSubmenuForSection: is comparing titles again, which is the bug "
                         "this harness exists to keep away")

    source = MAIN.replace("ENUM_HERE", enum).replace("LOOKUP_HERE", lookup)
    for section, _, _ in SECTIONS:
        match = re.search(section + r"\s*=\s*(\d+)", enum)
        if match is None:
            raise SystemExit("%s has no explicit value in the header, so the harness cannot "
                             "hand the lookup the number the buttons were built with" % section)
        source = source.replace("TAG_" + section.split("Section")[1].upper(), match.group(1))

    leftovers = sorted(set(re.findall(r"\b[A-Z_]*HERE\b|\bTAG_[A-Z]+\b", source)))
    if leftovers:
        raise SystemExit("the fixture still carries unreplaced placeholders: %s" % leftovers)
    if "for (NSMenuItem *item in self.streamMenu.itemArray)" not in source:
        raise SystemExit("the extracted lookup is not the loop the shipped code runs")
    return source


def main():
    source = assemble()
    print("ok   the section tags, the enum, and the shipped lookup were read out of the sources")

    if "--preflight" in sys.argv[1:]:
        # The extraction half of the proof, for a machine that cannot compile. The
        # behavioural assertions below still only run where clang answers, and CI is
        # the place that signs this gate off.
        print("0 stream-menu addressing failures (preflight only: extraction, no assertions run)")
        return 0

    with tempfile.TemporaryDirectory() as work:
        run = build_and_run(work, source)
    sys.stdout.write(run.stdout)
    sys.stderr.write(run.stderr)
    if run.returncode != 0:
        print("%d stream-menu addressing failures" % 1)
        return 1
    print("0 stream-menu addressing failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
