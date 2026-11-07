#include "Limelight-internal.h"

#ifdef StreamConfig
#undef StreamConfig
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
#ifdef VideoPortNumber
#undef VideoPortNumber
#endif
#ifdef VideoPingPayload
#undef VideoPingPayload
#endif
#ifdef EncryptionFeaturesEnabled
#undef EncryptionFeaturesEnabled
#endif
#ifdef NegotiatedVideoFormat
#undef NegotiatedVideoFormat
#endif
#ifdef VideoCallbacks
#undef VideoCallbacks
#endif
#ifdef ListenerCallbacks
#undef ListenerCallbacks
#endif

#define FIRST_FRAME_MAX 1500
#define FIRST_FRAME_TIMEOUT_SEC 10

#define FIRST_FRAME_PORT 47996

#define StreamConfig (ctx->connectionContext->StreamConfig)
#define RemoteAddr (ctx->connectionContext->RemoteAddr)
#define LocalAddr (ctx->connectionContext->LocalAddr)
#define AddrLen (ctx->connectionContext->AddrLen)
#define VideoPortNumber (ctx->connectionContext->VideoPortNumber)
#define VideoPingPayload (ctx->connectionContext->VideoPingPayload)
#define EncryptionFeaturesEnabled (ctx->connectionContext->EncryptionFeaturesEnabled)
#define NegotiatedVideoFormat (ctx->connectionContext->NegotiatedVideoFormat)
#define VideoCallbacks (ctx->connectionContext->VideoCallbacks)
#define AppVersionQuad (ctx->connectionContext->AppVersionQuad)
#define ListenerCallbacks (ctx->connectionContext->ListenerCallbacks)

// We can't request an IDR frame until the depacketizer knows
// that a packet was lost. This timeout bounds the time that
// the RTP queue will wait for missing/reordered packets.
#define RTP_QUEUE_DELAY 10

// Desired number of video packets in the socket receive buffer.
// Increase this for remote/high-FPS sessions to better tolerate
// bursty delivery from tunnel/VPN paths.
#define RTP_RECV_PACKETS_BUFFERED_BASE 2048
#define RTP_RECV_PACKETS_BUFFERED_REMOTE 4096
#define RTP_RECV_PACKETS_BUFFERED_HIGH_FPS 6144

// Initialize the video stream (context)
void initializeVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext) {
    ctx->connectionContext = connectionContext;
    initializeVideoDepacketizerCtx(&ctx->depacketizerContext, connectionContext, StreamConfig.packetSize);
    RtpvInitializeQueue(&ctx->rtpQueue, &ctx->depacketizerContext);
    ctx->decryptionCtx = PltCreateCryptoContext();
    ctx->rtpSocket = INVALID_SOCKET;
    ctx->firstFrameSocket = INVALID_SOCKET;
    ctx->receivedDataFromPeer = false;
    ctx->firstDataTimeMs = 0;
    ctx->receivedFullFrame = false;
}

// Initialize the video stream
void initializeVideoStream(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    initializeVideoStreamCtx(&ctx->videoContext, ctx);
}

// Clean up the video stream (context)
void destroyVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx) {
    PltDestroyCryptoContext(ctx->decryptionCtx);
    destroyVideoDepacketizerCtx(&ctx->depacketizerContext);
    RtpvCleanupQueue(&ctx->rtpQueue);
    ctx->decryptionCtx = NULL;
}

// Clean up the video stream
void destroyVideoStream(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    destroyVideoStreamCtx(&ctx->videoContext);
}

// UDP Ping proc
static void VideoPingThreadProc(void* context) {
    PML_VIDEO_STREAM_CONTEXT ctx = (PML_VIDEO_STREAM_CONTEXT)context;
    LiSetThreadConnectionContext(ctx->connectionContext);
    char legacyPingData[] = { 0x50, 0x49, 0x4E, 0x47 };
    LC_SOCKADDR saddr;

    LC_ASSERT(VideoPortNumber != 0);

    memcpy(&saddr, &RemoteAddr, sizeof(saddr));
    SET_PORT(&saddr, VideoPortNumber);

    // We do not check for errors here. Socket errors will be handled
    // on the read-side in ReceiveThreadProc(). This avoids potential
    // issues related to receiving ICMP port unreachable messages due
    // to sending a packet prior to the host PC binding to that port.
    int pingCount = 0;
    while (!PltIsThreadInterrupted(&ctx->udpPingThread)) {
        if (VideoPingPayload.payload[0] != 0) {
            pingCount++;
            VideoPingPayload.sequenceNumber = BE32(pingCount);

            sendto(ctx->rtpSocket, (char*)&VideoPingPayload, sizeof(VideoPingPayload), 0, (struct sockaddr*)&saddr, AddrLen);
        }
        else {
            sendto(ctx->rtpSocket, legacyPingData, sizeof(legacyPingData), 0, (struct sockaddr*)&saddr, AddrLen);
        }

        PltSleepMsInterruptible(&ctx->udpPingThread, 500);
    }
}

// Receive thread proc
static void VideoReceiveThreadProc(void* context) {
    PML_VIDEO_STREAM_CONTEXT ctx = (PML_VIDEO_STREAM_CONTEXT)context;
    LiSetThreadConnectionContext(ctx->connectionContext);
    int err;
    int bufferSize, receiveSize, decryptedSize, minSize;
    char* buffer;
    char* encryptedBuffer;
    int queueStatus;
    bool useSelect;
    int waitingForVideoMs;
    bool encrypted;

    encrypted = !!(EncryptionFeaturesEnabled & SS_ENC_VIDEO);
    decryptedSize = StreamConfig.packetSize + MAX_RTP_HEADER_SIZE;
    minSize = sizeof(RTP_PACKET) + ((EncryptionFeaturesEnabled & SS_ENC_VIDEO) ? sizeof(ENC_VIDEO_HEADER) : 0);
    receiveSize = decryptedSize + ((EncryptionFeaturesEnabled & SS_ENC_VIDEO) ? sizeof(ENC_VIDEO_HEADER) : 0);
    bufferSize = decryptedSize + sizeof(RTPV_QUEUE_ENTRY);
    buffer = NULL;

    if (setNonFatalRecvTimeoutMs(ctx->rtpSocket, UDP_RECV_POLL_TIMEOUT_MS) < 0) {
        // SO_RCVTIMEO failed, so use select() to wait
        useSelect = true;
    }
    else {
        // SO_RCVTIMEO timeout set for recv()
        useSelect = false;
    }

    // Allocate a staging buffer to use for each received packet
    if (encrypted) {
        encryptedBuffer = (char*)malloc(receiveSize);
        if (encryptedBuffer == NULL) {
            Limelog("Video Receive: malloc() failed\n");
            ListenerCallbacks.connectionTerminated(-1);
            return;
        }
    }
    else {
        encryptedBuffer = NULL;
    }

    waitingForVideoMs = 0;
    while (!PltIsThreadInterrupted(&ctx->receiveThread)) {
        PRTP_PACKET packet;

        if (buffer == NULL) {
            buffer = (char*)malloc(bufferSize);
            if (buffer == NULL) {
                Limelog("Video Receive: malloc() failed\n");
                ListenerCallbacks.connectionTerminated(-1);
                break;
            }
        }

        err = recvUdpSocket(ctx->rtpSocket,
                            encrypted ? encryptedBuffer : buffer,
                            receiveSize,
                            useSelect);
        if (err < 0) {
            Limelog("Video Receive: recvUdpSocket() failed: %d\n", (int)LastSocketError());
            ListenerCallbacks.connectionTerminated(LastSocketFail());
            break;
        }
        else if  (err == 0) {
            if (!ctx->receivedDataFromPeer) {
                // If we wait many seconds without ever receiving a video packet,
                // assume something is broken and terminate the connection.
                waitingForVideoMs += UDP_RECV_POLL_TIMEOUT_MS;
                if (waitingForVideoMs >= FIRST_FRAME_TIMEOUT_SEC * 1000) {
                    Limelog("Terminating connection due to lack of video traffic\n");
                    ListenerCallbacks.connectionTerminated(ML_ERROR_NO_VIDEO_TRAFFIC);
                    break;
                }
            }

            // Receive timed out; try again
            continue;
        }

        if (!ctx->receivedDataFromPeer) {
            ctx->receivedDataFromPeer = true;
            Limelog("Received first video packet after %d ms\n", waitingForVideoMs);

            ctx->firstDataTimeMs = PltGetMillis();
        }

#ifndef LC_FUZZING
        if (!ctx->receivedFullFrame) {
            uint64_t now = PltGetMillis();

            if (now - ctx->firstDataTimeMs >= FIRST_FRAME_TIMEOUT_SEC * 1000) {
                Limelog("Terminating connection due to lack of a successful video frame\n");
                ListenerCallbacks.connectionTerminated(ML_ERROR_NO_VIDEO_FRAME);
                break;
            }
        }
#endif

        if (err < minSize) {
            // Runt packet
            continue;
        }

        // Decrypt the packet into the buffer if encryption is enabled
        if (encrypted) {
            PENC_VIDEO_HEADER encHeader = (PENC_VIDEO_HEADER)encryptedBuffer;

            // If this frame is below our current frame number, discard it before decryption
            // to save CPU cycles decrypting FEC shards for a frame we already reassembled.
            //
            // Since this is happening _before_ decryption, this packet is not trusted yet.
            // It's imperative that we do not mutate any state based on this packet until
            // after it has been decrypted successfully!
            //
            // It's possible for an attacker to inject a fake packet that has any value of
            // header fields they want, however this provides them no benefit because we will
            // simply drop said packet here (if it's below the current frame number) or it
            // will pass this check and be dropped during decryption (if contents is tampered)
            // or after decryption in the RTP queue (if it's a replay of a previous authentic
            // packet from the host).
            //
            // In short, an attacker spoofing this value via MITM or sending malicious values
            // impersonating the host from off-link doesn't gain them anything. If they have
            // a true MITM, they can DoS our connection by just dropping all our traffic, so
            // tampering with packets to fail this check doesn't accomplish anything they
            // couldn't already do. If they're not on-link, we just throw their malicious
            // traffic away (as mentioned in the paragraph above) and continue accepting
            // legitmate video traffic.
            if (encHeader->frameNumber && LE32(encHeader->frameNumber) < RtpvGetCurrentFrameNumber(&ctx->rtpQueue)) {
                continue;
            }

            if (!PltDecryptMessage(ctx->decryptionCtx, ALGORITHM_AES_GCM, 0,
                                   (unsigned char*)StreamConfig.remoteInputAesKey, sizeof(StreamConfig.remoteInputAesKey),
                                   encHeader->iv, sizeof(encHeader->iv),
                                   encHeader->tag, sizeof(encHeader->tag),
                                   ((unsigned char*)(encHeader + 1)), err - sizeof(ENC_VIDEO_HEADER), // The ciphertext is after the header
                                   (unsigned char*)buffer, &err)) {
                Limelog("Failed to decrypt video packet!\n");
                continue;
            }
        }

        // Convert fields to host byte-order
        packet = (PRTP_PACKET)&buffer[0];
        packet->sequenceNumber = BE16(packet->sequenceNumber);
        packet->timestamp = BE32(packet->timestamp);
        packet->ssrc = BE32(packet->ssrc);

        queueStatus = RtpvAddPacket(&ctx->rtpQueue, packet, err, (PRTPV_QUEUE_ENTRY)&buffer[decryptedSize]);

        if (queueStatus == RTPF_RET_QUEUED) {
            // The queue owns the buffer
            buffer = NULL;
        }
    }

    if (buffer != NULL) {
        free(buffer);
    }

    if (encryptedBuffer != NULL) {
        free(encryptedBuffer);
    }
}

void notifyKeyFrameReceivedCtx(PML_VIDEO_STREAM_CONTEXT ctx) {
    // Remember that we got a full frame successfully
    ctx->receivedFullFrame = true;
}

void notifyKeyFrameReceived(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    notifyKeyFrameReceivedCtx(&ctx->videoContext);
}

// Decoder thread proc
static void VideoDecoderThreadProc(void* context) {
    PML_VIDEO_STREAM_CONTEXT ctx = (PML_VIDEO_STREAM_CONTEXT)context;
    LiSetThreadConnectionContext(ctx->connectionContext);
    while (!PltIsThreadInterrupted(&ctx->decoderThread)) {
        VIDEO_FRAME_HANDLE frameHandle;
        PDECODE_UNIT decodeUnit;

        if (!LiWaitForNextVideoFrameCtx(&ctx->depacketizerContext, &frameHandle, &decodeUnit)) {
            return;
        }

        LiCompleteVideoFrameCtx(&ctx->depacketizerContext, frameHandle, VideoCallbacks.submitDecodeUnit(decodeUnit));
    }
}

// Read the first frame of the video stream (context)
static int readFirstFrameCtx(PML_VIDEO_STREAM_CONTEXT ctx) {
    // All that matters is that we close this socket.
    // This starts the flow of video on Gen 3 servers.

    closeSocket(ctx->firstFrameSocket);
    ctx->firstFrameSocket = INVALID_SOCKET;

    return 0;
}

// Read the first frame of the video stream
int readFirstFrame(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return readFirstFrameCtx(&ctx->videoContext);
}

// Terminate the video stream (context)
void stopVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx) {
    LiSetThreadConnectionContext(ctx->connectionContext);
    if (!ctx->receivedDataFromPeer) {
        Limelog("No video traffic was ever received from the host!\n");
    }

    VideoCallbacks.stop();

    // Wake up client code that may be waiting on the decode unit queue
    stopVideoDepacketizerCtx(&ctx->depacketizerContext);

    PltInterruptThread(&ctx->udpPingThread);
    PltInterruptThread(&ctx->receiveThread);
    if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
        PltInterruptThread(&ctx->decoderThread);
    }

    if (ctx->firstFrameSocket != INVALID_SOCKET) {
        shutdownTcpSocket(ctx->firstFrameSocket);
    }

    PltJoinThread(&ctx->udpPingThread);
    PltJoinThread(&ctx->receiveThread);
    if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
        PltJoinThread(&ctx->decoderThread);
    }

    if (ctx->firstFrameSocket != INVALID_SOCKET) {
        closeSocket(ctx->firstFrameSocket);
        ctx->firstFrameSocket = INVALID_SOCKET;
    }
    if (ctx->rtpSocket != INVALID_SOCKET) {
        closeSocket(ctx->rtpSocket);
        ctx->rtpSocket = INVALID_SOCKET;
    }

    VideoCallbacks.cleanup();
}

// Terminate the video stream
void stopVideoStream(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    stopVideoStreamCtx(&ctx->videoContext);
}

// Start the video stream (context)
int startVideoStreamCtx(PML_VIDEO_STREAM_CONTEXT ctx, void* rendererContext, int drFlags) {
    int err;
    int recvPacketsBuffered;
    int recvBufferBytes;

    LiSetThreadConnectionContext(ctx->connectionContext);

    ctx->firstFrameSocket = INVALID_SOCKET;

    // This must be called before the decoder thread starts submitting
    // decode units
    LC_ASSERT(NegotiatedVideoFormat != 0);
    err = VideoCallbacks.setup(NegotiatedVideoFormat, StreamConfig.width,
        StreamConfig.height, StreamConfig.fps, rendererContext, drFlags);
    if (err != 0) {
        return err;
    }

    recvPacketsBuffered = RTP_RECV_PACKETS_BUFFERED_BASE;
    if (StreamConfig.streamingRemotely == STREAM_CFG_REMOTE) {
        recvPacketsBuffered = RTP_RECV_PACKETS_BUFFERED_REMOTE;
    }
    if (StreamConfig.fps >= 120 && recvPacketsBuffered < RTP_RECV_PACKETS_BUFFERED_HIGH_FPS) {
        recvPacketsBuffered = RTP_RECV_PACKETS_BUFFERED_HIGH_FPS;
    }
    recvBufferBytes = recvPacketsBuffered * (StreamConfig.packetSize + MAX_RTP_HEADER_SIZE);

    Limelog("Video recv buffer target: packets=%d bytes=%d remote=%d fps=%d pkt=%d\n",
            recvPacketsBuffered,
            recvBufferBytes,
            StreamConfig.streamingRemotely == STREAM_CFG_REMOTE ? 1 : 0,
            StreamConfig.fps,
            StreamConfig.packetSize);

    ctx->rtpSocket = bindUdpSocket(RemoteAddr.ss_family, &LocalAddr, AddrLen,
                              recvBufferBytes,
                              SOCK_QOS_TYPE_VIDEO);
    if (ctx->rtpSocket == INVALID_SOCKET) {
        VideoCallbacks.cleanup();
        return LastSocketError();
    }

    VideoCallbacks.start();

    err = PltCreateThread("VideoRecv", VideoReceiveThreadProc, ctx, &ctx->receiveThread);
    if (err != 0) {
        VideoCallbacks.stop();
        closeSocket(ctx->rtpSocket);
        VideoCallbacks.cleanup();
        return err;
    }

    if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
        err = PltCreateThread("VideoDec", VideoDecoderThreadProc, ctx, &ctx->decoderThread);
        if (err != 0) {
            VideoCallbacks.stop();
            PltInterruptThread(&ctx->receiveThread);
            PltJoinThread(&ctx->receiveThread);
            closeSocket(ctx->rtpSocket);
            VideoCallbacks.cleanup();
            return err;
        }
    }

    if (AppVersionQuad[0] == 3) {
        // Connect this socket to open port 47998 for our ping thread
        ctx->firstFrameSocket = connectTcpSocket(&RemoteAddr, AddrLen,
                                            FIRST_FRAME_PORT, FIRST_FRAME_TIMEOUT_SEC);
        if (ctx->firstFrameSocket == INVALID_SOCKET) {
            VideoCallbacks.stop();
            stopVideoDepacketizerCtx(&ctx->depacketizerContext);
            PltInterruptThread(&ctx->receiveThread);
            if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
                PltInterruptThread(&ctx->decoderThread);
            }
            PltJoinThread(&ctx->receiveThread);
            if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
                PltJoinThread(&ctx->decoderThread);
            }
            closeSocket(ctx->rtpSocket);
            VideoCallbacks.cleanup();
            return LastSocketError();
        }
    }

    // Start pinging before reading the first frame so GFE knows where
    // to send UDP data
    err = PltCreateThread("VideoPing", VideoPingThreadProc, ctx, &ctx->udpPingThread);
    if (err != 0) {
        VideoCallbacks.stop();
        stopVideoDepacketizerCtx(&ctx->depacketizerContext);
        PltInterruptThread(&ctx->receiveThread);
        if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
            PltInterruptThread(&ctx->decoderThread);
        }
        PltJoinThread(&ctx->receiveThread);
        if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
            PltJoinThread(&ctx->decoderThread);
        }
        closeSocket(ctx->rtpSocket);
        if (ctx->firstFrameSocket != INVALID_SOCKET) {
            closeSocket(ctx->firstFrameSocket);
            ctx->firstFrameSocket = INVALID_SOCKET;
        }
        VideoCallbacks.cleanup();
        return err;
    }

    if (AppVersionQuad[0] == 3) {
        // Read the first frame to start the flow of video
        err = readFirstFrameCtx(ctx);
        if (err != 0) {
            stopVideoStreamCtx(ctx);
            return err;
        }
    }

    return 0;
}

// Start the video stream
int startVideoStream(void* rendererContext, int drFlags) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return startVideoStreamCtx(&ctx->videoContext, rendererContext, drFlags);
}
