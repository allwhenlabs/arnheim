// The app itself: puts Arnheim's files in place, runs serve.py, opens the page, and keeps it going.
import AppKit
import ServiceManagement

enum Phase: Equatable {
    case starting(String)  // getting ready, or serve.py started and not answering yet: what is happening, in words
    case running  // this app's serve.py answers
    case waitingOther  // something on the port takes connections but doesn't answer yet (another copy starting)
    case elsewhere  // an Arnheim this app didn't start answers on the port
    case gone  // ...and has stopped since
    case needsPython(Bool)  // no Python 3.7 or newer; true while Apple's command line tools are being installed
    case stopped(String)  // why, in words
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let places = Places.current()
    let bundled = Bundled.load()
    let work = DispatchQueue(label: "org.arnheim.app.work", qos: .userInitiated)
    var statusItem: NSStatusItem?
    let statusLine = NSMenuItem(title: "Getting Arnheim ready", action: nil, keyEquivalent: "")
    var loginItem: NSMenuItem?
    var phase: Phase = .starting("Getting Arnheim ready") {
        didSet { if phase != oldValue { show() } }
    }
    var server: Process?
    var serverStarted = Date()
    var restarts: [Date] = []
    var quitting = false
    var openWhenReady = true
    var fragment = ""  // where on the page to open: "" for the building, "#/" for the Overview
    var python: Python?
    var folders: [String]?
    var environment: [String: String] = [:]
    var picturesBytes: Int64 = 0
    var fraction: Double?
    var timer: Timer?
    var probing = false
    var ticks = 0
    var misses = 0
    var waitingSince = Date()
    var window: StartWindow?
    var signalSource: DispatchSourceRead?
    let clock: DateFormatter = {
        let format = DateFormatter()
        format.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return format
    }()

    // MARK: starting

    func applicationDidFinishLaunching(_ notification: Notification) {
        catchSignals()
        if launchedAtLogin() { openWhenReady = false }  // at login it starts quietly, without a browser tab
        try? FileManager.default.createDirectory(at: places.logs, withIntermediateDirectories: true)
        tidyLog()
        makeMenu()
        say("Arnheim app starting" + (bundled.map { ", with Arnheim \($0.commit)" } ?? "")
            + ". Port \(places.port); Arnheim's files in \(places.app.path).")
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
            guard let self = self, self.openWhenReady, self.window == nil else { return }
            if self.phase != .running, self.phase != .elsewhere, !self.phase.isNeedsPython { self.showWindow() }
        }
        begin()
    }

    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }

    /// Opening the app again (a double-click while it runs) opens the page.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        ask("")
        return false
    }

    func launchedAtLogin() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent,
              event.eventID == AEEventID(kAEOpenApplication) else { return false }
        return event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue == OSType(keyAELaunchedAsLogInItem)
    }

    /// Starts Arnheim, unless one already answers on the port: then that one is opened.
    func begin() {
        guard !quitting, server == nil else { return }
        let port = places.port
        work.async { [weak self] in
            guard let self = self else { return }
            self.clearLeftover()
            let answer = Tools.probe(port: port)
            DispatchQueue.main.async { self.found(answer) }
        }
    }

    func found(_ answer: Answer) {
        guard !quitting, server == nil else { return }
        switch answer {
        case .arnheim: elsewhere()
        case .other: portTaken()
        case .silent:
            waitingSince = Date()
            phase = .waitingOther
        case .nothing: prepare()
        }
    }

    /// Puts Arnheim's files in place, finds Python (once), then starts serve.py.
    func prepare() {
        guard !quitting, server == nil else { return }
        guard let bundled = bundled else {
            phase = .stopped("This copy of the app has no Arnheim inside. Download it again.")
            return
        }
        phase = .starting("Getting Arnheim ready")
        let places = self.places, known = python, knownFolders = folders
        work.async { [weak self] in
            guard let self = self else { return }
            var trouble: String?
            do {
                if let did = try Install.ensure(bundled, places) { self.say(did) }
            } catch {
                trouble = "Arnheim's files couldn't be put in place: \(error.localizedDescription)"
            }
            let search = knownFolders ?? Tools.searchPath()
            let found = trouble == nil ? (known ?? Tools.findPython(in: search)) : nil
            let bytes = Install.picturesBytes(places.app.appendingPathComponent("serve.py"))
            DispatchQueue.main.async {
                self.folders = search
                if let trouble = trouble {
                    self.say(trouble)
                    self.phase = .stopped(trouble)
                    return
                }
                guard let found = found else {
                    self.needPython()
                    return
                }
                self.picturesBytes = bytes
                self.python = found
                self.environment = AppDelegate.childEnvironment(search)
                self.launch(found)
            }
        }
    }

    func launch(_ python: Python) {
        guard !quitting, server == nil else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python.path)
        process.arguments = [places.app.appendingPathComponent("serve.py").path, "--no-browser", String(places.port)]
        process.currentDirectoryURL = places.app
        process.environment = environment
        let output = appendingLog()
        process.standardOutput = output ?? FileHandle.nullDevice
        process.standardError = output ?? FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        process.terminationHandler = { [weak self] ended in
            AppDelegate.onMainLoop { self?.ended(ended) }
        }
        do {
            try process.run()
        } catch {
            try? output?.close()
            let why = "Python couldn't start Arnheim: \(error.localizedDescription)"
            say(why)
            phase = .stopped(why)
            return
        }
        try? output?.close()  // serve.py has its own copy
        server = process
        serverStarted = Date()
        waitingSince = Date()
        fraction = nil
        try? "\(getpid()) \(process.processIdentifier)\n".write(to: places.pidFile, atomically: true, encoding: .utf8)
        say("Started serve.py with \(python.path) (Python \(python.version)), process \(process.processIdentifier).")
        phase = .starting("Starting Arnheim")
    }

    static func childEnvironment(_ folders: [String]) -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        for name in ["PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__",
                     "ARNHEIM_ALWAYS", "ARNHEIM_APP_HOME", "ARNHEIM_APP_PORT", "ARNHEIM_APP_NO_OPEN", "ARNHEIM_APP_PYTHON"] {
            environment.removeValue(forKey: name)
        }
        environment["PATH"] = folders.joined(separator: ":")
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["ARNHEIM_NO_BROWSER"] = "1"
        return environment
    }

    /// A serve.py this app started and left running when it went (a crash, say) holds the port: it is stopped,
    /// so this app runs its own. One that another copy of this app still runs is left alone. On the work queue.
    func clearLeftover() {
        guard let text = try? String(contentsOf: places.pidFile, encoding: .utf8) else { return }
        let ids = text.split(whereSeparator: { $0 == " " || $0.isNewline }).compactMap { pid_t(String($0)) }
        if ids.count == 2 {
            let (owner, child) = (ids[0], ids[1])
            if owner != getpid(), Tools.alive(owner), Tools.commandLine(owner).contains("/Contents/MacOS/Arnheim") {
                return  // another copy of this app runs it
            }
            let serve = places.app.appendingPathComponent("serve.py").path
            if Tools.alive(child), Tools.commandLine(child).contains(serve) {
                say("Stopping serve.py (process \(child)), left running by an earlier start of this app.")
                kill(child, SIGTERM)
                for _ in 0..<50 where Tools.alive(child) { usleep(100_000) }
                if Tools.alive(child) {
                    kill(child, SIGKILL)
                    usleep(300_000)
                }
                killpg(child, SIGTERM)  // and what it left running
            }
        }
        try? FileManager.default.removeItem(at: places.pidFile)
    }

    // MARK: watching

    func tick() {
        guard !quitting else { return }
        ticks += 1
        switch phase {
        case .starting where server != nil:
            watchDownload()
            guard !probing else { return }
            probe { [weak self] answer in
                guard let self = self, self.server != nil, case .starting = self.phase else { return }
                if answer == .arnheim { self.ready() }
            }
        case .waitingOther:
            guard !probing else { return }
            probe { [weak self] answer in
                guard let self = self, self.phase == .waitingOther, self.server == nil else { return }
                switch answer {
                case .arnheim: self.elsewhere()
                case .nothing: self.prepare()
                case .other: self.portTaken()
                case .silent:
                    if Date().timeIntervalSince(self.waitingSince) > 600 {
                        self.phase = .stopped("Something on port \(self.places.port) takes connections but doesn't answer. "
                                              + "Quit it, then choose Open Arnheim.")
                    }
                }
            }
        case .elsewhere, .gone:
            guard ticks % 5 == 0, !probing else { return }
            probe { [weak self] answer in
                guard let self = self, self.server == nil else { return }
                if answer == .arnheim {
                    self.misses = 0
                    if self.phase == .gone { self.phase = .elsewhere }
                } else if self.phase == .elsewhere {
                    self.misses += 1
                    if self.misses >= 2 {
                        self.phase = .gone
                        self.say("The Arnheim started outside this app no longer answers. Open Arnheim starts one here.")
                    }
                }
            }
        default:
            break
        }
    }

    /// The pictures' download, as serve.py makes it, shown as it goes (the first start only).
    func watchDownload() {
        if picturesBytes > 0, let got = Install.downloaded(places.app) {
            if got >= picturesBytes {
                fraction = nil
                phase = .starting("Unpacking the pictures")
            } else {
                fraction = Double(got) / Double(picturesBytes)
                phase = .starting("Downloading the pictures, once: \(got / 1_000_000) of \(picturesBytes / 1_000_000) MB")
            }
            waitingSince = Date()
        } else if Date().timeIntervalSince(waitingSince) > 300 {
            fraction = nil
            phase = .starting("Still starting. Show the log to see what it says.")
        }
    }

    func probe(_ then: @escaping (Answer) -> Void) {
        probing = true
        let port = places.port
        work.async { [weak self] in
            let answer = Tools.probe(port: port)
            DispatchQueue.main.async {
                self?.probing = false
                then(answer)
            }
        }
    }

    func ready() {
        fraction = nil
        phase = .running
        say("Arnheim answers at \(places.page().absoluteString)")
        if openWhenReady {
            openWhenReady = false
            openPage(fragment)
        }
        closeWindow()
    }

    func elsewhere() {
        misses = 0
        phase = .elsewhere
        say("Arnheim already answers on port \(places.port), started outside this app, so this app doesn't start another.")
        if openWhenReady {
            openWhenReady = false
            openPage(fragment)
        }
        closeWindow()
    }

    func portTaken() {
        let why = "Port \(places.port) is used by another program, so Arnheim can't start. Quit that program, then choose Open Arnheim."
        say(why)
        phase = .stopped(why)
    }

    func ended(_ process: Process) {
        guard process === server else { return }
        server = nil
        let group = process.processIdentifier  // serve.py leads a process group of its own
        if group > 1, group != getpgrp(), killpg(group, SIGTERM) == 0 {
            say("Stopped what serve.py left running.")
        }
        try? FileManager.default.removeItem(at: places.pidFile)
        if quitting {
            say("serve.py has stopped.")
            NSApp.reply(toApplicationShouldTerminate: true)
            return
        }
        let how = process.terminationReason == .uncaughtSignal
            ? "was stopped (signal \(process.terminationStatus))" : "stopped (exit status \(process.terminationStatus))"
        say("serve.py \(how).")
        if Date().timeIntervalSince(serverStarted) > 300 { restarts.removeAll() }  // it had been running a while
        let last = lastWords()
        probe { [weak self] answer in
            guard let self = self, !self.quitting, self.server == nil else { return }
            switch answer {
            case .arnheim: self.elsewhere()
            case .other: self.portTaken()
            case .silent:
                self.waitingSince = Date()
                self.phase = .waitingOther
            case .nothing: self.again(last)
            }
        }
    }

    /// serve.py stopped by itself: start it again a few times, waiting longer each time, then say so.
    func again(_ last: String?) {
        let waits: [Double] = [2, 5, 15, 30]
        guard restarts.count < waits.count else {
            let why = "Arnheim stopped and didn't start again." + (last.map { " The log ends: \($0)" } ?? "")
            say("Gave up after \(waits.count) tries. \(why)")
            phase = .stopped(why + " Open Arnheim tries again.")
            return
        }
        let wait = waits[restarts.count]
        restarts.append(Date())
        phase = .starting("Arnheim stopped. Starting it again in \(Int(wait)) seconds")
        say("Starting serve.py again in \(Int(wait)) seconds (try \(restarts.count) of \(waits.count)).")
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) { [weak self] in
            guard let self = self, !self.quitting, self.server == nil, case .starting = self.phase else { return }
            self.begin()
        }
    }

    // MARK: no Python

    func needPython() {
        phase = .needsPython(false)
        say("No Python 3.7 or newer was found. Apple's command line tools bring one.")
        closeWindow()
        guard !places.quiet else { return }
        activate()
        let alert = NSAlert()
        alert.messageText = "Arnheim needs Python"
        alert.informativeText = "Arnheim runs on Python, which comes with Apple's free command line tools. Choose Install "
            + "and follow Apple's window: it takes a few minutes. Arnheim starts by itself once they are in."
        alert.addButton(withTitle: "Install")
        alert.addButton(withTitle: "Quit Arnheim")
        guard alert.runModal() == .alertFirstButtonReturn else {
            NSApp.terminate(nil)
            return
        }
        say("Asking macOS to install Apple's command line tools (xcode-select --install).")
        work.async { _ = Tools.run("/usr/bin/xcode-select", ["--install"], timeout: 30) }
        openWhenReady = true
        phase = .needsPython(true)
        lookForPython()
    }

    func lookForPython() {
        let known = folders
        work.asyncAfter(deadline: .now() + 10) { [weak self] in
            let found = Tools.findPython(in: known ?? Tools.searchPath())
            DispatchQueue.main.async {
                guard let self = self, !self.quitting, self.phase == .needsPython(true) else { return }
                if let found = found {
                    self.say("Python is here now (\(found.path)): starting Arnheim.")
                    self.python = found
                    self.prepare()
                } else {
                    self.lookForPython()
                }
            }
        }
    }

    // MARK: the menu

    func makeMenu() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = Icons.menuBar()
        item.button?.toolTip = "Arnheim"
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        statusLine.isEnabled = false
        menu.addItem(statusLine)
        menu.addItem(.separator())
        menu.addItem(entry("Open Arnheim", #selector(openArnheim), "o"))
        menu.addItem(entry("Connect my agents", #selector(connectAgents), ""))
        menu.addItem(.separator())
        let login = entry("Start at login", #selector(toggleLogin), "")
        loginItem = login
        menu.addItem(login)
        menu.addItem(entry("Show the log", #selector(showLog), ""))
        menu.addItem(.separator())
        menu.addItem(entry("Quit Arnheim", #selector(quit), "q"))
        item.menu = menu
        statusItem = item
        refreshLogin()
        show()
    }

    func entry(_ title: String, _ action: Selector, _ key: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    func menuNeedsUpdate(_ menu: NSMenu) { refreshLogin() }

    /// The menu's first line and the window, as things stand.
    func show() {
        var heading = "Starting Arnheim"
        var busy = true
        let text: String
        switch phase {
        case .starting(let detail): text = detail
        case .running: text = "Arnheim is running"
        case .elsewhere: text = "Arnheim is running (started outside this app)"
        case .gone: text = "Arnheim isn't running. Open Arnheim starts it."
        case .waitingOther: text = "Waiting for the Arnheim starting on port \(places.port)"
        case .needsPython(let installing):
            heading = "Arnheim needs Python"
            text = installing ? "Waiting for Apple's command line tools to finish installing" : "Arnheim needs Python 3.7 or newer"
        case .stopped(let why):
            heading = "Arnheim stopped"
            text = why
            busy = false
        }
        statusLine.title = text.count > 72 ? String(text.prefix(70)) + "…" : text
        statusLine.toolTip = text
        statusItem?.button?.appearsDisabled = !(phase == .running || phase == .elsewhere)
        window?.update(heading: heading, detail: text, fraction: fraction, busy: busy)
    }

    @objc func openArnheim() { ask("") }

    /// The Overview, where the page shows how to connect your agents.
    @objc func connectAgents() { ask("#/") }

    func ask(_ fragment: String) {
        switch phase {
        case .running, .elsewhere:
            openPage(fragment)
        case .stopped, .gone:
            self.fragment = fragment
            openWhenReady = true
            restarts.removeAll()
            phase = .starting("Starting Arnheim")
            showWindow()
            begin()
        case .needsPython(let installing):
            if installing {
                self.fragment = fragment
                openWhenReady = true
            } else {
                needPython()
            }
        case .starting, .waitingOther:
            self.fragment = fragment
            openWhenReady = true
            showWindow()
        }
    }

    func refreshLogin() {
        guard let item = loginItem else { return }
        if places.testing {  // a test never touches the login item
            item.isEnabled = false
            item.state = .off
            item.toolTip = "Left alone while ARNHEIM_APP_HOME is set."
            return
        }
        item.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    @objc func toggleLogin() {
        guard !places.testing else {
            say("Start at login is left alone while ARNHEIM_APP_HOME is set.")
            return
        }
        let service = SMAppService.mainApp
        let on = service.status == .enabled
        if !on, Bundle.main.bundlePath.contains("/AppTranslocation/") {
            tell("Move Arnheim to Applications first",
                 "macOS is running Arnheim from a temporary place, because it was opened where it was downloaded. Quit "
                 + "Arnheim, drag it into your Applications folder, open it from there, then choose Start at login again.")
            return
        }
        do {
            if on {
                try service.unregister()
                say("Arnheim no longer starts at login.")
            } else {
                try service.register()
                say("Arnheim starts at login now.")
            }
        } catch {
            if service.status != .requiresApproval {
                say("Start at login didn't change: \(error.localizedDescription)")
                tell("Start at login didn't change", error.localizedDescription)
            }
        }
        if service.status == .requiresApproval {
            tell("Allow Arnheim to start at login",
                 "macOS asks you to allow it first: in System Settings, General, Login Items, switch Arnheim on.")
            SMAppService.openSystemSettingsLoginItems()
        }
        refreshLogin()
    }

    @objc func showLog() {
        let files = FileManager.default
        if !files.fileExists(atPath: places.log.path) { files.createFile(atPath: places.log.path, contents: nil) }
        if places.quiet {
            say("The log is \(places.log.path) (left closed: ARNHEIM_APP_NO_OPEN is set).")
            return
        }
        NSWorkspace.shared.open(places.log)
    }

    @objc func quit() { NSApp.terminate(nil) }

    // MARK: stopping

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return server?.isRunning == true ? .terminateLater : .terminateNow }
        quitting = true
        timer?.invalidate()
        closeWindow()
        guard let server = server, server.isRunning else { return .terminateNow }
        let pid = server.processIdentifier
        say("Stopping serve.py (process \(pid)).")
        kill(pid, SIGTERM)
        // While macOS waits for the reply, the run loop runs in the modal panel mode, and the main dispatch queue
        // may be busy with whatever asked the app to quit: so a run loop timer, and no dispatch.
        let deadline = Timer(timeInterval: 8, repeats: false) { [weak self] _ in
            guard let self = self, let server = self.server, server.isRunning else { return }
            self.say("serve.py didn't stop within 8 seconds, so it is stopped at once.")
            kill(server.processIdentifier, SIGKILL)
        }
        RunLoop.main.add(deadline, forMode: .common)
        RunLoop.main.add(deadline, forMode: .modalPanel)
        return .terminateLater
    }

    /// Runs a block on the main thread from the run loop, in every mode the app may be in while it quits, rather
    /// than through the main dispatch queue (see applicationShouldTerminate). Safe from any thread.
    static func onMainLoop(_ block: @escaping () -> Void) {
        let modes = [CFRunLoopMode.commonModes.rawValue, RunLoop.Mode.modalPanel.rawValue as CFString] as CFArray
        CFRunLoopPerformBlock(CFRunLoopGetMain(), modes, block)
        CFRunLoopWakeUp(CFRunLoopGetMain())
    }

    func applicationWillTerminate(_ notification: Notification) {
        say("The Arnheim app has quit.")
    }

    /// SIGTERM, SIGINT and SIGHUP stop serve.py first, as Quit does. The handler only writes a byte to a pipe,
    /// which the main queue reads; children start with the usual handling of every signal.
    func catchSignals() {
        var ends: [Int32] = [-1, -1]
        guard pipe(&ends) == 0 else { return }
        for end in ends { _ = fcntl(end, F_SETFD, FD_CLOEXEC) }
        _ = fcntl(ends[1], F_SETFL, O_NONBLOCK)
        signalWriteEnd = ends[1]
        for number in [SIGTERM, SIGINT, SIGHUP] {
            var action = sigaction()
            action.__sigaction_u.__sa_handler = { _ in
                var byte: UInt8 = 1
                _ = write(signalWriteEnd, &byte, 1)
            }
            sigemptyset(&action.sa_mask)
            action.sa_flags = SA_RESTART
            sigaction(number, &action, nil)
        }
        let reader = ends[0]
        let source = DispatchSource.makeReadSource(fileDescriptor: reader, queue: .main)
        source.setEventHandler { [weak self] in
            var buffer = [UInt8](repeating: 0, count: 16)
            _ = read(reader, &buffer, buffer.count)
            self?.say("Asked to stop: stopping Arnheim, then the app.")
            // From the run loop, not from inside this dispatch block: quitting waits for serve.py, and that news
            // must still get through (applicationShouldTerminate).
            NSApp.perform(#selector(NSApplication.terminate(_:)), with: nil, afterDelay: 0, inModes: [.default, .modalPanel])
        }
        source.resume()
        signalSource = source
    }

    // MARK: windows, the browser and the log

    func showWindow() {
        guard !places.quiet else { return }
        if window == nil {
            window = StartWindow(showLog: { [weak self] in self?.showLog() }, closed: { [weak self] in self?.window = nil })
        }
        show()
        window?.show()
    }

    func closeWindow() {
        window?.close()
        window = nil
    }

    func activate() {
        if #available(macOS 14.0, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    func tell(_ heading: String, _ detail: String) {
        say("\(heading). \(detail)")
        guard !places.quiet else { return }
        activate()
        let alert = NSAlert()
        alert.messageText = heading
        alert.informativeText = detail
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    func openPage(_ fragment: String) {
        let url = places.page(fragment)
        if places.quiet {
            say("Opening \(url.absoluteString) (left closed: ARNHEIM_APP_NO_OPEN is set).")
            return
        }
        say("Opening \(url.absoluteString)")
        NSWorkspace.shared.open(url)
    }

    func appendingLog() -> FileHandle? {
        let descriptor = open(places.log.path, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0o644)
        return descriptor >= 0 ? FileHandle(fileDescriptor: descriptor, closeOnDealloc: true) : nil
    }

    /// A line of what the app did, in the log beside what serve.py says, and on its own output.
    func say(_ line: String) {
        let stamped = "[Arnheim app \(clock.string(from: Date()))] \(line)\n"
        FileHandle.standardOutput.write(Data(stamped.utf8))
        let descriptor = open(places.log.path, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0o644)
        guard descriptor >= 0 else { return }
        let bytes = Array(stamped.utf8)
        _ = bytes.withUnsafeBytes { write(descriptor, $0.baseAddress, $0.count) }
        close(descriptor)
    }

    /// A log past 5 MB starts again, the old one kept as serve.old.log.
    func tidyLog() {
        let files = FileManager.default
        guard let size = (try? files.attributesOfItem(atPath: places.log.path))?[.size] as? NSNumber,
              size.int64Value > 5_000_000 else { return }
        let old = places.logs.appendingPathComponent("serve.old.log")
        try? files.removeItem(at: old)
        try? files.moveItem(at: places.log, to: old)
    }

    /// The last line serve.py wrote, to say why it stopped.
    func lastWords() -> String? {
        guard let handle = try? FileHandle(forReadingFrom: places.log) else { return nil }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        try? handle.seek(toOffset: size > 8192 ? size - 8192 : 0)
        let text = String(decoding: handle.readDataToEndOfFile(), as: UTF8.self)
        let line = text.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .last { !$0.isEmpty && !$0.hasPrefix("[Arnheim app") }
        return line.map { $0.count > 160 ? String($0.prefix(158)) + "…" : $0 }
    }
}

extension Phase {
    var isNeedsPython: Bool {
        if case .needsPython = self { return true }
        return false
    }
}
