import Foundation

@objcMembers
final class MLLogCategoryDescriptor: NSObject {
  let domainKey: String
  let categoryKey: String
  // Keys, not sentences. Issue #30: these two fields held the text itself -- the name
  // written bilingually ("发现 / Discovery") and the badge Chinese-only ("发现") -- so the
  // log panel's category menu and its badges showed Chinese on an English system, and
  // there was nothing to translate, because no key ever reached a table.
  let nameKey: String
  let badgeKey: String

  init(domainKey: String, categoryKey: String, nameKey: String, badgeKey: String) {
    self.domainKey = domainKey
    self.categoryKey = categoryKey
    self.nameKey = nameKey
    self.badgeKey = badgeKey
  }

  var displayName: String { LanguageManager.shared.localize(nameKey) }

  var badgeText: String { LanguageManager.shared.localize(badgeKey) }

  // What the filter box matches against. The panel renders one language, so matching
  // only what is on screen means an English player cannot find a category by its
  // Chinese name and a Chinese player cannot find it by its English one. Every
  // localization is searchable, plus the ASCII keys the log lines themselves carry,
  // so the box answers the words a player happens to think in.
  var searchableText: String {
    var parts = [nameKey, badgeKey, domainKey, categoryKey]
    for code in ["en", "zh-Hans"] {
      for key in [nameKey, badgeKey] {
        if let value = LanguageManager.shared.localizedString(key, languageCode: code) {
          parts.append(value)
        }
      }
    }
    return parts.joined(separator: "\n")
  }

  var systemImageName: String {
    switch categoryKey {
    case "discovery":
      return "dot.radiowaves.left.and.right"
    case "discovery.mdns":
      return "wave.3.right.circle"
    case "network":
      return "network"
    case "network.http":
      return "arrow.left.arrow.right.circle"
    case "network.transport":
      return "point.3.connected.trianglepath.dotted"
    case "network.tls":
      return "lock.shield"
    case "pairing":
      return "person.2.badge.key"
    case "pairing.identity":
      return "person.crop.rectangle.badge.checkmark"
    case "stream":
      return "play.tv"
    case "stream.lifecycle":
      return "arrow.triangle.2.circlepath"
    case "input":
      return "cursorarrow"
    case "input.scroll":
      return "arrow.up.and.down.circle"
    case "input.mouse":
      return "cursorarrow.motionlines"
    case "input.click":
      return "cursorarrow.click"
    case "input.capture":
      return "lock.open"
    case "video":
      return "video"
    case "video.decoder":
      return "film"
    case "audio":
      return "speaker.wave.2"
    case "audio.pipeline":
      return "waveform.path"
    case "ui":
      return "macwindow"
    case "ui.window":
      return "rectangle.on.rectangle"
    case "system":
      return "gearshape.2"
    case "system.noise":
      return "speaker.slash"
    default:
      return "ellipsis.circle"
    }
  }

  func matchesFilterKey(_ filterKey: String?) -> Bool {
    guard let filterKey, !filterKey.isEmpty, filterKey != "all" else {
      return true
    }
    if categoryKey == filterKey || domainKey == filterKey {
      return true
    }
    return categoryKey.hasPrefix(filterKey + ".")
  }
}

@objcMembers
final class MLLogCategoryClassifier: NSObject {
  private static let descriptors: [String: MLLogCategoryDescriptor] = [
    "discovery": .init(
      domainKey: "discovery",
      categoryKey: "discovery",
      nameKey: "Discovery",
      badgeKey: "Discovery"
    ),
    "discovery.mdns": .init(
      domainKey: "discovery",
      categoryKey: "discovery.mdns",
      nameKey: "Discovery · mDNS",
      badgeKey: "Discovery/mDNS"
    ),
    "network": .init(
      domainKey: "network",
      categoryKey: "network",
      nameKey: "Network",
      badgeKey: "Network"
    ),
    "network.http": .init(
      domainKey: "network",
      categoryKey: "network.http",
      nameKey: "Network · Request",
      badgeKey: "Network/Request"
    ),
    "network.transport": .init(
      domainKey: "network",
      categoryKey: "network.transport",
      nameKey: "Network · Transport",
      badgeKey: "Network/Transport"
    ),
    "network.tls": .init(
      domainKey: "network",
      categoryKey: "network.tls",
      nameKey: "Network · TLS",
      badgeKey: "Network/TLS"
    ),
    "pairing": .init(
      domainKey: "pairing",
      categoryKey: "pairing",
      nameKey: "Pairing",
      badgeKey: "Pairing"
    ),
    "pairing.identity": .init(
      domainKey: "pairing",
      categoryKey: "pairing.identity",
      nameKey: "Pairing · Identity",
      badgeKey: "Pairing/Identity"
    ),
    "stream": .init(
      domainKey: "stream",
      categoryKey: "stream",
      nameKey: "Stream",
      badgeKey: "Stream"
    ),
    "stream.lifecycle": .init(
      domainKey: "stream",
      categoryKey: "stream.lifecycle",
      nameKey: "Stream · Lifecycle",
      badgeKey: "Stream/Lifecycle"
    ),
    "input": .init(
      domainKey: "input",
      categoryKey: "input",
      nameKey: "Input",
      badgeKey: "Input"
    ),
    "input.scroll": .init(
      domainKey: "input",
      categoryKey: "input.scroll",
      nameKey: "Input · Scroll",
      badgeKey: "Input/Scroll"
    ),
    "input.mouse": .init(
      domainKey: "input",
      categoryKey: "input.mouse",
      nameKey: "Input · Mouse",
      badgeKey: "Input/Mouse"
    ),
    "input.click": .init(
      domainKey: "input",
      categoryKey: "input.click",
      nameKey: "Input · Click",
      badgeKey: "Input/Click"
    ),
    "input.capture": .init(
      domainKey: "input",
      categoryKey: "input.capture",
      nameKey: "Input · Capture",
      badgeKey: "Input/Capture"
    ),
    "video": .init(
      domainKey: "video",
      categoryKey: "video",
      nameKey: "Video",
      badgeKey: "Video"
    ),
    "video.decoder": .init(
      domainKey: "video",
      categoryKey: "video.decoder",
      nameKey: "Video · Decoder",
      badgeKey: "Video/Decoder"
    ),
    "audio": .init(
      domainKey: "audio",
      categoryKey: "audio",
      nameKey: "Audio",
      badgeKey: "Audio"
    ),
    "audio.pipeline": .init(
      domainKey: "audio",
      categoryKey: "audio.pipeline",
      nameKey: "Audio · Pipeline",
      badgeKey: "Audio/Pipeline"
    ),
    "ui": .init(
      domainKey: "ui",
      categoryKey: "ui",
      nameKey: "UI",
      badgeKey: "UI"
    ),
    "ui.window": .init(
      domainKey: "ui",
      categoryKey: "ui.window",
      nameKey: "UI · Window",
      badgeKey: "UI/Window"
    ),
    "system": .init(
      domainKey: "system",
      categoryKey: "system",
      nameKey: "System",
      badgeKey: "System"
    ),
    "system.noise": .init(
      domainKey: "system",
      categoryKey: "system.noise",
      nameKey: "System · Noise",
      badgeKey: "System/Noise"
    ),
    "other": .init(
      domainKey: "other",
      categoryKey: "other",
      nameKey: "Other",
      badgeKey: "Other"
    ),
  ]

  private static let orderedFilterKeys: [String] = [
    "discovery",
    "discovery.mdns",
    "network",
    "network.http",
    "network.transport",
    "network.tls",
    "pairing",
    "pairing.identity",
    "stream",
    "stream.lifecycle",
    "input",
    "input.scroll",
    "input.mouse",
    "input.click",
    "input.capture",
    "video",
    "video.decoder",
    "audio",
    "audio.pipeline",
    "ui",
    "ui.window",
    "system",
    "system.noise",
    "other",
  ]

  private static let orderedDomainKeys: [String] = [
    "discovery",
    "network",
    "pairing",
    "stream",
    "input",
    "video",
    "audio",
    "ui",
    "system",
    "other",
  ]

  static func filterOptions() -> [MLLogCategoryDescriptor] {
    orderedFilterKeys.compactMap { descriptors[$0] }
  }

  static func domainFilterOptions() -> [MLLogCategoryDescriptor] {
    orderedDomainKeys.compactMap { descriptors[$0] }
  }

  static func detailFilterOptions(forDomainFilterKey filterKey: String?) -> [MLLogCategoryDescriptor] {
    let normalized = (filterKey ?? "all").lowercased()
    if normalized == "all" || normalized.isEmpty {
      return orderedFilterKeys.compactMap { key in
        guard let descriptor = descriptors[key] else { return nil }
        return descriptor.categoryKey == descriptor.domainKey ? nil : descriptor
      }
    }

    if normalized == "other" {
      return descriptors["other"].map { [ $0 ] } ?? []
    }

    return orderedFilterKeys.compactMap { key in
      guard let descriptor = descriptors[key] else { return nil }
      guard descriptor.domainKey == normalized else { return nil }
      return descriptor.categoryKey == descriptor.domainKey ? nil : descriptor
    }
  }

  static func descriptor(forCategoryKey categoryKey: String) -> MLLogCategoryDescriptor {
    descriptors[categoryKey] ?? descriptors["other"]!
  }

  static func displayName(forFilterKey filterKey: String?) -> String {
    guard let filterKey, !filterKey.isEmpty, filterKey != "all" else {
      return "全部 / All"
    }
    return descriptor(forCategoryKey: filterKey).displayName
  }

  static func descriptor(forNoiseCategory noiseCategory: DebugNoiseCategory) -> MLLogCategoryDescriptor {
    switch noiseCategory {
    case .appKitMenuInconsistency:
      return descriptor(forCategoryKey: "system.noise")
    case .networkStackNoise, .systemTransportFallback:
      return descriptor(forCategoryKey: "network.transport")
    case .discoveryChatter:
      return descriptor(forCategoryKey: "discovery.mdns")
    case .hostIdentityMismatch:
      return descriptor(forCategoryKey: "pairing.identity")
    }
  }

  static func descriptor(forLine line: String) -> MLLogCategoryDescriptor {
    descriptor(forCategoryKey: categoryKey(forLine: line))
  }

  private static func categoryKey(forLine line: String) -> String {
    let normalized = line.lowercased()

    if normalized.contains("[clickdiag]") {
      return "input.click"
    }

    if normalized.contains("[inputdiag]") {
      if normalized.contains("scroll") {
        return "input.scroll"
      }
      if normalized.contains("mouse-button") {
        return "input.click"
      }
      if containsAny(normalized, [
        "sendabsolutemouseposition",
        "absolute pos=",
        "moves=",
        "rawδ=",
        "sentδ=",
        "remotetarget=(",
      ]) {
        return "input.mouse"
      }
    }

    if containsAny(normalized, [
      "capturemouse armed",
      "mouse uncapture",
      "mouse exit event",
      "rearming mouse capture",
      "rearm skipped",
      "mouse-entered-view",
      "mouse-exited-view",
      "free mouse uncaptured",
      "window became key; rearming input capture",
    ]) {
      return "input.capture"
    }

    if containsAny(normalized, [
      "starting discovery",
      "stopping discovery",
      "starting mdns discovery",
      "stopping mdns discovery",
      "restarting mdns search",
      "resolved address:",
      "discovery summary for ",
      "found service:",
      "found new host:",
      "found existing host through mdns",
      "found host through mdns",
    ]) {
      return "discovery.mdns"
    }

    if containsAny(normalized, [
      "server certificate mismatch",
      "received response from incorrect host:",
      "client certificate imported",
    ]) {
      return "pairing.identity"
    }

    if containsAny(normalized, [
      "tls错误",
      "tls error",
      "code=-1200",
      "code=-1202",
      "certificate is invalid",
      "证书无效",
    ]) {
      return "network.tls"
    }

    if containsAny(normalized, [
      "making request:",
      "received response:",
      "requesting:",
      "request failed with error",
      "app list successfully retreived",
      "app list successfully retrieved",
    ]) {
      return "network.http"
    }

    if containsAny(normalized, [
      "nsurlerrordomain",
      "connection error:",
      "网络连接已中断",
      "请求超时",
      "无法连接服务器",
      "finished with error",
      "failed to connect",
      "nw_",
      "tcp_input",
    ]) {
      return "network.transport"
    }

    if containsAny(normalized, [
      "microphone",
      "audio data shards",
      "surroundaudioinfo",
    ]) {
      return "audio.pipeline"
    }

    if containsAny(normalized, [
      "got sps",
      "got pps",
      "constructing new h264 format description",
      "pull renderer dequeued frame",
      "renderer pacing target updated",
      "requested idr",
    ]) {
      return "video.decoder"
    }

    if containsAny(normalized, [
      "window-will-enter-fullscreen",
      "window-did-enter-fullscreen",
      "window-will-exit-fullscreen",
      "window-did-exit-fullscreen",
      "window-resigned-key",
      "other-window-became-key",
      "startup display mode",
      "performclosestreamwindow",
      "active space change decision",
    ]) {
      return "ui.window"
    }

    if containsAny(normalized, [
      "stream target selection",
      "stream target classification",
      "stream risk assessment",
      "recommended fallback",
      "stream timing config",
      "resume?",
      "listartconnectionctx",
      "clconnectionstarted",
      "connectionstarted",
      "input stream established",
      "disconnect requested",
      "begin-stop:",
      "stream stop took",
      "cancel pending reconnect",
      "connection status update:",
      "reconnect requested:",
      "reconnect stop took",
      "disconnect-from-stream",
      "performclose invoked",
    ]) {
      return "stream.lifecycle"
    }

    if let noiseCategory = DebugLogNoiseClassifier.category(for: line) {
      return descriptor(forNoiseCategory: noiseCategory).categoryKey
    }

    return "other"
  }

  private static func containsAny(_ line: String, _ needles: [String]) -> Bool {
    needles.contains { line.contains($0) }
  }
}

enum DebugNoiseCategory: String, CaseIterable {
  case appKitMenuInconsistency
  case networkStackNoise
  case systemTransportFallback
  case discoveryChatter
  case hostIdentityMismatch

  var displayName: String {
    switch self {
    case .appKitMenuInconsistency:
      return "AppKit 菜单噪音 / AppKit Menu Inconsistency"
    case .networkStackNoise:
      return "系统网络噪音 / Network Stack Noise"
    case .systemTransportFallback:
      return "系统传输回退噪音 / System Transport Fallback"
    case .discoveryChatter:
      return "发现服务噪音 / Discovery Chatter"
    case .hostIdentityMismatch:
      return "主机身份不匹配 / Host Identity Mismatch"
    }
  }
}

enum DebugLogNoiseClassifier {
  static func category(for line: String) -> DebugNoiseCategory? {
    if line.localizedCaseInsensitiveContains("Discovery summary for ")
      || line.localizedCaseInsensitiveContains("Resolved address:")
    {
      return .discoveryChatter
    }

    if isServerCertificateMismatchLine(line) || isIncorrectHostLine(line) {
      return .hostIdentityMismatch
    }

    if line.localizedCaseInsensitiveContains("Internal inconsistency in menus") {
      return .appKitMenuInconsistency
    }

    if line.localizedCaseInsensitiveContains("NSURLErrorDomain")
      && (line.contains("-1001") || line.contains("-1004") || line.contains("-1005"))
    {
      return .systemTransportFallback
    }

    if line.localizedCaseInsensitiveContains("nw_")
      || line.localizedCaseInsensitiveContains("tcp_input")
      || line.localizedCaseInsensitiveContains("Request failed with error")
      || (line.localizedCaseInsensitiveContains("Connection ")
        && line.localizedCaseInsensitiveContains("failed"))
      || (line.localizedCaseInsensitiveContains("Task <")
        && line.localizedCaseInsensitiveContains("finished with error"))
    {
      return .networkStackNoise
    }

    return nil
  }

  static func isServerCertificateMismatchLine(_ line: String) -> Bool {
    line.localizedCaseInsensitiveContains("Server certificate mismatch")
  }

  static func isIncorrectHostLine(_ line: String) -> Bool {
    line.localizedCaseInsensitiveContains("Received response from incorrect host:")
  }

  static func extractErrorCodeDescription(from line: String) -> String {
    if let code = firstMatch(in: line, pattern: #"Code=(-?\d+)"#) {
      return "error \(code)"
    }
    if let code = firstMatch(in: line, pattern: #"(-1001|-1004|-1005)"#) {
      return "error \(code)"
    }
    return "error unknown"
  }

  static func extractTarget(from line: String) -> String {
    if let endpoint = firstMatch(in: line, pattern: #"((?:\d{1,3}\.){3}\d{1,3}:\d+)"#) {
      return endpoint
    }
    if let endpoint = firstMatch(in: line, pattern: #"(\[[0-9a-fA-F:]+\]:\d+)"#) {
      return endpoint
    }
    if let host = firstMatch(in: line, pattern: #"https?://([^\s/]+)"#) {
      return host
    }
    return "unknown target"
  }

  static func extractDiscoveryHost(from line: String) -> String {
    if let host = firstMatch(in: line, pattern: #"Discovery summary for\s+([^:]+):"#) {
      return host
    }
    if let host = firstMatch(in: line, pattern: #"Resolved address:\s+([^\s]+)\s+->"#) {
      return host
    }
    return "unknown"
  }

  static func extractDiscoveryState(from line: String) -> String? {
    firstMatch(in: line, pattern: #":\s*(\d+\s+online,\s*\d+\s+offline)"#)
  }

  static func extractIncorrectHost(from line: String) -> String? {
    firstMatch(in: line, pattern: #"incorrect host:\s*([^\s]+)"#)
  }

  static func extractExpectedHost(from line: String) -> String? {
    firstMatch(in: line, pattern: #"expected:\s*([^\s]+)"#)
  }

  static func shortHostIdentity(_ identity: String?) -> String? {
    guard let identity, !identity.isEmpty else { return nil }
    guard identity.count > 8 else { return identity }
    return String(identity.prefix(8)) + "…"
  }

  private static func firstMatch(in text: String, pattern: String) -> String? {
    guard let regex = try? NSRegularExpression(pattern: pattern) else {
      return nil
    }
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    guard let match = regex.firstMatch(in: text, options: [], range: range) else {
      return nil
    }
    let captureIndex = match.numberOfRanges > 1 ? 1 : 0
    let captureRange = match.range(at: captureIndex)
    guard
      let swiftRange = Range(captureRange, in: text),
      !swiftRange.isEmpty
    else {
      return nil
    }
    return String(text[swiftRange])
  }
}

enum DebugLogLevel: String, CaseIterable {
  case all
  case debug
  case info
  case warn
  case error
  case unknown

  var rank: Int {
    switch self {
    case .all: return -1
    case .debug: return 0
    case .info: return 1
    case .warn: return 2
    case .error: return 3
    case .unknown: return 0
    }
  }

  var displayText: String {
    switch self {
    case .all: return "All"
    case .debug: return "Debug"
    case .info: return "Info"
    case .warn: return "Warn"
    case .error: return "Error"
    case .unknown: return "Unknown"
    }
  }
}

struct DebugLogEntry: Identifiable {
  let id: String
  let timestamp: Date?
  let timestampText: String?
  let level: DebugLogLevel
  let message: String
  let defaultTitle: String
  let defaultDetail: String?
  let rawLine: String
  let count: Int
  let category: MLLogCategoryDescriptor
  let searchIndex: String
  let noiseCategory: DebugNoiseCategory?
  let isNoiseSummary: Bool

  // Keys, not sentences (issue #30). The parser used to build both halves in Chinese, so an
  // English system read Chinese in the panel and a Chinese system that switched languages
  // after a scan kept seeing the language of the parse. A row is parsed once and rendered
  // on every rebuild, so the translation belongs here: an unknown key -- a raw log line, a
  // host name -- answers with itself, which is what the panel showed before.
  var displayTitle: String { LanguageManager.shared.localize(defaultTitle) }

  var displayDetail: String? {
    guard let defaultDetail else { return nil }
    return LanguageManager.shared.localize(defaultDetail)
  }

  var searchableText: String {
    searchIndex
  }

  func matchesCategoryFilter(_ filterKey: String) -> Bool {
    category.matchesFilterKey(filterKey)
  }

  func matchesKeyword(_ keyword: String) -> Bool {
    keyword.isEmpty || searchIndex.contains(keyword)
  }
}

private struct DebugLogPresentation {
  let title: String
  let detail: String?
}

enum DebugLogParser {
  private static let loggerDateFormatter: DateFormatter = {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"
    return formatter
  }()

  private static let timestampPrefixRegex = try? NSRegularExpression(
    pattern: #"^\[([^\]]+)\]\s*(.*)$"#)
  private static let levelPrefixRegex = try? NSRegularExpression(
    pattern: #"^(<DEBUG>|<INFO>|<WARN>|<ERROR>)\s*(.*)$"#)

  static func parseEntries(from text: String) -> [DebugLogEntry] {
    let rows = text.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
    return rows.map(parseSingleLine)
  }

  static func curatedEntries(
    fromRawText text: String,
    minimumLevel: DebugLogLevel,
    showSystemNoise: Bool,
    aggregationWindowSeconds: TimeInterval = 5.0
  ) -> [DebugLogEntry] {
    var result: [DebugLogEntry] = []
    let entries = parseEntries(from: text)
    var pending: PendingNoiseAggregation?

    func flushPending(force: Bool, now: Date?) {
      guard let current = pending else { return }
      if !force, let now, now.timeIntervalSince(current.startTime) < aggregationWindowSeconds {
        return
      }
      let summaryLine: String
      switch current.category {
      case .discoveryChatter:
        if current.target == "resolved-address" {
          summaryLine =
            "\(current.category.displayName): \(Int(aggregationWindowSeconds))s, \(current.count) lines (\(current.reason) address repeats)"
        } else {
          summaryLine =
            "\(current.category.displayName): \(Int(aggregationWindowSeconds))s, \(current.count) lines (\(current.reason), \(current.target))"
        }
      case .hostIdentityMismatch:
        var details: [String] = []
        if current.certificateMismatchCount > 0 {
          details.append("证书不匹配 \(current.certificateMismatchCount) 次")
        }
        if current.incorrectHostCount > 0 {
          details.append("错误主机 \(current.incorrectHostCount) 次")
        }
        if let expected = DebugLogNoiseClassifier.shortHostIdentity(current.expectedHostIdentity) {
          details.append("期望 \(expected)")
        }
        if let actual = DebugLogNoiseClassifier.shortHostIdentity(current.actualHostIdentity) {
          details.append("收到 \(actual)")
        }
        let detailText = details.isEmpty ? "主机身份校验失败" : details.joined(separator: ", ")
        summaryLine =
          "\(current.category.displayName): \(Int(aggregationWindowSeconds))s, \(current.count) lines (\(detailText))"
      default:
        summaryLine =
          "\(current.category.displayName): \(Int(aggregationWindowSeconds))s, \(current.count) lines (\(current.reason), target \(current.target))"
      }
      let summary = DebugLogEntry(
        id: makeStableID(
          timestampText: current.timestampText,
          rawLine: summaryLine,
          category: MLLogCategoryClassifier.descriptor(forNoiseCategory: current.category),
          noiseCategory: current.category,
          isNoiseSummary: true
        ),
        timestamp: current.lastTimestamp ?? current.startTime,
        timestampText: current.timestampText,
        level: .warn,
        message: summaryLine,
        defaultTitle: summaryLine,
        defaultDetail: nil,
        rawLine: summaryLine,
        count: current.count,
        category: MLLogCategoryClassifier.descriptor(forNoiseCategory: current.category),
        searchIndex: makeSearchIndex(
          category: MLLogCategoryClassifier.descriptor(forNoiseCategory: current.category),
          defaultTitle: summaryLine,
          defaultDetail: nil,
          message: summaryLine,
          rawLine: summaryLine
        ),
        noiseCategory: current.category,
        isNoiseSummary: true
      )
      if matchesMinimumLevel(summary.level, minimumLevel: minimumLevel) {
        result.append(summary)
      }
      pending = nil
    }

    for entry in entries {
      let category = DebugLogNoiseClassifier.category(for: entry.rawLine)

      if showSystemNoise {
        flushPending(force: true, now: entry.timestamp)
        if matchesMinimumLevel(entry.level, minimumLevel: minimumLevel) {
          result.append(entry)
        }
        continue
      }

      guard let category else {
        flushPending(force: true, now: entry.timestamp)
        if matchesMinimumLevel(entry.level, minimumLevel: minimumLevel) {
          result.append(entry)
        }
        continue
      }

      if var current = pending, current.category == category {
        let shouldContinueWindow: Bool
        if let now = entry.timestamp, let last = current.lastTimestamp {
          shouldContinueWindow = now.timeIntervalSince(last) <= aggregationWindowSeconds
        } else {
          shouldContinueWindow = true
        }

        if shouldContinueWindow {
          current.count += 1
          current.lastTimestamp = entry.timestamp ?? current.lastTimestamp
          current.timestampText = entry.timestampText ?? current.timestampText
          if category == .discoveryChatter {
            current.reason = DebugLogNoiseClassifier.extractDiscoveryHost(from: entry.rawLine)
            current.target =
              DebugLogNoiseClassifier.extractDiscoveryState(from: entry.rawLine)
              ?? (entry.rawLine.localizedCaseInsensitiveContains("Resolved address:")
                ? "resolved-address" : "state changed")
          } else if category == .hostIdentityMismatch {
            if DebugLogNoiseClassifier.isServerCertificateMismatchLine(entry.rawLine) {
              current.certificateMismatchCount += 1
            }
            if DebugLogNoiseClassifier.isIncorrectHostLine(entry.rawLine) {
              current.incorrectHostCount += 1
            }
            if let actual = DebugLogNoiseClassifier.extractIncorrectHost(from: entry.rawLine) {
              current.actualHostIdentity = actual
            }
            if let expected = DebugLogNoiseClassifier.extractExpectedHost(from: entry.rawLine) {
              current.expectedHostIdentity = expected
            }
            current.reason = "主机身份校验"
            current.target = "cert-or-host-mismatch"
          } else {
            current.reason = DebugLogNoiseClassifier.extractErrorCodeDescription(from: entry.rawLine)
            current.target = DebugLogNoiseClassifier.extractTarget(from: entry.rawLine)
          }
          pending = current
          continue
        }
      }

      flushPending(force: true, now: entry.timestamp)
      let startTime = entry.timestamp ?? Date()
      pending = PendingNoiseAggregation(
        category: category,
        count: 1,
        startTime: startTime,
        lastTimestamp: entry.timestamp,
        timestampText: entry.timestampText,
        reason: category == .discoveryChatter
          ? DebugLogNoiseClassifier.extractDiscoveryHost(from: entry.rawLine)
          : category == .hostIdentityMismatch
            ? "主机身份校验"
          : DebugLogNoiseClassifier.extractErrorCodeDescription(from: entry.rawLine),
        target: category == .discoveryChatter
          ? (DebugLogNoiseClassifier.extractDiscoveryState(from: entry.rawLine)
            ?? (entry.rawLine.localizedCaseInsensitiveContains("Resolved address:")
              ? "resolved-address" : "state changed"))
          : category == .hostIdentityMismatch
            ? "cert-or-host-mismatch"
          : DebugLogNoiseClassifier.extractTarget(from: entry.rawLine)
        ,
        certificateMismatchCount: DebugLogNoiseClassifier.isServerCertificateMismatchLine(entry.rawLine) ? 1 : 0,
        incorrectHostCount: DebugLogNoiseClassifier.isIncorrectHostLine(entry.rawLine) ? 1 : 0,
        actualHostIdentity: DebugLogNoiseClassifier.extractIncorrectHost(from: entry.rawLine),
        expectedHostIdentity: DebugLogNoiseClassifier.extractExpectedHost(from: entry.rawLine)
      )

      let startLine =
        "\(category.displayName): aggregating for \(Int(aggregationWindowSeconds))s window"
      let startEntry = DebugLogEntry(
        id: makeStableID(
          timestampText: entry.timestampText,
          rawLine: startLine,
          category: MLLogCategoryClassifier.descriptor(forNoiseCategory: category),
          noiseCategory: category,
          isNoiseSummary: true
        ),
        timestamp: entry.timestamp,
        timestampText: entry.timestampText,
        level: .info,
        message: startLine,
        defaultTitle: startLine,
        defaultDetail: nil,
        rawLine: startLine,
        count: 1,
        category: MLLogCategoryClassifier.descriptor(forNoiseCategory: category),
        searchIndex: makeSearchIndex(
          category: MLLogCategoryClassifier.descriptor(forNoiseCategory: category),
          defaultTitle: startLine,
          defaultDetail: nil,
          message: startLine,
          rawLine: startLine
        ),
        noiseCategory: category,
        isNoiseSummary: true
      )
      if matchesMinimumLevel(startEntry.level, minimumLevel: minimumLevel) {
        result.append(startEntry)
      }
    }

    flushPending(force: true, now: Date())
    return result
  }

  static func matchesMinimumLevel(_ level: DebugLogLevel, minimumLevel: DebugLogLevel) -> Bool {
    if minimumLevel == .all {
      return true
    }
    return level.rank >= minimumLevel.rank
  }

  static func foldConsecutiveDuplicates(_ entries: [DebugLogEntry]) -> [DebugLogEntry] {
    guard !entries.isEmpty else { return [] }

    var folded: [DebugLogEntry] = []
    var current = entries[0]
    var repeatCount = max(1, current.count)

    func flushCurrent() {
      let merged = DebugLogEntry(
        id: current.id,
        timestamp: current.timestamp,
        timestampText: current.timestampText,
        level: current.level,
        message: current.message,
        defaultTitle: current.defaultTitle,
        defaultDetail: current.defaultDetail,
        rawLine: current.rawLine,
        count: repeatCount,
        category: current.category,
        searchIndex: current.searchIndex,
        noiseCategory: current.noiseCategory,
        isNoiseSummary: current.isNoiseSummary
      )
      folded.append(merged)
    }

    for next in entries.dropFirst() {
      let isSameKind =
        current.level == next.level
        && current.message == next.message
        && current.category.categoryKey == next.category.categoryKey
        && current.noiseCategory == next.noiseCategory
        && current.isNoiseSummary == next.isNoiseSummary
      if isSameKind {
        repeatCount += max(1, next.count)
      } else {
        flushCurrent()
        current = next
        repeatCount = max(1, next.count)
      }
    }
    flushCurrent()
    return folded
  }

  private static func parseSingleLine(_ line: String) -> DebugLogEntry {
    var remaining = line
    var timestampText: String?
    var timestamp: Date?

    if let matched = matchLine(remaining, regex: timestampPrefixRegex), matched.count >= 2 {
      timestampText = matched[0]
      remaining = matched[1]
      if let ts = timestampText {
        timestamp = loggerDateFormatter.date(from: ts)
      }
    }

    var level: DebugLogLevel = .unknown
    var message = remaining
    if let matched = matchLine(remaining, regex: levelPrefixRegex), matched.count >= 2 {
      switch matched[0] {
      case "<DEBUG>": level = .debug
      case "<INFO>": level = .info
      case "<WARN>": level = .warn
      case "<ERROR>": level = .error
      default: level = .unknown
      }
      message = matched[1]
    }

    let category = MLLogCategoryClassifier.descriptor(forLine: line)
    let presentation = defaultPresentation(
      forMessage: message,
      rawLine: line,
      level: level,
      category: category,
      isNoiseSummary: false
    )

    return DebugLogEntry(
      id: makeStableID(
        timestampText: timestampText,
        rawLine: line,
        category: category,
        noiseCategory: nil,
        isNoiseSummary: false
      ),
      timestamp: timestamp,
      timestampText: timestampText,
      level: level,
      message: message,
      defaultTitle: presentation.title,
      defaultDetail: presentation.detail,
      rawLine: line,
      count: 1,
      category: category,
      searchIndex: makeSearchIndex(
        category: category,
        defaultTitle: presentation.title,
        defaultDetail: presentation.detail,
        message: message,
        rawLine: line
      ),
      noiseCategory: nil,
      isNoiseSummary: false
    )
  }

  private static func defaultPresentation(
    forMessage message: String,
    rawLine: String,
    level: DebugLogLevel,
    category: MLLogCategoryDescriptor,
    isNoiseSummary: Bool
  ) -> DebugLogPresentation {
    if isNoiseSummary {
      return DebugLogPresentation(title: message, detail: nil)
    }

    let normalized = message.lowercased()
    let cleaned = stripTechnicalPrefix(from: message)

    switch category.categoryKey {
    case "discovery.mdns":
      if normalized == "starting discovery" {
        return .init(title: "Starting host scan", detail: "Preparing to probe known hosts and LAN broadcast services")
      }
      if normalized == "starting mdns discovery" {
        return .init(title: "Starting mDNS discovery", detail: nil)
      }
      if normalized == "stopping discovery" {
        return .init(title: "Stopping host scan", detail: nil)
      }
      if normalized == "stopping mdns discovery" {
        return .init(title: "Stopping mDNS discovery", detail: nil)
      }
      if normalized == "updating hosts..." {
        return .init(title: "Updating the host list", detail: nil)
      }
      if let host = firstCapture(in: message, pattern: #"Found new host:\s*(.+)$"#) {
        return .init(title: "New host discovered", detail: host)
      }
      if let host = firstCapture(in: message, pattern: #"Found existing host through MDNS:\s*(.+)$"#) {
        return .init(title: "mDNS resolved a known host", detail: host)
      }
      if let captures = captures(in: message, pattern: #"Resolved address:\s*([^\s]+)\s*->\s*(.+)$"#), captures.count >= 2 {
        return .init(title: "Resolved a host address", detail: "\(captures[0]) -> \(captures[1])")
      }
      if let captures = captures(in: message, pattern: #"Discovery summary for\s+([^:]+):\s*(.+)$"#), captures.count >= 2 {
        return .init(title: "Host probe result", detail: "\(captures[0]) -> \(captures[1])")
      }
      if let host = firstCapture(in: message, pattern: #"Found service:\s+.+\.\s([^ ]+)\s+-?\d+$"#) {
        return .init(title: "Broadcast service discovered", detail: host)
      }
      return .init(title: cleaned, detail: nil)

    case "pairing.identity":
      if normalized.contains("server certificate mismatch") {
        return .init(title: "Server certificate does not match the saved identity", detail: "This usually means the wrong host was reached, or the host certificate changed")
      }
      if normalized.contains("client certificate imported in memory without keychain access") {
        return .init(title: "Client certificate imported into memory", detail: "This connection will not be written to the Keychain")
      }
      if let captures = captures(in: message, pattern: #"incorrect host:\s*([^\s]+)\s+expected:\s*([^\s]+)"#), captures.count >= 2 {
        let actual = DebugLogNoiseClassifier.shortHostIdentity(captures[0]) ?? captures[0]
        let expected = DebugLogNoiseClassifier.shortHostIdentity(captures[1]) ?? captures[1]
        return .init(title: "Host responded with a mismatched identity", detail: String(format: LanguageManager.shared.localize("Actual %@, expected %@"), actual, expected))
      }
      return .init(title: cleaned, detail: nil)

    case "network.tls":
      if let code = firstCapture(in: message, pattern: #"error\s+(-?\d+)"#) ?? firstCapture(in: message, pattern: #"Code=(-?\d+)"#) {
        return .init(title: "TLS / certificate handshake failed", detail: String(format: LanguageManager.shared.localize("Error code %@"), code))
      }
      return .init(title: "TLS / certificate verification failed", detail: cleaned)

    case "network.http", "network.transport":
      if let code = firstCapture(in: message, pattern: #"Request failed with error\s+(-?\d+)"#) {
        return .init(title: friendlyNetworkFailureTitle(for: code), detail: String(format: LanguageManager.shared.localize("Error code %@"), code))
      }
      if normalized.contains("app list successfully retreived") || normalized.contains("app list successfully retrieved") {
        let tries = firstCapture(in: message, pattern: #"took\s+(\d+)\s+tries"#) ?? "0"
        return .init(title: "App list retrieved", detail: String(format: LanguageManager.shared.localize("Took %@ tries"), tries))
      }
      if normalized.contains("stun failed to get wan address") {
        let code = firstCapture(in: message, pattern: #":\s*(-?\d+)$"#) ?? "unknown"
        return .init(title: "STUN failed to get the WAN address", detail: String(format: LanguageManager.shared.localize("Error code %@"), code))
      }
      if normalized.contains("requesting:") && normalized.contains("/resume?") {
        return .init(title: "Requesting a stream session resume", detail: nil)
      }
      if normalized.contains("received response:") {
        return .init(title: "Host response received", detail: nil)
      }
      if normalized.contains("making request:") {
        return .init(title: "Sending a host request", detail: nil)
      }
      return .init(title: cleaned, detail: nil)

    case "stream.lifecycle":
      if normalized.contains("stream target selection:") {
        let active = value(forKey: "active", in: message)
        return .init(title: "Stream target selected", detail: active)
      }
      if normalized.contains("stream target classification:") {
        let reason = value(forKey: "reason", in: message)
        return .init(title: "Stream path decision completed", detail: reason)
      }
      if let detail = suffix(in: cleaned, after: "Stream risk assessment:") {
        return .init(title: "Stream spec evaluation", detail: detail)
      }
      if let detail = suffix(in: cleaned, after: "Recommended fallback:") {
        return .init(title: "Suggested fallback configuration", detail: detail)
      }
      if let detail = suffix(in: cleaned, after: "Stream timing config:") {
        return .init(title: "Stream timing configuration applied", detail: detail)
      }
      if normalized.contains("listartconnectionctx") {
        return .init(title: "Starting the stream connection", detail: nil)
      }
      if normalized.contains("clconnectionstarted") || normalized.contains("connectionstarted") {
        return .init(title: "Stream connection started", detail: cleaned)
      }
      if normalized.contains("input stream established") {
        return .init(title: "Input link established", detail: nil)
      }
      if normalized.contains("performclose invoked") {
        return .init(title: "The user asked to close the stream window", detail: nil)
      }
      if normalized.contains("disconnect requested") {
        return .init(title: "Stream disconnect requested", detail: cleaned)
      }
      if normalized.contains("stream stop took") {
        return .init(title: "Stream stopped", detail: cleaned)
      }
      if normalized.contains("input summary") {
        return .init(title: "Input statistics summary", detail: suffixAfterFirstColon(in: cleaned) ?? cleaned)
      }
      return .init(title: cleaned, detail: nil)

    case "input.scroll":
      if normalized.contains("scroll-trace start") {
        return .init(title: "Scroll input started", detail: cleaned)
      }
      if normalized.contains("scroll-trace render") {
        return .init(title: "Scroll effect shown", detail: cleaned)
      }
      return .init(title: cleaned, detail: nil)

    case "input.mouse":
      if normalized.contains("absolute pos=") {
        return .init(title: "Sending an absolute pointer position", detail: cleaned)
      }
      if normalized.contains("relative raw=") {
        return .init(title: "Sending a relative pointer delta", detail: cleaned)
      }
      return .init(title: cleaned, detail: nil)

    case "input.click":
      return .init(title: "Pointer click event", detail: cleaned)

    case "input.capture":
      if let reason = value(forKey: "reason", in: message) {
        return .init(title: "Pointer capture state changed", detail: reason)
      }
      return .init(title: "Pointer capture state changed", detail: cleaned)

    case "video.decoder":
      if normalized.contains("got sps") || normalized.contains("got pps") {
        return .init(title: "Video stream parameters updated", detail: cleaned)
      }
      if normalized.contains("constructing new h264 format description") {
        return .init(title: "Rebuilding the H.264 decode format", detail: nil)
      }
      if normalized.contains("renderer pacing target updated") {
        return .init(title: "Render pacing target updated", detail: cleaned)
      }
      return .init(title: cleaned, detail: nil)

    case "audio.pipeline":
      if normalized.contains("microphone disabled in settings") {
        return .init(title: "The microphone is switched off in settings", detail: nil)
      }
      if normalized.contains("microphone setting:") {
        return .init(title: "Microphone configuration applied", detail: cleaned)
      }
      return .init(title: cleaned, detail: nil)

    case "ui.window":
      if normalized.contains("startup display mode requesting fullscreen toggle") {
        return .init(title: "Requesting fullscreen", detail: nil)
      }
      if normalized.contains("window-did-enter-fullscreen") {
        return .init(title: "Window entered fullscreen", detail: nil)
      }
      if normalized.contains("window-did-exit-fullscreen") {
        return .init(title: "Window left fullscreen", detail: nil)
      }
      return .init(title: cleaned, detail: nil)

    default:
      return .init(title: cleaned, detail: nil)
    }
  }

  private static func stripTechnicalPrefix(from message: String) -> String {
    var result = message
    for prefix in ["[diag] ", "[inputdiag] ", "[clickdiag] "] {
      if result.hasPrefix(prefix) {
        result.removeFirst(prefix.count)
        break
      }
    }
    return result
  }

  private static func friendlyNetworkFailureTitle(for code: String) -> String {
    switch code {
    case "-1202":
      return "Certificate verification failed, falling back"
    case "-1200":
      return "TLS connection failed, falling back"
    case "-1001":
      return "Request timed out, falling back"
    case "-1004":
      return "Could not reach the server, falling back"
    case "-1005":
      return "Network connection dropped"
    default:
      return "Network request failed, falling back"
    }
  }

  private static func suffix(in text: String, after needle: String) -> String? {
    guard let range = text.range(of: needle) else { return nil }
    let suffix = text[range.upperBound...].trimmingCharacters(in: .whitespacesAndNewlines)
    return suffix.isEmpty ? nil : String(suffix)
  }

  private static func suffixAfterFirstColon(in text: String) -> String? {
    guard let index = text.firstIndex(of: ":") else { return nil }
    let suffix = text[text.index(after: index)...].trimmingCharacters(in: .whitespacesAndNewlines)
    return suffix.isEmpty ? nil : String(suffix)
  }

  private static func value(forKey key: String, in text: String) -> String? {
    firstCapture(in: text, pattern: #"(?<![A-Za-z0-9_])\#(key)=([^\s]+)"#)
  }

  private static func firstCapture(in text: String, pattern: String) -> String? {
    captures(in: text, pattern: pattern)?.first
  }

  private static func captures(in text: String, pattern: String) -> [String]? {
    guard let regex = try? NSRegularExpression(pattern: pattern) else {
      return nil
    }
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    guard let match = regex.firstMatch(in: text, options: [], range: range) else {
      return nil
    }

    var results: [String] = []
    for index in 1..<match.numberOfRanges {
      let captureRange = match.range(at: index)
      guard let swiftRange = Range(captureRange, in: text), !swiftRange.isEmpty else {
        results.append("")
        continue
      }
      results.append(String(text[swiftRange]))
    }
    return results.isEmpty ? nil : results
  }

  private static func makeSearchIndex(
    category: MLLogCategoryDescriptor,
    defaultTitle: String,
    defaultDetail: String?,
    message: String,
    rawLine: String
  ) -> String {
    var parts = [category.searchableText, defaultTitle, defaultDetail ?? "", message, rawLine]
    // The row shows one language; the filter box has to answer the other one too, so every
    // table's value for a key is searchable, which is how a category name already works.
    for code in ["en", "zh-Hans"] {
      for key in [defaultTitle, defaultDetail ?? ""] where !key.isEmpty {
        if let value = LanguageManager.shared.localizedString(key, languageCode: code) {
          parts.append(value)
        }
      }
    }
    return parts.joined(separator: "\n").lowercased()
  }

  private static func makeStableID(
    timestampText: String?,
    rawLine: String,
    category: MLLogCategoryDescriptor,
    noiseCategory: DebugNoiseCategory?,
    isNoiseSummary: Bool
  ) -> String {
    "\(timestampText ?? "")|\(category.categoryKey)|\(noiseCategory?.rawValue ?? "none")|\(isNoiseSummary ? "1" : "0")|\(rawLine)"
  }

  private static func matchLine(_ input: String, regex: NSRegularExpression?) -> [String]? {
    guard let regex else { return nil }
    let nsRange = NSRange(input.startIndex..<input.endIndex, in: input)
    guard let match = regex.firstMatch(in: input, options: [], range: nsRange) else { return nil }
    var captures: [String] = []
    for index in 1..<match.numberOfRanges {
      let range = match.range(at: index)
      guard let swiftRange = Range(range, in: input) else {
        captures.append("")
        continue
      }
      captures.append(String(input[swiftRange]))
    }
    return captures
  }
}

private struct PendingNoiseAggregation {
  let category: DebugNoiseCategory
  var count: Int
  let startTime: Date
  var lastTimestamp: Date?
  var timestampText: String?
  var reason: String
  var target: String
  var certificateMismatchCount: Int
  var incorrectHostCount: Int
  var actualHostIdentity: String?
  var expectedHostIdentity: String?
}
