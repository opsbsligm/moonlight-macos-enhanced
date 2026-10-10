#!/usr/bin/env python3
"""The USB redirection chain over a real socket, against a host that really answers.

The session gate pins the sequencing against a responder that lives in that file's own
memory; the policy and enumeration gates pin their layers the same way. What none of them
could claim until now is the seam the feature actually breaks on: the bytes a
Sunshine-shaped host writes, read by the parser the app ships, trimmed the way the panel
trims, fed to the state machine and the policy. Every stage of that chain is code in this
repository; every join between two stages was untested until this file.

So this gate runs a real HTTP server on a real loopback socket, in a thread, answering
`/serverinfo` in the shape Sunshine answers it (docs/usb-redirection-host-contract.md 1.7:
one root element carrying status_code, flat child tags), and compiles the real shipping
files into the driver:

  HttpResponse.m / ServerInfoResponse.m   the libxml2 parse the app itself uses
  ServerInfoResponse.m populateHost       the trim the app itself applies
  TemporaryHost/.m + Utils.m              the object that trim lands on
  DeviceRedirectionSession.m              the sequencing under test
  DeviceRedirectionPolicy.m               the allow-list decision
  USBDeviceEnumeration.m + USBBusSnapshot.m  registry nodes -> descriptor -> verdict

The driver fetches over a BSD socket -- no HTTP library, no NSURLSession, one
connect/write/read -- so the answer it parsed travelled the same route a click on the
panel's "check host" button takes. The panel (SettingsDevicesPane.swift checkHost) does
exactly this sequence; this file is the proof that the sequence survives the wire. The
identifiers and the capability tag are padded with a space on purpose: libxml2 keeps the
whitespace it is given, the app trims it on every read, and "did the trim happen before
the compare" is exactly the class of defect that silently turns an offering host into a
refusing one.

What is asserted, and each has a mutation listed below or in the layer's own gate:

  the advertised answer parses, trims, matches the expected uuid, and leaves a session
    that may bind; the full bind/state/item walk then runs with the slots spent;
  `0`, a missing tag, `yes`, a wrong-case tag and a 404 all refuse, and a stranger's
    capability is never credited to our host by the uuid compare;
  populateHost lands a trimmed uuid on the object -- real bytes, shipped trim;
  the policy is asked the same question with the same value and agrees with the panel,
    including that wire padding is framing and not a different answer;
  registry nodes in the shapes the live bus publishes walk enumerator -> policy -> audit
    line (the M2 seam, with no hardware dependency), and a live read of the runner's own
    bus yields verdict lines that name no serial;
  a duplicated tag collapses to one answer inside the parse, and the session layer is
    still strict about it when the two answers survive to it.
"""
import http.server
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apple_toolchain

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

MIN_DRIVER_CHECKS = 24
SERVER_UNIQUE_ID = "aa:bb:cc:dd:ee:ff"

failures = []


def check(ok, message):
    print("%-4s %s" % ("ok" if ok else "FAIL", message))
    if not ok:
        failures.append(message)


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ---------------------------------------------------------------------------
# The host: a real socket, Sunshine's shape, behaviour picked by URL.
# ---------------------------------------------------------------------------

class HostHandler(http.server.BaseHTTPRequestHandler):
    """Answers /serverinfo the way nvhttp.cpp assembles it: flat root children.

    The URL picks the behaviour so one server covers the matrix without a restart:
      /serverinfo            -- advertises (padded uuid, padded tag: the trim must save it)
      /serverinfo/no         -- knows the tag, refuses with 0
      /serverinfo/silent     -- never heard of the tag (the common case today)
      /serverinfo/stranger   -- advertises, but its uniqueid is not the panel's host
      /serverinfo/textyes    -- answers the truth in prose, which is not the contract
      /serverinfo/case-wrong -- the tag in another case is another tag
      /serverinfo/ambiguous  -- the tag twice, 1 then 0; the parse keeps one
      /serverinfo/http-404   -- a body that says it is a failure
    """

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's name
        body = self.answer_for(self.path).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        # The transport status stays 200 even for the 404 body: this is the app's own
        # protocol, where the answer lives in the root attributes and `isStatusOk`
        # reads the parsed status_code, not the transport.

    def answer_for(self, path):
        parts = {
            "/serverinfo/no": (' "%s"' % SERVER_UNIQUE_ID, "<usbRedirection>0</usbRedirection>"),
            "/serverinfo/silent": (' "%s"' % SERVER_UNIQUE_ID, ""),
            "/serverinfo/stranger": (' "11:22:33:44:55:66 "', "<usbRedirection>1</usbRedirection>"),
            "/serverinfo/textyes": (' "%s"' % SERVER_UNIQUE_ID,
                                     "<usbRedirection>yes</usbRedirection>"),
            "/serverinfo/case-wrong": (' "%s"' % SERVER_UNIQUE_ID,
                                        "<USBRedirection>1</USBRedirection>"),
            "/serverinfo/ambiguous": (' "%s"' % SERVER_UNIQUE_ID,
                                       "<usbRedirection>1</usbRedirection>"
                                       "<usbRedirection>0</usbRedirection>"),
            "/serverinfo/http-404": None,
        }
        if path.startswith("/serverinfo/http-404"):
            return ('<root status_code="404" status_message="Not Found">'
                    "<hostname>ghost</hostname></root>")
        unique, tag = parts.get(path, (' "%s" ' % SERVER_UNIQUE_ID,
                                        "<usbRedirection>1 </usbRedirection>"))
        return ('<root status_code="200" status_message="OK">'
                "<hostname>homelab-pc</hostname>"
                "<version>2.6.0.123</version>"
                "<uniqueid> %s </uniqueid>"
                "<PairStatus>1</PairStatus>"
                "<currentgame>7</currentgame>"
                "<state>DIRECTED_STREAMING_SERVER_STOPPING</state>"
                "%s"
                "</root>" % (unique.strip(' "'), tag))

    def log_message(self, *args):
        pass  # a gate that logs its own traffic buries its own verdicts


class HostFixture:
    def __enter__(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HostHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def http_get(port, path):
    """Fetch one path over a bare socket and return the body the parser will see."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                      "Connection: close\r\n\r\n" % path).encode("utf-8"))
        chunks = []
        while True:
            part = sock.recv(65536)
            if not part:
                break
            chunks.append(part)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    length = int(re.search(rb"Content-Length: (\d+)", head).group(1))
    assert len(body) == length, "the host lied about its own content length"
    return body


# ---------------------------------------------------------------------------
# The bundle: the shipping sources, imports flattened, one translation unit.
# ---------------------------------------------------------------------------

SHIM = """
// The two things the shipping files ask their headers for, answered inside the bundle:
// a logger (HttpResponse's parse noise is not what this gate reports on, and the
// production Logger.m wants a log directory a harness has no business creating), and
// the CoreData-generated Host/App property declarations TemporaryHost.h names. The real
// Host is an NSManagedObject; the harness never builds a managed object store, so the
// properties are re-declared on plain NSObject classes and only the code paths that
// travel the wire -- populateHost and the propagate guards -- are exercised.
#import <Foundation/Foundation.h>
typedef enum { LOG_D, LOG_I, LOG_W, LOG_E } LogLevel;
static inline void Log(LogLevel level, NSString *fmt, ...) { (void)level; (void)fmt; }
@interface Host : NSObject
@property(nonatomic, copy) NSString *address;
@property(nonatomic, copy, nullable) NSString *customName;
@property(nonatomic, copy) NSString *appVersion;
@property(nonatomic, copy) NSString *gfeVersion;
@property(nonatomic, copy) NSString *externalAddress;
@property(nonatomic, copy) NSString *localAddress;
@property(nonatomic, copy) NSString *ipv6Address;
@property(nonatomic, copy) NSString *mac;
@property(nonatomic, copy) NSString *name;
@property(nonatomic, copy) NSString *uuid;
@property(nonatomic, retain) NSNumber *pairState;
@property(nonatomic, retain) NSData *serverCert;
@property(nonatomic) int serverCodecModeSupport;
@property(nonatomic, retain) NSSet *appList;
@end
@interface App : NSObject
@property(nonatomic, copy) NSString *identifier;
@property(nonatomic, copy) NSString *name;
@property(nonatomic, copy) NSString *app_id;
@property(nonatomic, retain) Host *appHost;
@property(nonatomic) BOOL hdrSupported;
@property(nonatomic) BOOL hidden;
@property(nonatomic) BOOL pinned;
@end
@implementation Host
@end
@implementation App
@end
"""

SOURCES = [
    "Limelight/Utility/Utils.h",
    "Limelight/Network/HttpResponse.h",
    "Limelight/Database/TemporaryHost.h",
    "Limelight/Database/TemporaryApp.h",
    "Limelight/Network/ServerInfoResponse.h",
    "Limelight/Stream/DeviceRedirectionSession.h",
    "Limelight/Stream/DeviceRedirectionPolicy.h",
    "Limelight/Stream/USBDeviceEnumeration.h",
    "Limelight/Stream/USBBusSnapshot.h",
    "Limelight/Utility/Utils.m",
    "Limelight/Network/HttpResponse.m",
    "Limelight/Database/TemporaryHost.m",
    "Limelight/Database/TemporaryApp.m",
    "Limelight/Network/ServerInfoResponse.m",
    "Limelight/Stream/DeviceRedirectionSession.m",
    "Limelight/Stream/DeviceRedirectionPolicy.m",
    "Limelight/Stream/USBDeviceEnumeration.m",
    "Limelight/Stream/USBBusSnapshot.m",
]


def bundle():
    text = SHIM
    for rel in SOURCES:
        body = read(rel)
        body = re.sub(r'#import "[^"]*\.h"\n', "", body)
        body = body.replace("#import <Foundation/Foundation.h>\n", "")
        body = body.replace("#import <libxml2/libxml/xmlreader.h>\n",
                            "#include <libxml/parser.h>\n")
        # HttpResponse.m keeps its synthesize -- the protocol properties live
        # there. A subclass that re-synthesizes the same names collides with the
        # superclass ivars once both bodies share one translation unit, so the
        # strip applies to ServerInfoResponse.m alone: an artifact of flattening
        # two units, not of the shipped code.
        if rel == "Limelight/Network/ServerInfoResponse.m":
            body = re.sub(r"^@synthesize data, statusCode, statusMessage;\n", "",
                          body, flags=re.M)
        # The CoreData App row names its primary key `id`; the shim calls it
        # app_id so the word cannot read as a selector. Only TemporaryApp.m
        # crosses that rename, and each of its access sites is listed.
        body = body.replace("self.id = app.id;", "self.id = app.app_id;")
        body = body.replace("parent.id = self.id;", "parent.app_id = self.id;")
        body = body.replace("((App*)object).id", "((App*)object).app_id")
        body = body.replace("parent.host = host;", "parent.appHost = host;")
        body = body.replace("((App*)object).host.uuid", "((App*)object).appHost.uuid")
        body = body.replace("#import <IOKit/IOKitLib.h>\n", "#import <IOKit/IOKitLib.h>\n")
        text += body + "\n"
    return text


# ---------------------------------------------------------------------------
# The driver: the bundle above, pointed at the socket.
# ---------------------------------------------------------------------------

DRIVER_HEAD = r"""
#import <sys/socket.h>
#import <netinet/in.h>
#import <arpa/inet.h>
#import <unistd.h>

@@RULES@@

static int failures = 0;
static int checks_run = 0;

static void check_case(BOOL ok, const char *what) {
    checks_run++;
    if (!ok) failures++;
    printf("%-4s %s\n", ok ? "ok" : "FAIL", what);
}

/// A minimal HTTP/1.1 GET over a BSD socket, body after the header block, and only if
/// the framing agrees with itself. One connect/write/read: the point of the round trip
/// is that the bytes cross a real kernel on the way back to the shipped parser.
static NSData *fetch(NSInteger port, NSString *path) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return nil;
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) { close(fd); return nil; }
    NSString *request = [NSString stringWithFormat:
        @"GET %@ HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n", path];
    NSData *request_data = [request dataUsingEncoding:NSUTF8StringEncoding];
    if (write(fd, request_data.bytes, request_data.length) < 0) { close(fd); return nil; }
    NSMutableData *raw = [NSMutableData data];
    char buffer[16384];
    ssize_t got;
    while ((got = read(fd, buffer, sizeof(buffer))) > 0) {
        [raw appendBytes:buffer length:(NSUInteger)got];
    }
    close(fd);
    NSData *marker = [@"\r\n\r\n" dataUsingEncoding:NSUTF8StringEncoding];
    NSRange split = [raw rangeOfData:marker options:0 range:NSMakeRange(0, raw.length)];
    if (split.location == NSNotFound) return nil;
    NSData *headers = [raw subdataWithRange:NSMakeRange(0, split.location)];
    NSString *head_text = [[NSString alloc] initWithData:headers
                                                encoding:NSASCIIStringEncoding];
    NSRegularExpression *cl = [NSRegularExpression
        regularExpressionWithPattern:@"Content-Length: ([0-9]+)" options:0 error:NULL];
    NSTextCheckingResult *match = [cl firstMatchInString:head_text options:0
                                                   range:NSMakeRange(0, head_text.length)];
    if (!match) return nil;
    NSInteger declared = [[head_text substringWithRange:
        [match rangeAtIndex:1]] integerValue];
    NSData *body = [raw subdataWithRange:NSMakeRange(NSMaxRange(split),
                                                     raw.length - NSMaxRange(split))];
    return (NSInteger)body.length == declared ? body : nil;
}

static NSCharacterSet *padding(void) {
    return [NSCharacterSet whitespaceAndNewlineCharacterSet];
}

/// The panel's own sequence (SettingsDevicesPane.swift checkHost), as one function, so a
/// case can only change the server's answer and not the reading of it: fetch, parse,
/// trim, compare the uuid, hand the trimmed tag value to the session. `answered` comes
/// back so a case can tell "refused" from "not heard" -- the distinction the panel exists
/// to make and the one this file exists to prove survives the parse.
static MLDeviceRedirectionSession *panel_session(NSInteger port, NSString *path,
                                                 NSString *expected_uuid,
                                                 NSString **tag_out,
                                                 BOOL *answered_out) {
    ServerInfoResponse *response = [[ServerInfoResponse alloc] init];
    NSData *body = fetch(port, path);
    if (body != nil) [response populateWithData:body];
    NSString *answered_uuid = [[response getStringTag:TAG_UNIQUE_ID] ?: @""
        stringByTrimmingCharactersInSet:padding()];
    NSString *advertised = [[response getStringTag:MLDeviceRedirectionServerInfoTagName()]
        ?: @"" stringByTrimmingCharactersInSet:padding()];
    const BOOL answered = [response isStatusOk]
        && expected_uuid.length > 0
        && [answered_uuid isEqualToString:expected_uuid];
    if (tag_out != NULL) *tag_out = answered ? advertised : nil;
    if (answered_out != NULL) *answered_out = answered;
    NSMutableArray<MLDeviceRedirectionField *> *fields = [NSMutableArray array];
    if (answered && advertised != nil) {
        [fields addObject:[MLDeviceRedirectionField
            fieldNamed:MLDeviceRedirectionServerInfoTagName() value:advertised]];
    }
    return [MLDeviceRedirectionSession sessionFromServerInfoFields:fields];
}

static MLDeviceRedirectionSession *answered_on(MLDeviceRedirectionSession *session,
                                               MLDeviceRedirectionChannel channel,
                                               NSString *tag, id value) {
    MLDeviceRedirectionSession *asked = [session sessionByRecordingRequest:channel];
    return [asked sessionByRecordingResponse:
        [MLDeviceRedirectionHostResponse responseOnChannel:channel
            fields:@[[MLDeviceRedirectionField fieldNamed:tag value:value]]]];
}
"""

DRIVER_MAIN = r"""
int main(int argc, char **argv) {
    (void)argc;
    const NSInteger port = (NSInteger)atoi(argv[1]);
    NSString *unique_id = [@(argv[2]) copy];
    @autoreleasepool {
    // 1. The advertise path over the wire: padded identifiers, padded tag. The trim the
    //    app applies everywhere else is what makes this match; a compare written before
    //    the trim would fail loudly here and silently in production.
    NSString *advertised = nil;
    BOOL answered = NO;
    MLDeviceRedirectionSession *idle = panel_session(port, @"/serverinfo",
                                                     unique_id, &advertised, &answered);
    check_case(answered && [advertised isEqualToString:@"1"],
               "an offering host survives the wire, the parse and the trim");
    check_case(idle.phase == MLDeviceRedirectionPhaseIdle && idle.mayRequestBind,
               "the advertised answer leaves a session that may ask for a bind");

    // 2. The whole exchange, driven by what the parsed answer said. Bind, state, one
    //    upload: the walk the stream path will take the day a host exists for it.
    MLDeviceRedirectionSession *bound = answered_on(idle, MLDeviceRedirectionChannelBind,
                                                    @"usbRedirectionBound", @"1");
    check_case(bound.phase == MLDeviceRedirectionPhaseBound && bound.mayRequestState,
               "an explicit bind yes advances the parsed session to asking for room");
    MLDeviceRedirectionSession *ready = answered_on(bound, MLDeviceRedirectionChannelState,
                                                    @"usbRedirectionSlots", @2);
    check_case(ready.phase == MLDeviceRedirectionPhaseReady && ready.availableSlots == 2
               && ready.mayUploadDeviceDescriptor,
               "two slots is an answer that authorises the first upload");
    MLDeviceRedirectionSession *delivered = answered_on(ready, MLDeviceRedirectionChannelItem,
                                                        @"usbRedirectionAccepted", @1);
    check_case(delivered.phase == MLDeviceRedirectionPhaseReady
               && delivered.availableSlots == 1,
               "a delivered device spends one slot on a session that came off the wire");

    // 3. The app's own trim, on the object it lands on: real bytes through populateHost.
    ServerInfoResponse *direct = [[ServerInfoResponse alloc] init];
    [direct populateWithData:fetch(port, @"/serverinfo")];
    TemporaryHost *host = [[TemporaryHost alloc] init];
    [direct populateHost:host];
    check_case([host.uuid isEqualToString:unique_id],
               "populateHost lands a uuid the wire padded as the trimmed value it compares");
    check_case(host.pairState == PairStatePaired && [host.currentGame isEqualToString:@"0"],
               "a stopping host parses to paired with no game, through the shipped rules");

    // 4. A refusal is an answer; a missing tag is the same refusal by another route.
    NSString *no_tag = nil;
    BOOL no_answered = NO;
    MLDeviceRedirectionSession *refused = panel_session(port, @"/serverinfo/no",
                                                        unique_id, &no_tag, &no_answered);
    check_case(no_answered && [no_tag isEqualToString:@"0"]
               && refused.stop == MLDeviceRedirectionStopHostNotAdvertised,
               "a heard refusal reaches the panel and closes the session the same way");
    MLDeviceRedirectionSession *silent = panel_session(port, @"/serverinfo/silent",
                                                       unique_id, NULL, NULL);
    check_case(silent.phase == MLDeviceRedirectionPhaseClosed
               && silent.stop == MLDeviceRedirectionStopHostNotAdvertised,
               "the old host and the refusing host agree on their one shared answer");

    // 5. Prose, casing and a stranger: none of them is a yes, and the panel says so with
    //    the uuid compare or the trim, not with luck.
    MLDeviceRedirectionSession *textyes = panel_session(port, @"/serverinfo/textyes",
                                                        unique_id, NULL, NULL);
    check_case(textyes.stop == MLDeviceRedirectionStopHostNotAdvertised,
               "a host that writes truth in prose is a host that did not answer in numbers");
    MLDeviceRedirectionSession *case_wrong = panel_session(port, @"/serverinfo/case-wrong",
                                                           unique_id, NULL, NULL);
    check_case(case_wrong.stop == MLDeviceRedirectionStopHostNotAdvertised,
               "a tag in another case is another tag, on the wire as in the field list");
    MLDeviceRedirectionSession *stranger = panel_session(port, @"/serverinfo/stranger",
                                                         unique_id, NULL, NULL);
    check_case(stranger.phase == MLDeviceRedirectionPhaseClosed
               && !stranger.mayRequestBind,
               "a capability from a host with another uuid is not credited to ours");

    // 6. The 404 parses, says so, and entitles nothing.
    ServerInfoResponse *broken = [[ServerInfoResponse alloc] init];
    [broken populateWithData:fetch(port, @"/serverinfo/http-404")];
    check_case(![broken isStatusOk],
               "a 404 body parses far enough to report its own failure");
    MLDeviceRedirectionSession *notfound = panel_session(port, @"/serverinfo/http-404",
                                                         unique_id, NULL, NULL);
    check_case(notfound.phase == MLDeviceRedirectionPhaseClosed
               && !notfound.mayRequestBind,
               "a parsed failure never leaves a session that can ask for anything");

    // 7. One tag, two answers: the parse collapses to the last one it kept, and the
    //    session is strict about a field that survived twice. Locking today's behaviour,
    //    not endorsing it -- if the parse starts keeping both, this case must change.
    NSString *ambiguous_tag = nil;
    MLDeviceRedirectionSession *collapsed = panel_session(port, @"/serverinfo/ambiguous",
                                                          unique_id, &ambiguous_tag, NULL);
    check_case(collapsed.phase == MLDeviceRedirectionPhaseClosed
               && [ambiguous_tag isEqualToString:@"0"],
               "the parse hands the session one answer per tag, and it is the last one read");
    MLDeviceRedirectionSession *twice = [MLDeviceRedirectionSession
        sessionFromServerInfoFields:@[
            [MLDeviceRedirectionField fieldNamed:MLDeviceRedirectionServerInfoTagName()
                                           value:@"1"],
            [MLDeviceRedirectionField fieldNamed:MLDeviceRedirectionServerInfoTagName()
                                           value:@"0"]]];
    check_case(twice.stop == MLDeviceRedirectionStopAmbiguousResponse,
               "two answers that reach the session are ambiguity, not a coin flip");

    // 8. The policy is asked the same question with the same value, and must not answer
    //    differently from the panel: one host, one spelling of yes, two callers.
    const BOOL policy_advertised =
        [MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:
            @{MLDeviceRedirectionServerInfoTagName(): advertised ?: @"",
              @"uniqueid": unique_id, @"PairStatus": @"1"}];
    check_case(policy_advertised == (advertised != nil && [advertised isEqualToString:@"1"]),
               "the parse, the trim and the policy agree on the one answer");
    check_case(![MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:
                     @{MLDeviceRedirectionServerInfoTagName(): @"yes"}],
               "prose is a no to the policy exactly as it is to the session");
    check_case(![MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:nil],
               "a host with no answer at all gets the same refusal through this door");
    check_case([MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:
                    @{MLDeviceRedirectionServerInfoTagName(): @" 1 "}],
               "the padding the wire carries is framing, and the policy trims before it reads");

    // 9. The M2 seam: registry nodes in the shapes the live bus publishes (measured in
    //    usb-bus-snapshot-tests.py), through the enumerator, into the policy the answer
    //    on the wire just unlocked. Bus -> policy -> audit line, every step shipping.
    MLUSBDeviceIdentity *dock = MLUSBDeviceIdentityFromRegistryNodes(@[
        @{ @"idVendor": @0x17EF, @"idProduct": @0x305F },
        @{ @"bInterfaceClass": @0x01, @"bInterfaceProtocol": @0x02 },
        @{ @"bInterfaceClass": @0x0B, @"bInterfaceProtocol": @0x00 },
    ]);
    MLUSBDeviceIdentity *headset = MLUSBDeviceIdentityFromRegistryNodes(@[
        @{ @"idVendor": @0x17EF, @"idProduct": @0x3060,
           @"bInterfaceClass": @0x03, @"bInterfaceProtocol": @0x00 },
    ]);
    MLDeviceRedirectionPolicy *policy =
        [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:YES
                                                     hostIsPaired:YES
                                      hostSupportsDeviceRedirection:policy_advertised
                                          allowedInterfaceClasses:[NSSet setWithObject:@0x03]
                                         localInputDevicesAllowed:NO
                                                            rules:@[ [MLDeviceRedirectionRule
                                                        familyRuleForVendorID:0x17EF
                                                                      enabled:YES] ]];
    MLDeviceRedirectionVerdict *dock_verdict = [policy verdictForDevice:dock.descriptor];
    check_case(!dock_verdict.isAllowed
               && dock_verdict.denial == MLDeviceRedirectionDenialClassReserved,
               "a dock's reserved face cannot be outvoted by its audio face, over any link");
    MLDeviceRedirectionVerdict *headset_verdict = [policy verdictForDevice:headset.descriptor];
    check_case(headset_verdict.isAllowed && headset_verdict.ruleIndex == 0,
               "the device the rule names is allowed on the bus-shaped path");
    NSString *line = [headset diagnosticLineForVerdict:headset_verdict];
    check_case([line rangeOfString:@"vid=17ef"].location != NSNotFound
               && [line rangeOfString:@"token=none"].location != NSNotFound,
               "the audit line says which device and carries no serial to log");
    MLDeviceRedirectionPolicy *unoffering =
        [[MLDeviceRedirectionPolicy alloc] initWithFeatureEnabled:YES
                                                     hostIsPaired:YES
                                      hostSupportsDeviceRedirection:NO
                                          allowedInterfaceClasses:[NSSet setWithObject:@0x03]
                                         localInputDevicesAllowed:NO
                                                            rules:@[ [MLDeviceRedirectionRule
                                                        familyRuleForVendorID:0x17EF
                                                                      enabled:YES] ]];
    check_case([unoffering verdictForDevice:headset.descriptor].denial
                   == MLDeviceRedirectionDenialHostUnsupported,
               "the same device with the same rule stops at the host that did not offer");

    // 10. The runner's own bus, read through the shipping snapshot and straight into the
    //     same policy. No expectation about what is plugged in -- only that a read bus
    //     produces verdict lines that name no serial and lose no device on the way.
    MLUSBBusSnapshotStatus status = MLUSBBusSnapshotStatusBusUnreadable;
    NSArray<MLUSBDeviceIdentity *> *live = MLUSBBusSnapshotCopyDeviceIdentities(&status);
    check_case(status == MLUSBBusSnapshotStatusRead,
               "the harness's own machine can read its bus through the shipping snapshot");
    BOOL lines_clean = YES;
    for (MLUSBDeviceIdentity *identity in live) {
        NSString *audit = [identity diagnosticLineForVerdict:[policy verdictForDevice:identity.descriptor]];
        if ([audit rangeOfString:@"token="].location == NSNotFound) lines_clean = NO;
    }
    check_case(lines_clean,
               "every device on the real bus reaches a verdict line without a serial in it");

    printf("%s (%d checks)\n", failures ? "RUN FAILED" : "RUN PASSED", checks_run);
    }
    return failures ? 1 : 0;
}
"""


def compiled(source, work, cc, sdk, port, uuid):
    path = os.path.join(work, "loopback_driver.m")
    binary = os.path.join(work, "loopback_driver")
    open(path, "w", encoding="utf-8").write(source)
    built = subprocess.run([cc, "-x", "objective-c", "-fobjc-arc", "-isysroot", sdk,
                            "-Wall", "-Werror",
                            "-I", os.path.join(sdk, "usr", "include", "libxml2"),
                            "-framework", "Foundation", "-framework", "IOKit",
                           "-framework", "CFNetwork",
                           "-lxml2",
                            path, "-o", binary],
                           capture_output=True, text=True)
    if built.returncode != 0:
        return None, (built.stdout + built.stderr)[-2500:]
    ran = subprocess.run([binary, str(port), uuid], capture_output=True, text=True)
    return ran, (ran.stdout + ran.stderr)


def run_bundle(label, rules, cc, sdk, port, expect_pass):
    with tempfile.TemporaryDirectory() as work:
        ran, out = compiled(DRIVER_HEAD.replace("@@RULES@@", rules) + DRIVER_MAIN,
                            work, cc, sdk, port, SERVER_UNIQUE_ID)
        if ran is None:
            check(False, "%s: the harness compiled (%s)"
                  % (label, (out or "").strip()[-800:]))
            return
        if expect_pass:
            for line in (out or "").strip().splitlines():
                print(line)
            reported = re.search(r"RUN PASSED \((\d+) checks\)", out or "")
            check(ran.returncode == 0, "the chain walks the wire and answers every case")
            count = int(reported.group(1)) if reported else -1
            check(count >= MIN_DRIVER_CHECKS,
                  "the compiled run reports its own case list (%d checks, floor %d)"
                  % (count, MIN_DRIVER_CHECKS))
        else:
            check(ran.returncode != 0 or "RUN FAILED" in (out or ""),
                  "the check still fails when %s" % label)


def mutated(rules, label, before, after):
    check(before in rules, "%s: the source it mutates is still there" % label)
    return rules.replace(before, after, 1)


def main():
    print("-- the USB chain over a socket, with the app's own parser on the other end --")

    with HostFixture() as host:
        body = http_get(host.port, "/serverinfo").decode("utf-8")
        check("<usbRedirection>1 </usbRedirection>" in body
              and 'status_code="200"' in body and "<uniqueid> " in body,
              "the fixture answers in the shape the contract says a host answers with")
        check(b"404" in http_get(host.port, "/serverinfo/http-404"),
              "the broken route really serves the parsed failure")

        rules = bundle()
        check(all(("@implementation " + name) in rules
                  for name in ("HttpResponse", "ServerInfoResponse",
                               "TemporaryHost", "TemporaryApp",
                               "MLDeviceRedirectionSession",
                               "MLDeviceRedirectionPolicy",
                               "MLUSBDeviceIdentity"))
              and len(SOURCES) == 18,
              "the bundle carries every shipping source the chain touches")
        for name in ("HttpResponse.m", "ServerInfoResponse.m", "DeviceRedirectionSession.m",
                     "DeviceRedirectionPolicy.m", "USBDeviceEnumeration.m", "USBBusSnapshot.m"):
            check(("%s" % name.split(".")[0]) in rules,
                  "%s is compiled into this gate, not reimplemented by it" % name)

        cc, sdk = apple_toolchain.clang_and_sdk("the usb host loopback")
        run_bundle("the shipping chain", rules, cc, sdk, host.port, expect_pass=True)

        run_bundle("a parse that trusts every transport status",
                   mutated(rules, "the parsed status",
                           "self.statusCode = status;",
                           "self.statusCode = 200; (void)status;"),
                   cc, sdk, host.port, expect_pass=False)
        run_bundle("a parse that stores no tag",
                   mutated(rules, "the parsed tags",
                           "[_elements setObject:value forKey:key];",
                           "(void)value; (void)key;"),
                   cc, sdk, host.port, expect_pass=False)
        run_bundle("a populateHost that stores the uuid the wire sent",
                   mutated(rules, "the uuid trim",
                           "host.uuid = [[self getStringTag:TAG_UNIQUE_ID] trim];",
                           "host.uuid = [self getStringTag:TAG_UNIQUE_ID];"),
                   cc, sdk, host.port, expect_pass=False)
        run_bundle("a policy that reads the capability without trimming",
                   mutated(rules, "the policy trim",
                           'NSString *answered = [(NSString *)value stringByTrimmingCharactersInSet:\n            [NSCharacterSet whitespaceAndNewlineCharacterSet]];\n        return [answered isEqualToString:@"1"];',
                           'return [(NSString *)value isEqualToString:@"1"];'),
                   cc, sdk, host.port, expect_pass=False)
        check("if (status != NULL)" in rules,
              "the bus status guard: the source it mutates is still there")
        run_bundle("a bus read whose status never reaches the caller",
                   rules.replace("if (status != NULL)", "if (status == NULL)"),
                   cc, sdk, host.port, expect_pass=False)

    print("%d usb-host-loopback failures" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
