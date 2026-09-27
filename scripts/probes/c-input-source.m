// Bounded, listen-only diagnosis of C and left-click provenance.
// Records no other key codes or character text; never requests permission.

#import <Foundation/Foundation.h>
#import <ApplicationServices/ApplicationServices.h>
#import <IOKit/hid/IOHIDManager.h>
#import <IOKit/hid/IOHIDKeys.h>
#import <IOKit/hidsystem/IOHIDLib.h>
#import <mach/mach_time.h>
#include <libproc.h>
static double seconds(uint64_t t) { mach_timebase_info_data_t b;mach_timebase_info(&b);return (double)t*b.numer/b.denom/1e9; }
static void hid(void *c,IOReturn r,void *sender,IOHIDValueRef v) {
 if(r || !v)return;
 IOHIDElementRef e=IOHIDValueGetElement(v);
 uint32_t page=IOHIDElementGetUsagePage(e), usage=IOHIDElementGetUsage(e);
 if(!((page==7 && usage==6)||(page==9 && usage==1)))return;
 IOHIDDeviceRef d=IOHIDElementGetDevice(e);
 NSString *name=(__bridge NSString *)IOHIDDeviceGetProperty(d,CFSTR(kIOHIDProductKey));
 printf("HID t=%.6f page=%u usage=%u value=%ld report=%u type=%u device=%s\n",seconds(IOHIDValueGetTimeStamp(v)),page,usage,(long)IOHIDValueGetIntegerValue(v),IOHIDElementGetReportID(e),IOHIDElementGetType(e),name.UTF8String?:"?");fflush(stdout);
}
static CGEventRef tap(CGEventTapProxy proxy,CGEventType type,CGEventRef e,void *ctx) {
 if(type==kCGEventKeyDown || type==kCGEventKeyUp) {
  if(CGEventGetIntegerValueField(e,kCGKeyboardEventKeycode)!=8)return e;
  pid_t pid=(pid_t)CGEventGetIntegerValueField(e,kCGEventSourceUnixProcessID);
  char path[PROC_PIDPATHINFO_MAXSIZE]={0};if(pid>0)proc_pidpath(pid,path,sizeof(path));
  printf("CG t=%.6f type=%u key=C pid=%d path=%s hidDown=%d sessionDown=%d sourceState=%lld\n",(double)CGEventGetTimestamp(e)/1e9,type,pid,path,CGEventSourceKeyState(kCGEventSourceStateHIDSystemState,8),CGEventSourceKeyState(kCGEventSourceStateCombinedSessionState,8),CGEventGetIntegerValueField(e,kCGEventSourceStateID));
 } else if(type==kCGEventLeftMouseDown || type==kCGEventLeftMouseUp) {
  printf("CG t=%.6f type=%u button=left clicks=%lld pid=%lld\n",(double)CGEventGetTimestamp(e)/1e9,type,CGEventGetIntegerValueField(e,kCGMouseEventClickState),CGEventGetIntegerValueField(e,kCGEventSourceUnixProcessID));
 }
 fflush(stdout);return e;
}
int main(int argc,const char **argv) {@autoreleasepool {
 setbuf(stdout,NULL);
 IOHIDAccessType access=IOHIDCheckAccess(kIOHIDRequestTypeListenEvent);
 printf("listenAccess=%d\n",access);
 if(access!=kIOHIDAccessTypeGranted)return 2;
 IOHIDManagerRef manager=IOHIDManagerCreate(NULL,0);IOHIDManagerSetDeviceMatching(manager,NULL);
 IOHIDManagerRegisterInputValueCallback(manager,hid,NULL);
 IOHIDManagerScheduleWithRunLoop(manager,CFRunLoopGetMain(),kCFRunLoopCommonModes);
 printf("hidOpen=%x\n",IOHIDManagerOpen(manager,0));
 CGEventMask mask=CGEventMaskBit(kCGEventKeyDown)|CGEventMaskBit(kCGEventKeyUp)|CGEventMaskBit(kCGEventLeftMouseDown)|CGEventMaskBit(kCGEventLeftMouseUp);
 CFMachPortRef port=CGEventTapCreate(kCGSessionEventTap,kCGHeadInsertEventTap,kCGEventTapOptionListenOnly,mask,tap,NULL);
 printf("tapAvailable=%d\n",port!=NULL);
 CFRunLoopSourceRef source=NULL;
 if(port){source=CFMachPortCreateRunLoopSource(NULL,port,0);CFRunLoopAddSource(CFRunLoopGetMain(),source,kCFRunLoopCommonModes);}
 int duration=argc>1?atoi(argv[1]):120;
 CFRunLoopRunInMode(kCFRunLoopDefaultMode,MAX(1,MIN(300,duration)),false);
 if(source){CFRunLoopRemoveSource(CFRunLoopGetMain(),source,kCFRunLoopCommonModes);CFRelease(source);}
 if(port){CFMachPortInvalidate(port);CFRelease(port);}
 IOHIDManagerUnscheduleFromRunLoop(manager,CFRunLoopGetMain(),kCFRunLoopCommonModes);IOHIDManagerClose(manager,0);CFRelease(manager);
}}
