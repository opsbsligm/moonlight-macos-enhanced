#import <Foundation/Foundation.h>
#import <CoreData/CoreData.h>
#include <assert.h>
#define PairStateUnpaired 0
#define StateUnknown 0
@interface App : NSObject @end
@implementation App @end
@interface Host : NSObject
@property NSString *address,*externalAddress,*localAddress,*ipv6Address,*mac,*name,*customName,*uuid;
@property NSData *serverCert;
@property NSNumber *pairState;
@property int serverCodecModeSupport;
@property NSSet *apps;
@property NSUInteger appReads;
- (NSSet *)appList;
@end
@implementation Host
- (NSSet *)appList { self.appReads++; return self.apps; }
@end
@interface TemporaryHost : NSObject
@property NSString *address,*externalAddress,*localAddress,*ipv6Address,*mac,*name,*customName,*uuid,*currentGame;
@property NSData *serverCert;
@property int pairState,state,serverCodecModeSupport;
@property NSSet *appList;
@property NSDictionary *addressLatencies,*addressStates;
- (id)initMetadataFromHost:(Host *)h;
- (id)initFromHost:(Host *)h;
@end
@interface TemporaryApp : NSObject
@property TemporaryHost *host;
- (id)initFromApp:(App *)a withTempHost:(TemporaryHost *)h;
@end
@implementation TemporaryApp
- (id)initFromApp:(App *)a withTempHost:(TemporaryHost *)h {if((self=[super init]))self.host=h;return self;}
@end
@implementation TemporaryHost
@@CONSTRUCTORS@@
@end
@interface Context : NSObject
@property NSArray *hosts;
@property BOOL fail;
@property NSUInteger reads;
- (void)performBlockAndWait:(void (^)(void))block;
- (NSArray *)executeFetchRequest:(NSFetchRequest *)request error:(NSError **)error;
@end
@implementation Context
- (void)performBlockAndWait:(void (^)(void))block {block();}
- (NSArray *)executeFetchRequest:(NSFetchRequest *)request error:(NSError **)error {
  self.reads++; assert([request.entityName isEqual:@"Host"]);
  assert(request.fetchLimit==(request.predicate?1:0));
  if(self.fail){*error=[NSError errorWithDomain:@"test" code:1 userInfo:nil];return nil;}
  if(request.predicate==nil)return self.hosts;
  NSArray *matches=[self.hosts filteredArrayUsingPredicate:request.predicate];
  return matches.count?[matches subarrayWithRange:NSMakeRange(0,1)]:@[];
}
@end
@interface DataManager : NSObject { @public Context *_managedObjectContext; }
- (TemporaryHost *)hostMetadataForUUID:(NSString *)uuid;
- (NSArray<TemporaryHost *> *)getHostMetadata;
@end
@implementation DataManager
@@FETCH@@
@end
int main(void) { @autoreleasepool {
  for(int i=0;i<100;i++) {
    __weak TemporaryHost *weakHost;
    __weak TemporaryHost *weakBulkHost;
    @autoreleasepool {
      Host *h=[Host new];h.uuid=@"A";h.address=@"local";h.externalAddress=@"wan";h.localAddress=@"lan";h.ipv6Address=@"v6";
      h.name=@"Test";h.customName=@"Alias";h.mac=@"mac";h.pairState=@1;h.serverCert=[NSData dataWithBytes:"x" length:1];
      h.serverCodecModeSupport=42;h.apps=[NSSet setWithObjects:[App new],[App new],[App new],nil];
      DataManager *dm=[DataManager new];dm->_managedObjectContext=[Context new];dm->_managedObjectContext.hosts=@[h];
      TemporaryHost *t=[dm hostMetadataForUUID:@"A"];weakHost=t;
      assert(t && t.appList.count==0 && h.appReads==0);
      assert([t.uuid isEqual:h.uuid] && [t.name isEqual:h.name] && [t.customName isEqual:h.customName]);
      assert([t.address isEqual:h.address] && [t.externalAddress isEqual:h.externalAddress] && [t.localAddress isEqual:h.localAddress] && [t.ipv6Address isEqual:h.ipv6Address]);
      assert(t.serverCert==h.serverCert && t.serverCodecModeSupport==42 && t.pairState==1);
      Host *second=[Host new]; second.uuid=@"B"; second.name=@"Second"; second.apps=h.apps;
      dm->_managedObjectContext.hosts=@[h,second];
      NSArray<TemporaryHost *> *bulk=[dm getHostMetadata];weakBulkHost=bulk.firstObject;
      assert(bulk.count==2 && [bulk[0].uuid isEqual:@"A"] && [bulk[1].uuid isEqual:@"B"]);
      assert(bulk[0].serverCert==h.serverCert && bulk[0].serverCodecModeSupport==42);
      assert(bulk[0].pairState==1 && bulk[1].pairState==PairStateUnpaired);
      assert(bulk[0].appList.count==0 && bulk[1].appList.count==0 && h.appReads==0 && second.appReads==0);
      dm->_managedObjectContext.hosts=@[]; assert([dm getHostMetadata].count==0 && [dm getHostMetadata]!=nil);
      dm->_managedObjectContext.hosts=@[h,second];
      NSUInteger reads=dm->_managedObjectContext.reads;
      assert([dm hostMetadataForUUID:@""]==nil && dm->_managedObjectContext.reads==reads);
      assert([dm hostMetadataForUUID:@"missing"]==nil);
      h.serverCert=nil; assert([dm hostMetadataForUUID:@"A"].pairState==PairStateUnpaired);
      dm->_managedObjectContext.fail=YES;assert([dm hostMetadataForUUID:@"A"]==nil);
      assert([dm getHostMetadata]==nil);
      dm->_managedObjectContext=nil; assert([dm getHostMetadata]==nil);
      // The existing streaming/library constructor must still own all apps.
      TemporaryHost *full=[[TemporaryHost alloc] initFromHost:h];
      assert(full.appList.count==3 && [full.uuid isEqual:h.uuid] && h.appReads==1);
      for(TemporaryApp *app in full.appList) assert(app.host==full);
      full.appList=[NSSet set]; // break only the deliberately constructed full test graph

    }
    assert(weakHost==nil && weakBulkHost==nil); // no application -> host -> application ownership cycle
  }
  puts("ok: 100 shipping single/bulk metadata fetch/constructor lifetimes, no app traversal; real Foundation/predicate, fake context");
}return 0;}
