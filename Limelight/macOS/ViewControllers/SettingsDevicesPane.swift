//
//  SettingsDevicesPane.swift
//  Moonlight for macOS
//
//  The devices panel: what this build may hand over, and what would happen to each device on the
//  bus if it could.
//
//  Nothing on this page decides anything. Every string a player reads here was produced by
//  `MLDeviceRedirectionPanelModel`, which is the object scripts/device-redirection-panel-model-tests.py
//  drives, and a rule written inside a SwiftUI `body` would be a rule no gate has ever exercised.
//  The formatting left in this file is formatting: hexadecimal identifiers, yes and no, and the
//  order rows are drawn in.
//
//  Why the four preconditions sit above the list of refusals: docs/usb-redirection-design.md 3
//  records that a page of refusals without them would dress a missing signing identity up as a room
//  full of broken devices. Today every refusal this page can produce is caused by the first one, and
//  the page says so in the same words the log uses, so a screenshot and a log line agree.
//
//  UNLOCK(stage3): the switches here are read by this page and by nothing that streams. That is the
//  design rather than a stub -- a switch that redirected devices before the driver existed would be
//  a switch that did nothing while claiming otherwise. Four things have to land first, and none of
//  them is a switch; docs/usb-redirection-design.md 9.3 is the checklist, and the short form:
//    1. the driver extension target built as part of the app;
//    2. the app and that extension signed with a Developer ID identity and the hardened runtime --
//       the first card on this page is reading the answer from the running binary right now, which
//       is why it cannot be talked into showing something hopeful;
//    3. notarisation and stapling, so a downloaded copy opens at all;
//    4. the helper's install-and-enable lifecycle, which DriverLifecycle.m already models and
//       already refuses to fake.
//  The host half is separate and belongs where a stream connects: the question the Check Host button
//  asks is the question `+[MLDeviceRedirectionPolicy hostAdvertisesDeviceRedirectionInServerInfo:]`
//  will have to be asked of the real connection, with the same answer deciding the same way.
//

import AppKit
import SwiftUI

/// The interface classes the page offers a switch for. Labels only -- nothing here consults this
/// list to decide a device, and the classes that no rule can ever reach come from the model. A
/// class missing from this list is still reachable through the number field below it, because a page
/// that could only ever allow nine classes would be a second allow list with the visible kind of
/// invisible, which is the thing every layer of this feature has refused to be.
private struct OfferedInterfaceClass {
  let majorClass: Int
  let labelKey: String
}

private let offeredInterfaceClasses: [OfferedInterfaceClass] = [
  OfferedInterfaceClass(majorClass: 0x01, labelKey: "USB class audio"),
  OfferedInterfaceClass(majorClass: 0x02, labelKey: "USB class communications"),
  OfferedInterfaceClass(majorClass: 0x03, labelKey: "USB class human interface"),
  OfferedInterfaceClass(majorClass: 0x05, labelKey: "USB class physical"),
  OfferedInterfaceClass(majorClass: 0x06, labelKey: "USB class image"),
  OfferedInterfaceClass(majorClass: 0x07, labelKey: "USB class printer"),
  OfferedInterfaceClass(majorClass: 0x08, labelKey: "USB class mass storage"),
  OfferedInterfaceClass(majorClass: 0x0E, labelKey: "USB class video"),
  OfferedInterfaceClass(majorClass: 0xEF, labelKey: "USB class miscellaneous"),
]

struct DevicesView: View {
  @EnvironmentObject private var settingsModel: SettingsModel
  @ObservedObject var languageManager = LanguageManager.shared

  /// Read from the running binary, once, because the question the first card answers is what *this*
  /// build can do. A build setting would only say what was asked for. The initialiser is spelled
  /// out rather than reached through a no-argument factory, because a factory named after its own
  /// class is what the importer rewrites into `init()` and leaves competing with the one below.
  @SwiftUI.State private var panel = MLDeviceRedirectionPanelModel(defaults: .standard)

  /// The model is Objective-C and deliberately not observable, so every write bumps this and every
  /// bump re-renders the page. Reading it is not required for that: a `@State` write invalidates this
  /// view on its own. It is not used as an `.id()` either -- the view's identity has to survive a
  /// keystroke, or the rule editor loses what the player is in the middle of typing.
  @SwiftUI.State private var panelRevision = 0

  @SwiftUI.State private var rows: [MLDeviceRedirectionPanelRow] = []
  @SwiftUI.State private var isCheckingHost = false
  @SwiftUI.State private var vendorText = ""
  @SwiftUI.State private var productText = ""
  @SwiftUI.State private var wholeVendorFamily = false
  @SwiftUI.State private var ruleWasRefused = false
  @SwiftUI.State private var classText = ""
  @SwiftUI.State private var classWasRefused = false

  var body: some View {
    ScrollView {
      LazyVStack(spacing: 32) {
        readinessSection
        switchesSection
        rulesSection
        busSection
        FormSection(title: "What stands in the way") {
          VStack(alignment: .leading, spacing: 8) {
            HStack {
              Text(languageManager.localize("Reason"))
              Spacer()
              Text(panel.blockingReasonName)
                .font(.system(.body, design: .monospaced))
                .foregroundColor(panel.mayBecomeActive ? .green : .orange)
            }
            SettingDescriptionRow(textKey: "Devices panel reason detail")
            SettingDescriptionRow(textKey: "Devices panel audit detail")
            Text(panel.auditLine)
              .font(.system(.caption, design: .monospaced))
              .foregroundColor(.secondary)
              .textSelection(.enabled)
              .frame(maxWidth: .infinity, alignment: .leading)
          }
          .padding(6)
        }
      }
      .padding()
    }
  }

  // MARK: - What has to be true first

  private var readinessSection: some View {
    FormSection(title: "What has to be true first") {
      VStack(alignment: .leading, spacing: 10) {
        statusRow(
          titleKey: "This build",
          value: MLCodeSignatureFormName(panel.signatureProfile.form),
          satisfied: panel.signatureProfile.mayAttemptDriverExtension)
        Divider()
        statusRow(
          titleKey: "Driver extension entitlement",
          value: yesNo(panel.signatureProfile.hasDriverKitEntitlement),
          satisfied: panel.signatureProfile.hasDriverKitEntitlement)
        Divider()
        statusRow(
          titleKey: "System extension entitlement",
          value: yesNo(panel.signatureProfile.hasSystemExtensionEntitlement),
          satisfied: panel.signatureProfile.hasSystemExtensionEntitlement)
        Divider()
        hostRow
        Divider()
        SettingDescriptionRow(textKey: "Devices panel preconditions detail")
      }
      .padding(6)
    }
  }

  private func statusRow(titleKey: String, value: String, satisfied: Bool) -> some View {
    HStack {
      Text(languageManager.localize(titleKey))
      Spacer()
      Text(value)
        .font(.system(.body, design: .monospaced))
        .foregroundColor(satisfied ? .green : .secondary)
    }
  }

  private var hostRow: some View {
    HStack(spacing: 10) {
      Text(languageManager.localize("The host offers it"))
      Spacer()
      Text(MLDeviceRedirectionHostClaimName(panel.hostClaim))
        .font(.system(.body, design: .monospaced))
        .foregroundColor(panel.hostClaim == .offered ? .green : .secondary)
      Button(action: checkHost) {
        if isCheckingHost {
          ProgressView().controlSize(.small)
        } else {
          Text(languageManager.localize("Check host"))
        }
      }
      .disabled(isCheckingHost)
      .help(languageManager.localize("Check host detail"))
    }
  }

  // MARK: - Switches

  private var switchesSection: some View {
    FormSection(title: "Switches") {
      VStack(alignment: .leading, spacing: 12) {
        ToggleCell(
          title: "USB device redirection",
          hintKey: "USB device redirection detail",
          boolBinding: Binding(
            get: { panel.featureEnabled },
            set: {
              panel.featureEnabled = $0
              panelRevision += 1
            }))
        ToggleCell(
          title: "Local input devices",
          hintKey: "Local input devices detail",
          boolBinding: Binding(
            get: { panel.localInputDevicesAllowed },
            set: {
              panel.localInputDevicesAllowed = $0
              panelRevision += 1
            }))
        Divider()
        InlineSectionLabel(title: "Allowed interface classes")
        ForEach(offeredInterfaceClasses, id: \.majorClass) { offered in
          ToggleCell(
            title: offered.labelKey,
            boolBinding: Binding(
              get: { panel.allowedInterfaceClasses.contains(NSNumber(value: offered.majorClass)) },
              set: {
                panel.setInterfaceClassAllowed($0, forClass: UInt(offered.majorClass))
                panelRevision += 1
              }))
        }
        classEntryRow
        SettingDescriptionRow(textKey: "Devices panel reserved detail")
      }
      .padding(6)
    }
  }

  private var classEntryRow: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack {
        TextField(languageManager.localize("Class number, 0 to 255"), text: $classText)
          .textFieldStyle(.roundedBorder)
          .frame(maxWidth: 160)
        Button(languageManager.localize("Add")) { allowTypedClass() }
        if classWasRefused {
          Text(languageManager.localize("That is not a class number"))
            .font(.footnote)
            .foregroundColor(.orange)
        }
        Spacer()
      }
      SettingDescriptionRow(textKey: "Devices panel class entry detail")
    }
  }

  // MARK: - Rules

  private var rulesSection: some View {
    FormSection(title: "Allow rules") {
      VStack(alignment: .leading, spacing: 12) {
        if panel.rules.isEmpty {
          SettingDescriptionRow(textKey: "No rules yet detail")
        }
        ForEach(Array(panel.rules.enumerated()), id: \.offset) { index, rule in
          ruleRow(index: index, rule: rule)
          if index + 1 < panel.rules.count {
            Divider()
          }
        }
        Divider()
        ruleEditor
        if panel.unreadableStoredRuleCount > 0 {
          Divider()
          unreadableRulesRow
        }
      }
      .padding(6)
    }
  }

  private func ruleRow(index: Int, rule: MLDeviceRedirectionRule) -> some View {
    HStack(spacing: 10) {
      Text(ruleLine(rule))
        .font(.system(.body, design: .monospaced))
      Spacer()
      Toggle(
        "", isOn: Binding(
          get: { rule.enabled },
          set: {
            panel.setRuleEnabled($0, atIndex: UInt(index))
            panelRevision += 1
          }))
        .toggleStyle(.switch)
        .controlSize(.small)
        .labelsHidden()
      Button(languageManager.localize("Remove")) {
        panel.removeRule(atIndex: UInt(index))
        panelRevision += 1
      }
    }
  }

  private var ruleEditor: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack {
        TextField(languageManager.localize("Vendor ID in hex"), text: $vendorText)
          .textFieldStyle(.roundedBorder)
          .frame(maxWidth: 110)
        TextField(languageManager.localize("Product ID in hex"), text: $productText)
          .textFieldStyle(.roundedBorder)
          .frame(maxWidth: 110)
          .disabled(wholeVendorFamily)
        Toggle(languageManager.localize("Whole vendor"), isOn: $wholeVendorFamily)
          .toggleStyle(.checkbox)
        Button(languageManager.localize("Add")) { addRule() }
        Spacer()
      }
      if ruleWasRefused {
        Text(languageManager.localize("That rule could not describe a device"))
          .font(.footnote)
          .foregroundColor(.orange)
      }
      SettingDescriptionRow(textKey: "Devices panel rule detail")
    }
  }

  private var unreadableRulesRow: some View {
    HStack {
      Text(
        languageManager.localize("Records that cannot be honoured") + " "
          + "\(panel.unreadableStoredRuleCount)")
      Spacer()
      Button(languageManager.localize("Remove")) {
        panel.removeUnhonourableStoredRecords()
        panelRevision += 1
      }
    }
  }

  // MARK: - The bus

  private var busSection: some View {
    FormSection(title: "Devices on this Mac") {
      VStack(alignment: .leading, spacing: 10) {
        HStack {
          // Before the first scan there is no status to print: `busStatus` holds the enumeration's
          // zero value, which is the same value a readable bus gets.
          Text(
            panel.busHasBeenScanned
              ? MLUSBBusSnapshotStatusName(panel.busStatus)
              : languageManager.localize("Bus not scanned"))
            .font(.system(.body, design: .monospaced))
            .foregroundColor(panel.busHasBeenScanned && panel.busStatus == .read ? .green : .orange)
          Spacer()
          Button(languageManager.localize("Scan the bus"), action: scanBus)
        }
        if panel.busHasBeenScanned && rows.isEmpty {
          SettingDescriptionRow(textKey: "No devices on the bus detail")
        }
        ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
          HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
              Text(row.identityLine)
                .font(.system(.caption, design: .monospaced))
              Text(row.decisionLine)
                .font(.system(.caption, design: .monospaced))
                .foregroundColor(row.allowed ? .green : .secondary)
            }
            Spacer()
            // The identifiers come off the device the row was built from, not out of the line above
            // it. A page that recovered them from its own text would be parsing what it printed, and
            // would keep working -- wrongly -- the moment the wording changed.
            Button(languageManager.localize("Use this device")) { prefill(ruleEditor: row) }
              .disabled(row.identity?.vendorID == nil)
          }
        }
        SettingDescriptionRow(textKey: "Devices panel privacy detail")
      }
      .padding(6)
    }
  }

  // MARK: - Actions

  /// The host asked, on a background queue, with its own answer credited to nobody else.
  ///
  /// The uuid check is not ceremony: several machines can answer `/serverinfo` on one address space,
  /// and crediting a stranger's capability bit would hand devices to a host that never offered them.
  private func checkHost() {
    guard let host = pairedTemporaryHost() else {
      note(advertised: nil)
      return
    }
    guard let address = ConnectionEndpointStore.allEndpoints(for: host).first else {
      note(advertised: nil)
      return
    }
    isCheckingHost = true
    // Trimmed, because `ServerInfoResponse` stores a trimmed uuid, and an empty one is not a
    // match: a host whose identifier this app never learned cannot be credited with an answer
    // it did not sign, and comparing two missing identifiers optional-to-optional would do
    // exactly that and call the stranger's capability bit our host's.
    let expectedUuid = (host.uuid ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    DispatchQueue.global(qos: .userInitiated).async {
      let serverInfo = ServerInfoResponse()
      if let http = HttpManager(
        host: address, uniqueId: IdManager.getUniqueId(), serverCert: host.serverCert)
      {
        let request = HttpRequest(
          for: serverInfo,
          with: http.newServerInfoRequest(true),
          fallbackError: 401,
          fallbackRequest: http.newHttpServerInfoRequest(true))
        http.executeRequestSynchronously(request)
      }
      // Trimmed, because that is how this app reads every other tag of the same response:
      // `ServerInfoResponse` trims each one before it stores it, so `host.uuid` holds a trimmed
      // string and an untrimmed answer could never equal it. The failure this avoids is silent --
      // the page would report a host that offered devices as one that refused them.
      let answeredUuid = (serverInfo.getStringTag(TAG_UNIQUE_ID) ?? "")
        .trimmingCharacters(in: .whitespacesAndNewlines)
      let advertisedTag = serverInfo.getStringTag(MLDeviceRedirectionServerInfoTagName())?
        .trimmingCharacters(in: .whitespacesAndNewlines)
      let answered = serverInfo.isStatusOk()
        && !expectedUuid.isEmpty
        && answeredUuid == expectedUuid
      note(advertised: answered ? advertisedTag : nil)
    }
  }

  private func note(advertised: String?) {
    DispatchQueue.main.async {
      isCheckingHost = false
      panel.noteServerInfoValue(advertised)
      panelRevision += 1
    }
  }

  /// Reading the bus iterates the registry, so it happens when the button is pressed and not while
  /// the page draws itself.
  private func scanBus() {
    rows = panel.rowsByScanningBus(hostPaired: hostIsPaired)
    panelRevision += 1
  }

  /// Puts a device a scan found into the rule editor. Nothing is stored: a player still presses Add,
  /// because typing is not the part worth saving a confirmation for.
  private func prefill(ruleEditor row: MLDeviceRedirectionPanelRow) {
    guard let identity = row.identity, let vendorID = identity.vendorID else {
      return
    }
    vendorText = String(format: "%04X", vendorID.uint32Value)
    wholeVendorFamily = identity.productID == nil
    productText = identity.productID.map { String(format: "%04X", $0.uint32Value) } ?? ""
    ruleWasRefused = false
  }

  private func addRule() {
    guard let vendorID = hexadecimalIdentifier(vendorText) else {
      ruleWasRefused = true
      return
    }
    var productID: UInt16 = 0
    if !wholeVendorFamily {
      // No default. A page that filled in a product id the player never typed would authorise one
      // device while appearing to authorise another, and an allow list exists precisely to make that
      // impossible.
      guard let typed = hexadecimalIdentifier(productText) else {
        ruleWasRefused = true
        return
      }
      productID = typed
    }
    ruleWasRefused = !panel.addRule(
      vendorID: UInt(vendorID), productID: UInt(productID), family: wholeVendorFamily)
    if !ruleWasRefused {
      vendorText = ""
      productText = ""
    }
    panelRevision += 1
  }

  private func allowTypedClass() {
    let trimmed = classText.trimmingCharacters(in: .whitespacesAndNewlines)
    guard let majorClass = Int(trimmed), (0...255).contains(majorClass) else {
      classWasRefused = true
      panelRevision += 1
      return
    }
    classWasRefused = !panel.setInterfaceClassAllowed(true, forClass: UInt(majorClass))
    if !classWasRefused {
      classText = ""
    }
    panelRevision += 1
  }

  // MARK: - Reading the page's surroundings

  /// The host this page is configuring, when it is one of the paired ones.
  ///
  /// `DataManager` is read here on the main thread, the way the settings model already reads it when
  /// the page opens. Nothing streams while a settings page is open, and a panel that cached the host
  /// list would be showing a machine that was unpaired an hour ago.
  private func pairedTemporaryHost() -> TemporaryHost? {
    guard let hostId = settingsModel.selectedHost?.id, hostId != SettingsModel.globalHostId else {
      return nil
    }
    guard let hosts = DataManager().getHosts() as? [TemporaryHost] else {
      return nil
    }
    return hosts.first(where: { !$0.uuid.isEmpty && $0.uuid == hostId })
  }

  private var hostIsPaired: Bool {
    pairedTemporaryHost() != nil
  }

  // MARK: - Formatting

  private func yesNo(_ value: Bool) -> String {
    languageManager.localize(value ? "Yes" : "No")
  }

  /// `vid=1234 pid=5678` or `vid=1234 any product`. The identifiers come from the rule, which is
  /// the only place they exist; a product id on a family rule would be a wildcard that quietly
  /// became one device.
  private func ruleLine(_ rule: MLDeviceRedirectionRule) -> String {
    "vid=" + hexadecimal(rule.vendorID)
      + (rule.productIsWildcard ? " any product" : " pid=" + hexadecimal(rule.productID))
  }

  /// Four hexadecimal digits, because an identifier written as `1234` and one written as `00001234`
  /// are the same device and a support thread should not have to decide which one a screenshot shows.
  private func hexadecimal(_ value: UInt16) -> String {
    String(format: "%04X", UInt32(value))
  }

  private func hexadecimalIdentifier(_ text: String) -> UInt16? {
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
      .replacingOccurrences(of: "0x", with: "", options: .caseInsensitive)
    guard !trimmed.isEmpty, let value = UInt32(trimmed, radix: 16), value <= 0xFFFF else {
      return nil
    }
    return UInt16(value)
  }
}
