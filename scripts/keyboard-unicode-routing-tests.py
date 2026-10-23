#!/usr/bin/env python3
"""Compile shipping keyDown/keyUp; verify Unicode/code exclusivity on queued sends."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
from apple_toolchain import clang_and_sdk
import ml_probe_fixture

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('keyboard_base', root / 'scripts/keyboard-concurrency-tests.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
shipping = (root / 'Limelight/Input/HIDSupport.m').read_text()
methods = '\n'.join(base.method(shipping, s) for s in base.SIGNATURES)
source = ml_probe_fixture.apply(base.build(methods))
header = root / 'Limelight/Input/KeyboardTextRouting.h'
source = source.replace('#import "' + str(header) + '"', header.read_text())
source = source.replace('static int LiSendUtf8TextEventCtx(void *ctx, const char *text, unsigned int length) {\n    (void)ctx; (void)text; (void)length; abort();\n}', '''static NSMutableArray *texts;
static int LiSendUtf8TextEventCtx(void *ctx, const char *text, unsigned int length) {
    (void)ctx;
    [texts addObject:[[NSString alloc] initWithBytes:text length:length encoding:NSUTF8StringEncoding]];
    return 0;
}''')
source = source.replace('static void HIDDispatchInput(id support, HIDInputLease lease, void (^block)(void)) { block(); }', '''static NSMutableArray *jobs;
static void HIDDispatchInput(id support, HIDInputLease lease, void (^block)(void)) {
    [jobs addObject:[block copy]];
}''')
assert 'static NSMutableArray *jobs;' in source
source += r'''
static void drain(void) {
    while (jobs.count) { void (^b)(void) = jobs.firstObject; [jobs removeObjectAtIndex:0]; b(); }
}
static NSEvent *edge(NSEventType type, unsigned short code, NSString *text, NSUInteger mods, BOOL repeat) {
    return [NSEvent keyEventWithType:type location:NSZeroPoint modifierFlags:mods
        timestamp:1 windowNumber:0 context:nil characters:text charactersIgnoringModifiers:text
        isARepeat:repeat keyCode:code];
}
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL line %d\n", __LINE__); return 1; } } while (0)
int main(void) { @autoreleasepool {
    gHostEvents = [NSMutableArray new]; texts = [NSMutableArray new]; jobs = [NSMutableArray new];
    MLKeyboardUnderProbe *k = [MLKeyboardUnderProbe new];
    // The queued block survives the event and its temporary text buffer.
    @autoreleasepool {
        NSString *s = [NSString stringWithFormat:@"%C%C", (unichar)0x4e2d, (unichar)0x6587];
        [k keyDown:edge(NSEventTypeKeyDown, 49, s, 0, NO)];
        [k keyUp:edge(NSEventTypeKeyUp, 49, @"", 0, NO)];
        CHECK(texts.count == 0 && gHostEvents.count == 0 && jobs.count == 1);
    }
    drain(); CHECK(texts.count == 1 && [texts[0] isEqualToString:@"\u4e2d\u6587"]);
    CHECK(gHostEvents.count == 0 && k.keyboardForwardedKeyDownKeyCodes.count == 0);
    for (NSString *s in @[@"\U0001f600", @"\uff21", @"e\u0301"]) {
        [k keyDown:edge(NSEventTypeKeyDown, 49, s, 0, NO)];
        [k keyUp:edge(NSEventTypeKeyUp, 49, s, 0, NO)]; drain();
        CHECK([texts.lastObject isEqualToString:s]);
    }
    NSUInteger n = texts.count;
    // ASCII, shortcuts, function keys, controls, and empty/dead-key events keep the wire route.
    for (NSNumber *m in @[@0, @(NSEventModifierFlagCommand), @(NSEventModifierFlagControl), @(NSEventModifierFlagOption)]) {
        NSString *s = m.unsignedLongValue ? @"\u4e2d" : @"w";
        NSUInteger wireBefore = gHostEvents.count;
        [k keyDown:edge(NSEventTypeKeyDown, 13, s, m.unsignedLongValue, NO)];
        [k keyUp:edge(NSEventTypeKeyUp, 13, s, m.unsignedLongValue, NO)]; drain();
        CHECK(texts.count == n && gHostEvents.count == wireBefore + 2);
    }
    for (NSString *s in @[@"", @"\uf700", @"\u4e2d\n", @"\177"]) {
        [k keyDown:edge(NSEventTypeKeyDown, 49, s, 0, NO)];
        [k keyUp:edge(NSEventTypeKeyUp, 49, s, 0, NO)]; drain(); CHECK(texts.count == n);
    }
    // A wire DOWN owns its physical key until UP, even if a repeat changes characters.
    [k keyDown:edge(NSEventTypeKeyDown, 13, @"w", 0, NO)];
    [k keyDown:edge(NSEventTypeKeyDown, 13, @"\u4e2d", 0, YES)];
    [k keyUp:edge(NSEventTypeKeyUp, 13, @"\u4e2d", 0, NO)]; drain(); CHECK(texts.count == n);
    k.shouldSendInputEvents = NO;
    [k keyDown:edge(NSEventTypeKeyDown, 49, @"\u4e2d", 0, NO)]; drain(); CHECK(texts.count == n);
    puts("Unicode routing replay passed"); return 0;
}}
'''
cc, sdk = clang_and_sdk('Unicode routing replay')

def run(code):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / 'probe.m').write_text(code)
        built = subprocess.run([cc, '-fobjc-arc', '-fblocks', '-O1', '-isysroot', sdk,
            '-framework', 'AppKit', str(p / 'probe.m'), '-o', str(p / 'probe')], capture_output=True, text=True)
        if built.returncode:
            raise RuntimeError(built.stderr)
        return subprocess.run([str(p / 'probe')], capture_output=True, text=True)

result = run(source)
assert result.returncode == 0, result.stdout + result.stderr
print(result.stdout.strip())
for label, old, new in (
    ('wire owner rerouted as text', 'savedCode == nil ? HIDUnicodeTextForEvent(event) : nil', 'HIDUnicodeTextForEvent(event)'),
    ('text also sends a key code', '        return;\n    }\n    if (translated == 0)', '    }\n    if (translated == 0)'),
    ('text silently lost', 'LiSendUtf8TextEventCtx(textCtx, committed.bytes, (unsigned int)committed.length);', '(void)textCtx;'),
    ('ASCII rerouted as text', 'if (!nonASCII) return nil;', 'if (NO) return nil;'),
    ('shortcut modifiers ignored', 'if (event.modifierFlags & (NSEventModifierFlagCommand |',
     'if (0 & (NSEventModifierFlagCommand |'),
    ('function keys injected as text', '(c >= 0xE000 && c <= 0xF8FF)', '(NO)'),
):
    assert source.count(old) == 1, label
    result = run(source.replace(old, new, 1))
    assert result.returncode == 1 and 'FAIL line' in result.stderr, label
    print('caught:', label)
