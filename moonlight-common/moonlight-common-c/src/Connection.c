#include "Limelight-internal.h"

#ifdef RemoteAddrString
#undef RemoteAddrString
#endif
#ifdef RemoteAddr
#undef RemoteAddr
#endif
#ifdef LocalAddr
#undef LocalAddr
#endif
#ifdef AddrLen
#undef AddrLen
#endif
#ifdef ConnectionAppVersionQuad
#undef ConnectionAppVersionQuad
#endif
#ifdef StreamConfig
#undef StreamConfig
#endif
#ifdef ListenerCallbacks
#undef ListenerCallbacks
#endif
#ifdef VideoCallbacks
#undef VideoCallbacks
#endif
#ifdef AudioCallbacks
#undef AudioCallbacks
#endif
#ifdef NegotiatedVideoFormat
#undef NegotiatedVideoFormat
#endif
#ifdef ConnectionInterrupted
#undef ConnectionInterrupted
#endif
#ifdef HighQualitySurroundSupported
#undef HighQualitySurroundSupported
#endif
#ifdef HighQualitySurroundEnabled
#undef HighQualitySurroundEnabled
#endif
#ifdef NormalQualityOpusConfig
#undef NormalQualityOpusConfig
#endif
#ifdef HighQualityOpusConfig
#undef HighQualityOpusConfig
#endif
#ifdef AudioPacketDuration
#undef AudioPacketDuration
#endif
#ifdef AudioEncryptionEnabled
#undef AudioEncryptionEnabled
#endif
#ifdef ReferenceFrameInvalidationSupported
#undef ReferenceFrameInvalidationSupported
#endif
#ifdef RtspPortNumber
#undef RtspPortNumber
#endif
#ifdef ControlPortNumber
#undef ControlPortNumber
#endif
#ifdef AudioPortNumber
#undef AudioPortNumber
#endif
#ifdef VideoPortNumber
#undef VideoPortNumber
#endif
#ifdef MicPortNumber
#undef MicPortNumber
#endif
#ifdef AudioPingPayload
#undef AudioPingPayload
#endif
#ifdef VideoPingPayload
#undef VideoPingPayload
#endif
#ifdef MicPingPayload
#undef MicPingPayload
#endif
#ifdef ControlConnectData
#undef ControlConnectData
#endif
#ifdef SunshineFeatureFlags
#undef SunshineFeatureFlags
#endif
#ifdef EncryptionFeaturesSupported
#undef EncryptionFeaturesSupported
#endif
#ifdef EncryptionFeaturesRequested
#undef EncryptionFeaturesRequested
#endif
#ifdef EncryptionFeaturesEnabled
#undef EncryptionFeaturesEnabled
#endif

// TLS for connection context
#if defined(_MSC_VER)
static __declspec(thread) PML_CONNECTION_CONTEXT tls_CurrentConnectionContext = NULL;
#else
static __thread PML_CONNECTION_CONTEXT tls_CurrentConnectionContext = NULL;
#endif

void LiSetThreadConnectionContext(PML_CONNECTION_CONTEXT ctx) {
    tls_CurrentConnectionContext = ctx;
}

PML_CONNECTION_CONTEXT LiGetThreadConnectionContext(void) {
    return tls_CurrentConnectionContext;
}

    PML_CONNECTION_CONTEXT LiGetGlobalConnectionContextPtr(void) {
        return &gConnectionContext;
    }

    PML_INPUT_STREAM_CONTEXT LiGetInputContextFromConnectionCtx(PML_CONNECTION_CONTEXT ctx) {
        return ctx != NULL ? &ctx->inputContext : NULL;
    }

// Macros to redirect global access to context
#define RemoteAddrString (ctx->RemoteAddrString)
#define RemoteAddr (ctx->RemoteAddr)
#define LocalAddr (ctx->LocalAddr)
#define AddrLen (ctx->AddrLen)
#define ConnectionAppVersionQuad (ctx->AppVersionQuad)
#define StreamConfig (ctx->StreamConfig)
#define ListenerCallbacks (ctx->ListenerCallbacks)
#define VideoCallbacks (ctx->VideoCallbacks)
#define AudioCallbacks (ctx->AudioCallbacks)
#define NegotiatedVideoFormat (ctx->NegotiatedVideoFormat)
#define ConnectionInterrupted (ctx->ConnectionInterrupted)
#define HighQualitySurroundSupported (ctx->HighQualitySurroundSupported)
#define HighQualitySurroundEnabled (ctx->HighQualitySurroundEnabled)
#define NormalQualityOpusConfig (ctx->NormalQualityOpusConfig)
#define HighQualityOpusConfig (ctx->HighQualityOpusConfig)
#define AudioPacketDuration (ctx->AudioPacketDuration)
#define AudioEncryptionEnabled (ctx->AudioEncryptionEnabled)
#define ReferenceFrameInvalidationSupported (ctx->ReferenceFrameInvalidationSupported)
#define RtspPortNumber (ctx->RtspPortNumber)
#define ControlPortNumber (ctx->ControlPortNumber)
#define AudioPortNumber (ctx->AudioPortNumber)
#define VideoPortNumber (ctx->VideoPortNumber)
#define MicPortNumber (ctx->MicPortNumber)
#define AudioPingPayload (ctx->AudioPingPayload)
#define VideoPingPayload (ctx->VideoPingPayload)
#define MicPingPayload (ctx->MicPingPayload)
#define ControlConnectData (ctx->ControlConnectData)
#define SunshineFeatureFlags (ctx->SunshineFeatureFlags)
#define EncryptionFeaturesSupported (ctx->EncryptionFeaturesSupported)
#define EncryptionFeaturesRequested (ctx->EncryptionFeaturesRequested)
#define EncryptionFeaturesEnabled (ctx->EncryptionFeaturesEnabled)

#define connectionStage (ctx->stage)
#define originalTerminationCallback (ctx->originalTerminationCallback)
#define alreadyTerminated (ctx->alreadyTerminated)
#define terminationCallbackThread (ctx->terminationCallbackThread)
#define terminationCallbackErrorCode (ctx->terminationCallbackErrorCode)

// Global instance for legacy API
ML_CONNECTION_CONTEXT gConnectionContext;
int AppVersionQuad[4];

// Connection stages
static const char* stageNames[STAGE_MAX] = {
    "none",
    "platform initialization",
    "name resolution",
    "audio stream initialization",
    "RTSP handshake",
    "control stream initialization",
    "video stream initialization",
    "input stream initialization",
    "control stream establishment",
    "video stream establishment",
    "audio stream establishment",
    "input stream establishment",
    "microphone stream initialization"
};

// Get the name of the current stage based on its number
const char* LiGetStageName(int stage) {
    return stageNames[stage];
}

// Interrupt a pending connection attempt (Context version)
void LiInterruptConnectionCtx(PML_CONNECTION_CONTEXT ctx) {
    // Signal anyone waiting on the global interrupted flag
    ConnectionInterrupted = true;
}

void LiInterruptConnection(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    LiInterruptConnectionCtx(ctx);
}

// Stop the connection by undoing the step at the current stage and those before it (Context version)
void LiStopConnectionCtx(PML_CONNECTION_CONTEXT ctx) {
    // Disable termination callbacks now
    alreadyTerminated = true;

    // Set the interrupted flag
    LiInterruptConnectionCtx(ctx);

    if (connectionStage == STAGE_INPUT_STREAM_START) {
        Limelog("Stopping input stream...");
        stopInputStreamCtx(&ctx->inputContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_AUDIO_STREAM_START) {
        Limelog("Stopping audio stream...");
        stopAudioStreamCtx(&ctx->audioContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_VIDEO_STREAM_START) {
        Limelog("Stopping video stream...");
        stopVideoStreamCtx(&ctx->videoContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_CONTROL_STREAM_START) {
        Limelog("Stopping control stream...");
        stopControlStreamCtx(&ctx->controlContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_INPUT_STREAM_INIT) {
        Limelog("Cleaning up input stream...");
        destroyInputStreamCtx(&ctx->inputContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_VIDEO_STREAM_INIT) {
        Limelog("Cleaning up video stream...");
        destroyVideoStreamCtx(&ctx->videoContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_CONTROL_STREAM_INIT) {
        Limelog("Cleaning up control stream...");
        destroyControlStreamCtx(&ctx->controlContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_RTSP_HANDSHAKE) {
        Limelog("Cleaning up RTSP handshake...");
        // No explicit RTSP handshake cleanup needed here
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_AUDIO_STREAM_INIT) {
        Limelog("Cleaning up audio stream...");
        destroyAudioStreamCtx(&ctx->audioContext);
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_NAME_RESOLUTION) {
        Limelog("Cleaning up host name resolution...");
        if (RemoteAddrString != NULL) {
            free(RemoteAddrString);
            RemoteAddrString = NULL;
        }
        connectionStage--;
        Limelog("done\n");
    }
    if (connectionStage == STAGE_PLATFORM_INIT) {
        Limelog("Cleaning up platform...");
        cleanupPlatform();
        connectionStage--;
        Limelog("done\n");
    }
    LC_ASSERT(connectionStage == STAGE_NONE);
}

void LiStopConnection(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    LiStopConnectionCtx(ctx);
}

static void terminationCallbackThreadFunc(void* context)
{
    PML_CONNECTION_CONTEXT ctx = (PML_CONNECTION_CONTEXT)context;
    LiSetThreadConnectionContext(ctx);
    originalTerminationCallback(terminationCallbackErrorCode);
}

// This shim callback runs the client's connectionTerminated() callback on a
// separate thread.
static void ClInternalConnectionTerminated(int errorCode)
{
    int err;
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();

    // Avoid recursion and issuing multiple callbacks
    if (alreadyTerminated || ConnectionInterrupted) {
        return;
    }

    terminationCallbackErrorCode = errorCode;
    alreadyTerminated = true;

    // Invoke the termination callback on a separate thread
    err = PltCreateThread("AsyncTerm", terminationCallbackThreadFunc, ctx, &terminationCallbackThread);
    if (err != 0) {
        // Nothing we can safely do here, so we'll just assert on debug builds
        Limelog("Failed to create termination thread: %d\n", err);
        LC_ASSERT(err == 0);
    }

    // Detach the thread since we never wait on it
    PltDetachThread(&terminationCallbackThread);
}

static bool parseRtspPortNumberFromUrl(const char* rtspSessionUrl, uint16_t* port)
{
    // If the session URL is not present, we will just use the well known port
    if (rtspSessionUrl == NULL) {
        return false;
    }

    // Pick the last colon in the string to match the port number
    char* portNumberStart = strrchr(rtspSessionUrl, ':');
    if (portNumberStart == NULL) {
        return false;
    }

    // Skip the colon
    portNumberStart++;

    // Validate the port number
    long int rawPort = strtol(portNumberStart, NULL, 10);
    if (rawPort <= 0 || rawPort > 65535) {
        return false;
    }

    *port = (uint16_t)rawPort;
    return true;
}

// Starts the connection to the streaming machine (Context version)
int LiStartConnectionCtx(PML_CONNECTION_CONTEXT ctx, PSERVER_INFORMATION serverInfo, PSTREAM_CONFIGURATION streamConfig, PCONNECTION_LISTENER_CALLBACKS clCallbacks,
    PDECODER_RENDERER_CALLBACKS drCallbacks, PAUDIO_RENDERER_CALLBACKS arCallbacks, void* renderContext, int drFlags,
    void* audioContext, int arFlags) {
    int err;

    // Set TLS for the current thread (usually main/GUI thread)
    LiSetThreadConnectionContext(ctx);

    connectionStage = STAGE_NONE;

    if (drCallbacks != NULL && (drCallbacks->capabilities & CAPABILITY_PULL_RENDERER) && drCallbacks->submitDecodeUnit) {
        Limelog("CAPABILITY_PULL_RENDERER cannot be set with a submitDecodeUnit callback\n");
        LC_ASSERT(false);
        err = -1;
        goto Cleanup;
    }

    if (drCallbacks != NULL && (drCallbacks->capabilities & CAPABILITY_PULL_RENDERER) && (drCallbacks->capabilities & CAPABILITY_DIRECT_SUBMIT)) {
        Limelog("CAPABILITY_PULL_RENDERER and CAPABILITY_DIRECT_SUBMIT cannot be set together\n");
        LC_ASSERT(false);
        err = -1;
        goto Cleanup;
    }

    if (serverInfo->serverCodecModeSupport == 0) {
        Limelog("serverCodecModeSupport field in SERVER_INFORMATION must be set!\n");
        LC_ASSERT(false);
        err = -1;
        goto Cleanup;
    }

    // Extract the appversion from the supplied string
    if (extractVersionQuadFromString(serverInfo->serverInfoAppVersion,
                                     ConnectionAppVersionQuad) < 0) {
        Limelog("Invalid appversion string: %s\n", serverInfo->serverInfoAppVersion);
        err = -1;
        goto Cleanup;
    }
    memcpy(AppVersionQuad, ConnectionAppVersionQuad, sizeof(AppVersionQuad));

    // Replace missing callbacks with placeholders
    fixupMissingCallbacks(&drCallbacks, &arCallbacks, &clCallbacks);
    memcpy(&VideoCallbacks, drCallbacks, sizeof(VideoCallbacks));
    memcpy(&AudioCallbacks, arCallbacks, sizeof(AudioCallbacks));

#ifdef LC_DEBUG_RECORD_MODE
    // Install the pass-through recorder callbacks
    setRecorderCallbacks(&VideoCallbacks, &AudioCallbacks);
#endif

    // Hook the termination callback so we can avoid issuing a termination callback
    // after LiStopConnection() is called.
    //
    // Initialize ListenerCallbacks before anything that could call Limelog().
    originalTerminationCallback = clCallbacks->connectionTerminated;
    memcpy(&ListenerCallbacks, clCallbacks, sizeof(ListenerCallbacks));
    ListenerCallbacks.connectionTerminated = ClInternalConnectionTerminated;

    memset(&LocalAddr, 0, sizeof(LocalAddr));
    NegotiatedVideoFormat = 0;
    memcpy(&StreamConfig, streamConfig, sizeof(StreamConfig));
    RemoteAddrString = strdup(serverInfo->address);

    // The values in RTSP SETUP will be used to populate these.
    VideoPortNumber = 0;
    ControlPortNumber = 0;
    AudioPortNumber = 0;

    // Parse RTSP port number from RTSP session URL
    if (!parseRtspPortNumberFromUrl(serverInfo->rtspSessionUrl, &RtspPortNumber)) {
        // Use the well known port if parsing fails
        RtspPortNumber = 48010;

        Limelog("RTSP port: %u (RTSP URL parsing failed)\n", RtspPortNumber);
    }
    else {
        Limelog("RTSP port: %u\n", RtspPortNumber);
    }

    alreadyTerminated = false;
    ConnectionInterrupted = false;

    // Validate the audio configuration
    if (MAGIC_BYTE_FROM_AUDIO_CONFIG(StreamConfig.audioConfiguration) != 0xCA ||
            CHANNEL_COUNT_FROM_AUDIO_CONFIGURATION(StreamConfig.audioConfiguration) > AUDIO_CONFIGURATION_MAX_CHANNEL_COUNT) {
        Limelog("Invalid audio configuration specified\n");
        err = -1;
        goto Cleanup;
    }

    // FEC only works in 16 byte chunks, so we must round down
    // the given packet size to the nearest multiple of 16.
    StreamConfig.packetSize -= StreamConfig.packetSize % 16;

    if (StreamConfig.packetSize == 0) {
        Limelog("Invalid packet size specified\n");
        err = -1;
        goto Cleanup;
    }

    // Height must not be odd or NVENC will fail to initialize
    if (StreamConfig.height & 0x1) {
        Limelog("Encoder height must not be odd. Rounding %d to %d\n",
                StreamConfig.height,
                StreamConfig.height & ~0x1);
        StreamConfig.height = StreamConfig.height & ~0x1;
    }

    // Dimensions over 4096 are only supported with HEVC on NVENC
    if (!(StreamConfig.supportedVideoFormats & ~VIDEO_FORMAT_MASK_H264) &&
            (StreamConfig.width > 4096 || StreamConfig.height > 4096)) {
        Limelog("WARNING: Streaming at resolutions above 4K using H.264 will likely fail! Trying anyway!\n");
    }
    // Dimensions over 8192 aren't supported at all (even on Turing)
    else if (StreamConfig.width > 8192 || StreamConfig.height > 8192) {
        Limelog("WARNING: Streaming at resolutions above 8K will likely fail! Trying anyway!\n");
    }

    // Reference frame invalidation doesn't seem to work with resolutions much
    // higher than 1440p. I haven't figured out a pattern to indicate which
    // resolutions will work and which won't, but we can at least exclude
    // 4K from RFI to avoid significant persistent artifacts after frame loss.
    if (StreamConfig.width == 3840 && StreamConfig.height == 2160 &&
            (VideoCallbacks.capabilities & CAPABILITY_REFERENCE_FRAME_INVALIDATION_AVC) &&
            !IS_SUNSHINE_CTX(ctx)) {
        Limelog("Disabling reference frame invalidation for 4K streaming with GFE\n");
        VideoCallbacks.capabilities &= ~CAPABILITY_REFERENCE_FRAME_INVALIDATION_AVC;
    }

    Limelog("Initializing platform...");
    ListenerCallbacks.stageStarting(STAGE_PLATFORM_INIT);
    err = initializePlatform();
    if (err != 0) {
        Limelog("failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_PLATFORM_INIT, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_PLATFORM_INIT);
    ListenerCallbacks.stageComplete(STAGE_PLATFORM_INIT);
    Limelog("done\n");

    Limelog("Resolving host name...");
    ListenerCallbacks.stageStarting(STAGE_NAME_RESOLUTION);
    LC_ASSERT(RtspPortNumber != 0);
    if (RtspPortNumber != 48010) {
        // If we have an alternate RTSP port, use that as our test port. The host probably
        // isn't listening on 47989 or 47984 anyway, since they're using alternate ports.
        err = resolveHostName(serverInfo->address, AF_UNSPEC, RtspPortNumber, &RemoteAddr, &AddrLen);
        if (err != 0) {
            // Sleep for a second and try again. It's possible that we've attempt to connect
            // before the host has gotten around to listening on the RTSP port. Give it some
            // time before retrying.
            PltSleepMs(1000);
            err = resolveHostName(serverInfo->address, AF_UNSPEC, RtspPortNumber, &RemoteAddr, &AddrLen);
        }
    }
    else {
        // We use TCP 47984 and 47989 first here because we know those should always be listening
        // on hosts using the standard ports.
        //
        // TCP 48010 is a last resort because:
        // a) it's not always listening and there's a race between listen() on the host and our connect()
        // b) it's not used at all by certain host versions which perform RTSP over ENet
        err = resolveHostName(serverInfo->address, AF_UNSPEC, 47984, &RemoteAddr, &AddrLen);
        if (err != 0) {
            err = resolveHostName(serverInfo->address, AF_UNSPEC, 47989, &RemoteAddr, &AddrLen);
        }
        if (err != 0) {
            err = resolveHostName(serverInfo->address, AF_UNSPEC, 48010, &RemoteAddr, &AddrLen);
        }
    }
    if (err != 0) {
        Limelog("failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_NAME_RESOLUTION, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_NAME_RESOLUTION);
    ListenerCallbacks.stageComplete(STAGE_NAME_RESOLUTION);
    Limelog("done\n");

    // If STREAM_CFG_AUTO was requested, determine the streamingRemotely value
    // now that we have resolved the target address and impose the video packet
    // size cap if required.
    if (StreamConfig.streamingRemotely == STREAM_CFG_AUTO) {
        bool isNat64 = isNat64SynthesizedAddress(&RemoteAddr);

        // It's possible to have a NAT64 prefix on a ULA or other private range,
        // so we must exclude NAT64 addresses from our local address checks.
        if (!isNat64 && isPrivateNetworkAddress(&RemoteAddr)) {
            StreamConfig.streamingRemotely = STREAM_CFG_LOCAL;
        }
        else {
            StreamConfig.streamingRemotely = STREAM_CFG_REMOTE;

            if (RemoteAddr.ss_family == AF_INET || isNat64) {
                // Cap packet size at 1024 for remote IPv4 streaming to avoid fragmentation.
                Limelog("Packet size capped at 1024 bytes for remote IPv4 streaming\n");
                StreamConfig.packetSize = 1024;
            }
            else {
                // IPv6 guarantees a minimum MTU of 1280 before fragmentation, so use a higher
                // packet size cap for remote IPv6 streaming (when not using NAT64 which isn't
                // end-to-end IPv6 traffic).
                Limelog("Packet size capped at 1184 bytes for remote IPv6 streaming\n");
                StreamConfig.packetSize = 1184;
            }
        }
    }

    Limelog("Initializing audio stream...");
    ListenerCallbacks.stageStarting(STAGE_AUDIO_STREAM_INIT);
    err = initializeAudioStreamCtx(&ctx->audioContext, ctx);
    if (err != 0) {
        Limelog("failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_AUDIO_STREAM_INIT, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_AUDIO_STREAM_INIT);
    ListenerCallbacks.stageComplete(STAGE_AUDIO_STREAM_INIT);
    Limelog("done\n");

    Limelog("Starting RTSP handshake...");
    ListenerCallbacks.stageStarting(STAGE_RTSP_HANDSHAKE);
    err = performRtspHandshakeCtx(ctx, serverInfo);
    if (err != 0) {
        Limelog("failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_RTSP_HANDSHAKE, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_RTSP_HANDSHAKE);
    ListenerCallbacks.stageComplete(STAGE_RTSP_HANDSHAKE);
    Limelog("done\n");

    Limelog("Initializing control stream...");
    ListenerCallbacks.stageStarting(STAGE_CONTROL_STREAM_INIT);
    err = initializeControlStreamCtx(&ctx->controlContext, ctx);
    if (err != 0) {
        Limelog("failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_CONTROL_STREAM_INIT, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_CONTROL_STREAM_INIT);
    ListenerCallbacks.stageComplete(STAGE_CONTROL_STREAM_INIT);
    Limelog("done\n");

    Limelog("Initializing video stream...");
    ListenerCallbacks.stageStarting(STAGE_VIDEO_STREAM_INIT);
    initializeVideoStreamCtx(&ctx->videoContext, ctx);
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_VIDEO_STREAM_INIT);
    ListenerCallbacks.stageComplete(STAGE_VIDEO_STREAM_INIT);
    Limelog("done\n");

    Limelog("Initializing input stream...");
    ListenerCallbacks.stageStarting(STAGE_INPUT_STREAM_INIT);
    initializeInputStreamCtx(&ctx->inputContext, ctx);
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_INPUT_STREAM_INIT);
    ListenerCallbacks.stageComplete(STAGE_INPUT_STREAM_INIT);
    Limelog("done\n");

    Limelog("Starting control stream...");
    ListenerCallbacks.stageStarting(STAGE_CONTROL_STREAM_START);
    err = startControlStreamCtx(&ctx->controlContext);
    if (err != 0) {
        Limelog("failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_CONTROL_STREAM_START, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_CONTROL_STREAM_START);
    ListenerCallbacks.stageComplete(STAGE_CONTROL_STREAM_START);
    Limelog("done\n");

    Limelog("Starting video stream...");
    ListenerCallbacks.stageStarting(STAGE_VIDEO_STREAM_START);
    err = startVideoStreamCtx(&ctx->videoContext, renderContext, drFlags);
    if (err != 0) {
        Limelog("Video stream start failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_VIDEO_STREAM_START, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_VIDEO_STREAM_START);
    ListenerCallbacks.stageComplete(STAGE_VIDEO_STREAM_START);
    Limelog("done\n");

    Limelog("Starting audio stream...");
    ListenerCallbacks.stageStarting(STAGE_AUDIO_STREAM_START);
    err = startAudioStreamCtx(&ctx->audioContext, audioContext, arFlags);
    if (err != 0) {
        Limelog("Audio stream start failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_AUDIO_STREAM_START, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_AUDIO_STREAM_START);
    ListenerCallbacks.stageComplete(STAGE_AUDIO_STREAM_START);
    Limelog("done\n");

    Limelog("Starting input stream...");
    ListenerCallbacks.stageStarting(STAGE_INPUT_STREAM_START);
    err = startInputStreamCtx(&ctx->inputContext);
    if (err != 0) {
        Limelog("Input stream start failed: %d\n", err);
        ListenerCallbacks.stageFailed(STAGE_INPUT_STREAM_START, err);
        goto Cleanup;
    }
    connectionStage++;
    LC_ASSERT(connectionStage == STAGE_INPUT_STREAM_START);
    ListenerCallbacks.stageComplete(STAGE_INPUT_STREAM_START);
    Limelog("done\n");

    // Avoid sending best-effort startup mouse movement before the client has
    // been notified that the stream is ready. This legacy wake-display nudge
    // is non-essential and can stall connection startup on some hosts.
    Limelog("Signaling connection started\n");
    ListenerCallbacks.connectionStarted();

Cleanup:
    if (err != 0) {
        // Undo any work we've done here before failing
        LiStopConnectionCtx(ctx);
    }
    return err;
}

int LiStartConnection(PSERVER_INFORMATION serverInfo, PSTREAM_CONFIGURATION streamConfig, PCONNECTION_LISTENER_CALLBACKS clCallbacks,
    PDECODER_RENDERER_CALLBACKS drCallbacks, PAUDIO_RENDERER_CALLBACKS arCallbacks, void* renderContext, int drFlags,
    void* audioContext, int arFlags) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return LiStartConnectionCtx(ctx, serverInfo, streamConfig, clCallbacks, drCallbacks, arCallbacks, renderContext, drFlags, audioContext, arFlags);
}

const char* LiGetLaunchUrlQueryParameters(void) {
    // v0 = Video encryption and control stream encryption v2
    // v1 = RTSP encryption
    return "&corever=1";
}
