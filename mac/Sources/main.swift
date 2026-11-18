// Arnheim's Mac app: a menu bar app that keeps Arnheim (serve.py) running and opens it in the browser.
// docs/mac.md says what it does for a person; mac/build.sh builds it.
//
//   Arnheim                  the app, as Finder opens it
//   Arnheim --find-python    prints the Python it would run serve.py with, then quits (for tests)
//   Arnheim --version        prints the version of Arnheim it carries, then quits
//
// For tests: ARNHEIM_APP_HOME (its folder, instead of ~/Library/Application Support/Arnheim, with the log in
// its logs/), ARNHEIM_APP_PORT (the port, instead of 8740), ARNHEIM_APP_NO_OPEN=1 (no browser, no windows)
// and ARNHEIM_APP_PYTHON (this Python and no other).
import AppKit

let words = CommandLine.arguments.dropFirst()
if words.contains("--find-python") {
    if let python = Tools.findPython(in: Tools.searchPath()) {
        print("\(python.path) \(python.version)")
        exit(0)
    }
    print("none")
    exit(1)
}
if words.contains("--version") {
    if let bundled = Bundled.load() {
        print("Arnheim \(bundled.commit) (\(bundled.version))")
        exit(0)
    }
    print("This app carries no copy of Arnheim.")
    exit(1)
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.accessory)
application.run()
