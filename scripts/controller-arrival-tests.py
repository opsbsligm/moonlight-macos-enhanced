#!/usr/bin/env python3
"""Replay the shipping arrival method with deterministic input/main queues."""
from pathlib import Path
import subprocess
import tempfile
from apple_toolchain import clang_and_sdk

text = Path('Limelight/Input/HIDSupport.m').read_text()
start = text.index('- (void)sendControllerArrivalForEntry:')
end = text.index('{', start) + 1
depth = 1
while depth:
    depth += (text[end] == '{') - (text[end] == '}')
    end += 1
method = text[start:end]
start = text.index('- (void)sendControllerRemovalForEntry:')
end = text.index('{', start) + 1
depth = 1
while depth:
    depth += (text[end] == '{') - (text[end] == '}')
    end += 1
method += '\n' + text[start:end]
harness = r'''
#import <Foundation/Foundation.h>
typedef void *PML_INPUT_STREAM_CONTEXT;
typedef struct { void *context; uint64_t generation; } HIDInputLease;
static NSMutableArray *inputJobs, *mainJobs;
static int sends, resultCode, notes, removals, removalMask;
static BOOL initialized = YES;
static const uint16_t kHIDArrivalCapabilities = 3;
@interface HIDDeviceControllerEntry : NSObject
@property int playerIndex;
@property uint8_t protocolType;
@property uint32_t supportedButtonFlags;
@property uint64_t advertisedInputGeneration;
@property BOOL advertisedToHost;
@end
@implementation HIDDeviceControllerEntry
@end
@interface MLControllerInventory : NSObject
+ (instancetype)sharedInventory;
- (void)noteControllerArrival:(int)slot protocolType:(uint8_t)type;
@end
@implementation MLControllerInventory
+ (instancetype)sharedInventory { static id s; if (!s) s = [self new]; return s; }
- (void)noteControllerArrival:(int)slot protocolType:(uint8_t)type { notes++; }
@end
@interface HIDSupport : NSObject
@property int controllerDriver;
@property BOOL shouldSendInputEvents;
@property void *inputContext;
@property uint64_t generation;
@property NSMutableDictionary *deviceControllerTable;
- (int)activeDeviceMask;
- (void)sendControllerRemovalForEntry:(HIDDeviceControllerEntry *)entry;
- (void)sendControllerArrivalForEntry:(HIDDeviceControllerEntry *)entry;
@end
static HIDInputLease HIDAcquireInputContext(HIDSupport *s) {
    return (HIDInputLease){s.inputContext, s.generation};
}
static int LiSendControllerArrivalEventCtx(void *ctx, uint8_t slot, uint16_t mask,
                                           uint8_t type, uint32_t buttons, uint16_t caps) {
    sends++; return resultCode;
}
static void LiSendMultiControllerEventCtx(void *ctx, int slot, int mask, int buttons,
    int lt, int rt, int lx, int ly, int rx, int ry) { removals++; removalMask = mask; }
static void HIDDispatchInput(HIDSupport *s, HIDInputLease lease, dispatch_block_t job) {
    [inputJobs addObject:[^{
        if (initialized && s.inputContext == lease.context && s.generation == lease.generation) job();
    } copy]];
}
static void enqueueMain(dispatch_queue_t queue, dispatch_block_t job) { [mainJobs addObject:[job copy]]; }
#define dispatch_async enqueueMain
@implementation HIDSupport
- (int)activeDeviceMask { return self.deviceControllerTable.count ? 1 : 0; }
__METHOD__
@end
static void drain(NSMutableArray *jobs) {
    while (jobs.count) { dispatch_block_t b = jobs.firstObject; [jobs removeObjectAtIndex:0]; b(); }
}
#define CHECK(x) do { if (!(x)) { NSLog(@"failed line %d", __LINE__); return 1; } } while (0)
int main(void) { @autoreleasepool {
    inputJobs = [NSMutableArray new]; mainJobs = [NSMutableArray new];
    HIDSupport *s = [HIDSupport new]; s.shouldSendInputEvents = YES; s.generation = 1;
    HIDDeviceControllerEntry *e = [HIDDeviceControllerEntry new];
    s.deviceControllerTable = [@{@"a":e} mutableCopy];
    [s sendControllerArrivalForEntry:e]; CHECK(!e.advertisedToHost && sends == 0 && notes == 0);
    s.inputContext = (void *)1; resultCode = -1;
    [s sendControllerArrivalForEntry:e]; drain(inputJobs); drain(mainJobs);
    CHECK(sends == 1 && notes == 0 && !e.advertisedToHost && e.advertisedInputGeneration == 0);
    resultCode = 0;
    [s sendControllerArrivalForEntry:e]; [s sendControllerArrivalForEntry:e];
    CHECK(notes == 0 && !e.advertisedToHost);
    drain(inputJobs); CHECK(sends == 2 && notes == 0);
    drain(mainJobs); CHECK(notes == 1 && e.advertisedToHost);
    s.generation = 2;
    [s sendControllerArrivalForEntry:e]; s.generation = 3;
    drain(inputJobs); drain(mainJobs); CHECK(sends == 2 && notes == 1);
    [s sendControllerArrivalForEntry:e]; drain(inputJobs);
    s.generation = 4; drain(mainJobs); CHECK(notes == 1);
    [s sendControllerArrivalForEntry:e]; drain(inputJobs); drain(mainJobs);
    CHECK(sends == 4 && notes == 2 && e.advertisedInputGeneration == 4);
    s.controllerDriver = 1; s.generation = 5;
    [s sendControllerArrivalForEntry:e]; drain(inputJobs); CHECK(sends == 4);
    s.controllerDriver = 0; s.shouldSendInputEvents = NO;
    [s sendControllerArrivalForEntry:e]; drain(inputJobs); CHECK(sends == 4);
    s.shouldSendInputEvents = YES; initialized = NO;
    [s sendControllerArrivalForEntry:e]; drain(inputJobs); CHECK(sends == 4);
    initialized = YES;
    [s sendControllerArrivalForEntry:e]; drain(inputJobs);
    [s.deviceControllerTable removeAllObjects];
    [s sendControllerRemovalForEntry:e]; drain(inputJobs); drain(mainJobs);
    CHECK(notes == 2 && removals == 1 && removalMask == 0);
    s.generation = 6;
    // Even without a successful arrival in this generation, a normal state
    // packet could have activated the slot. Removal must still clear it.
    [s sendControllerRemovalForEntry:e]; drain(inputJobs); CHECK(removals == 2);
    puts("arrival lifecycle replay passed"); return 0;
}}
'''
cc, sdk = clang_and_sdk('controller arrival replay')
def run(source):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / 'probe.m').write_text(harness.replace('__METHOD__', source))
        subprocess.run([cc, '-fobjc-arc', '-fblocks', '-Wall', '-Werror', '-isysroot', sdk,
                        '-framework', 'Foundation', str(path / 'probe.m'), '-o', str(path / 'probe')], check=True)
        return subprocess.run([str(path / 'probe')], capture_output=True, text=True)
r = run(method)
assert r.returncode == 0, r.stderr
print(r.stdout.strip())
for name, old, new in (
    ('send failure ignored', 'if (result != 0) return;', '(void)result;'),
    ('queue dedup removed', 'if (entry.advertisedInputGeneration == inputLease.generation) return;', ''),
    ('stale completion accepted', 'current.generation != inputLease.generation ||', ''),
    ('removal depends on successful arrival',
     '        LiSendMultiControllerEventCtx(inputCtx, playerIndex, mask, 0, 0, 0, 0, 0, 0, 0);',
     '        if (entry.advertisedInputGeneration != inputLease.generation) return;\n'
     '        LiSendMultiControllerEventCtx(inputCtx, playerIndex, mask, 0, 0, 0, 0, 0, 0, 0);'),
):
    assert method.count(old) == 1, name
    r = run(method.replace(old, new))
    assert r.returncode == 1 and 'failed line' in r.stderr, name + r.stderr
    print('caught:', name)
