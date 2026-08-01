#include "Limelight-internal.h"

#ifdef AudioPortNumber
#undef AudioPortNumber
#endif
#ifdef RemoteAddr
#undef RemoteAddr
#endif
#ifdef AudioPingPayload
#undef AudioPingPayload
#endif
#ifdef AddrLen
#undef AddrLen
#endif
#ifdef StreamConfig
#undef StreamConfig
#endif
#ifdef AudioCallbacks
#undef AudioCallbacks
#endif
#ifdef AudioEncryptionEnabled
#undef AudioEncryptionEnabled
#endif
#ifdef HighQualitySurroundEnabled
#undef HighQualitySurroundEnabled
#endif
#ifdef HighQualitySurroundSupported
#undef HighQualitySurroundSupported
#endif
#ifdef HighQualityOpusConfig
#undef HighQualityOpusConfig
#endif
#ifdef NormalQualityOpusConfig
#undef NormalQualityOpusConfig
#endif
#ifdef AudioPacketDuration
#undef AudioPacketDuration
#endif

#define AudioPortNumber (ctx->connectionContext->AudioPortNumber)
#define RemoteAddr (ctx->connectionContext->RemoteAddr)
#define AudioPingPayload (ctx->connectionContext->AudioPingPayload)
#define AddrLen (ctx->connectionContext->AddrLen)
#define StreamConfig (ctx->connectionContext->StreamConfig)
#define AudioCallbacks (ctx->connectionContext->AudioCallbacks)
#define AudioEncryptionEnabled (ctx->connectionContext->AudioEncryptionEnabled)
#define HighQualitySurroundEnabled (ctx->connectionContext->HighQualitySurroundEnabled)
#define HighQualitySurroundSupported (ctx->connectionContext->HighQualitySurroundSupported)
#define HighQualityOpusConfig (ctx->connectionContext->HighQualityOpusConfig)
#define NormalQualityOpusConfig (ctx->connectionContext->NormalQualityOpusConfig)
#define AudioPacketDuration (ctx->connectionContext->AudioPacketDuration)
#ifdef LC_DEBUG
#define INVALID_OPUS_HEADER 0x00
#endif

#define MAX_PACKET_SIZE 1400

typedef struct _QUEUE_AUDIO_PACKET_HEADER {
    LINKED_BLOCKING_QUEUE_ENTRY lentry;
    int size;
} QUEUED_AUDIO_PACKET_HEADER, *PQUEUED_AUDIO_PACKET_HEADER;

typedef struct _QUEUED_AUDIO_PACKET {
    QUEUED_AUDIO_PACKET_HEADER header;
    char data[MAX_PACKET_SIZE];
} QUEUED_AUDIO_PACKET, *PQUEUED_AUDIO_PACKET;

static void logChosenOpusConfig(const char *label,
                                POPUS_MULTISTREAM_CONFIGURATION opusConfig) {
    char mappingStr[256];
    size_t offset = 0;
    int i;

    if (label == NULL || opusConfig == NULL) {
        return;
    }

    mappingStr[0] = '\0';
    for (i = 0; i < opusConfig->channelCount &&
                i < AUDIO_CONFIGURATION_MAX_CHANNEL_COUNT &&
                offset < sizeof(mappingStr);
         i++) {
        int written = snprintf(mappingStr + offset, sizeof(mappingStr) - offset,
                               "%s%u", i == 0 ? "" : ",",
                               (unsigned int)opusConfig->mapping[i]);
        if (written < 0 || (size_t)written >= sizeof(mappingStr) - offset) {
            offset = sizeof(mappingStr) - 1;
            break;
        }
        offset += (size_t)written;
    }

    mappingStr[sizeof(mappingStr) - 1] = '\0';
    Limelog("%s: channels=%d streams=%d coupled=%d samplesPerFrame=%d mapping=[%s]\n",
            label, opusConfig->channelCount, opusConfig->streams,
            opusConfig->coupledStreams, opusConfig->samplesPerFrame, mappingStr);
}

static void AudioPingThreadProc(void* context) {
    PML_AUDIO_STREAM_CONTEXT ctx = (PML_AUDIO_STREAM_CONTEXT)context;
    LiSetThreadConnectionContext(ctx->connectionContext);
    char legacyPingData[] = { 0x50, 0x49, 0x4E, 0x47 };
    LC_SOCKADDR saddr;

    LC_ASSERT(AudioPortNumber != 0);

    memcpy(&saddr, &RemoteAddr, sizeof(saddr));
    SET_PORT(&saddr, AudioPortNumber);

    // We do not check for errors here. Socket errors will be handled
    // on the read-side in ReceiveThreadProc(). This avoids potential
    // issues related to receiving ICMP port unreachable messages due
    // to sending a packet prior to the host PC binding to that port.
    int pingCount = 0;
    while (!PltIsThreadInterrupted(&ctx->udpPingThread)) {
        if (AudioPingPayload.payload[0] != 0) {
            pingCount++;
            AudioPingPayload.sequenceNumber = BE32(pingCount);

            sendto(ctx->rtpSocket, (char*)&AudioPingPayload, sizeof(AudioPingPayload), 0, (struct sockaddr*)&saddr, AddrLen);
        }
        else {
            sendto(ctx->rtpSocket, legacyPingData, sizeof(legacyPingData), 0, (struct sockaddr*)&saddr, AddrLen);
        }

        PltSleepMsInterruptible(&ctx->udpPingThread, 500);
    }
}

// Initialize the audio stream and start (context)
int initializeAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext) {
    ctx->connectionContext = connectionContext;
    ctx->rtpSocket = INVALID_SOCKET;
    LbqInitializeLinkedBlockingQueue(&ctx->packetQueue, 30);
    RtpaInitializeQueue(&ctx->rtpAudioQueue);
    ctx->lastSeq = 0;
    ctx->receivedDataFromPeer = false;
    ctx->pingThreadStarted = false;
    ctx->firstReceiveTime = 0;
    ctx->audioDecryptionCtx = PltCreateCryptoContext();
#ifdef LC_DEBUG
    ctx->opusHeaderByte = INVALID_OPUS_HEADER;
#endif

    // Copy and byte-swap the AV RI key ID used for the audio encryption IV
    memcpy(&ctx->avRiKeyId, StreamConfig.remoteInputAesIv, sizeof(ctx->avRiKeyId));
    ctx->avRiKeyId = BE32(ctx->avRiKeyId);

    return 0;
}

// Initialize the audio stream and start
int initializeAudioStream(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return initializeAudioStreamCtx(&ctx->audioContext, ctx);
}

// This is called when the RTSP SETUP message is parsed and the audio port
// number is parsed out of it. Alternatively, it's also called if parsing fails
// and will use the well known audio port instead.
int notifyAudioPortNegotiationCompleteCtx(PML_AUDIO_STREAM_CONTEXT ctx) {
    if (ctx == NULL || ctx->connectionContext == NULL) {
        return -1;
    }
    LiSetThreadConnectionContext(ctx->connectionContext);
    LC_ASSERT(!ctx->pingThreadStarted);
    LC_ASSERT(AudioPortNumber != 0);

    // For GFE 3.22 compatibility, we must start the audio ping thread before the RTSP handshake.
    // It will not reply to our RTSP PLAY request until the audio ping has been received.
    ctx->rtpSocket = bindUdpSocket(RemoteAddr.ss_family, &LocalAddr, AddrLen, 0, SOCK_QOS_TYPE_AUDIO);
    if (ctx->rtpSocket == INVALID_SOCKET) {
        return LastSocketFail();
    }

    // We may receive audio before our threads are started, but that's okay. We'll
    // drop the first 1 second of audio packets to catch up with the backlog.
    int err = PltCreateThread("AudioPing", AudioPingThreadProc, ctx, &ctx->udpPingThread);
    if (err != 0) {
        return err;
    }

    ctx->pingThreadStarted = true;
    return 0;
}

int notifyAudioPortNegotiationComplete(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return notifyAudioPortNegotiationCompleteCtx(&ctx->audioContext);
}

static void freePacketList(PLINKED_BLOCKING_QUEUE_ENTRY entry) {
    PLINKED_BLOCKING_QUEUE_ENTRY nextEntry;

    while (entry != NULL) {
        nextEntry = entry->flink;

        // The entry is stored within the data allocation
        free(entry->data);

        entry = nextEntry;
    }
}

// Tear down the audio stream once we're done with it (context)
void destroyAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx) {
    if (ctx->rtpSocket != INVALID_SOCKET) {
        if (ctx->pingThreadStarted) {
            PltInterruptThread(&ctx->udpPingThread);
            PltJoinThread(&ctx->udpPingThread);
        }

        closeSocket(ctx->rtpSocket);
        ctx->rtpSocket = INVALID_SOCKET;
    }

    PltDestroyCryptoContext(ctx->audioDecryptionCtx);
    freePacketList(LbqDestroyLinkedBlockingQueue(&ctx->packetQueue));
    RtpaCleanupQueue(&ctx->rtpAudioQueue);
    ctx->audioDecryptionCtx = NULL;
}

// Tear down the audio stream once we're done with it
void destroyAudioStream(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    destroyAudioStreamCtx(&ctx->audioContext);
}

static bool queuePacketToLbq(PML_AUDIO_STREAM_CONTEXT ctx, PQUEUED_AUDIO_PACKET* packet) {
    int err;

    do {
        err = LbqOfferQueueItem(&ctx->packetQueue, *packet, &(*packet)->header.lentry);
        if (err == LBQ_SUCCESS) {
            // The LBQ owns the buffer now
            *packet = NULL;
        }
        else if (err == LBQ_BOUND_EXCEEDED) {
            Limelog("Audio packet queue overflow\n");

            // The audio queue is full, so free all existing items and try again
            freePacketList(LbqFlushQueueItems(&ctx->packetQueue));
        }
    } while (err == LBQ_BOUND_EXCEEDED);

    return err == LBQ_SUCCESS;
}

static void decodeInputData(PML_AUDIO_STREAM_CONTEXT ctx, PQUEUED_AUDIO_PACKET packet) {
    LiSetThreadConnectionContext(ctx->connectionContext);
    // If the packet size is zero, this is a placeholder for a missing
    // packet. Trigger packet loss concealment logic in libopus by
    // invoking the decoder with a NULL buffer.
    if (packet->header.size == 0) {
        AudioCallbacks.decodeAndPlaySample(NULL, 0);
        return;
    }

    PRTP_PACKET rtp = (PRTP_PACKET)&packet->data[0];
    if (ctx->lastSeq != 0 && (unsigned short)(ctx->lastSeq + 1) != rtp->sequenceNumber) {
        Limelog("Network dropped audio data (expected %d, but received %d)\n", ctx->lastSeq + 1, rtp->sequenceNumber);
    }

    ctx->lastSeq = rtp->sequenceNumber;

    if (AudioEncryptionEnabled) {
        // We must have room for the AES padding which may be written to the buffer
        unsigned char decryptedOpusData[ROUND_TO_PKCS7_PADDED_LEN(MAX_PACKET_SIZE)];
        unsigned char iv[16] = { 0 };
        int dataLength = packet->header.size - sizeof(*rtp);

        LC_ASSERT(dataLength <= MAX_PACKET_SIZE);

        // The IV is the avkeyid (equivalent to the rikeyid) +
        // the RTP sequence number, in big endian.
        uint32_t ivSeq = BE32(ctx->avRiKeyId + rtp->sequenceNumber);

        memcpy(iv, &ivSeq, sizeof(ivSeq));

        if (!PltDecryptMessage(ctx->audioDecryptionCtx, ALGORITHM_AES_CBC, CIPHER_FLAG_RESET_IV | CIPHER_FLAG_FINISH,
                               (unsigned char*)StreamConfig.remoteInputAesKey, sizeof(StreamConfig.remoteInputAesKey),
                               iv, sizeof(iv),
                               NULL, 0,
                               (unsigned char*)(rtp + 1), dataLength,
                               decryptedOpusData, &dataLength)) {
            Limelog("Failed to decrypt audio packet (sequence number: %u)\n", rtp->sequenceNumber);
            LC_ASSERT_VT(false);
            return;
        }

#ifdef LC_DEBUG
        if (ctx->opusHeaderByte == INVALID_OPUS_HEADER) {
            ctx->opusHeaderByte = decryptedOpusData[0];
            LC_ASSERT_VT(ctx->opusHeaderByte != INVALID_OPUS_HEADER);
        }
        else {
            // Opus header should stay constant for the entire stream.
            // If it doesn't, it may indicate that the RtpAudioQueue
            // incorrectly recovered a data shard or the decryption
            // of the audio packet failed. Sunshine violates this for
            // surround sound in some cases, so just ignore it.
            LC_ASSERT_VT(decryptedOpusData[0] == ctx->opusHeaderByte || IS_SUNSHINE());
        }
#endif

        AudioCallbacks.decodeAndPlaySample((char*)decryptedOpusData, dataLength);
    }
    else {
#ifdef LC_DEBUG
        if (ctx->opusHeaderByte == INVALID_OPUS_HEADER) {
            ctx->opusHeaderByte = ((uint8_t*)(rtp + 1))[0];
            LC_ASSERT_VT(ctx->opusHeaderByte != INVALID_OPUS_HEADER);
        }
        else {
            // Opus header should stay constant for the entire stream.
            // If it doesn't, it may indicate that the RtpAudioQueue
            // incorrectly recovered a data shard. Sunshine violates
            // this for surround sound in some cases, so just ignore it.
            LC_ASSERT_VT(((uint8_t*)(rtp + 1))[0] == ctx->opusHeaderByte || IS_SUNSHINE());
        }
#endif

        AudioCallbacks.decodeAndPlaySample((char*)(rtp + 1), packet->header.size - sizeof(*rtp));
    }
}

static void AudioReceiveThreadProc(void* context) {
    PML_AUDIO_STREAM_CONTEXT ctx = (PML_AUDIO_STREAM_CONTEXT)context;
    LiSetThreadConnectionContext(ctx->connectionContext);
    PRTP_PACKET rtp;
    PQUEUED_AUDIO_PACKET packet;
    int queueStatus;
    bool useSelect;
    uint32_t packetsToDrop;
    int waitingForAudioMs;

    packet = NULL;
    packetsToDrop = 500 / AudioPacketDuration;

    if (setNonFatalRecvTimeoutMs(ctx->rtpSocket, UDP_RECV_POLL_TIMEOUT_MS) < 0) {
        // SO_RCVTIMEO failed, so use select() to wait
        useSelect = true;
    }
    else {
        // SO_RCVTIMEO timeout set for recv()
        useSelect = false;
    }

    waitingForAudioMs = 0;
    while (!PltIsThreadInterrupted(&ctx->receiveThread)) {
        if (packet == NULL) {
            packet = (PQUEUED_AUDIO_PACKET)malloc(sizeof(*packet));
            if (packet == NULL) {
                Limelog("Audio Receive: malloc() failed\n");
                ListenerCallbacks.connectionTerminated(-1);
                break;
            }
        }

        packet->header.size = recvUdpSocket(ctx->rtpSocket, &packet->data[0], MAX_PACKET_SIZE, useSelect);
        if (packet->header.size < 0) {
            Limelog("Audio Receive: recvUdpSocket() failed: %d\n", (int)LastSocketError());
            ListenerCallbacks.connectionTerminated(LastSocketFail());
            break;
        }
        else if (packet->header.size == 0) {
            // Receive timed out; try again
            
            if (!ctx->receivedDataFromPeer) {
                waitingForAudioMs += UDP_RECV_POLL_TIMEOUT_MS;
            }
            else {
                // If we hit this path, there are no queued audio packets on the host PC,
                // so we don't need to drop anything.
                packetsToDrop = 0;
            }
            continue;
        }

        if (packet->header.size < (int)sizeof(RTP_PACKET)) {
            // Runt packet
            continue;
        }

        rtp = (PRTP_PACKET)&packet->data[0];

        if (!ctx->receivedDataFromPeer) {
            ctx->receivedDataFromPeer = true;
            Limelog("Received first audio packet after %d ms\n", waitingForAudioMs);

            if (ctx->firstReceiveTime != 0) {
                packetsToDrop += (uint32_t)(PltGetMillis() - ctx->firstReceiveTime) / AudioPacketDuration;
            }

            Limelog("Initial audio resync period: %d milliseconds\n", packetsToDrop * AudioPacketDuration);
        }

        // GFE accumulates audio samples before we are ready to receive them, so
        // we will drop the ones that arrived before the receive thread was ready.
        if (packetsToDrop > 0) {
            // Only count actual audio data (not FEC) in the packets to drop calculation
            if (rtp->packetType == 97) {
                packetsToDrop--;
            }
            continue;
        }

        // Convert fields to host byte-order
        rtp->sequenceNumber = BE16(rtp->sequenceNumber);
        rtp->timestamp = BE32(rtp->timestamp);
        rtp->ssrc = BE32(rtp->ssrc);

        queueStatus = RtpaAddPacket(&ctx->rtpAudioQueue, (PRTP_PACKET)&packet->data[0], (uint16_t)packet->header.size);
        if (RTPQ_HANDLE_NOW(queueStatus)) {
            if ((AudioCallbacks.capabilities & CAPABILITY_DIRECT_SUBMIT) == 0) {
                if (!queuePacketToLbq(ctx, &packet)) {
                    // An exit signal was received
                    break;
                }
                else {
                    // Ownership should have been taken by the LBQ
                    LC_ASSERT(packet == NULL);
                }
            }
            else {
                decodeInputData(ctx, packet);
            }
        }
        else {
            if (RTPQ_PACKET_CONSUMED(queueStatus)) {
                // The queue consumed our packet, so we must allocate a new one
                packet = NULL;
            }

            if (RTPQ_PACKET_READY(queueStatus)) {
                // If packets are ready, pull them and send them to the decoder
                uint16_t length;
                PQUEUED_AUDIO_PACKET queuedPacket;
                while ((queuedPacket = (PQUEUED_AUDIO_PACKET)RtpaGetQueuedPacket(&ctx->rtpAudioQueue, sizeof(QUEUED_AUDIO_PACKET_HEADER), &length)) != NULL) {
                    // Populate header data (not preserved in queued packets)
                    queuedPacket->header.size = length;

                    if ((AudioCallbacks.capabilities & CAPABILITY_DIRECT_SUBMIT) == 0) {
                        if (!queuePacketToLbq(ctx, &queuedPacket)) {
                            // An exit signal was received
                            free(queuedPacket);
                            break;
                        }
                        else {
                            // Ownership should have been taken by the LBQ
                            LC_ASSERT(queuedPacket == NULL);
                        }
                    }
                    else {
                        decodeInputData(ctx, queuedPacket);
                        free(queuedPacket);
                    }
                }
                
                // Break on exit
                if (queuedPacket != NULL) {
                    break;
                }
            }
        }
    }
    
    if (packet != NULL) {
        free(packet);
    }
}

static void AudioDecoderThreadProc(void* context) {
    int err;
    PQUEUED_AUDIO_PACKET packet;

    PML_AUDIO_STREAM_CONTEXT ctx = (PML_AUDIO_STREAM_CONTEXT)context;
    LiSetThreadConnectionContext(ctx->connectionContext);
    while (!PltIsThreadInterrupted(&ctx->decoderThread)) {
        err = LbqWaitForQueueElement(&ctx->packetQueue, (void**)&packet);
        if (err != LBQ_SUCCESS) {
            // An exit signal was received
            return;
        }

        decodeInputData(ctx, packet);

        free(packet);
    }
}

void stopAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx) {
    LiSetThreadConnectionContext(ctx->connectionContext);
    if (!ctx->receivedDataFromPeer) {
        Limelog("No audio traffic was ever received from the host!\n");
    }

    AudioCallbacks.stop();

    PltInterruptThread(&ctx->receiveThread);
    if ((AudioCallbacks.capabilities & CAPABILITY_DIRECT_SUBMIT) == 0) {        
        // Signal threads waiting on the LBQ
        LbqSignalQueueShutdown(&ctx->packetQueue);
        PltInterruptThread(&ctx->decoderThread);
    }
    
    PltJoinThread(&ctx->receiveThread);
    if ((AudioCallbacks.capabilities & CAPABILITY_DIRECT_SUBMIT) == 0) {
        PltJoinThread(&ctx->decoderThread);
    }

    AudioCallbacks.cleanup();
}

void stopAudioStream(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    stopAudioStreamCtx(&ctx->audioContext);
}

int startAudioStreamCtx(PML_AUDIO_STREAM_CONTEXT ctx, void* audioContext, int arFlags) {
    int err;
    OPUS_MULTISTREAM_CONFIGURATION chosenConfig;

    LiSetThreadConnectionContext(ctx->connectionContext);

    if (HighQualitySurroundEnabled) {
        LC_ASSERT(HighQualitySurroundSupported);
        LC_ASSERT(HighQualityOpusConfig.channelCount != 0);
        LC_ASSERT(HighQualityOpusConfig.streams != 0);
        chosenConfig = HighQualityOpusConfig;
    }
    else {
        LC_ASSERT(NormalQualityOpusConfig.channelCount != 0);
        LC_ASSERT(NormalQualityOpusConfig.streams != 0);
        chosenConfig = NormalQualityOpusConfig;
    }

    chosenConfig.samplesPerFrame = 48 * AudioPacketDuration;
    Limelog("Audio stream starting: highQualityEnabled=%d highQualitySupported=%d audioPacketDuration=%d\n",
            HighQualitySurroundEnabled ? 1 : 0,
            HighQualitySurroundSupported ? 1 : 0,
            AudioPacketDuration);
    logChosenOpusConfig("Audio stream chosen Opus config", &chosenConfig);

    err = AudioCallbacks.init(StreamConfig.audioConfiguration, &chosenConfig, audioContext, arFlags);
    if (err != 0) {
        return err;
    }

    AudioCallbacks.start();

    err = PltCreateThread("AudioRecv", AudioReceiveThreadProc, ctx, &ctx->receiveThread);
    if (err != 0) {
        AudioCallbacks.stop();
        closeSocket(ctx->rtpSocket);
        AudioCallbacks.cleanup();
        return err;
    }

    if ((AudioCallbacks.capabilities & CAPABILITY_DIRECT_SUBMIT) == 0) {
        err = PltCreateThread("AudioDec", AudioDecoderThreadProc, ctx, &ctx->decoderThread);
        if (err != 0) {
            AudioCallbacks.stop();
            PltInterruptThread(&ctx->receiveThread);
            PltJoinThread(&ctx->receiveThread);
            closeSocket(ctx->rtpSocket);
            AudioCallbacks.cleanup();
            return err;
        }
    }

    return 0;
}

int startAudioStream(void* audioContext, int arFlags) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return startAudioStreamCtx(&ctx->audioContext, audioContext, arFlags);
}

int LiGetPendingAudioFramesCtx(PML_AUDIO_STREAM_CONTEXT ctx) {
    return LbqGetItemCount(&ctx->packetQueue);
}

int LiGetPendingAudioFrames(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return LiGetPendingAudioFramesCtx(&ctx->audioContext);
}

int LiGetPendingAudioDurationCtx(PML_AUDIO_STREAM_CONTEXT ctx) {
    return LiGetPendingAudioFramesCtx(ctx) * AudioPacketDuration;
}

int LiGetPendingAudioDuration(void) {
    PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
    return LiGetPendingAudioDurationCtx(&ctx->audioContext);
}
