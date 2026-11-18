// Draws Arnheim's app icon at every size macOS wants, into the .iconset folder it is given; mac/build.sh then
// makes Arnheim.icns from it with iconutil. A tower at night with one floor lit amber, as the building lights a
// floor where something waits on you, and a flag on its mast.
//
//   swiftc mac/icon.swift -o make-icon && ./make-icon Arnheim.iconset
import AppKit

func colour(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
            blue: CGFloat(hex & 0xff) / 255, alpha: alpha)
}

/// The icon in a 1024 by 1024 space, y upwards. Apple's grid puts the rounded square at 824 in the middle.
func draw() {
    let tile = NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824), xRadius: 185, yRadius: 185)
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = colour(0x000000, 0.35)
    shadow.shadowBlurRadius = 22
    shadow.shadowOffset = NSSize(width: 0, height: -10)
    shadow.set()
    colour(0x111726).setFill()
    tile.fill()
    NSGraphicsContext.restoreGraphicsState()

    NSGraphicsContext.saveGraphicsState()
    tile.addClip()
    NSGradient(starting: colour(0x0e1322), ending: colour(0x30436e))!.draw(in: tile, angle: 90)  // the night sky
    for (x, y, r) in [(210.0, 800.0, 5.0), (300, 700, 3.5), (760, 820, 4.5), (820, 650, 3), (700, 760, 2.5), (180, 610, 3)] {
        colour(0xffffff, 0.75).setFill()
        NSBezierPath(ovalIn: NSRect(x: x - r, y: y - r, width: r * 2, height: r * 2)).fill()
    }
    colour(0x0a0e17).setFill()
    NSRect(x: 100, y: 100, width: 824, height: 150).fill()  // the ground

    let stone = NSGradient(starting: colour(0xe6e8ee), ending: colour(0xa4abba))!
    stone.draw(in: NSRect(x: 362, y: 250, width: 300, height: 490), angle: 0)  // the tower
    stone.draw(in: NSRect(x: 422, y: 740, width: 180, height: 60), angle: 0)  // its top floor
    colour(0xd5d9e2).setFill()
    NSRect(x: 508, y: 800, width: 8, height: 84).fill()  // the mast
    let flag = NSBezierPath()
    flag.move(to: NSPoint(x: 516, y: 884))
    flag.line(to: NSPoint(x: 572, y: 864))
    flag.line(to: NSPoint(x: 516, y: 844))
    flag.close()
    colour(0xf4ae3d).setFill()
    flag.fill()

    colour(0x8a91a2).setFill()
    for floor in 1...5 { NSRect(x: 362, y: 250 + CGFloat(floor) * 88 - 2, width: 300, height: 4).fill() }  // between floors

    for floor in 1...4 {  // four rows of windows above the lobby, the third lit
        let y = 250 + CGFloat(floor) * 88 + 22
        let lit = floor == 3
        for column in 0..<4 {
            let pane = NSRect(x: 386 + CGFloat(column) * 68, y: y, width: 48, height: 44)
            NSGraphicsContext.saveGraphicsState()
            if lit {
                let glow = NSShadow()
                glow.shadowColor = colour(0xf4ae3d, 0.9)
                glow.shadowBlurRadius = 26
                glow.shadowOffset = .zero
                glow.set()
            }
            colour(lit ? 0xf4ae3d : 0x27314a).setFill()
            NSBezierPath(roundedRect: pane, xRadius: 4, yRadius: 4).fill()
            NSGraphicsContext.restoreGraphicsState()
        }
    }
    colour(0x27314a).setFill()  // the lobby: wide windows either side of the door
    NSBezierPath(roundedRect: NSRect(x: 386, y: 270, width: 80, height: 50), xRadius: 4, yRadius: 4).fill()
    NSBezierPath(roundedRect: NSRect(x: 558, y: 270, width: 80, height: 50), xRadius: 4, yRadius: 4).fill()
    colour(0x161c2b).setFill()
    NSRect(x: 484, y: 250, width: 56, height: 74).fill()
    NSGraphicsContext.restoreGraphicsState()
}

let arguments = CommandLine.arguments
guard arguments.count == 2 else {
    print("Give the .iconset folder to write: make-icon Arnheim.iconset")
    exit(2)
}
let folder = URL(fileURLWithPath: arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
let sizes: [(String, Int)] = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32), ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256), ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]
for (name, pixels) in sizes {
    guard let picture = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
                                         samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                         bytesPerRow: 0, bitsPerPixel: 0),
          let context = NSGraphicsContext(bitmapImageRep: picture)
    else {
        print("Couldn't make a \(pixels)-pixel picture.")
        exit(1)
    }
    picture.size = NSSize(width: pixels, height: pixels)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.cgContext.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
    draw()
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    guard let png = picture.representation(using: .png, properties: [:]) else {
        print("Couldn't save \(name).")
        exit(1)
    }
    try png.write(to: folder.appendingPathComponent(name))
}
