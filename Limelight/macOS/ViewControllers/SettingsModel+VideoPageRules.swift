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
}
