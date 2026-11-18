// The small window that says what is happening while Arnheim starts, and the menu bar's picture.
import AppKit

final class StartWindow: NSObject, NSWindowDelegate {
    let window: NSWindow
    private let heading = NSTextField(labelWithString: "Starting Arnheim")
    private let detail = NSTextField(wrappingLabelWithString: "")
    private let bar = NSProgressIndicator()
    private let note = NSTextField(wrappingLabelWithString: "")
    private static let stays = "Arnheim stays in the menu bar at the top of your screen: its menu opens the page again, "
        + "shows the log and quits."
    private let showLog: () -> Void
    private let closed: () -> Void

    init(showLog: @escaping () -> Void, closed: @escaping () -> Void) {
        self.showLog = showLog
        self.closed = closed
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 200),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        super.init()
        window.title = "Arnheim"
        window.isReleasedWhenClosed = false
        window.delegate = self
        heading.font = .boldSystemFont(ofSize: 15)
        detail.font = .systemFont(ofSize: 13)
        note.font = .systemFont(ofSize: 11)
        note.textColor = .secondaryLabelColor
        for label in [detail, note] { label.preferredMaxLayoutWidth = 400 }
        bar.style = .bar
        bar.minValue = 0
        bar.maxValue = 1
        bar.isIndeterminate = true
        let log = NSButton(title: "Show the log", target: self, action: #selector(logPressed))
        let hide = NSButton(title: "Hide", target: self, action: #selector(hidePressed))
        hide.keyEquivalent = "\r"
        let gap = NSView()
        gap.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let buttons = NSStackView(views: [log, gap, hide])
        buttons.orientation = .horizontal
        let stack = NSStackView(views: [heading, detail, bar, note, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 20, bottom: 16, right: 20)
        stack.translatesAutoresizingMaskIntoConstraints = false
        let content = NSView()
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            stack.topAnchor.constraint(equalTo: content.topAnchor),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            bar.widthAnchor.constraint(equalToConstant: 400),
            buttons.widthAnchor.constraint(equalToConstant: 400),
            detail.widthAnchor.constraint(equalToConstant: 400),
            note.widthAnchor.constraint(equalToConstant: 400),
        ])
        window.contentView = content
    }

    func show() {
        if #available(macOS 14.0, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
        if !window.isVisible { window.center() }
        window.makeKeyAndOrderFront(nil)
    }

    /// fraction: how far a download has got (0 to 1), or nil for "busy, no telling how long". busy false: no bar.
    func update(heading: String, detail: String, fraction: Double?, busy: Bool) {
        self.heading.stringValue = heading
        self.detail.stringValue = detail
        note.stringValue = busy ? "Your browser opens Arnheim when it is ready. " + StartWindow.stays : StartWindow.stays
        if !busy {
            bar.stopAnimation(nil)
            bar.isHidden = true
        } else if let fraction = fraction {
            bar.isHidden = false
            bar.isIndeterminate = false
            bar.doubleValue = fraction
        } else {
            bar.isHidden = false
            bar.isIndeterminate = true
            bar.startAnimation(nil)
        }
    }

    func close() {
        window.delegate = nil
        window.close()
    }

    @objc private func logPressed() { showLog() }

    @objc private func hidePressed() { window.close() }

    func windowWillClose(_ notification: Notification) { closed() }
}

enum Icons {
    /// The menu bar's picture: a small tower with a window on each floor, drawn as a template so macOS colours
    /// it for a light or dark menu bar.
    static func menuBar() -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
            NSColor.black.set()
            let body = NSBezierPath(rect: NSRect(x: 4.6, y: 1.6, width: 8.8, height: 11.8))
            body.lineWidth = 1.2
            body.stroke()
            NSRect(x: 6.5, y: 13.4, width: 5, height: 1.8).fill()  // the top floor
            NSRect(x: 8.4, y: 15.2, width: 1.2, height: 2.3).fill()  // the mast
            for y in [3.6, 6.6, 9.6] {
                for x in [6.6, 9.4] { NSRect(x: x, y: y, width: 2, height: 1.6).fill() }
            }
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Arnheim"
        return image
    }
}
