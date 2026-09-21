//
//  VideoFormatNegotiation.h
//  Moonlight
//

#ifndef VideoFormatNegotiation_h
#define VideoFormatNegotiation_h

#import "Limelight.h"

/*
 The set of video format bits a client advertises is the whole of what it can receive,
 and the server picks one bit out of it. Two of the inputs to that set are easy to
 conflate, because for as long as this client existed only one thing ever asked for
 10-bit samples:

   - the codec profile bits (H264/H265/AV1, 8 or 10 bit, 4:2:0 or 4:4:4) live in
     StreamConfiguration.supportedVideoFormats;
   - the dynamic range of the picture (SDR, HDR10 PQ, HLG) lives in
     StreamConfiguration.dynamicRangeMode, a separate field.

 Limelight.h draws the same line: VIDEO_FORMAT_MASK_10BIT is a profile mask, and the
 comment over dynamicRangeMode calls it the preferred dynamic range mode "for HDR-capable
 10-bit streams", which is a statement about the picture, not a consequence of the
 profile. Issue #22 asks for the combination this two-dimensional model allows and this
 client never offered: 10-bit samples carrying an SDR picture. The Qt client reaches it
 because its 10-bit checkbox and its HDR checkbox are two controls; here HDR was the only
 route to a 10-bit bit, so the combination could not be asked for at all.

 Keeping the answer in one place matters because the same combination has to be judged
 the same way by the code that negotiates and the code that renders. The renderer is told
 the dynamic range separately, so a 10-bit stream arriving under SDR has to be drawn with
 the BT.709 matrix rather than the BT.2020 one.
*/
typedef struct {
    // Decode support and the codec preference already combined: HEVC and AV1 are only
    // ever available together with the hardware that can take them.
    BOOL hevcAvailable;
    BOOL av1Available;

    // The three things a person can ask for. hdrRequested also selects the transfer
    // function elsewhere; the other two change the bits offered, never the picture.
    BOOL hdrRequested;
    BOOL sdrTenBitRequested;
    BOOL yuv444Requested;
} MLVideoFormatRequest;

/*
 10-bit samples, whether or not the picture is HDR. Named because three places in the
 negotiation need the same answer, and 10-bit quietly becoming HDR is exactly the
 mistake this makes visible: it is the shape that would hand an SDR stream to the
 BT.2020 path and produce the washed-out or oversaturated image issue #22 describes.
*/
static inline BOOL MLVideoFormatRequestWantsTenBit(MLVideoFormatRequest request) {
    return request.hdrRequested || request.sdrTenBitRequested;
}

/*
 One 4:2:0 bit is always offered, because every host takes H.264 and a client that
 advertises nothing cannot start. Everything else is a conditional add.
*/
static inline int MLResolveSupportedVideoFormats(MLVideoFormatRequest request) {
    const BOOL wantsTenBit = MLVideoFormatRequestWantsTenBit(request);
    int formats = VIDEO_FORMAT_H264;

    if (request.hevcAvailable) {
        formats |= VIDEO_FORMAT_H265;
        if (wantsTenBit) {
            formats |= VIDEO_FORMAT_H265_MAIN10;
        }
    }

    if (request.yuv444Requested) {
        formats |= VIDEO_FORMAT_H264_HIGH8_444;
        if (request.hevcAvailable) {
            formats |= VIDEO_FORMAT_H265_REXT8_444;
            if (wantsTenBit) {
                formats |= VIDEO_FORMAT_H265_REXT10_444;
            }
        }
    }

    if (request.av1Available) {
        // AV1 splits by sample depth instead of adding a second bit, so the 10-bit
        // request has to reach this branch too or it would be answered with 8-bit
        // samples and nothing would say so.
        formats |= wantsTenBit ? VIDEO_FORMAT_AV1_MAIN10 : VIDEO_FORMAT_AV1_MAIN8;
        if (request.yuv444Requested) {
            formats |= VIDEO_FORMAT_AV1_HIGH8_444;
            if (wantsTenBit) {
                formats |= VIDEO_FORMAT_AV1_HIGH10_444;
            }
        }
    }

    return formats;
}

/*
 HDR cannot be honoured without a 10-bit path, because PQ and HLG both define themselves
 over 10-bit samples: a client asking for HDR with neither HEVC nor AV1 available is
 asking for a picture that cannot be encoded. 10-bit SDR carries no such requirement. If
 the only codec available is 8-bit, the request simply is not expressible, and the
 function above already left the 10-bit bits off -- which is why this is not the same
 test as the one above it, and why the assert over the call site stays about HDR alone.
*/
static inline BOOL MLVideoFormatRequestIsSatisfiable(MLVideoFormatRequest request) {
    if (!request.hdrRequested) {
        return YES;
    }
    return request.hevcAvailable || request.av1Available;
}

#endif /* VideoFormatNegotiation_h */
