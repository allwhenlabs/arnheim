// Where the app keeps Arnheim, and putting the version it carries there.
import Foundation

struct Places {
    let support: URL  // ~/Library/Application Support/Arnheim, or ARNHEIM_APP_HOME
    let app: URL  // support/app: Arnheim's files, with the person's data/, baked/ and .voice/ beside them
    let logs: URL
    let log: URL  // what serve.py prints, and what this app did
    let pidFile: URL  // "<this app's process> <serve.py's process>", so a copy left running is found again
    let port: Int
    let quiet: Bool  // ARNHEIM_APP_NO_OPEN=1: no browser and no windows, for tests
    let testing: Bool  // ARNHEIM_APP_HOME given: the login item is never touched

    static func current() -> Places {
        let environment = ProcessInfo.processInfo.environment
        let home = URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
        var support = home.appendingPathComponent("Library/Application Support/Arnheim", isDirectory: true)
        var logs = home.appendingPathComponent("Library/Logs/Arnheim", isDirectory: true)
        var testing = false
        if let given = environment["ARNHEIM_APP_HOME"], !given.isEmpty {
            support = URL(fileURLWithPath: (given as NSString).expandingTildeInPath, isDirectory: true)
            logs = support.appendingPathComponent("logs", isDirectory: true)
            testing = true
        }
        var port = 8740
        if let given = environment["ARNHEIM_APP_PORT"], let number = Int(given), number > 0, number < 65536 {
            port = number
        }
        return Places(
            support: support, app: support.appendingPathComponent("app", isDirectory: true), logs: logs,
            log: logs.appendingPathComponent("serve.log"), pidFile: support.appendingPathComponent("serve.pid"),
            port: port, quiet: environment["ARNHEIM_APP_NO_OPEN"] == "1", testing: testing)
    }

    func page(_ fragment: String = "") -> URL {
        URL(string: "http://127.0.0.1:\(port)/\(fragment)")!
    }
}

/// The copy of Arnheim inside the app (Contents/Resources/arnheim), as mac/build.sh put it there.
struct Bundled {
    let folder: URL
    let version: String  // a fingerprint of its files: any change makes a new one
    let commit: String
    let top: [String]  // its files and folders at the top, which an update replaces

    static func load() -> Bundled? {
        guard let resources = Bundle.main.resourceURL,
              let data = try? Data(contentsOf: resources.appendingPathComponent("arnheim.json")),
              let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let version = info["version"] as? String, let top = info["top"] as? [String]
        else { return nil }
        let folder = resources.appendingPathComponent("arnheim", isDirectory: true)
        guard FileManager.default.fileExists(atPath: folder.appendingPathComponent("serve.py").path) else { return nil }
        return Bundled(folder: folder, version: version, commit: info["commit"] as? String ?? "", top: top)
    }
}

enum Install {
    static let stampName = ".arnheim-app.json"  // which version is in the folder, and its top-level names
    static let kept: Set<String> = ["data", "baked", ".voice", ".share-key"]  // the person's, never replaced

    /// Makes sure places.app holds the version the app carries: copied the first time, and on a different
    /// version the code is replaced in place while data/, baked/ and .voice/ stay where they are. The stamp is
    /// written last, so an update cut short is done again at the next start. Gives what it did, or nil.
    static func ensure(_ bundled: Bundled, _ places: Places) throws -> String? {
        let files = FileManager.default
        let app = places.app
        let stamp = app.appendingPathComponent(stampName)
        let serve = app.appendingPathComponent("serve.py")
        let had = files.fileExists(atPath: app.path)
        var oldTop: [String] = []
        if had, let data = try? Data(contentsOf: stamp),
           let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if info["version"] as? String == bundled.version, files.fileExists(atPath: serve.path) {
                return nil
            }
            oldTop = info["top"] as? [String] ?? []
        }
        try files.createDirectory(at: app, withIntermediateDirectories: true)
        // Pictures made for another version would show the drawn look with a note to delete them: do it here.
        var note = ""
        let baked = app.appendingPathComponent("baked")
        if had, files.fileExists(atPath: baked.path),
           let before = picturesPrint(serve), let after = picturesPrint(bundled.folder.appendingPathComponent("serve.py")),
           before != after {
            try files.removeItem(at: baked)
            note = " The pictures were for the old version, so serve.py downloads the new ones."
        }
        for name in Set(oldTop).union(bundled.top).subtracting(kept) {
            let old = app.appendingPathComponent(name)
            if files.fileExists(atPath: old.path) || (try? files.destinationOfSymbolicLink(atPath: old.path)) != nil {
                try files.removeItem(at: old)
            }
        }
        for name in bundled.top where !kept.contains(name) {
            try files.copyItem(at: bundled.folder.appendingPathComponent(name), to: app.appendingPathComponent(name))
        }
        let info: [String: Any] = ["version": bundled.version, "commit": bundled.commit, "top": bundled.top]
        try JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted, .sortedKeys]).write(to: stamp, options: .atomic)
        return had
            ? "Updated Arnheim's files to \(bundled.commit), keeping data/, baked/ and .voice/.\(note)"
            : "Put Arnheim's files (\(bundled.commit)) in \(app.path)."
    }

    /// The fingerprint of the pictures a serve.py is made for (PICTURES["files"] in serve.py).
    static func picturesPrint(_ serve: URL) -> String? {
        first(#""files":\s*"([0-9a-f]{64})""#, in: serve)
    }

    /// How big the pictures' download is, in bytes (PICTURES["bytes"] in serve.py), or 0.
    static func picturesBytes(_ serve: URL) -> Int64 {
        Int64(first(#""bytes":\s*(\d+)"#, in: serve) ?? "") ?? 0
    }

    /// How much of the pictures serve.py has downloaded so far, while it is downloading them: the size of the
    /// hidden zip it writes beside baked/ (serve.py, fetch_pictures), if it changed in the last half minute.
    static func downloaded(_ app: URL) -> Int64? {
        let files = FileManager.default
        guard let names = try? files.contentsOfDirectory(atPath: app.path) else { return nil }
        var newest: (Date, Int64)?
        for name in names where name.hasPrefix(".baked-") && name.hasSuffix(".zip") {
            guard let about = try? files.attributesOfItem(atPath: app.appendingPathComponent(name).path),
                  let changed = about[.modificationDate] as? Date, let size = about[.size] as? NSNumber
            else { continue }
            if newest == nil || changed > newest!.0 { newest = (changed, size.int64Value) }
        }
        guard let (changed, size) = newest, Date().timeIntervalSince(changed) < 30 else { return nil }
        return size
    }

    private static func first(_ pattern: String, in file: URL) -> String? {
        guard let text = try? String(contentsOf: file, encoding: .utf8),
              let expression = try? NSRegularExpression(pattern: pattern),
              let match = expression.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let range = Range(match.range(at: 1), in: text)
        else { return nil }
        return String(text[range])
    }
}
