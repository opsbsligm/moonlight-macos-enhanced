#pragma once

#include "Platform.h"
#include "Limelight.h"
#include "PlatformSockets.h"
#include "PlatformThreads.h"
#include "PlatformCrypto.h"
#include "Video.h"
#include "Input.h"
#include "RtpAudioQueue.h"
#include "ByteBuffer.h"
#include <stdatomic.h>

// Forward declarations for context types
typedef struct _ML_CONNECTION_CONTEXT ML_CONNECTION_CONTEXT, *PML_CONNECTION_CONTEXT;
typedef struct _ML_CONTROL_STREAM_CONTEXT ML_CONTROL_STREAM_CONTEXT, *PML_CONTROL_STREAM_CONTEXT;
typedef struct _ML_DEPACKETIZER_CONTEXT ML_DEPACKETIZER_CONTEXT, *PML_DEPACKETIZER_CONTEXT;

#include "RtpVideoQueue.h"

#include "../enet/include/enet/enet.h"

// Common globals
extern int AppVersionQuad[4];

// Encryption flags shared by Sunshine and Moonlight in RTSP
#define SS_ENC_CONTROL_V2 0x01
#define SS_ENC_VIDEO 0x02
#define SS_ENC_AUDIO 0x04
#define SS_ENC_MICROPHONE 0x08

// Microphone RTP stream values
#define MIC_PACKET_MAGIC 0x12345678
#define MIC_PACKET_TYPE_OPUS 0x61
#define MAX_MIC_PACKET_SIZE 1400


// ENet channel ID values
#define CTRL_CHANNEL_GENERIC      0x00
#define CTRL_CHANNEL_URGENT       0x01 // IDR and reference frame invalidation requests
#define CTRL_CHANNEL_KEYBOARD     0x02
#define CTRL_CHANNEL_MOUSE        0x03
#define CTRL_CHANNEL_PEN          0x04
#define CTRL_CHANNEL_TOUCH        0x05
#define CTRL_CHANNEL_UTF8         0x06
#define CTRL_CHANNEL_GAMEPAD_BASE 0x10 // 0x10 to 0x1F by controller index
#define CTRL_CHANNEL_SENSOR_BASE  0x20 // 0x20 to 0x2F by controller index
#define CTRL_CHANNEL_COUNT        0x30

#ifndef UINT24_MAX
#define UINT24_MAX 0xFFFFFF
#endif

#define U16(x) ((unsigned short) ((x) & UINT16_MAX))
#define U24(x) ((unsigned int) ((x) & UINT24_MAX))
#define U32(x) ((unsigned int) ((x) & UINT32_MAX))

#define isBefore16(x, y) (U16((x) - (y)) > (UINT16_MAX/2))
#define isBefore24(x, y) (U24((x) - (y)) > (UINT24_MAX/2))
#define isBefore32(x, y) (U32((x) - (y)) > (UINT32_MAX/2))

#define APP_VERSION_AT_LEAST(a, b, c)                                                       \
    ((AppVersionQuad[0] > (a)) ||                                                           \
     (AppVersionQuad[0] == (a) && AppVersionQuad[1] > (b)) ||                               \
     (AppVersionQuad[0] == (a) && AppVersionQuad[1] == (b) && AppVersionQuad[2] >= (c)))

#define APP_VERSION_AT_LEAST_CTX(ctx, a, b, c)                                              \
    ((ctx->AppVersionQuad[0] > (a)) ||                                                      \
     (ctx->AppVersionQuad[0] == (a) && ctx->AppVersionQuad[1] > (b)) ||                     \
     (ctx->AppVersionQuad[0] == (a) && ctx->AppVersionQuad[1] == (b) && ctx->AppVersionQuad[2] >= (c)))

#define IS_SUNSHINE() (AppVersionQuad[3] < 0)
#define IS_SUNSHINE_CTX(ctx) (ctx->AppVersionQuad[3] < 0)

// Client feature flags for x-ml-general.featureFlags SDP attribute
#define ML_FF_FEC_STATUS 0x01 // Client sends SS_FRAME_FEC_STATUS for frame losses
#define ML_FF_SESSION_ID_V1 0x02 // Client supports X-SS-Ping-Payload and X-SS-Connect-Data
#define ML_FF_CLIPBOARD_TEXT 0x04 // Client supports clipboard text sync
#define ML_FF_CLIPBOARD_IMAGE 0x08 // Client supports clipboard image sync

// Clipboard control stream packet type and payload kinds used by the Sunshine
// clipboard sync extension.
#define SS_CLIPBOARD_PTYPE 0x5508

#define LI_CLIPBOARD_MSG_BIND 0x01
#define LI_CLIPBOARD_MSG_UNBIND 0x02
#define LI_CLIPBOARD_MSG_SNAPSHOT_REQUEST 0x03
#define LI_CLIPBOARD_MSG_ITEM_START 0x04
#define LI_CLIPBOARD_MSG_ITEM_CHUNK 0x05
#define LI_CLIPBOARD_MSG_ITEM_END 0x06
#define LI_CLIPBOARD_MSG_ITEM_CANCEL 0x07

#define LI_CLIPBOARD_TRANSFER_FLAG_SNAPSHOT 0x01
#define LI_CLIPBOARD_MAX_CHUNK_SIZE 16384
#define LI_CLIPBOARD_MAX_IMAGE_SIZE (4U * 1024U * 1024U)

#define UDP_RECV_POLL_TIMEOUT_MS 100

// At this value or above, we will request high quality audio unless CAPABILITY_SLOW_OPUS_DECODER
// is set on the audio renderer.
#define HIGH_AUDIO_BITRATE_THRESHOLD 15000

// Below this value, we will request 20 ms audio frames to reduce bandwidth if the audio
// renderer sets CAPABILITY_SUPPORTS_ARBITRARY_AUDIO_DURATION.
#define LOW_AUDIO_BITRATE_TRESHOLD 5000

// Internal macro for checking the magic byte of the audio configuration value
#define MAGIC_BYTE_FROM_AUDIO_CONFIG(x) ((x) & 0xFF)

int serviceEnetHost(ENetHost* client, ENetEvent* event, enet_uint32 timeoutMs);
int gracefullyDisconnectEnetPeer(ENetHost* host, ENetPeer* peer, enet_uint32 lingerTimeoutMs);
int extractVersionQuadFromString(const char* string, int* quad);
bool isReferenceFrameInvalidationSupportedByDecoder(void);
bool isReferenceFrameInvalidationEnabled(void);
void* extendBuffer(void* ptr, size_t newSize);

void fixupMissingCallbacks(PDECODER_RENDERER_CALLBACKS* drCallbacks, PAUDIO_RENDERER_CALLBACKS* arCallbacks,
    PCONNECTION_LISTENER_CALLBACKS* clCallbacks);
void setRecorderCallbacks(PDECODER_RENDERER_CALLBACKS drCallbacks, PAUDIO_RENDERER_CALLBACKS arCallbacks);

char* getSdpPayloadForStreamConfig(int rtspClientVersion, int* length);

// Forward declarations
typedef struct _ML_CONTROL_STREAM_CONTEXT ML_CONTROL_STREAM_CONTEXT, *PML_CONTROL_STREAM_CONTEXT;

int initializeControlStream(void);
int startControlStream(void);
int stopControlStream(void);
void destroyControlStream(void);
void connectionDetectedFrameLoss(uint32_t startFrame, uint32_t endFrame);
void connectionReceivedCompleteFrame(uint32_t frameIndex);
void connectionSawFrame(uint32_t frameIndex);
void connectionSendFrameFecStatus(PSS_FRAME_FEC_STATUS fecStatus);
int sendInputPacketOnControlStream(unsigned char* data, int length, uint8_t channelId, uint32_t flags, bool moreData);
int sendInputPacketOnControlStreamCtx(PML_CONTROL_STREAM_CONTEXT ctx, unsigned char* data, int length, uint8_t channelId, uint32_t flags, bool moreData);
void flushInputOnControlStream(void);
void flushInputOnControlStreamCtx(PML_CONTROL_STREAM_CONTEXT ctx);
bool isControlDataInTransit(void);
bool isControlDataInTransitCtx(PML_CONTROL_STREAM_CONTEXT ctx);
bool LiGetEstimatedRttInfo(uint32_t* estimatedRtt, uint32_t* estimatedRttVariance);
bool LiGetEstimatedRttInfoCtx(PML_CONTROL_STREAM_CONTEXT ctx, uint32_t* estimatedRtt, uint32_t* estimatedRttVariance);

int performRtspHandshake(PSERVER_INFORMATION serverInfo);

void initializeVideoDepacketizer(int pktSize);
void destroyVideoDepacketizer(void);
void queueRtpPacket(PRTPV_QUEUE_ENTRY queueEntry);
void stopVideoDepacketizer(void);
void requestDecoderRefresh(void);
void notifyFrameLost(unsigned int frameNumber, bool speculative);

void initializeVideoStream(void);
void destroyVideoStream(void);
void notifyKeyFrameReceived(void);
int startVideoStream(void* rendererContext, int drFlags);
void stopVideoStream(void);

// Forward declarations
// typedef struct _ML_CONNECTION_CONTEXT ML_CONNECTION_CONTEXT, *PML_CONNECTION_CONTEXT; (Moved to top)
// typedef struct _ML_CONTROL_STREAM_CONTEXT ML_CONTROL_STREAM_CONTEXT, *PML_CONTROL_STREAM_CONTEXT; (Moved to top)

// Depacketizer context
typedef struct _ML_DEPACKETIZER_CONTEXT {
    PLENTRY nalChainHead;
    PLENTRY nalChainTail;
    int nalChainDataLength;

    unsigned int nextFrameNumber;
    unsigned int startFrameNumber;
    bool waitingForNextSuccessfulFrame;
    bool waitingForIdrFrame;
    bool waitingForRefInvalFrame;
    unsigned int lastPacketInStream;
    bool decodingFrame;
    int frameType;
    uint16_t lastPacketPayloadLength;
    bool strictIdrFrameWait;
    uint64_t syntheticPtsBase;
    uint16_t frameHostProcessingLatency;
    uint64_t firstPacketReceiveTime;
    unsigned int firstPacketPresentationTime;
    bool dropStatePending;
    bool idrFrameProcessed;

    unsigned int consecutiveFrameDrops;

    LINKED_BLOCKING_QUEUE decodeUnitQueue;

    PML_CONNECTION_CONTEXT connectionContext;
} ML_DEPACKETIZER_CONTEXT, *PML_DEPACKETIZER_CONTEXT;

void initializeVideoDepacketizerCtx(PML_DEPACKETIZER_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext, int pktSize);
void destroyVideoDepacketizerCtx(PML_DEPACKETIZER_CONTEXT ctx);
void queueRtpPacketCtx(PML_DEPACKETIZER_CONTEXT ctx, PRTPV_QUEUE_ENTRY queueEntry);
void stopVideoDepacketizerCtx(PML_DEPACKETIZER_CONTEXT ctx);
void requestDecoderRefreshCtx(PML_DEPACKETIZER_CONTEXT ctx);
void notifyFrameLostCtx(PML_DEPACKETIZER_CONTEXT ctx, unsigned int frameNumber, bool speculative);
int LiGetPendingVideoFramesCtx(PML_DEPACKETIZER_CONTEXT ctx);

bool LiWaitForNextVideoFrameCtx(PML_DEPACKETIZER_CONTEXT ctx, VIDEO_FRAME_HANDLE* frameHandle, PDECODE_UNIT* decodeUnit);
bool LiPollNextVideoFrameCtx(PML_DEPACKETIZER_CONTEXT ctx, VIDEO_FRAME_HANDLE* frameHandle, PDECODE_UNIT* decodeUnit);
bool LiPeekNextVideoFrameCtx(PML_DEPACKETIZER_CONTEXT ctx, PDECODE_UNIT* decodeUnit);
void LiWakeWaitForVideoFrameCtx(PML_DEPACKETIZER_CONTEXT ctx);
void LiCompleteVideoFrameCtx(PML_DEPACKETIZER_CONTEXT ctx, VIDEO_FRAME_HANDLE handle, int drStatus);

// Video stream context (multi-stream scaffolding)
typedef struct _ML_VIDEO_STREAM_CONTEXT {
    PML_CONNECTION_CONTEXT connectionContext;
    RTP_VIDEO_QUEUE rtpQueue;
    ML_DEPACKETIZER_CONTEXT depacketizerContext;
    SOCKET rtpSocket;
    SOCKET firstFrameSocket;
    PPLT_CRYPTO_CONTEXT decryptionCtx;
    PLT_THREAD udpPingThread;
    PLT_THREAD receiveThread;
    PLT_THREAD decoderThread;
    bool receivedDataFromPeer;
    uint64_t firstDataTimeMs;
    bool receivedFullFrame;
} ML_VIDEO_STREAM_CONTEXT, *PML_VIDEO_STREAM_CONTEXT;

void initializeVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext);
void destroyVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx);
void notifyKeyFrameReceivedCtx(PML_VIDEO_STREAM_CONTEXT ctx);
int startVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx, void* rendererContext, int drFlags);
void stopVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx);

// Audio stream context (multi-stream scaffolding)
typedef struct _ML_AUDIO_STREAM_CONTEXT {
        PML_CONNECTION_CONTEXT connectionContext;
        SOCKET rtpSocket;
        LINKED_BLOCKING_QUEUE packetQueue;
        RTP_AUDIO_QUEUE rtpAudioQueue;
        PLT_THREAD udpPingThread;
        PLT_THREAD receiveThread;
        PLT_THREAD decoderThread;
        PPLT_CRYPTO_CONTEXT audioDecryptionCtx;
        uint32_t avRiKeyId;
        unsigned short lastSeq;
        bool pingThreadStarted;
        bool receivedDataFromPeer;
        uint64_t firstReceiveTime;
#ifdef LC_DEBUG
        uint8_t opusHeaderByte;
#endif
} ML_AUDIO_STREAM_CONTEXT, *PML_AUDIO_STREAM_CONTEXT;

int initializeAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext);
int notifyAudioPortNegotiationCompleteCtx(PML_AUDIO_STREAM_CONTEXT ctx);
void destroyAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx);
int startAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx, void* audioContext, int arFlags);
void stopAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx);
int LiGetPendingAudioFramesCtx(PML_AUDIO_STREAM_CONTEXT ctx);
int LiGetPendingAudioDurationCtx(PML_AUDIO_STREAM_CONTEXT ctx);

// Control stream context (multi-stream scaffolding)
typedef struct _ML_CONTROL_STREAM_CONTEXT {
        PML_CONNECTION_CONTEXT connectionContext;
        SOCKET ctlSock;
        ENetHost* client;
        ENetPeer* peer;
        PLT_MUTEX enetMutex;
        bool usePeriodicPing;

        PLT_THREAD lossStatsThread;
        PLT_THREAD invalidateRefFramesThread;
        PLT_THREAD requestIdrFrameThread;
        PLT_THREAD controlReceiveThread;
        PLT_THREAD asyncCallbackThread;
        uint32_t lastGoodFrame;
        uint32_t lastSeenFrame;
        bool stopping;
        bool disconnectPending;
        bool encryptedControlStream;
        bool hdrEnabled;
        SS_HDR_METADATA hdrMetadata;

        int intervalGoodFrameCount;
        int intervalTotalFrameCount;
        uint64_t intervalStartTimeMs;
        int lastIntervalLossPercentage;
        int lastConnectionStatusUpdate;
        uint32_t currentEnetSequenceNumber;
        uint64_t firstFrameTimeMs;

        LINKED_BLOCKING_QUEUE invalidReferenceFrameTuples;
        LINKED_BLOCKING_QUEUE frameFecStatusQueue;
        LINKED_BLOCKING_QUEUE asyncCallbackQueue;
        PLT_EVENT idrFrameRequiredEvent;

        PPLT_CRYPTO_CONTEXT encryptionCtx;
        PPLT_CRYPTO_CONTEXT decryptionCtx;

        struct {
            bool active;
            uint8_t itemType;
            uint8_t transferFlags;
            uint64_t itemId;
            uint64_t contentHash;
            uint32_t totalLength;
            uint32_t receivedLength;
            char* mimeType;
            char* name;
            uint8_t* data;
        } incomingClipboardTransfer;

        // Protocol version tables
        short* packetTypes;
        short* payloadLengths;
        char** preconstructedPayloads;
        bool supportsIdrFrameRequest;
} ML_CONTROL_STREAM_CONTEXT, *PML_CONTROL_STREAM_CONTEXT;

int initializeControlStreamCtx(PML_CONTROL_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext);
int startControlStreamCtx(PML_CONTROL_STREAM_CONTEXT ctx);
int stopControlStreamCtx(PML_CONTROL_STREAM_CONTEXT ctx);
void destroyControlStreamCtx(PML_CONTROL_STREAM_CONTEXT ctx);
int LiBindClipboardSessionCtx(PML_CONTROL_STREAM_CONTEXT ctx);
int LiUnbindClipboardSessionCtx(PML_CONTROL_STREAM_CONTEXT ctx);
int LiRequestClipboardSnapshotCtx(PML_CONTROL_STREAM_CONTEXT ctx);
int LiSendClipboardItemCtx(PML_CONTROL_STREAM_CONTEXT ctx,
                           const LI_CLIPBOARD_ITEM* item);

// Microphone stream context (multi-stream scaffolding)
typedef struct _ML_MICROPHONE_STREAM_CONTEXT {
    PML_CONNECTION_CONTEXT connectionContext;
    SOCKET micSocket;
    PPLT_CRYPTO_CONTEXT micEncryptionCtx;
    uint32_t micRiKeyId;
    uint16_t micSequenceNumber;
    struct sockaddr_storage micRemoteAddr;
    SOCKADDR_LEN micAddrLen;
    uint16_t micPortNumber;
    bool micAddrValid;
} ML_MICROPHONE_STREAM_CONTEXT, *PML_MICROPHONE_STREAM_CONTEXT;

int initializeMicrophoneStreamCtx(PML_MICROPHONE_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext);
void destroyMicrophoneStreamCtx(PML_MICROPHONE_STREAM_CONTEXT ctx);
int sendMicrophoneDataCtx(PML_MICROPHONE_STREAM_CONTEXT ctx, const char* data, int length);
int sendMicrophoneOpusDataCtx(PML_MICROPHONE_STREAM_CONTEXT ctx, const unsigned char* opusData, int opusLength);

// Input stream context (multi-stream scaffolding)
typedef struct _ML_INPUT_STREAM_CONTEXT {
        PML_CONNECTION_CONTEXT connectionContext;
        SOCKET inputSock;
        unsigned char currentAesIv[16];
        bool initialized;
        bool encryptedControlStream;
        bool needsBatchedScroll;
        int batchedScrollDelta;
        PPLT_CRYPTO_CONTEXT cryptoContext;

        LINKED_BLOCKING_QUEUE packetQueue;
        LINKED_BLOCKING_QUEUE packetHolderFreeList;
        PLT_THREAD inputSendThread;

        float absCurrentPosX;
        float absCurrentPosY;

        uint8_t currentPenButtonState;
        PLT_MUTEX batchedInputMutex;
        struct {
            float x, y, z;
            bool dirty;
        } currentGamepadSensorState[16][2];
        struct {
            int deltaX, deltaY;
            bool dirty;
        } currentRelativeMouseState;
        struct {
            int x, y;
            int width, height;
            bool dirty;
        } currentAbsoluteMouseState;
        atomic_bool scrollTraceLoggingEnabled;
        atomic_bool scrollTraceAwaitingRender;
        atomic_bool scrollTraceLastDispatchHighRes;
        atomic_bool scrollTraceLastDispatchHorizontal;
        atomic_uint_fast64_t scrollTraceId;
        atomic_uint_fast64_t scrollTraceStartMs;
        atomic_uint_fast64_t scrollTraceLastLocalDispatchMs;
        atomic_uint_fast64_t scrollTraceLastQueuedMs;
        atomic_uint_fast64_t scrollTraceLastSentMs;
        atomic_int_fast16_t scrollTraceLastDispatchAmount;
} ML_INPUT_STREAM_CONTEXT, *PML_INPUT_STREAM_CONTEXT;

static inline void LiSetScrollTraceDiagnosticsEnabledCtx(PML_INPUT_STREAM_CONTEXT ctx, bool enabled) {
    if (ctx == NULL) {
        return;
    }

    atomic_store_explicit(&ctx->scrollTraceLoggingEnabled, enabled, memory_order_relaxed);
}

static inline bool LiIsScrollTraceDiagnosticsEnabledCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL &&
           atomic_load_explicit(&ctx->scrollTraceLoggingEnabled, memory_order_relaxed);
}

static inline void LiStartScrollTraceCtx(PML_INPUT_STREAM_CONTEXT ctx, uint64_t traceId, uint64_t startedMs) {
    if (ctx == NULL) {
        return;
    }

    atomic_store_explicit(&ctx->scrollTraceId, traceId, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceStartMs, startedMs, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastLocalDispatchMs, 0, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastQueuedMs, 0, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastSentMs, 0, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastDispatchAmount, 0, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastDispatchHighRes, false, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastDispatchHorizontal, false, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceAwaitingRender, false, memory_order_relaxed);
}

static inline void LiNoteScrollTraceLocalDispatchCtx(PML_INPUT_STREAM_CONTEXT ctx,
                                                     uint64_t traceId,
                                                     uint64_t dispatchMs,
                                                     short amount,
                                                     bool highRes,
                                                     bool horizontal) {
    if (ctx == NULL) {
        return;
    }

    atomic_store_explicit(&ctx->scrollTraceId, traceId, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastLocalDispatchMs, dispatchMs, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastDispatchAmount, amount, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastDispatchHighRes, highRes, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceLastDispatchHorizontal, horizontal, memory_order_relaxed);
}

static inline void LiNoteScrollTraceQueuedCtx(PML_INPUT_STREAM_CONTEXT ctx, uint64_t queuedMs) {
    if (ctx == NULL) {
        return;
    }

    atomic_store_explicit(&ctx->scrollTraceLastQueuedMs, queuedMs, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceAwaitingRender, false, memory_order_relaxed);
}

static inline void LiNoteScrollTraceSentCtx(PML_INPUT_STREAM_CONTEXT ctx, uint64_t sentMs) {
    if (ctx == NULL) {
        return;
    }

    atomic_store_explicit(&ctx->scrollTraceLastSentMs, sentMs, memory_order_relaxed);
    atomic_store_explicit(&ctx->scrollTraceAwaitingRender, true, memory_order_relaxed);
}

static inline void LiCompleteScrollTraceRenderCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    if (ctx == NULL) {
        return;
    }

    atomic_store_explicit(&ctx->scrollTraceAwaitingRender, false, memory_order_relaxed);
}

static inline uint64_t LiGetScrollTraceIdCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL ? atomic_load_explicit(&ctx->scrollTraceId, memory_order_relaxed) : 0;
}

static inline uint64_t LiGetScrollTraceStartMsCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL ? atomic_load_explicit(&ctx->scrollTraceStartMs, memory_order_relaxed) : 0;
}

static inline uint64_t LiGetScrollTraceLocalDispatchMsCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL ? atomic_load_explicit(&ctx->scrollTraceLastLocalDispatchMs, memory_order_relaxed) : 0;
}

static inline uint64_t LiGetScrollTraceQueuedMsCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL ? atomic_load_explicit(&ctx->scrollTraceLastQueuedMs, memory_order_relaxed) : 0;
}

static inline uint64_t LiGetScrollTraceSentMsCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL ? atomic_load_explicit(&ctx->scrollTraceLastSentMs, memory_order_relaxed) : 0;
}

static inline short LiGetScrollTraceLastDispatchAmountCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL ? (short)atomic_load_explicit(&ctx->scrollTraceLastDispatchAmount, memory_order_relaxed) : 0;
}

static inline bool LiGetScrollTraceLastDispatchHighResCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL &&
           atomic_load_explicit(&ctx->scrollTraceLastDispatchHighRes, memory_order_relaxed);
}

static inline bool LiGetScrollTraceLastDispatchHorizontalCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL &&
           atomic_load_explicit(&ctx->scrollTraceLastDispatchHorizontal, memory_order_relaxed);
}

static inline bool LiIsScrollTraceAwaitingRenderCtx(PML_INPUT_STREAM_CONTEXT ctx) {
    return ctx != NULL &&
           atomic_load_explicit(&ctx->scrollTraceAwaitingRender, memory_order_relaxed);
}

// Connection context (multi-stream scaffolding)
typedef struct _ML_CONNECTION_CONTEXT {
    char* RemoteAddrString;
    struct sockaddr_storage RemoteAddr;
    struct sockaddr_storage LocalAddr;
    SOCKADDR_LEN AddrLen;
    int AppVersionQuad[4];
    STREAM_CONFIGURATION StreamConfig;
    CONNECTION_LISTENER_CALLBACKS ListenerCallbacks;
    DECODER_RENDERER_CALLBACKS VideoCallbacks;
    AUDIO_RENDERER_CALLBACKS AudioCallbacks;
    int NegotiatedVideoFormat;
    volatile bool ConnectionInterrupted;
    bool HighQualitySurroundSupported;
    bool HighQualitySurroundEnabled;
    OPUS_MULTISTREAM_CONFIGURATION NormalQualityOpusConfig;
    OPUS_MULTISTREAM_CONFIGURATION HighQualityOpusConfig;
    int AudioPacketDuration;
    bool AudioEncryptionEnabled;
    bool ReferenceFrameInvalidationSupported;

    uint16_t RtspPortNumber;
    uint16_t ControlPortNumber;
    uint16_t AudioPortNumber;
    uint16_t VideoPortNumber;
    uint16_t MicPortNumber;

    SS_PING AudioPingPayload;
    SS_PING VideoPingPayload;
    SS_PING MicPingPayload;
    uint32_t ControlConnectData;

    uint32_t SunshineFeatureFlags;
    uint32_t EncryptionFeaturesSupported;
    uint32_t EncryptionFeaturesRequested;
    uint32_t EncryptionFeaturesEnabled;

    ML_VIDEO_STREAM_CONTEXT videoContext;
    ML_AUDIO_STREAM_CONTEXT audioContext;
    ML_CONTROL_STREAM_CONTEXT controlContext;
    ML_INPUT_STREAM_CONTEXT inputContext;
    ML_MICROPHONE_STREAM_CONTEXT micContext;

    // Connection state
    int stage;
    ConnListenerConnectionTerminated originalTerminationCallback;
    bool alreadyTerminated;
    PLT_THREAD terminationCallbackThread;
    int terminationCallbackErrorCode;
} ML_CONNECTION_CONTEXT, *PML_CONNECTION_CONTEXT;

extern ML_CONNECTION_CONTEXT gConnectionContext;
PML_CONNECTION_CONTEXT LiGetThreadConnectionContext(void);

static inline PML_CONNECTION_CONTEXT LiGetEffectiveConnectionContext(void) {
    PML_CONNECTION_CONTEXT tctx = LiGetThreadConnectionContext();
    return (tctx != NULL) ? tctx : &gConnectionContext;
}

// Legacy global access routed to the global connection context
#ifndef RemoteAddrString
#define RemoteAddrString (LiGetEffectiveConnectionContext()->RemoteAddrString)
#endif
#ifndef RemoteAddr
#define RemoteAddr (LiGetEffectiveConnectionContext()->RemoteAddr)
#endif
#ifndef LocalAddr
#define LocalAddr (LiGetEffectiveConnectionContext()->LocalAddr)
#endif
#ifndef AddrLen
#define AddrLen (LiGetEffectiveConnectionContext()->AddrLen)
#endif
#ifndef StreamConfig
#define StreamConfig (LiGetEffectiveConnectionContext()->StreamConfig)
#endif
#ifndef ListenerCallbacks
#define ListenerCallbacks (LiGetEffectiveConnectionContext()->ListenerCallbacks)
#endif
#ifndef VideoCallbacks
#define VideoCallbacks (LiGetEffectiveConnectionContext()->VideoCallbacks)
#endif
#ifndef AudioCallbacks
#define AudioCallbacks (LiGetEffectiveConnectionContext()->AudioCallbacks)
#endif
#ifndef NegotiatedVideoFormat
#define NegotiatedVideoFormat (LiGetEffectiveConnectionContext()->NegotiatedVideoFormat)
#endif
#ifndef ConnectionInterrupted
#define ConnectionInterrupted (LiGetEffectiveConnectionContext()->ConnectionInterrupted)
#endif
#ifndef HighQualitySurroundSupported
#define HighQualitySurroundSupported (LiGetEffectiveConnectionContext()->HighQualitySurroundSupported)
#endif
#ifndef HighQualitySurroundEnabled
#define HighQualitySurroundEnabled (LiGetEffectiveConnectionContext()->HighQualitySurroundEnabled)
#endif
#ifndef NormalQualityOpusConfig
#define NormalQualityOpusConfig (LiGetEffectiveConnectionContext()->NormalQualityOpusConfig)
#endif
#ifndef HighQualityOpusConfig
#define HighQualityOpusConfig (LiGetEffectiveConnectionContext()->HighQualityOpusConfig)
#endif
#ifndef AudioPacketDuration
#define AudioPacketDuration (LiGetEffectiveConnectionContext()->AudioPacketDuration)
#endif
#ifndef AudioEncryptionEnabled
#define AudioEncryptionEnabled (LiGetEffectiveConnectionContext()->AudioEncryptionEnabled)
#endif
#ifndef ReferenceFrameInvalidationSupported
#define ReferenceFrameInvalidationSupported (LiGetEffectiveConnectionContext()->ReferenceFrameInvalidationSupported)
#endif

#ifndef RtspPortNumber
#define RtspPortNumber (LiGetEffectiveConnectionContext()->RtspPortNumber)
#endif
#ifndef ControlPortNumber
#define ControlPortNumber (LiGetEffectiveConnectionContext()->ControlPortNumber)
#endif
#ifndef AudioPortNumber
#define AudioPortNumber (LiGetEffectiveConnectionContext()->AudioPortNumber)
#endif
#ifndef VideoPortNumber
#define VideoPortNumber (LiGetEffectiveConnectionContext()->VideoPortNumber)
#endif
#ifndef MicPortNumber
#define MicPortNumber (LiGetEffectiveConnectionContext()->MicPortNumber)
#endif

#ifndef AudioPingPayload
#define AudioPingPayload (LiGetEffectiveConnectionContext()->AudioPingPayload)
#endif
#ifndef VideoPingPayload
#define VideoPingPayload (LiGetEffectiveConnectionContext()->VideoPingPayload)
#endif
#ifndef MicPingPayload
#define MicPingPayload (LiGetEffectiveConnectionContext()->MicPingPayload)
#endif
#ifndef ControlConnectData
#define ControlConnectData (LiGetEffectiveConnectionContext()->ControlConnectData)
#endif

#ifndef SunshineFeatureFlags
#define SunshineFeatureFlags (LiGetEffectiveConnectionContext()->SunshineFeatureFlags)
#endif
#ifndef EncryptionFeaturesSupported
#define EncryptionFeaturesSupported (LiGetEffectiveConnectionContext()->EncryptionFeaturesSupported)
#endif
#ifndef EncryptionFeaturesRequested
#define EncryptionFeaturesRequested (LiGetEffectiveConnectionContext()->EncryptionFeaturesRequested)
#endif
#ifndef EncryptionFeaturesEnabled
#define EncryptionFeaturesEnabled (LiGetEffectiveConnectionContext()->EncryptionFeaturesEnabled)
#endif

int initializeInputStreamCtx(PML_INPUT_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext);
void destroyInputStreamCtx(PML_INPUT_STREAM_CONTEXT ctx);
int startInputStreamCtx(PML_INPUT_STREAM_CONTEXT ctx);
int stopInputStreamCtx(PML_INPUT_STREAM_CONTEXT ctx);

// Debug helpers (ABI validation)
uint32_t LiGetInputContextStructSize(void);
uint32_t LiGetInputContextOffsetInitialized(void);
uint32_t LiGetInputContextOffsetConnectionContext(void);
int LiInputContextIsInitialized(PML_INPUT_STREAM_CONTEXT ctx);
void* LiInputContextGetConnectionCtx(PML_INPUT_STREAM_CONTEXT ctx);
PML_INPUT_STREAM_CONTEXT LiGetInputContextFromConnectionCtx(PML_CONNECTION_CONTEXT ctx);
PML_CONNECTION_CONTEXT LiGetGlobalConnectionContextPtr(void);
uint32_t LiGetHostFeatureFlagsCtx(PML_CONNECTION_CONTEXT ctx);


int LiSendMouseMoveEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short deltaX, short deltaY);
int LiSendMousePositionEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short x, short y, short referenceWidth, short referenceHeight);
int LiSendMouseMoveAsMousePositionEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short deltaX, short deltaY, short referenceWidth, short referenceHeight);
int LiSendMouseButtonEventCtx(PML_INPUT_STREAM_CONTEXT ctx, char action, int button);
int LiSendKeyboardEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short keyCode, char keyAction, char modifiers);
int LiSendKeyboardEvent2Ctx(PML_INPUT_STREAM_CONTEXT ctx, short keyCode, char keyAction, char modifiers, char flags);
int LiSendUtf8TextEventCtx(PML_INPUT_STREAM_CONTEXT ctx, const char *text, unsigned int length);
int LiSendControllerEventCtx(PML_INPUT_STREAM_CONTEXT ctx, int buttonFlags, unsigned char leftTrigger, unsigned char rightTrigger, short leftStickX, short leftStickY, short rightStickX, short rightStickY);
int LiSendMultiControllerEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short controllerNumber, short activeGamepadMask, int buttonFlags, unsigned char leftTrigger, unsigned char rightTrigger, short leftStickX, short leftStickY, short rightStickX, short rightStickY);
int LiSendHighResScrollEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short scrollAmount);
int LiSendScrollEventCtx(PML_INPUT_STREAM_CONTEXT ctx, signed char scrollClicks);
int LiSendHighResHScrollEventCtx(PML_INPUT_STREAM_CONTEXT ctx, short scrollAmount);
int LiSendHScrollEventCtx(PML_INPUT_STREAM_CONTEXT ctx, signed char scrollClicks);
int LiSendMicrophoneControlCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t control, int sampleRate, int channelCount, int bitrate);
int LiSendTouchEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t eventType, uint32_t pointerId, float x, float y, float pressureOrDistance, float contactAreaMajor, float contactAreaMinor, uint16_t rotation);
int LiSendPenEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t eventType, uint8_t toolType, uint8_t penButtons, float x, float y, float pressureOrDistance, float contactAreaMajor, float contactAreaMinor, uint16_t rotation, uint8_t tilt);
int LiSendControllerArrivalEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t controllerNumber, uint16_t activeGamepadMask, uint8_t type, uint32_t supportedButtonFlags, uint16_t capabilities);
int LiSendControllerTouchEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t controllerNumber, uint8_t eventType, uint32_t pointerId, float x, float y, float pressure);
int LiSendControllerMotionEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t controllerNumber, uint8_t motionType, float x, float y, float z);
int LiSendControllerBatteryEventCtx(PML_INPUT_STREAM_CONTEXT ctx, uint8_t controllerNumber, uint8_t batteryState, uint8_t batteryPercentage);

void LiRequestIdrFrameCtx(PML_CONTROL_STREAM_CONTEXT ctx);
bool LiGetCurrentHostDisplayHdrModeCtx(PML_CONTROL_STREAM_CONTEXT ctx);
bool LiGetHdrMetadataCtx(PML_CONTROL_STREAM_CONTEXT ctx, PSS_HDR_METADATA metadata);
void connectionDetectedFrameLossCtx(PML_CONTROL_STREAM_CONTEXT ctx, uint32_t startFrame, uint32_t endFrame);
void connectionReceivedCompleteFrameCtx(PML_CONTROL_STREAM_CONTEXT ctx, uint32_t frameIndex);
void connectionSawFrameCtx(PML_CONTROL_STREAM_CONTEXT ctx, uint32_t frameIndex);
void connectionSendFrameFecStatusCtx(PML_CONTROL_STREAM_CONTEXT ctx, PSS_FRAME_FEC_STATUS fecStatus);

int initializeAudioStream(void);
int notifyAudioPortNegotiationComplete(void);
void destroyAudioStream(void);
int startAudioStream(void* audioContext, int arFlags);
void stopAudioStream(void);

int initializeInputStream(void);
void destroyInputStream(void);
int startInputStream(void);
int stopInputStream(void);

// 麦克风流函数声明
int initializeMicrophoneStream(void);
void destroyMicrophoneStream(void);
int sendMicrophoneData(const char* data, int length);
int sendMicrophoneOpusData(const unsigned char* opusData, int opusLength);
bool isMicrophoneEncryptionEnabled(void);

// Connection functions
int LiStartConnectionCtx(PML_CONNECTION_CONTEXT ctx, PSERVER_INFORMATION serverInfo, PSTREAM_CONFIGURATION streamConfig, PCONNECTION_LISTENER_CALLBACKS clCallbacks,
    PDECODER_RENDERER_CALLBACKS drCallbacks, PAUDIO_RENDERER_CALLBACKS arCallbacks, void* renderContext, int drFlags,
    void* audioContext, int arFlags);
void LiStopConnectionCtx(PML_CONNECTION_CONTEXT ctx);
void LiInterruptConnectionCtx(PML_CONNECTION_CONTEXT ctx);
int performRtspHandshakeCtx(PML_CONNECTION_CONTEXT ctx, PSERVER_INFORMATION serverInfo);
char* getSdpPayloadForStreamConfigCtx(PML_CONNECTION_CONTEXT ctx, int rtspClientVersion, int* length);

void LiSetThreadConnectionContext(PML_CONNECTION_CONTEXT ctx);
