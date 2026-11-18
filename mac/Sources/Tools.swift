// Finding Python, running small commands, and asking the port whether Arnheim answers.
import Darwin
import Foundation

struct Python {
    let path: String
    let version: String
}

/// What answers on the port: Arnheim, another program, something that takes the connection but says nothing
/// (an Arnheim still downloading its pictures, say), or nothing at all.
enum Answer {
    case arnheim, other, silent, nothing
}

/// The write end of the pipe the signal handler wakes the app with (AppDelegate.catchSignals).
var signalWriteEnd: Int32 = -1

final class Collected {
    private let lock = NSLock()
    private var data = Data()
    private let done = DispatchSemaphore(value: 0)

    func add(_ more: Data) {
        lock.lock()
        data.append(more)
        lock.unlock()
    }

    func finish() { done.signal() }

    func wait(_ seconds: Double) { _ = done.wait(timeout: .now() + seconds) }

    var text: String {
        lock.lock()
        defer { lock.unlock() }
        return String(decoding: data, as: UTF8.self)
    }
}

enum Tools {
    static let home = NSHomeDirectory()

    /// Runs a program and gives (its exit status, what it printed), or nil when it couldn't start or ran
    /// past `timeout` seconds (then it is stopped).
    static func run(_ path: String, _ arguments: [String], timeout: Double,
                    environment: [String: String]? = nil) -> (status: Int32, output: String)? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = arguments
        if let environment = environment { process.environment = environment }
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        let ended = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in ended.signal() }
        let collected = Collected()
        pipe.fileHandleForReading.readabilityHandler = { handle in
            let more = handle.availableData
            if more.isEmpty {
                handle.readabilityHandler = nil
                collected.finish()
            } else {
                collected.add(more)
            }
        }
        do {
            try process.run()
        } catch {
            pipe.fileHandleForReading.readabilityHandler = nil
            return nil
        }
        if ended.wait(timeout: .now() + timeout) == .timedOut {
            process.terminate()
            if ended.wait(timeout: .now() + 1) == .timedOut {
                kill(process.processIdentifier, SIGKILL)
                _ = ended.wait(timeout: .now() + 1)
            }
            pipe.fileHandleForReading.readabilityHandler = nil
            return nil
        }
        collected.wait(1)  // the last of what it printed
        pipe.fileHandleForReading.readabilityHandler = nil
        return (process.terminationStatus, collected.text)
    }

    /// The folders the person's own terminal looks in for programs (their login shell's PATH), then the usual
    /// places, so serve.py finds git, gh, claude and codex as it does in their terminal. An app opened from
    /// Finder gets only /usr/bin:/bin:/usr/sbin:/sbin.
    static func searchPath() -> [String] {
        let usual = ["\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        let own = (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map(String.init)
        var seen = Set<String>()
        var found: [String] = []
        for folder in shellPath() + own + usual {
            let clean = (folder as NSString).standardizingPath
            if clean.hasPrefix("/"), !seen.contains(clean) {
                seen.insert(clean)
                found.append(clean)
            }
        }
        return found
    }

    /// The PATH the person's login shell sets up, or none if it doesn't say within a few seconds.
    static func shellPath() -> [String] {
        var shell = ProcessInfo.processInfo.environment["SHELL"] ?? ""
        if !shell.hasPrefix("/") || !FileManager.default.isExecutableFile(atPath: shell) { shell = "/bin/zsh" }
        let mark = "_ARNHEIM_PATH_"
        guard let (_, output) = run(shell, ["-l", "-i", "-c", "printf '\\n\(mark)%s\(mark)\\n' \"$PATH\""], timeout: 6),
              let start = output.range(of: mark),
              let end = output.range(of: mark, range: start.upperBound..<output.endIndex)
        else { return [] }
        return output[start.upperBound..<end.lowerBound].split(separator: ":").map(String.init)
    }

    /// Whether Apple's command line tools (or Xcode) are in, so /usr/bin/python3 runs Python rather than
    /// offering to install them. xcode-select -p only says where they are: it never offers anything.
    static func developerToolsPresent() -> Bool {
        guard let (status, output) = run("/usr/bin/xcode-select", ["-p"], timeout: 10), status == 0 else { return false }
        let folder = output.trimmingCharacters(in: .whitespacesAndNewlines)
        return !folder.isEmpty && FileManager.default.isExecutableFile(atPath: folder + "/usr/bin/python3")
    }

    /// The first python3 that is 3.7 or newer: in the person's own PATH first, as `python3` in their terminal
    /// would be, then the usual places. Apple's /usr/bin/python3 counts only once the command line tools are
    /// in, so looking never brings up Apple's offer to install them. ARNHEIM_APP_PYTHON names one instead.
    static func findPython(in folders: [String]) -> Python? {
        if let given = ProcessInfo.processInfo.environment["ARNHEIM_APP_PYTHON"], !given.isEmpty {
            return check((given as NSString).expandingTildeInPath)
        }
        var tools: Bool?
        var tried = Set<String>()
        for folder in folders + ["/Library/Frameworks/Python.framework/Versions/Current/bin"] {
            let candidate = ((folder as NSString).appendingPathComponent("python3") as NSString).standardizingPath
            let real = URL(fileURLWithPath: candidate).resolvingSymlinksInPath().path
            guard !tried.contains(real), FileManager.default.isExecutableFile(atPath: candidate) else { continue }
            tried.insert(real)
            if real == "/usr/bin/python3" || candidate == "/usr/bin/python3" {
                if tools == nil { tools = developerToolsPresent() }
                if tools != true { continue }
            }
            if let python = check(candidate) { return python }
        }
        return nil
    }

    static func check(_ path: String) -> Python? {
        guard FileManager.default.isExecutableFile(atPath: path),
              let (status, output) = run(path, ["-I", "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"], timeout: 30),
              status == 0
        else { return nil }
        let version = output.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = version.split(separator: ".").compactMap { Int($0) }
        guard parts.count >= 2, parts[0] > 3 || (parts[0] == 3 && parts[1] >= 7) else { return nil }
        return Python(path: path, version: version)
    }

    /// Asks the port for /look, which only Arnheim answers with {"look": ...}. Plain sockets, so no proxy,
    /// cache or App Transport Security rule comes between.
    static func probe(port: Int, timeout: Int = 2) -> Answer {
        let socket = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard socket >= 0 else { return .nothing }
        defer { close(socket) }
        var one: Int32 = 1
        setsockopt(socket, SOL_SOCKET, SO_NOSIGPIPE, &one, socklen_t(MemoryLayout<Int32>.size))
        var wait = timeval(tv_sec: timeout, tv_usec: 0)
        setsockopt(socket, SOL_SOCKET, SO_RCVTIMEO, &wait, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(socket, SOL_SOCKET, SO_SNDTIMEO, &wait, socklen_t(MemoryLayout<timeval>.size))
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(port).bigEndian)
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        let connected = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(socket, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        if connected != 0 { return .nothing }
        let request = Array("GET /look HTTP/1.0\r\nHost: 127.0.0.1:\(port)\r\nUser-Agent: Arnheim app\r\n\r\n".utf8)
        let sent = request.withUnsafeBytes { send(socket, $0.baseAddress, $0.count, 0) }
        if sent != request.count { return .silent }
        var reply: [UInt8] = []
        var buffer = [UInt8](repeating: 0, count: 4096)
        let end = Date().addingTimeInterval(Double(timeout))
        while reply.count < 65536, Date() < end {
            let got = buffer.withUnsafeMutableBytes { recv(socket, $0.baseAddress, $0.count, 0) }
            if got <= 0 { break }
            reply.append(contentsOf: buffer[0..<got])
        }
        if reply.isEmpty { return .silent }
        let text = String(decoding: reply, as: UTF8.self)
        let first = text.prefix(while: { $0 != "\r" && $0 != "\n" }).split(separator: " ")
        guard first.count >= 2, first[0].hasPrefix("HTTP/"), first[1] == "200",
              let split = text.range(of: "\r\n\r\n") else { return .other }
        let body = Data(text[split.upperBound...].utf8)
        if let said = try? JSONSerialization.jsonObject(with: body) as? [String: Any], said["look"] is String {
            return .arnheim
        }
        return .other
    }

    static func alive(_ pid: pid_t) -> Bool {
        pid > 0 && (kill(pid, 0) == 0 || errno == EPERM)
    }

    /// A process's command line, as ps shows it, or "" when it has gone.
    static func commandLine(_ pid: pid_t) -> String {
        run("/bin/ps", ["-ww", "-p", "\(pid)", "-o", "command="], timeout: 5)?
            .output.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
}
