// 1024x1024 uygulama ikonu üretir: siyah yuvarlatılmış kare + beyaz aşağı ok.
// Kullanım: swift make_icon.swift <çıktı.png>
import Cocoa

let size: CGFloat = 1024
let out = CommandLine.arguments[1]

let image = NSImage(size: NSSize(width: size, height: size), flipped: false) { _ in
    // macOS ikon ızgarası: 824px kare, 100px kenar boşluğu, ~185px köşe yarıçapı
    let rect = NSRect(x: 100, y: 100, width: 824, height: 824)
    let path = NSBezierPath(roundedRect: rect, xRadius: 185, yRadius: 185)
    NSGradient(starting: NSColor(white: 0.16, alpha: 1), ending: NSColor(white: 0.04, alpha: 1))!
        .draw(in: path, angle: -90)

    let config = NSImage.SymbolConfiguration(pointSize: 420, weight: .semibold)
        .applying(.init(paletteColors: [.white]))
    if let arrow = NSImage(systemSymbolName: "arrow.down", accessibilityDescription: nil)?
        .withSymbolConfiguration(config) {
        let s = arrow.size
        arrow.draw(in: NSRect(x: (size - s.width) / 2, y: (size - s.height) / 2, width: s.width, height: s.height))
    }
    return true
}

let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
