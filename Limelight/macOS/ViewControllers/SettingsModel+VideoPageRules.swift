//
//  SettingsModel+VideoPageRules.swift
//  Moonlight for macOS
//
//  Which video controls are live, and which sentence explains why they are not.
//
//  These answers used to be `private var`s inside `SettingsVideoPane`, which
//  meant the only way to check them was to look at the page. Looking at the page
//  was blocked, so "Video Toolbox interpolation is gated honestly on this Mac"
//  was an unreadable claim: the picker could stay enabled while the capability
//  said unavailable, or the sentence could say the opposite of the gate, and
//  nothing in the build or the gates would notice.
//
//  Moving the rule here costs the page nothing -- it reads the same answers --
//  and lets the Debug render probe assert that the page it is looking at agrees
//  with them. That coupling is the point: the rule lives in one place, so the
//  probe cannot certify a copy of itself, and a change to the gate changes the
//  expectation the rendered page is checked against.
//

import Foundation
import VideoToolbox

extension SettingsModel {
  /// The renderer mode as the rest of the app normalises it, without each caller
  /// having to remember to normalise first.
  var videoRendererModeIsMetal: Bool {
    SettingsModel.normalizedVideoRendererMode(selectedVideoRendererMode) == "Metal Renderer"
  }

  /// Whether Video Toolbox can really interpolate frames here. `isSupported` is
  /// not the question: measured on an Apple M2 it answers yes while every size
  /// reports zero interpolation slots, so the gate follows the measured slots.
  var frameInterpolationIsCapable: Bool {
    videoCapabilityMatrix.items.first(where: { $0.id == "enhancement.vtLowLatencyFI" })?
      .availability == .available
  }

  var frameInterpolationControlIsEnabled: Bool {
    videoRendererModeIsMetal && frameInterpolationIsCapable
  }

  var upscalingControlIsEnabled: Bool {
    videoRendererModeIsMetal
  }

  /// The explanation the page must show for frame interpolation. Three states,
  /// because two answers would be a lie on a Mac that has the API but not the
  /// slots, and on a Compatibility renderer the control is off for a different
  /// reason entirely.
  /// Which sentence the force switch carries. When the display already has cadence
  /// headroom the switch changes nothing, and the page says so; when it does not, the
  /// switch is the only way to run interpolation here, and the sentence names the cost.
  var frameInterpolationForceHintKey: String {
    let hostId = selectedHost?.id ?? Self.globalHostId
    let measuredRefresh = SettingsClass.videoCadenceMeasuredRefreshHz(for: hostId)
    let refreshHz = measuredRefresh > 0 ? measuredRefresh : StreamRiskAssessor.currentDisplayRefreshRateHz()
    let targetFps = effectiveFpsForBitrate()
    guard refreshHz > 0, targetFps > 0,
      !MLInterpolationHasCadenceHeadroom(refreshHz, Int32(targetFps))
    else {
      return "Force Frame Interpolation no conflict detail"
    }
    return "Force Frame Interpolation detail"
  }

  var frameInterpolationExplanationKey: String {
    if !videoRendererModeIsMetal {
      return "Frame Interpolation Metal only detail"
    }
    return frameInterpolationIsCapable
      ? "Frame Interpolation detail"
      : "Frame Interpolation unavailable detail"
  }

  var upscalingExplanationKey: String {
    videoRendererModeIsMetal ? "Upscaling detail" : "Upscaling Metal only detail"
  }

  /// Whether the two VideoToolbox super-resolution options can run at all. Both are macOS 26 API --
  /// the resolver asks them only inside `if (@available(macOS 26.0, *))` -- so on an older system the
  /// honest answer is that the option on screen cannot be honoured however the player resizes the
  /// window. The hint appears when it cannot, instead of being a paragraph nobody can act on.
  var videoToolboxSuperResolutionIsAvailable: Bool {
    ProcessInfo.processInfo.isOperatingSystemAtLeast(
      OperatingSystemVersion(majorVersion: 26, minorVersion: 0, patchVersion: 0))
  }

  /// Whether the VT low-latency scaler has a factor for the frame size this stream would send.
  /// `isSupported` is not the question, and neither is the OS version once the OS is new enough:
  /// measured on an Apple M2 (macOS 27.2), `supportedScaleFactorsForFrameWidth` answers empty for
  /// both 1920x1080 and 2560x1440 sources, so on this host the scaler can rebuild a 720p story
  /// and nothing else -- a player who picks the option with a 1080p stream will get the fallback
  /// however they resize the window, and the page has to say that before the stream starts
  /// rather than let the runtime line discover it. The probe below is the same question the
  /// capability matrix asks the configuration API; this one aims it at the resolution the
  /// player actually selected, which is the only shape the matrix's any-size answer cannot give.
  var vtLowLatencySuperResolutionIsUsableForSelectedSource: Bool {
    guard videoToolboxSuperResolutionIsAvailable else {
      return false
    }
    guard #available(macOS 26.0, *) else {
      return false
    }
    guard VTLowLatencySuperResolutionScalerConfiguration.isSupported else {
      return false
    }
    let source = effectiveResolutionForBitrate()
    guard source.width > 0, source.height > 0 else {
      return false
    }
    let factors = VTLowLatencySuperResolutionScalerConfiguration
      .__supportedScaleFactors(forFrameWidth: Int(source.width),
                               frameHeight: Int(source.height))
    return !factors.isEmpty
  }

  /// Which source shapes the VT scalers can work on, as the page states it before a stream.
  /// Three answers, because "your Mac is too old", "your stream size has no factors at all",
  /// and "the factors exist for smaller sources only" are three different things a player
  /// could act on -- resize the window forever for a refusal no resize can fix is the failure
  /// this row exists to prevent. Nil when there is nothing to warn about: the OS is new, and
  /// the selected source itself has factors, so the option on screen can be honoured.
  var superResolutionSourceHonestHintKey: String? {
    if !videoRendererModeIsMetal {
      return nil
    }
    if !videoToolboxSuperResolutionIsAvailable {
      return nil  // the macOS 26 hint row already carries that sentence
    }
    let requested = SettingsModel.upscalingModeRawValue(for: selectedUpscalingMode)
    // The two VT modes (3, 4) and Auto (6) are the requests this refusal can intercept;
    // MetalFX and Basic Scaling never touch the VT scaler lists, so a warning about them
    // would name a path the player did not choose.
    guard requested == 3 || requested == 4 || requested == 6 else {
      return nil
    }
    guard #available(macOS 26.0, *) else {
      return nil
    }
    let source = effectiveResolutionForBitrate()
    guard source.width > 0, source.height > 0 else {
      return nil
    }
    let factors = VTLowLatencySuperResolutionScalerConfiguration
      .__supportedScaleFactors(forFrameWidth: Int(source.width),
                               frameHeight: Int(source.height))
    if !factors.isEmpty {
      return nil
    }
    // The refusal can still be escapable: if any smaller offered resolution has factors, the
    // player can lower the stream resolution and the option becomes honoured rather than
    // overridden. When no offered size has factors at all, nothing the player picks changes
    // the answer, and the page says so plainly.
    let anyOfferedShapeWorks = SettingsModel.resolutions.contains { candidate in
      candidate == SettingsModel.matchDisplayResolutionSentinel
        ? false
        : !VTLowLatencySuperResolutionScalerConfiguration
            .__supportedScaleFactors(forFrameWidth: Int(candidate.width),
                                     frameHeight: Int(candidate.height)).isEmpty
    }
    return anyOfferedShapeWorks
      ? "Upscaling source has no factors hint"
      : "Upscaling no factors anywhere hint"
  }

  /// The frame rate this display can actually interpolate at, and the refresh rate it was worked
  /// out from. While a stream runs the renderer's measured answer wins: it comes from the display
  /// link and it is the number the admission itself refused against. Before a stream there is
  /// nothing measured, so the display mode is asked, and the row says which of the two it heard,
  /// because a 179.82 Hz measured period and a 180 Hz mode name are not the same input to the
  /// whole-multiple test -- the policy's tolerance exists so a 90 FPS stream on that panel is
  /// neither refused for a rounding error nor admitted on a cadence that would stutter.
  var frameInterpolationCadenceAdviceText: String? {
    // The raw value rather than the displayed title: a rename in the option list must not be
    // able to silence a warning by making the comparison stop matching.
    guard SettingsModel.frameInterpolationModeRawValue(for: selectedFrameInterpolationMode) != 0,
      frameInterpolationControlIsEnabled
    else {
      return nil
    }
    // While the switch forces admission, the advice to change refresh or frame rate
    // is optional rather than required, and the force row already carries the risk
    // sentence. Showing both would read as two answers to one question.
    if frameInterpolationForce {
      return nil
    }

    let hostId = selectedHost?.id ?? Self.globalHostId
    let measuredRefresh = SettingsClass.videoCadenceMeasuredRefreshHz(for: hostId)
    let refreshHz = measuredRefresh > 0 ? measuredRefresh : StreamRiskAssessor.currentDisplayRefreshRateHz()
    guard refreshHz > 0 else {
      return nil
    }

    let targetFps = effectiveFpsForBitrate()
    guard targetFps > 0, !MLInterpolationHasCadenceHeadroom(refreshHz, Int32(targetFps)) else {
      return nil
    }

    let languageManager = LanguageManager.shared
    let refresh = String(format: "%.2f", refreshHz)
    let suggested = Int(MLInterpolationSuggestedFpsForRefresh(refreshHz))
    guard suggested > 0 else {
      return String(
        format: languageManager.localize("Frame Interpolation Cadence No Headroom"), refresh)
    }
    return String(
      format: languageManager.localize("Frame Interpolation Cadence Advice"),
      refresh, String(targetFps), String(suggested)
    )
  }
}
