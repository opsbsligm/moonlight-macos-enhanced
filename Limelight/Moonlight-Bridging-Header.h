//
//  Use this file to import your target's public headers that you would like to expose to Swift.
//

#import "DataManager.h"
#import "TemporaryHost.h"
#import "ConnectionEndpointStore.h"
#import "ConnectionEditorViewController.h"
#import "HttpManager.h"
#import "HttpRequest.h"
#import "ServerInfoResponse.h"
#import "IdManager.h"
#import "LatencyProbe.h"
#import "StreamingSessionManager.h"
#import "AppsWorkspaceViewController.h"
#import "AppsViewController.h"
#import "AppDelegateForAppKit.h"
#import "AwdlAuthorizationHelper.h"
#import "Logger.h"
#import "DiagnosticsReportBuilder+Live.h"
// The one answer to "can this display interpolate at this frame rate, and if not what would
// work". Swift needs it for the pre-stream advice, and the renderer already calls it for the
// admission: two copies of that arithmetic is how a page ends up recommending a rate the
// stream then refuses.
#import "InterpolationCadencePolicy.h"
#import "DeviceRedirectionPanelModel.h"
