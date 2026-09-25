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

  /// The frame rate this display can actually interpolate at, and the refresh rate it was worked
  /// out from. While a stream runs the renderer's measured answer wins: it comes from the display
  /// link and it is the number the admission itself refused against. Before a stream there is
  /// nothing measured, so the display mode is asked, and the row says which of the two it heard,
  /// because a 179.82 Hz measured period and a 180 Hz mode name are not the same input to
  /// 1.5x arithmetic -- that difference is the whole reason 120 FPS can be recommended by a page
  /// and then refused by the stream.
  var frameInterpolationCadenceAdviceText: String? {
    // The raw value rather than the displayed title: a rename in the option list must not be
    // able to silence a warning by making the comparison stop matching.
    guard SettingsModel.frameInterpolationModeRawValue(for: selectedFrameInterpolationMode) != 0,
      frameInterpolationControlIsEnabled
    else {
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
