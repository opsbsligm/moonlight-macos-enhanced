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
case "locked":
    // Authoritative lock-screen state. Foreground-app heuristics lie while the
    // login window shares the display with a fullscreen stream; this dictionary
    // is what the WindowServer itself publishes.
    if let d = CGSessionCopyCurrentDictionary() as? [String: Any] {
        print((d["CGSSessionScreenIsLocked"] as? Int) ?? 0)
    } else { print(0) }
case "wins":
    // wins <pid> : one line per window of that pid: number|layer|alpha|x|y|w|h
    let pid = Int32(args[2])!
    if let list = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as? [[String: Any]] {
        for w in list where (w[kCGWindowOwnerPID as String] as? Int32) == pid {
            let num = w[kCGWindowNumber as String] as? Int ?? -1
            let layer = w[kCGWindowLayer as String] as? Int ?? -999
            let alpha = w[kCGWindowAlpha as String] as? Double ?? -1
            let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
            let x = b["X"] as? Double ?? 0, y = b["Y"] as? Double ?? 0
            let ww = b["Width"] as? Double ?? 0, hh = b["Height"] as? Double ?? 0
            print("\(num)|\(layer)|\(alpha)|\(x)|\(y)|\(ww)|\(hh)")
        }
    }
case "pos":
    let loc = CGEvent(source: nil)?.location ?? .zero
    print("\(loc.x) \(loc.y)")
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
case "dbl":
    // dbl x y: one press+release pair with clickState=2, which is how AppKit
    // delivers a real double-click (clickCount 2). Two single clicks posted back
    // to back read as two singles to some gesture recognisers, which is why a
    // synthetic double-press sometimes only selected the card.
    guard args.count == 4 else { die("dbl x y") }
    let p = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    CGWarpMouseCursorPosition(p)
    if let d = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left) {
        d.setIntegerValueField(.mouseEventClickState, value: 2)
        d.post(tap: .cghidEventTap)
    }
    usleep(40_000)
    if let u = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left) {
        u.setIntegerValueField(.mouseEventClickState, value: 2)
        u.post(tap: .cghidEventTap)
    }
case "down":
    guard args.count == 4 else { die("down x y") }
    let p = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    CGWarpMouseCursorPosition(p)
    if let d = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left) { d.post(tap: .cghidEventTap) }
case "drag":
    // drag x1 y1 x2 y2: press at x1y1, glide in bounded steps to x2y2, release.
    // Stepwise moves are what an NSPanGestureRecognizer needs to see Began ->
    // Changed... -> Ended; a single warp would read as a click.
    guard args.count == 6 else { die("drag x1 y1 x2 y2") }
    let p1 = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    let p2 = CGPoint(x: Double(args[4])!, y: Double(args[5])!)
    CGWarpMouseCursorPosition(p1)
    if let d = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: p1, mouseButton: .left) { d.post(tap: .cghidEventTap) }
    let steps = 20
    for i in 1...steps {
        let t = Double(i) / Double(steps)
        let p = CGPoint(x: p1.x + (p2.x - p1.x) * t, y: p1.y + (p2.y - p1.y) * t)
        CGWarpMouseCursorPosition(p)
        if let m = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDragged, mouseCursorPosition: p, mouseButton: .left) { m.post(tap: .cghidEventTap) }
        usleep(15_000)
    }
    usleep(60_000)
    if let u = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: p2, mouseButton: .left) { u.post(tap: .cghidEventTap) }
case "up":
    guard args.count == 4 else { die("up x y") }
    let p = CGPoint(x: Double(args[2])!, y: Double(args[3])!)
    CGWarpMouseCursorPosition(p)
    if let u = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left) { u.post(tap: .cghidEventTap) }
case "flick":
    // flick dx dy steps gap_us: post `steps` mouseMoved events that carry an
    // explicit relative delta (dx/dy split evenly) with a fixed gap, so a locked
    // session sees one continuous stroke without the pointer being warped. This
    // is the closest reproducible stand-in for a wrist flick on real hardware;
    // the matrix still records it as injected, not hardware.
    guard args.count == 6 else { die("flick dx dy steps gap_us") }
    let dx = Double(args[2])!, dy = Double(args[3])!
    let steps = Int(args[4])!, gap = UInt32(args[5])!
    let start = CGEvent(source: nil)?.location ?? .zero
    for i in 0..<steps {
        guard let m = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved,
                              mouseCursorPosition: CGPoint(x: start.x + dx * Double(i + 1) / Double(steps),
                                                           y: start.y + dy * Double(i + 1) / Double(steps)),
                              mouseButton: .left) else { continue }
        m.setIntegerValueField(.mouseEventDeltaX, value: Int64(dx / Double(steps)))
        m.setIntegerValueField(.mouseEventDeltaY, value: Int64(dy / Double(steps)))
        m.post(tap: .cghidEventTap)
        usleep(gap)
    }
case "mod":
    // mod <codeA> <codeB>: A down, B down while A is held, then both up. That
    // is the only shape where a modifierOnly rule on A+B can see both flags
    // held together; a single down/up pair never co-occurs and would test
    // nothing. Injected, so the acceptance matrix keeps saying injected.
    guard args.count == 4 else { die("mod codeA codeB") }
    let a = CGKeyCode(UInt16(args[2])!), b = CGKeyCode(UInt16(args[3])!)
    // Same shape as `combo`, which is proven on this host: post a real
    // down/down/up/up sequence and let the HID layer accumulate the flag
    // state, exactly like a pair of hands. Overwriting flags by hand broke
    // this twice -- the legacy Carbon constants first, then a shift bit
    // mistaken for maskSecondaryFn. The authoritative bits are
    // shift 0x20000, control 0x40000, option 0x80000, command 0x100000, and
    // this host's release shortcut is modifierOnly shift+option (0xA0000),
    // read from the per-host profile, not the global default.
    func post(_ c: CGKeyCode, _ down: Bool) {
        if let e = CGEvent(keyboardEventSource: nil, virtualKey: c, keyDown: down) {
            e.post(tap: .cghidEventTap)
        }
    }
    post(a, true)
    usleep(80_000)
    post(b, true)
    usleep(250_000)   // the app's modifierOnly settle window is 0.15 s
    post(b, false)
    usleep(40_000)
    post(a, false)
case "combo":
    // combo <keyCode>: inject control+option+key as a real sequence — modifiers
    // go down first so the HID layer recomputes flags the same way we hold them.
    // A keyDown posted with pre-set flags alone cannot be trusted: the event tap
    // rebuilds flags from the physical keyboard state.
    guard args.count == 3 else { die("combo keyCode") }
    let k = CGKeyCode(UInt16(args[2])!)
    func kd(_ c: CGKeyCode, _ f: CGEventFlags = []) {
        if let e = CGEvent(keyboardEventSource: nil, virtualKey: c, keyDown: true) { e.flags = f; e.post(tap: .cghidEventTap) }
        usleep(30_000)
    }
    func ku(_ c: CGKeyCode, _ f: CGEventFlags = []) {
        if let e = CGEvent(keyboardEventSource: nil, virtualKey: c, keyDown: false) { e.flags = f; e.post(tap: .cghidEventTap) }
        usleep(30_000)
    }
    let ctrl: CGEventFlags = .maskControl, alt: CGEventFlags = [.maskControl, .maskAlternate]
    kd(59, ctrl)                      // control down
    kd(58, alt)                       // option down while control is held
    kd(k, alt)                        // the real key with both held
    ku(k, alt)
    ku(58, ctrl)                      // option up (control still down)
    ku(59)                            // control up
case "key":
    // key <keyCode> <flags> : down then up with the given CGEventFlags mask.
    // maskShift 0x20000, maskControl 0x40000, maskAlternate 0x80000, maskCommand 0x100000. The pure-modifier release
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
