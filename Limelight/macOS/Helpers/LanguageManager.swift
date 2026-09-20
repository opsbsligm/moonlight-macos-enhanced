//
//  LanguageManager.swift
//  Moonlight for macOS
//
//  Created by SkyHua on 2024/01/17.
//

import SwiftUI

enum AppLanguage: String, CaseIterable, Identifiable {
  case system = "System"
  case english = "English"
  case chinese = "简体中文"

  var id: String { rawValue }
}

@objcMembers
@objc(LanguageManager)
public class LanguageManager: NSObject, ObservableObject {
  public static let shared = LanguageManager()

  @AppStorage("appLanguage") var currentLanguage: AppLanguage = .system

  public override init() {
    super.init()
    updateAppLanguage(postNotification: false)
  }

  @objc(applyAppLanguage) public func applyAppLanguage() {
    updateAppLanguage(postNotification: true)
  }

  private func updateAppLanguage(postNotification: Bool) {
    switch currentLanguage {
    case .system:
      UserDefaults.standard.removeObject(forKey: "AppleLanguages")
    case .english:
      UserDefaults.standard.set(["en"], forKey: "AppleLanguages")
    case .chinese:
      UserDefaults.standard.set(["zh-Hans"], forKey: "AppleLanguages")
    }

    guard postNotification else { return }
    NotificationCenter.default.post(name: .init("LanguageChanged"), object: nil)
  }

  // One bundle per language rather than one per lookup. The log panel indexes every key in
  // every language, and it builds one index per log line: a few thousand lines on screen
  // used to mean a bundle allocated on every lookup for an answer that cannot change while
  // the process runs.
  private lazy var languageBundles: [String: Bundle] = {
    var bundles: [String: Bundle] = [:]
    for code in ["en", "zh-Hans"] {
      if let path = Bundle.main.path(forResource: code, ofType: "lproj") {
        bundles[code] = Bundle(path: path)
      }
    }
    return bundles
  }()

  // Not private: a caller that owns a key rather than a sentence needs the same
  // per-language lookup to keep both languages searchable, which is how the log
  // panel's filter box still answers a Chinese name while showing English.
  func localizedString(_ key: String, languageCode: String) -> String? {
    guard let bundle = languageBundles[languageCode] else {
      return nil
    }

    let val = NSLocalizedString(
      key, tableName: nil, bundle: bundle, value: "___MISSING___", comment: "")
    return val == "___MISSING___" ? nil : val
  }

  public func localize(_ key: String) -> String {
    let useChinese: Bool

    if currentLanguage == .system {
      // Check system preference
      let preferred = Locale.preferredLanguages.first ?? "en"
      useChinese = preferred.hasPrefix("zh")
    } else {
      useChinese = currentLanguage == .chinese
    }

    // There is one table per language and it is the one in the bundle. Two Swift dictionaries
  // used to sit at the bottom of this file answering 227 of these keys, and because localize()
  // asked them first, 21 Chinese and 6 English rows in the .strings tables were text no user
  // ever saw, 131 sentences were the part of the localisation the shipped-image audit never
  // read (it reads the tables in the image, not this file), and the log panel's filter box --
  // which indexes the .strings tables -- indexed sentences the UI never showed. Deleting the
  // dictionaries is what makes one answer per key; l10n-audit refuses them coming back.
    if useChinese {
      if let val = localizedString(key, languageCode: "zh-Hans") { return val }
      // No `return key` here. Falling through is what makes an untranslated key read as
      // the English sentence instead of as `No Filter (Showing All)`-shaped source text:
      // English is the development language, and the table beside it answers every key
      // this build asks for. A key that reaches the player is a bug the audit already
      // refuses, so there is nothing left for the runtime to invent.
    }

    if let val = localizedString(key, languageCode: "en") { return val }
    return key
  }


}
