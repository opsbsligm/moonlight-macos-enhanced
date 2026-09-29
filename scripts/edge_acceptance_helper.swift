// One small helper so the live-acceptance script can inject real WindowServer
// events (the closest this machine gets to a hand on the mouse without a hand)
// and read the geometry the app itself sees. It says "injected", never "hardware".
import AppKit
import CoreGraphics

func die(_ msg: String) -> Never { FileHandle.standardError.write((msg + "\n").data(using: .utf8)!); exit(2) }

let args = CommandLine.arguments
guard args.count >= 2 else { die("usage: helper <screens|idle|move x y|click x y|key code flags> ") }
switch args[1] {
case "screens":
    // bounds.x bounds.y w h scale per screen, main first-ish; the acceptance
    // script needs the backing scale to turn points into screenshot pixels.
    for s in NSScreen.screens {
        print("\(s.frame.minX) \(s.frame.minY) \(s.frame.width) \(s.frame.height) \(s.backingScaleFactor)")
    }
case "idle":
    let t = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .mouseMoved)
    let t2 = CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: .keyDown)
    print(max(0, min(t, t2)))
case "move":
    guard args.count == 4 else { die("move x y") }
    let p = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    // Warp first so the position sticks, then post the move so the app sees a
    // mouseMoved like any pointer motion would produce.
    CGWarpMouseCursorPosition(p)
    if let e = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left) { e.post(tap: .cghidEventTap) }
case "click":
    guard args.count == 4 else { die("click x y") }
    let p = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    CGWarpMouseCursorPosition(p)
    if let d = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left) { d.post(tap: .cghidEventTap) }
    usleep(40_000)
    if let u = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left) { u.post(tap: .cghidEventTap) }
case "down":
    guard args.count == 4 else { die("down x y") }
    let p = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    CGWarpMouseCursorPosition(p)
    if let d = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left) { d.post(tap: .cghidEventTap) }
case "up":
    guard args.count == 4 else { die("up x y") }
    let p = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    CGWarpMouseCursorPosition(p)
    if let u = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left) { u.post(tap: .cghidEventTap) }
case "mod":
    // mod <codeA> <codeB>: A down, B down while A is held, then both up. That
    // is the only shape where a modifierOnly rule on A+B can see both flags
    // held together; a single down/up pair never co-occurs and would test
    // nothing. Injected, so the acceptance matrix keeps saying injected.
    guard args.count == 3 else { die("mod codeA codeB") }
    let a = CGKeyCode(UInt16(args[1])!), b = CGKeyCode(UInt16(args[2])!)
    let aFlag = CGEventFlags(rawValue: a == 56 ? 0x20 : (a == 58 ? 0x40 : (a == 59 ? 0x80 : (a == 61 ? 0x800 : 0x100))))
    if let e = CGEvent(keyboardEventSource: nil, virtualKey: a, keyDown: true) { e.post(tap: .cghidEventTap) }
    usleep(80_000)
    if let e = CGEvent(keyboardEventSource: nil, virtualKey: b, keyDown: true) { e.flags = aFlag; e.post(tap: .cghidEventTap) }
    usleep(120_000)
    if let e = CGEvent(keyboardEventSource: nil, virtualKey: b, keyDown: false) { e.post(tap: .cghidEventTap) }
    usleep(40_000)
    if let e = CGEvent(keyboardEventSource: nil, virtualKey: a, keyDown: false) { e.post(tap: .cghidEventTap) }
case "key":
    // key <keyCode> <flags> : down then up with the given CGEventFlags mask.
    // 0x100000 option, 0x80000 control, 0x20000 shift. The pure-modifier release
    // path uses key <shift-or-option code> with the *other* modifier already in
    // flags; the acceptance script sequences it and labels it injected.
    guard args.count == 4 else { die("key code flags") }
    let code = CGKeyCode(UInt16(args[2])!)
    let flags = CGEventFlags(rawValue: UInt64(args[3])!)
    if let d = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true) { d.flags = flags; d.post(tap: .cghidEventTap) }
    usleep(30_000)
    if let u = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false) { u.flags = flags; u.post(tap: .cghidEventTap) }
default:
    die("unknown subcommand \(args[1])")
}
