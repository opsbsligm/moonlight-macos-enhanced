// Shipping Swift completion/host-selection methods; no HTTP or Core Data side effects.
import Foundation
@propertyWrapper final class Box<Value> {
  var wrappedValue: Value
  init(wrappedValue: Value) { self.wrappedValue = wrappedValue }
}
enum PairState { case paired, unpaired }
final class TemporaryHost {
  var uuid: String; var pairState: PairState
  init(_ uuid: String, _ state: PairState = .paired) { self.uuid=uuid; self.pairState=state }
}
struct SelectedHost { let id: String }
final class SettingsModel {
  static let globalHostId="global"
  var selectedHost: SelectedHost? = SelectedHost(id:"A")
}
final class DataManager {
  static var hosts: [TemporaryHost] = [TemporaryHost("A"),TemporaryHost("B")]
  func hostMetadata(forUUID uuid: String) -> TemporaryHost? { Self.hosts.first { $0.uuid == uuid } }
}
final class Panel {
  var offered=0, unreachable=0
  func noteServerInfoValue(_ tag: String?) { assert(tag=="offered"); offered += 1 }
  func noteHostWasUnreachable() { unreachable += 1 }
}
struct Probe {
  let settingsModel=SettingsModel(), panel=Panel()
  @Box var hostCheckGeneration: UInt64=4
  @Box var pageIsVisible=true
  @Box var isCheckingHost=true
  @Box var panelRevision=0
  @@NOTE@@
  @@PAIRED@@
  func complete(generation: UInt64=4, expected: String="A", answered: Bool=true) {
    note(advertised:"offered",hostAnswered:answered,generation:generation,expectedUuid:expected)
  }
}
func drain(_ r: Probe) {
  let deadline=Date().addingTimeInterval(2)
  while r.isCheckingHost && Date()<deadline { RunLoop.main.run(until:Date().addingTimeInterval(0.001)) }
  assert(!r.isCheckingHost)
}
for scenario in 0..<8 {
  DataManager.hosts=[TemporaryHost("A"),TemporaryHost("B")]
  let r=Probe()
  if scenario==1 { r.hostCheckGeneration=5 } // new page/request generation
  if scenario==2 { r.pageIsVisible=false }
  if scenario==3 { r.settingsModel.selectedHost=SelectedHost(id:"B") }
  if scenario==4 { DataManager.hosts[0].pairState = .unpaired }
  if scenario==5 { r.settingsModel.selectedHost=SelectedHost(id:"global") }
  if scenario==6 { DataManager.hosts=[] }
  r.complete(answered:scenario != 7);drain(r)
  assert(r.panel.offered==(scenario==0 ? 1:0))
  assert(r.panel.unreachable==(scenario==7 ? 1:0))
  assert(r.panelRevision==((scenario==0 || scenario==7) ? 1:0))
}
let r=Probe();r.complete(expected:"");drain(r);assert(r.panel.offered==0 && r.panel.unreachable==0)
print("ok: 9 shipping Swift USB host completion scenarios; real Dispatch/main RunLoop, fake HTTP/host store")
