//
//  DebugVideoProbeExpectations.swift
//  Moonlight for macOS
//
//  A Debug-only bridge for the render probe: what the video and app pages are
//  supposed to show on this machine, right now, as the production code answers
//  it. Nothing here decides policy -- it forwards the same rules the panes read.
//
//  Compiled out of Release entirely (`#if DEBUG`), and only ever called from the
//  Debug render probe entry point, so a shipped binary carries neither this
//  code nor any behaviour attached to it.
//

import Foundation

#if DEBUG
@objc(MLDebugProbeExpectations)
final class DebugProbeExpectations: NSObject {
  /// Capability ids whose availability drives a control on the video page.
  private static let enhancementIDs = [
    "enhancement.vtLowLatencyFI",
    "enhancement.vtLowLatencySR",
    "enhancement.metalfx",
    "enhancement.vtQualitySR",
  ]

  /// `modelObject` is the model the page being measured is rendering from, passed
  /// as `AnyObject` so the Objective-C probe can hand it over. A fresh model is the
  /// fallback, and it is reported rather than hidden: a checker that quietly
  /// switched sources would certify a page it was not looking at.
  @objc(currentForModel:) static func current(for modelObject: AnyObject?) -> [String: Any] {
    let model = (modelObject as? SettingsModel) ?? SettingsModel()
    let localize = LanguageManager.shared.localize

    var capabilityRows: [[String: String]] = []
    for item in model.videoCapabilityMatrix.items {
      var row: [String: String] = [
        "id": item.id,
        "availability": localize(item.availability.localizationKey),
        "title": localize(item.titleKey),
      ]
      if let detailKey = item.detailKey {
        row["detail"] = localize(detailKey)
      }
      capabilityRows.append(row)
    }

    // Every string the video page is expected to display for the current state.
    // The probe asserts these are on screen, which ties the sentence to the
    // gate: renaming a key updates the expectation, dropping the row does not.
    let videoStrings: [String] = [
      localize(model.frameInterpolationExplanationKey),
      localize(model.upscalingExplanationKey),
      localize("Video Runtime Path Label"),
      localize(model.videoRuntimeStatusSummaryKey),
      localize(model.videoRuntimeStatusDetailKey),
      localize("Upscaling Engine Label"),
      localize(model.videoEnhancementRuntimeStatusSummaryKey),
      localize(model.videoEnhancementRuntimeStatusDetailKey),
      localize("Frame Interpolation Engine Label"),
      localize(model.videoFrameInterpolationRuntimeStatusSummaryKey),
      localize(model.videoFrameInterpolationRuntimeStatusDetailKey),
    ]

    return [
      "expectationsFromPageModel": modelObject is SettingsModel,
      "rendererMode": SettingsModel.normalizedVideoRendererMode(model.selectedVideoRendererMode),
      "rendererModeAsStored": model.selectedVideoRendererMode,
      "upscalingModeAsDisplayedByRules": model.selectedUpscalingMode,
      "frameInterpolationModeAsDisplayedByRules": model.selectedFrameInterpolationMode,
      "frameInterpolationCapable": model.frameInterpolationIsCapable,
      "expectedFrameInterpolationEnabled": model.frameInterpolationControlIsEnabled,
      "expectedUpscalingEnabled": model.upscalingControlIsEnabled,
      "videoStrings": videoStrings,
      // Which row a control belongs to is decided by the label beside it, so the
      // checker needs the titles the page itself would show, not copies of them.
      "controlTitles": [
        "frameInterpolation": localize("Frame Interpolation"),
        "upscaling": localize("Upscaling"),
      ],
      // The Advanced section holds the capability matrix and ships collapsed, and a
      // collapsed SwiftUI group vends nothing inside it. The probe has to open it to
      // read it, and the only honest way to tell "open" from "closed" is the wording
      // the page itself puts beside the triangle, so that wording is handed over
      // rather than duplicated: renaming it moves the checker along with it.
      "advancedSectionCollapsedLabel": localize("Collapsed"),
      "advancedSectionExpandedLabel": localize("Expanded"),
      "capabilityRows": capabilityRows,
      "enhancementAvailability": Dictionary(
        uniqueKeysWithValues: model.videoCapabilityMatrix.items
          .filter { Self.enhancementIDs.contains($0.id) }
          .map { ($0.id, localize($0.availability.localizationKey)) }
      ),
    ]
  }
}
#endif
