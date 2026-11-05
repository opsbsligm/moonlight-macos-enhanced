#import <Foundation/Foundation.h>
int main(int argc, char **argv) {
    @autoreleasepool {
        NSUserDefaults *d = [[NSUserDefaults alloc] initWithSuiteName:@(argv[1])];
        NSString *s = [d stringForKey:@"moonlight.stream.resolution"];
        id o = [d objectForKey:@"moonlight.stream.resolution"];
        printf("stringForKey -> %s\n", s ? s.UTF8String : "(nil)");
        printf("objectForKey -> %s\n", o ? [[o description] UTF8String] : "(nil)");
        NSDictionary *volatileDomain = [d volatileDomainForName:@(argv[1])];
        printf("volatileDomainForName -> %s\n",
               volatileDomain ? [[NSString stringWithFormat:@"%lu keys", (unsigned long)volatileDomain.count] UTF8String] : "(nil)");
        NSDictionary *whole = [d persistentDomainForName:@(argv[1])];
        printf("persistentDomainForName -> %s\n",
               whole ? [[NSString stringWithFormat:@"%lu keys", (unsigned long)whole.count] UTF8String] : "(nil)");
    }
    return 0;
}
