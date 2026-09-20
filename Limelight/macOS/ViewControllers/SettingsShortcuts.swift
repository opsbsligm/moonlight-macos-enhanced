//
//  SettingsShortcuts.swift
//  Moonlight for macOS
//
//  Created by Michael Kenny on 16/1/2024.
//  Copyright © 2024 Moonlight Game Streaming Project. All rights reserved.
//
import AppKit
import Carbon.HIToolbox
import CoreGraphics
import SwiftUI


@objcMembers
final class StreamShortcut: NSObject, Codable {
  static let noKeyCode = -1

  let keyCode: Int
  let modifierFlagsRaw: UInt
  let modifierOnly: Bool

  init(keyCode: Int = StreamShortcut.noKeyCode, modifierFlags: NSEvent.ModifierFlags, modifierOnly: Bool = false) {
    self.keyCode = keyCode
    self.modifierFlagsRaw = StreamShortcutProfile.relevantModifierFlags(modifierFlags).rawValue
    self.modifierOnly = modifierOnly
    super.init()
  }

  var modifierFlags: NSEvent.ModifierFlags {
    NSEvent.ModifierFlags(rawValue: modifierFlagsRaw)
  }

  var hasKeyCode: Bool {
    keyCode != StreamShortcut.noKeyCode
  }

  override func isEqual(_ object: Any?) -> Bool {
    guard let other = object as? StreamShortcut else { return false }
    return keyCode == other.keyCode
      && modifierFlagsRaw == other.modifierFlagsRaw
      && modifierOnly == other.modifierOnly
  }

  override var hash: Int {
    var hasher = Hasher()
    hasher.combine(keyCode)
    hasher.combine(modifierFlagsRaw)
    hasher.combine(modifierOnly)
    return hasher.finalize()
  }
}

@objcMembers
final class StreamShortcutProfile: NSObject {
  static let releaseMouseCaptureAction = "releaseMouseCapture"
  static let togglePerformanceOverlayAction = "togglePerformanceOverlay"
  static let toggleMouseModeAction = "toggleMouseMode"
  static let toggleFullscreenControlBallAction = "toggleFullscreenControlBall"
  static let showDisconnectOptionsAction = "showDisconnectOptions"
  static let disconnectStreamAction = "disconnectStream"
  static let closeAndQuitAppAction = "closeAndQuitApp"
  static let reconnectStreamAction = "reconnectStream"
  static let openControlCenterAction = "openControlCenter"
  static let toggleBorderlessWindowedAction = "toggleBorderlessWindowed"

  private static let orderedActions = [
    releaseMouseCaptureAction,
    togglePerformanceOverlayAction,
    toggleMouseModeAction,
    toggleFullscreenControlBallAction,
    showDisconnectOptionsAction,
    disconnectStreamAction,
    closeAndQuitAppAction,
    reconnectStreamAction,
    openControlCenterAction,
    toggleBorderlessWindowedAction,
  ]

  private static let supportedKeySymbols: [Int: String] = [
    kVK_ANSI_A: "A",
    kVK_ANSI_B: "B",
    kVK_ANSI_C: "C",
    kVK_ANSI_D: "D",
    kVK_ANSI_E: "E",
    kVK_ANSI_F: "F",
    kVK_ANSI_G: "G",
    kVK_ANSI_H: "H",
    kVK_ANSI_I: "I",
    kVK_ANSI_J: "J",
    kVK_ANSI_K: "K",
    kVK_ANSI_L: "L",
    kVK_ANSI_M: "M",
    kVK_ANSI_N: "N",
    kVK_ANSI_O: "O",
    kVK_ANSI_P: "P",
    kVK_ANSI_Q: "Q",
    kVK_ANSI_R: "R",
    kVK_ANSI_S: "S",
    kVK_ANSI_T: "T",
    kVK_ANSI_U: "U",
    kVK_ANSI_V: "V",
    kVK_ANSI_W: "W",
    kVK_ANSI_X: "X",
    kVK_ANSI_Y: "Y",
    kVK_ANSI_Z: "Z",
    kVK_ANSI_0: "0",
    kVK_ANSI_1: "1",
    kVK_ANSI_2: "2",
    kVK_ANSI_3: "3",
    kVK_ANSI_4: "4",
    kVK_ANSI_5: "5",
    kVK_ANSI_6: "6",
    kVK_ANSI_7: "7",
    kVK_ANSI_8: "8",
    kVK_ANSI_9: "9",
    kVK_ANSI_Minus: "-",
    kVK_ANSI_Equal: "=",
    kVK_ANSI_LeftBracket: "[",
    kVK_ANSI_RightBracket: "]",
    kVK_ANSI_Backslash: "\\",
    kVK_ANSI_Semicolon: ";",
    kVK_ANSI_Quote: "'",
    kVK_ANSI_Comma: ",",
    kVK_ANSI_Period: ".",
    kVK_ANSI_Slash: "/",
    kVK_ANSI_Grave: "`",
    kVK_Space: "Space",
    kVK_Tab: "Tab",
    kVK_Return: "Return",
    kVK_Delete: "Delete",
    kVK_ForwardDelete: "Forward Delete",
    kVK_Escape: "Esc",
    kVK_Home: "Home",
    kVK_End: "End",
    kVK_PageUp: "Page Up",
    kVK_PageDown: "Page Down",
    kVK_LeftArrow: "←",
    kVK_RightArrow: "→",
    kVK_UpArrow: "↑",
    kVK_DownArrow: "↓",
    kVK_F1: "F1",
    kVK_F2: "F2",
    kVK_F3: "F3",
    kVK_F4: "F4",
    kVK_F5: "F5",
    kVK_F6: "F6",
    kVK_F7: "F7",
    kVK_F8: "F8",
    kVK_F9: "F9",
    kVK_F10: "F10",
    kVK_F11: "F11",
    kVK_F12: "F12",
    kVK_F13: "F13",
    kVK_F14: "F14",
    kVK_F15: "F15",
    kVK_F16: "F16",
    kVK_F17: "F17",
    kVK_F18: "F18",
    kVK_F19: "F19",
    kVK_F20: "F20",
  ]

  private static let modifierDisplayOrder: [(NSEvent.ModifierFlags, String)] = [
    (.control, "⌃"),
    (.option, "⌥"),
    (.shift, "⇧"),
    (.command, "⌘"),
    (.function, "fn"),
  ]

  @objc static func relevantModifierFlags(_ flags: NSEvent.ModifierFlags) -> NSEvent.ModifierFlags {
    flags.intersection([.control, .option, .shift, .command, .function])
  }

  /// True only for a shortcut that cannot fire unless a modifier is held.
  ///
  /// Every consumer of a matched shortcut takes the key away from the game: the
  /// responder gate returns YES, a translation rule swallows the press, and an
  /// NSMenuItem key equivalent is claimed before the stream view ever sees the
  /// event. A shortcut bound to a bare key therefore deletes a movement or action
  /// key from the host, which is the "W and Space collide" report. The settings
  /// form rejects such a shortcut, but the streaming path cannot depend on that:
  /// shortcuts and translation rules are decoded from per-host stored data, and
  /// normalization repairs identity, not validity.
  @objc static func shortcutCanMatchKeyboardEvent(_ shortcut: StreamShortcut?) -> Bool {
    guard let shortcut, !shortcut.modifierOnly, shortcut.hasKeyCode else { return false }
    return modifierCount(relevantModifierFlags(shortcut.modifierFlags)) >= 1
  }

  /// True when Shift is the only thing holding this shortcut down.
  ///
  /// Shift is not a free modifier in a game: it is sprint, aim, crouch-walk and
  /// the jump variant, and a player holds it while pressing the movement cluster.
  /// A translation rule triggered by Shift+W therefore fires during ordinary
  /// play, and a matched rule consumes the press -- so the host never learns the
  /// player started running forward, and the release that does reach it reads as
  /// a key letting go on its own. The report this produced was "W and Space
  /// collide when I play": the binding looked harmless in the form and the game
  /// lost the keys at runtime.
  ///
  /// Control, Option and Command are excluded because no game reads them as an
  /// action of its own, so a rule behind one of them cannot be reached by playing.
  /// Function alone is left alone as well: a bare F-key binding carries its own
  /// risk, but a player chooses it knowingly and nothing has reported it.
  @objc static func shortcutUsesGameplayOnlyModifiers(_ shortcut: StreamShortcut?) -> Bool {
    guard let shortcut, !shortcut.modifierOnly, shortcut.hasKeyCode else { return false }
    let flags = relevantModifierFlags(shortcut.modifierFlags)
    let outsideGames: NSEvent.ModifierFlags = [.control, .option, .command]
    if !flags.intersection(outsideGames).isEmpty {
      return false
    }
    return flags.contains(.shift)
  }

  @objc static func actionOrder() -> [String] {
    orderedActions
  }

  @objc static func defaultShortcuts() -> [String: StreamShortcut] {
    [
      releaseMouseCaptureAction: StreamShortcut(modifierFlags: [.control, .option], modifierOnly: true),
      togglePerformanceOverlayAction: StreamShortcut(keyCode: kVK_ANSI_S, modifierFlags: [.control, .option]),
      toggleMouseModeAction: StreamShortcut(keyCode: kVK_ANSI_M, modifierFlags: [.control, .option]),
      toggleFullscreenControlBallAction: StreamShortcut(keyCode: kVK_ANSI_G, modifierFlags: [.control, .option]),
      showDisconnectOptionsAction: StreamShortcut(keyCode: kVK_ANSI_W, modifierFlags: [.command]),
      disconnectStreamAction: StreamShortcut(keyCode: kVK_ANSI_W, modifierFlags: [.control, .option]),
      closeAndQuitAppAction: StreamShortcut(keyCode: kVK_ANSI_W, modifierFlags: [.control, .shift]),
      reconnectStreamAction: StreamShortcut(keyCode: kVK_ANSI_R, modifierFlags: [.control, .option]),
      openControlCenterAction: StreamShortcut(keyCode: kVK_ANSI_C, modifierFlags: [.control, .option]),
      toggleBorderlessWindowedAction: StreamShortcut(keyCode: kVK_ANSI_B, modifierFlags: [.control, .option, .command]),
    ]
  }

  static func migratedShortcuts(_ shortcuts: [String: StreamShortcut]?) -> ([String: StreamShortcut], Bool) {
    var normalized = normalizedShortcuts(shortcuts)
    guard let shortcuts else { return (normalized, false) }

    var didMigrate = false

    if shortcuts[showDisconnectOptionsAction] == nil {
      normalized[showDisconnectOptionsAction] = defaultShortcut(for: showDisconnectOptionsAction)
      didMigrate = true

      if let disconnectShortcut = shortcuts[disconnectStreamAction],
        disconnectShortcut.isEqual(StreamShortcut(keyCode: kVK_ANSI_W, modifierFlags: [.command]))
      {
        normalized[disconnectStreamAction] = defaultShortcut(for: disconnectStreamAction)
      }
    }

    if shortcuts[reconnectStreamAction] == nil {
      normalized[reconnectStreamAction] = defaultShortcut(for: reconnectStreamAction)
      didMigrate = true
    }

    return (normalized, didMigrate)
  }

  @objc static func defaultShortcut(for action: String) -> StreamShortcut {
    if let shortcut = defaultShortcuts()[action] {
      return StreamShortcut(
        keyCode: shortcut.keyCode,
        modifierFlags: shortcut.modifierFlags,
        modifierOnly: shortcut.modifierOnly)
    }

    return StreamShortcut(modifierFlags: [.control, .option], modifierOnly: true)
  }

  @objc static func normalizedShortcuts(_ shortcuts: [String: StreamShortcut]?) -> [String: StreamShortcut] {
    var merged = defaultShortcuts()
    guard let shortcuts else { return merged }

    for action in orderedActions {
      guard let shortcut = shortcuts[action] else { continue }
      merged[action] = StreamShortcut(
        keyCode: shortcut.keyCode,
        modifierFlags: shortcut.modifierFlags,
        modifierOnly: shortcut.modifierOnly)
    }

    return merged
  }

  @objc static func displayTokens(for shortcut: StreamShortcut) -> [String] {
    var tokens = modifierDisplayOrder.compactMap { shortcut.modifierFlags.contains($0.0) ? $0.1 : nil }

    if !shortcut.modifierOnly, let key = keySymbol(for: shortcut.keyCode) {
      tokens.append(key)
    }

    return tokens
  }

  @objc static func menuKeyEquivalent(for shortcut: StreamShortcut) -> String {
    // A bare key here becomes an NSMenuItem key equivalent with an empty modifier
    // mask, and AppKit hands that key to the menu before the stream view sees it:
    // the game loses the key without the app ever logging a suppression.
    guard StreamShortcutProfile.shortcutCanMatchKeyboardEvent(shortcut),
          let key = keySymbol(for: shortcut.keyCode) else {
      return ""
    }

    // The table above exists to tell a person which key they bound, and for most of
    // them the name is the key. For the rest it is a word: `Space`, `Tab`, `Return`,
    // `Esc`, `Page Up`, an arrow glyph. Handing that word to AppKit does not make the
    // first letter a shortcut -- measured against a live NSMenu, a menu item whose key
    // equivalent is "space" matches neither Control+Option+S nor Control+Option+Space,
    // so the item shows a hint nobody can press, and the binding works only while the
    // stream view itself is receiving keys. One scalar inside ASCII is the line between
    // a character AppKit can compare and a label it cannot.
    guard key.utf16.count == 1,
          let scalar = key.unicodeScalars.first,
          scalar.value >= 0x20, scalar.value < 0x7F else {
      return ""
    }

    return key.lowercased()
  }

  @objc static func menuModifierMask(for shortcut: StreamShortcut) -> UInt {
    guard !shortcut.modifierOnly else { return 0 }
    return shortcut.modifierFlags.rawValue
  }

  @objc static func isModifierOnlyAction(_ action: String) -> Bool {
    action == releaseMouseCaptureAction
  }

  @objc static func validationErrorKey(
    for candidate: StreamShortcut,
    action: String,
    shortcuts: [String: StreamShortcut],
    keyboardTranslationRules: [KeyboardTranslationRule]
  ) -> String? {
    let modifiers = relevantModifierFlags(candidate.modifierFlags)

    if isModifierOnlyAction(action) {
      if !candidate.modifierOnly || candidate.hasKeyCode {
        return "Shortcut modifiers only required"
      }
      if modifierCount(modifiers) < 2 {
        return "Shortcut requires two modifiers"
      }
    } else {
      if candidate.modifierOnly || !candidate.hasKeyCode {
        return "Shortcut must include regular key"
      }
      let minimumModifierCount = allowsSingleModifierShortcut(for: action) ? 1 : 2
      if modifierCount(modifiers) < minimumModifierCount {
        return minimumModifierCount == 1 ? "Shortcut requires modifier" : "Shortcut requires two modifiers"
      }
      if keySymbol(for: candidate.keyCode) == nil {
        return "Shortcut key unsupported"
      }
    }

    if isReserved(candidate, action: action) {
      return "Shortcut reserved by system"
    }

    let normalized = normalizedShortcuts(shortcuts)
    for (otherAction, otherShortcut) in normalized where otherAction != action {
      if otherShortcut.isEqual(candidate) {
        return "Shortcut already in use"
      }
    }

    for rule in KeyboardTranslationProfile.normalizedRules(keyboardTranslationRules) {
      if rule.trigger.isEqual(candidate) {
        return "Shortcut already in use"
      }
    }

    return nil
  }

  static func modifierCount(_ flags: NSEvent.ModifierFlags) -> Int {
    modifierDisplayOrder.reduce(into: 0) { count, item in
      if flags.contains(item.0) {
        count += 1
      }
    }
  }

  private static func allowsSingleModifierShortcut(for action: String) -> Bool {
    action == showDisconnectOptionsAction || action == closeAndQuitAppAction
  }

  private static func isReserved(_ shortcut: StreamShortcut, action: String) -> Bool {
    let modifiers = relevantModifierFlags(shortcut.modifierFlags)
    let keyCode = shortcut.keyCode

    if shortcut.modifierOnly {
      return false
    }

    if keyCode == kVK_ANSI_W && modifiers == [.command] {
      return action != showDisconnectOptionsAction
    }

    return (keyCode == kVK_ANSI_F && modifiers == [.control, .command])
      || (keyCode == kVK_ANSI_F && modifiers == [.function])
      || (keyCode == kVK_ANSI_1 && modifiers == [.command])
      || (keyCode == kVK_ANSI_H && modifiers == [.command])
      || (keyCode == kVK_ANSI_Grave && modifiers == [.command])
  }

  @objc static func keySymbol(for keyCode: Int) -> String? {
    supportedKeySymbols[keyCode]
  }

  @objc static func remoteDisplayTokens(for shortcut: StreamShortcut,
                                        commandSendsControl: Bool = false) -> [String] {
    var tokens: [String] = []
    let modifiers = relevantModifierFlags(shortcut.modifierFlags)
    let controlHeld = modifiers.contains(.control)

    if controlHeld {
      tokens.append("Ctrl")
    }
    if modifiers.contains(.option) {
      tokens.append("Alt")
    }
    if modifiers.contains(.shift) {
      tokens.append("Shift")
    }
    if modifiers.contains(.command) {
      // These tokens name what the host receives, so they owe the player the same answer the
      // keyboard gives: a rule bound with Command arrives as Control once that switch is on,
      // and a card still reading "Win" would name a key the host never gets. Control and
      // Command are one bit to the host under that switch -- the same one bit the keyboard
      // path sends -- so one token is the honest count rather than two.
      if commandSendsControl {
        if !controlHeld {
          tokens.insert("Ctrl", at: 0)
        }
      } else {
        tokens.append("Win")
      }
    }
    if modifiers.contains(.function) {
      tokens.append("Fn")
    }

    if !shortcut.modifierOnly, let key = keySymbol(for: shortcut.keyCode) {
      tokens.append(key)
    }

    return tokens
  }
}

@objc enum KeyboardTranslationOutputKind: Int, CaseIterable {
  case remoteShortcut = 0
  case localAction = 1

  var displayKey: String {
    switch self {
    case .remoteShortcut:
      return "Remote Shortcut"
    case .localAction:
      return "Moonlight Action"
    }
  }
}

@objcMembers
final class KeyboardTranslationRule: NSObject, Codable, Identifiable {
  let id: String
  let trigger: StreamShortcut
  let outputKindRaw: Int
  let outputShortcut: StreamShortcut?
  let localAction: String?

  init(
    id: String = UUID().uuidString,
    trigger: StreamShortcut,
    outputShortcut: StreamShortcut
  ) {
    self.id = id
    self.trigger = StreamShortcut(
      keyCode: trigger.keyCode,
      modifierFlags: trigger.modifierFlags,
      modifierOnly: trigger.modifierOnly)
    self.outputKindRaw = KeyboardTranslationOutputKind.remoteShortcut.rawValue
    self.outputShortcut = StreamShortcut(
      keyCode: outputShortcut.keyCode,
      modifierFlags: outputShortcut.modifierFlags,
      modifierOnly: outputShortcut.modifierOnly)
    self.localAction = nil
    super.init()
  }

  init(
    id: String = UUID().uuidString,
    trigger: StreamShortcut,
    localAction: String
  ) {
    self.id = id
    self.trigger = StreamShortcut(
      keyCode: trigger.keyCode,
      modifierFlags: trigger.modifierFlags,
      modifierOnly: trigger.modifierOnly)
    self.outputKindRaw = KeyboardTranslationOutputKind.localAction.rawValue
    self.outputShortcut = nil
    self.localAction = localAction
    super.init()
  }

  var outputKind: KeyboardTranslationOutputKind {
    KeyboardTranslationOutputKind(rawValue: outputKindRaw) ?? .remoteShortcut
  }

  override func isEqual(_ object: Any?) -> Bool {
    guard let other = object as? KeyboardTranslationRule else { return false }
    let outputsEqual: Bool
    if let outputShortcut, let otherOutputShortcut = other.outputShortcut {
      outputsEqual = outputShortcut.isEqual(otherOutputShortcut)
    } else {
      outputsEqual = outputShortcut == nil && other.outputShortcut == nil
    }

    return id == other.id
      && trigger.isEqual(other.trigger)
      && outputKindRaw == other.outputKindRaw
      && outputsEqual
      && localAction == other.localAction
  }

  override var hash: Int {
    var hasher = Hasher()
    hasher.combine(id)
    hasher.combine(trigger.hash)
    hasher.combine(outputKindRaw)
    hasher.combine(outputShortcut?.hash)
    hasher.combine(localAction)
    return hasher.finalize()
  }
}

@objcMembers
final class KeyboardTranslationProfile: NSObject {
  static let localActionReleaseMouseCapture = StreamShortcutProfile.releaseMouseCaptureAction
  static let localActionTogglePerformanceOverlay =
    StreamShortcutProfile.togglePerformanceOverlayAction
  static let localActionToggleMouseMode = StreamShortcutProfile.toggleMouseModeAction
  static let localActionToggleFullscreenControlBall =
    StreamShortcutProfile.toggleFullscreenControlBallAction
  static let localActionShowDisconnectOptions = StreamShortcutProfile.showDisconnectOptionsAction
  static let localActionDisconnectStream = StreamShortcutProfile.disconnectStreamAction
  static let localActionCloseAndQuitApp = StreamShortcutProfile.closeAndQuitAppAction
  static let localActionReconnectStream = StreamShortcutProfile.reconnectStreamAction
  static let localActionOpenControlCenter = StreamShortcutProfile.openControlCenterAction
  static let localActionToggleBorderlessWindowed =
    StreamShortcutProfile.toggleBorderlessWindowedAction

  private static let orderedLocalActions = [
    localActionShowDisconnectOptions,
    localActionDisconnectStream,
    localActionCloseAndQuitApp,
    localActionReconnectStream,
    localActionOpenControlCenter,
    localActionReleaseMouseCapture,
    localActionToggleMouseMode,
    localActionTogglePerformanceOverlay,
    localActionToggleFullscreenControlBall,
    localActionToggleBorderlessWindowed,
  ]

  @objc static func defaultRules() -> [KeyboardTranslationRule] {
    []
  }

  /// The secure attention sequence, offered as a prefilled rule rather than as a new
  /// mechanism. macOS does not swallow Ctrl+Alt+Forward Delete the way Windows swallows the
  /// real thing, so the ordinary translation path already delivers it -- what a player lacked
  /// was a way to find out. Control and Option with Forward Delete is the one chord no local
  /// action claims (see StreamShortcutProfile.defaultShortcuts), and the gate reads both
  /// sides of that sentence rather than trusting it.
  @objc static func secureAttentionSequencePresetRule() -> KeyboardTranslationRule {
    let chord = StreamShortcut(keyCode: kVK_ForwardDelete, modifierFlags: [.control, .option])
    return KeyboardTranslationRule(trigger: chord, outputShortcut: chord)
  }

  @objc static func normalizedRules(_ rules: [KeyboardTranslationRule]?) -> [KeyboardTranslationRule] {
    guard let rules else { return defaultRules() }

    var normalized: [KeyboardTranslationRule] = []
    var seenIds = Set<String>()

    for rule in rules {
      let ruleId = seenIds.contains(rule.id) ? UUID().uuidString : rule.id
      seenIds.insert(ruleId)

      switch rule.outputKind {
      case .remoteShortcut:
        guard let outputShortcut = rule.outputShortcut else { continue }
        normalized.append(
          KeyboardTranslationRule(
            id: ruleId,
            trigger: rule.trigger,
            outputShortcut: outputShortcut))
      case .localAction:
        guard let localAction = rule.localAction else { continue }
        normalized.append(
          KeyboardTranslationRule(
            id: ruleId,
            trigger: rule.trigger,
            localAction: localAction))
      }
    }

    return normalized
  }

  @objc static func outputKinds() -> [String] {
    KeyboardTranslationOutputKind.allCases.map(\.displayKey)
  }

  @objc static func localActionOrder() -> [String] {
    orderedLocalActions
  }

  @objc static func localActionTitleKey(for action: String) -> String {
    switch action {
    case localActionReleaseMouseCapture:
      return "Release mouse capture"
    case localActionTogglePerformanceOverlay:
      return "Toggle performance overlay"
    case localActionToggleMouseMode:
      return "Toggle mouse mode"
    case localActionToggleFullscreenControlBall:
      return "Toggle fullscreen control ball"
    case localActionShowDisconnectOptions:
      return "Show Disconnect Options"
    case localActionDisconnectStream:
      return "Disconnect from Stream"
    case localActionCloseAndQuitApp:
      return "Close and Quit App"
    case localActionReconnectStream:
      return "Reconnect Stream"
    case localActionOpenControlCenter:
      return "Open control center"
    case localActionToggleBorderlessWindowed:
      return "Toggle borderless / windowed (advanced)"
    default:
      return action
    }
  }

  @objc static func displayTokens(forTrigger shortcut: StreamShortcut) -> [String] {
    StreamShortcutProfile.displayTokens(for: shortcut)
  }

  @objc static func displayTokens(forRemoteOutput shortcut: StreamShortcut,
                                  commandSendsControl: Bool = false) -> [String] {
    StreamShortcutProfile.remoteDisplayTokens(for: shortcut,
                                              commandSendsControl: commandSendsControl)
  }

  @objc static func validationErrorKey(
    forTrigger shortcut: StreamShortcut,
    editingRuleId: String?,
    rules: [KeyboardTranslationRule],
    streamShortcuts: [String: StreamShortcut]
  ) -> String? {
    let modifiers = StreamShortcutProfile.relevantModifierFlags(shortcut.modifierFlags)

    if shortcut.modifierOnly || !shortcut.hasKeyCode {
      return "Shortcut must include regular key"
    }
    if StreamShortcutProfile.modifierCount(modifiers) < 1 {
      return "Shortcut requires modifier"
    }
    if StreamShortcutProfile.shortcutUsesGameplayOnlyModifiers(shortcut) {
      return "Shortcut reserved by gameplay keys"
    }
    if StreamShortcutProfile.keySymbol(for: shortcut.keyCode) == nil {
      return "Shortcut key unsupported"
    }

    for rule in normalizedRules(rules) where rule.id != editingRuleId {
      if rule.trigger.isEqual(shortcut) {
        return "Shortcut already in use"
      }
    }

    let normalizedShortcuts = StreamShortcutProfile.normalizedShortcuts(streamShortcuts)
    for (_, streamShortcut) in normalizedShortcuts {
      if streamShortcut.isEqual(shortcut) {
        return "Shortcut already in use"
      }
    }

    return nil
  }

  @objc static func validationErrorKey(forRemoteOutput shortcut: StreamShortcut) -> String? {
    if shortcut.modifierOnly || !shortcut.hasKeyCode {
      return "Shortcut must include regular key"
    }
    if StreamShortcutProfile.keySymbol(for: shortcut.keyCode) == nil {
      return "Shortcut key unsupported"
    }
    return nil
  }
}
