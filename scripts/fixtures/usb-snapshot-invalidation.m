// Shipping snapshot with deterministic IOKit responses; no device is opened.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#include <assert.h>
static int mode, positions[256], references[256];
static CFMutableDictionaryRef MLTestMatching(const char *name) {
    assert(strcmp(name,"IOUSBHostDevice")==0);
    return CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
}
static kern_return_t MLTestServices(mach_port_t port,CFDictionaryRef dict,io_iterator_t *out) {
    (void)port;CFRelease(dict);
    if(mode==10)return KERN_FAILURE;
    *out=100;references[100]++;return KERN_SUCCESS;
}
static io_object_t MLTestNext(io_iterator_t iterator) {
    assert(references[iterator]>0);
    if(positions[iterator]++)return IO_OBJECT_NULL;
    if(mode==11 && iterator==100)return IO_OBJECT_NULL;
    io_object_t result=iterator==101?201:200;references[result]++;return result;
}
static boolean_t MLTestValid(io_iterator_t iterator) {
    assert(references[iterator]>0 && positions[iterator]>=1);
    return !((mode==1 && iterator==100)||(mode==2 && iterator==101)||(mode==3 && iterator==102));
}
static kern_return_t MLTestRelease(io_object_t object) {
    assert(object>0 && references[object]>0);references[object]--;return KERN_SUCCESS;
}
static kern_return_t MLTestChildren(io_registry_entry_t object,const io_name_t plane,io_iterator_t *out) {
    (void)plane;assert(object==200);
    if(mode==4)return KERN_FAILURE;
    *out=101;references[101]++;return KERN_SUCCESS;
}
static kern_return_t MLTestParents(io_registry_entry_t object,const io_name_t plane,io_iterator_t *out) {
    (void)plane;assert(object==201);
    *out=102;references[102]++;return KERN_SUCCESS;
}
static kern_return_t MLTestID(io_registry_entry_t object,uint64_t *out) {
    if((mode==8 && object==201)||(mode==9 && object==200))return KERN_FAILURE;
    *out=object;return KERN_SUCCESS;
}
static kern_return_t MLTestProperties(io_registry_entry_t object,CFMutableDictionaryRef *out,CFAllocatorRef allocator,IOOptionBits flags) {
    (void)allocator;(void)flags;
    if((mode==5 && object==200)||(mode==6 && object==201))return KERN_FAILURE;
    NSDictionary *properties=object==200?@{@"idVendor":@0x1234,@"idProduct":@0x5678,@"bDeviceClass":@0}:
        @{@"bInterfaceNumber":@0,@"bInterfaceClass":@8,@"bInterfaceSubClass":@6,@"bInterfaceProtocol":@80};
    *out=CFDictionaryCreateMutableCopy(NULL,0,(__bridge CFDictionaryRef)properties);return KERN_SUCCESS;
}
#define IOServiceMatching MLTestMatching
#define IOServiceGetMatchingServices MLTestServices
#define IOIteratorNext MLTestNext
#define IOIteratorIsValid MLTestValid
#define IOObjectRelease MLTestRelease
#define IORegistryEntryGetChildIterator MLTestChildren
#define IORegistryEntryGetParentIterator MLTestParents
#define IORegistryEntryGetRegistryEntryID MLTestID
#define IORegistryEntryCreateCFProperties MLTestProperties
@@RULES@@
int main(void) { @autoreleasepool {
    (void)MLTestValid; // legal negative mutations must not fail only as unused functions
    for(mode=0;mode<12;mode++) {
        if(mode==7)continue;
        memset(positions,0,sizeof positions);memset(references,0,sizeof references);
        MLUSBBusSnapshotStatus status=MLUSBBusSnapshotStatusRead;
        NSArray *devices=MLUSBBusSnapshotCopyDeviceIdentities(&status);
        BOOL success=mode==0 || mode==11;
        assert(status==(success?MLUSBBusSnapshotStatusRead:MLUSBBusSnapshotStatusBusUnreadable));
        assert(devices.count==(mode==0?1:0));
        for(int i=0;i<256;i++)assert(references[i]==0);
    }
    puts("shipping snapshot: 11 complete/empty/invalidation/failure cases, partial data refused, all IOKit refs released; API doubles");
}return 0;}
