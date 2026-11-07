#include "Limelight-internal.h"
#include "PlatformSockets.h"

// Macros to redirect global access to context
#ifdef RemoteAddr
#undef RemoteAddr
#endif
#ifdef LocalAddr
#undef LocalAddr
#endif
#ifdef AddrLen
#undef AddrLen
#endif
#ifdef MicPortNumber
#undef MicPortNumber
#endif

#define RemoteAddr (ctx->connectionContext->RemoteAddr)
#define LocalAddr (ctx->connectionContext->LocalAddr)
#define AddrLen (ctx->connectionContext->AddrLen)
#define MicPortNumber (ctx->connectionContext->MicPortNumber)

#define MIC_IV_LEN 16
#define MIC_HEADER_FLAGS 0x00

typedef struct _MICROPHONE_PACKET_HEADER {
  uint8_t flags;
  uint8_t packetType;
  uint16_t sequenceNumber;
  uint32_t timestamp;
  uint32_t ssrc;
} MICROPHONE_PACKET_HEADER, *PMICROPHONE_PACKET_HEADER;

// 初始化麦克风流
int initializeMicrophoneStreamCtx(PML_MICROPHONE_STREAM_CONTEXT ctx, PML_CONNECTION_CONTEXT connectionContext) {
  if (ctx == NULL || connectionContext == NULL) {
    return -1;
  }

  ctx->connectionContext = connectionContext;
  ctx->micSocket = INVALID_SOCKET;
  ctx->micEncryptionCtx = NULL;
  ctx->micRiKeyId = 0;
  ctx->micSequenceNumber = 0;
  ctx->micAddrValid = false;
  ctx->micAddrLen = 0;
  ctx->micPortNumber = 0;

  ctx->micEncryptionCtx = PltCreateCryptoContext();
  if (ctx->micEncryptionCtx == NULL) {
    return -1;
  }

  // 创建UDP socket
  ctx->micSocket = bindUdpSocket(RemoteAddr.ss_family, &LocalAddr, AddrLen, 0,
                            SOCK_QOS_TYPE_AUDIO);
  if (ctx->micSocket == INVALID_SOCKET) {
    PltDestroyCryptoContext(ctx->micEncryptionCtx);
    ctx->micEncryptionCtx = NULL;
    return LastSocketFail();
  }

  memcpy(&ctx->micRiKeyId, StreamConfig.remoteInputAesIv, sizeof(ctx->micRiKeyId));
  ctx->micRiKeyId = BE32(ctx->micRiKeyId);
  ctx->micSequenceNumber = 0;

  // Cache address details for mic sends to avoid dereferencing connectionContext later
  if (AddrLen > 0 && AddrLen <= sizeof(ctx->micRemoteAddr) && RemoteAddr.ss_family != AF_UNSPEC) {
    memcpy(&ctx->micRemoteAddr, &RemoteAddr, sizeof(ctx->micRemoteAddr));
    ctx->micAddrLen = AddrLen;
    ctx->micPortNumber = MicPortNumber;
    ctx->micAddrValid = true;
  }

  return 0;
}

int initializeMicrophoneStream(void) {
  PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
  return initializeMicrophoneStreamCtx(&ctx->micContext, ctx);
}

// 关闭麦克风流
void destroyMicrophoneStreamCtx(PML_MICROPHONE_STREAM_CONTEXT ctx) {
  if (ctx == NULL) {
    return;
  }
  if (ctx->micSocket != INVALID_SOCKET) {
    closeSocket(ctx->micSocket);
    ctx->micSocket = INVALID_SOCKET;
  }

  if (ctx->micEncryptionCtx != NULL) {
    PltDestroyCryptoContext(ctx->micEncryptionCtx);
    ctx->micEncryptionCtx = NULL;
  }

  ctx->micRiKeyId = 0;
  ctx->micSequenceNumber = 0;

  ctx->micAddrValid = false;
  ctx->micAddrLen = 0;
  ctx->micPortNumber = 0;
  memset(&ctx->micRemoteAddr, 0, sizeof(ctx->micRemoteAddr));
  ctx->connectionContext = NULL;
}

void destroyMicrophoneStream(void) {
  PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
  destroyMicrophoneStreamCtx(&ctx->micContext);
}

// 发送麦克风数据
int sendMicrophoneDataCtx(PML_MICROPHONE_STREAM_CONTEXT ctx, const char* data, int length) {
  LC_SOCKADDR saddr;
  ssize_t err;

  if (ctx == NULL || ctx->connectionContext == NULL) {
    return -1;
  }

  if (!ctx->micAddrValid || ctx->micAddrLen == 0 || ctx->micAddrLen > sizeof(saddr)) {
    return -1;
  }

  if (((struct sockaddr *)&ctx->micRemoteAddr)->sa_family == AF_UNSPEC) {
    return -1;
  }

  if (ctx->micSocket == INVALID_SOCKET) {
    return -1;
  }

  memset(&saddr, 0, sizeof(saddr));
  memcpy(&saddr, &ctx->micRemoteAddr, sizeof(saddr));
  SET_PORT(&saddr, ctx->micPortNumber);

  err = sendto(ctx->micSocket, data, length, 0, (struct sockaddr *)&saddr, ctx->micAddrLen);
  if (err < 0) {
    return (int)LastSocketError();
  }

  return (int)err;
}

int sendMicrophoneData(const char* data, int length) {
  PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
  return sendMicrophoneDataCtx(&ctx->micContext, data, length);
}

int sendMicrophoneOpusDataCtx(PML_MICROPHONE_STREAM_CONTEXT ctx, const unsigned char* opusData, int opusLength) {
  LC_SOCKADDR saddr;
  MICROPHONE_PACKET_HEADER header;
  unsigned char packet[MAX_MIC_PACKET_SIZE];
  int packetLength = 0;
  ssize_t err;

  if (ctx == NULL || ctx->connectionContext == NULL || opusData == NULL || opusLength <= 0) {
    return -1;
  }

  if (!ctx->micAddrValid || ctx->micAddrLen == 0 || ctx->micAddrLen > sizeof(saddr)) {
    return -1;
  }

  if (((struct sockaddr *)&ctx->micRemoteAddr)->sa_family == AF_UNSPEC ||
      ctx->micSocket == INVALID_SOCKET) {
    return -1;
  }

  if (opusLength > MAX_MIC_PACKET_SIZE - (int)sizeof(header)) {
    Limelog("MIC: Input data too large (%d)\n", opusLength);
    return -1;
  }

  memset(&header, 0, sizeof(header));
  header.flags = MIC_HEADER_FLAGS;
  header.packetType = MIC_PACKET_TYPE_OPUS;
  header.sequenceNumber = LE16(ctx->micSequenceNumber);
  header.timestamp = LE32((uint32_t)PltGetMillis());
  header.ssrc = LE32(MIC_PACKET_MAGIC);

  if ((EncryptionFeaturesEnabled & SS_ENC_MICROPHONE) && ctx->micEncryptionCtx != NULL) {
    unsigned char iv[MIC_IV_LEN] = {0};
    unsigned char encryptedData[ROUND_TO_PKCS7_PADDED_LEN(MAX_MIC_PACKET_SIZE)];
    int encryptedLength = (int)sizeof(encryptedData);
    uint32_t ivSeq = BE32(ctx->micRiKeyId + ctx->micSequenceNumber);

    memcpy(iv, &ivSeq, sizeof(ivSeq));

    if (!PltEncryptMessage(ctx->micEncryptionCtx,
                           ALGORITHM_AES_CBC,
                           CIPHER_FLAG_RESET_IV | CIPHER_FLAG_FINISH | CIPHER_FLAG_PAD_TO_BLOCK_SIZE,
                           (unsigned char*)StreamConfig.remoteInputAesKey,
                           sizeof(StreamConfig.remoteInputAesKey),
                           iv,
                           sizeof(iv),
                           NULL,
                           0,
                           (unsigned char*)opusData,
                           opusLength,
                           encryptedData,
                           &encryptedLength)) {
      Limelog("MIC: Encryption failed\n");
      return -1;
    }

    if (encryptedLength < 0 || encryptedLength > (int)sizeof(encryptedData)) {
      Limelog("MIC: Invalid encrypted length (%d)\n", encryptedLength);
      return -1;
    }

    packetLength = (int)sizeof(header) + encryptedLength;
    if (packetLength > MAX_MIC_PACKET_SIZE || packetLength > (int)sizeof(packet)) {
      Limelog("MIC: Encrypted packet too large (%d > %d)\n", packetLength, MAX_MIC_PACKET_SIZE);
      return -1;
    }

    memcpy(packet, &header, sizeof(header));
    memcpy(packet + sizeof(header), encryptedData, encryptedLength);
  }
  else {
    packetLength = (int)sizeof(header) + opusLength;
    if (packetLength > MAX_MIC_PACKET_SIZE || packetLength > (int)sizeof(packet)) {
      Limelog("MIC: Packet too large (%d > %d)\n", packetLength, MAX_MIC_PACKET_SIZE);
      return -1;
    }

    memcpy(packet, &header, sizeof(header));
    memcpy(packet + sizeof(header), opusData, opusLength);
  }

  ++ctx->micSequenceNumber;

  memset(&saddr, 0, sizeof(saddr));
  memcpy(&saddr, &ctx->micRemoteAddr, sizeof(saddr));
  SET_PORT(&saddr, ctx->micPortNumber);

  err = sendto(ctx->micSocket, (const char*)packet, packetLength, 0,
               (struct sockaddr*)&saddr, ctx->micAddrLen);
  if (err < 0) {
    return (int)LastSocketError();
  }

  return (int)err;
}

int sendMicrophoneOpusData(const unsigned char* opusData, int opusLength) {
  PML_CONNECTION_CONTEXT ctx = LiGetEffectiveConnectionContext();
  return sendMicrophoneOpusDataCtx(&ctx->micContext, opusData, opusLength);
}

bool isMicrophoneEncryptionEnabled(void) {
  return (EncryptionFeaturesEnabled & SS_ENC_MICROPHONE) != 0;
}
