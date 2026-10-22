#!/usr/bin/env python3
"""Compile the shipping table methods; replay distinct devices and slot exhaustion."""
from pathlib import Path
import subprocess
import tempfile
from apple_toolchain import clang_and_sdk


def method(text, anchor):
    start = text.index(anchor)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


source = Path('Limelight/Input/HIDSupport.m').read_text()
methods = '\n'.join(method(source, name) for name in (
    '- (NSString *)deviceKeyForDevice:',
    '- (HIDDeviceControllerEntry *)entryForDevice:',
    '- (int)allocatePlayerSlot {',
    '- (int)activeDeviceMask {'))
harness = r'''
#import <Foundation/Foundation.h>
typedef const void *IOHIDDeviceRef;
@interface Controller : NSObject
@property int lastButtonFlags;
@end
@implementation Controller
@end
@interface HIDDeviceControllerEntry : NSObject
@property(strong) Controller *controller;
@property int playerIndex;
@property uint8_t protocolType;
@property uint32_t supportedButtonFlags;
@end
@implementation HIDDeviceControllerEntry
@end
@interface HIDSupport : NSObject
@property(strong) NSMutableDictionary<NSString *, HIDDeviceControllerEntry *> *deviceControllerTable;
@end
@implementation HIDSupport
- (uint8_t)protocolTypeForDevice:(IOHIDDeviceRef)d { return 1; }
- (uint32_t)supportedButtonFlagsForDevice:(IOHIDDeviceRef)d { return 0xffff; }
__METHODS__
@end
#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)
int main(void) { @autoreleasepool {
    HIDSupport *s = [HIDSupport new];
    int handles[17] = {0};
    CHECK([s entryForDevice:NULL] == nil);
    HIDDeviceControllerEntry *a = [s entryForDevice:&handles[0]];
    HIDDeviceControllerEntry *b = [s entryForDevice:&handles[1]];
    CHECK(a != nil && b != nil && a != b);
    CHECK(s.deviceControllerTable.count == 2);
    CHECK(a.playerIndex == 0 && b.playerIndex == 1);
    CHECK([s entryForDevice:&handles[0]] == a);
    a.controller.lastButtonFlags = 0x1000;
    b.controller.lastButtonFlags = 0x2000;
    CHECK(a.controller.lastButtonFlags == 0x1000 && b.controller.lastButtonFlags == 0x2000);
    CHECK([s activeDeviceMask] == 3);
    [s.deviceControllerTable removeObjectForKey:[s deviceKeyForDevice:&handles[0]]];
    CHECK([s activeDeviceMask] == 2);
    CHECK([s entryForDevice:&handles[2]].playerIndex == 0);
    for (int i = 3; i < 17; i++) CHECK([s entryForDevice:&handles[i]] != nil);
    int overflow;
    CHECK(s.deviceControllerTable.count == 16);
    CHECK([s activeDeviceMask] == 0xffff);
    CHECK([s entryForDevice:&overflow] == nil);
    CHECK(s.deviceControllerTable.count == 16);
    puts("device table replay passed");
    return 0;
}}
'''.replace('__METHODS__', methods)
cc, sdk = clang_and_sdk('controller table replay')
def replay(code):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / 'probe.m').write_text(code)
        subprocess.run([cc, '-fobjc-arc', '-Wall', '-Werror', '-isysroot', sdk,
                        '-framework', 'Foundation', str(path / 'probe.m'), '-o', str(path / 'probe')],
                       check=True)
        return subprocess.run([str(path / 'probe')], capture_output=True, text=True)


result = replay(harness)
assert result.returncode == 0, result.stderr
print(result.stdout.strip())
mutations = (
    ('missing table initialization', 'self.deviceControllerTable = [NSMutableDictionary dictionary];',
     'self.deviceControllerTable = nil;'),
    ('identical device keys', '[NSString stringWithFormat:@"hid:%p", (void *)device]', '@"same-model"'),
    ('exhausted slot reused', '    return -1;', '    return 0;'),
)
for label, old, new in mutations:
    assert harness.count(old) == 1, label
    result = replay(harness.replace(old, new, 1))
    assert result.returncode == 1 and 'failed line' in result.stderr, label + result.stderr
    print('caught:', label)
