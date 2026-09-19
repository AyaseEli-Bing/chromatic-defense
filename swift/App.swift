// App.swift — 塔防 macOS App 壳
// 职责：NSWindow + WKWebView 渲染 HTML/JS + 启动 Python 子进程 + localhost socket 双向桥接
// 编译: swiftc -O -framework Cocoa -framework WebKit App.swift -o ../build/TowerDefense

import Cocoa
import WebKit
import Foundation

// ===== Socket 桥接：JS ↔ Swift ↔ Python =====
class GameBridge: NSObject, WKScriptMessageHandler {
    weak var webView: WKWebView?
    var sockFd: Int32 = -1
    var readBuffer = Data()
    let writeQueue = DispatchQueue(label: "td.write")
    let socketQueue = DispatchQueue(label: "td.socket")

    func setupScriptHandler(_ config: WKWebViewConfiguration) {
        let uc = config.userContentController
        uc.add(self, name: "cmd")
    }

    // JS → Swift → Python
    func userContentController(_ uc: WKUserContentController, didReceive message: WKScriptMessage) {
        if let body = message.body as? String {
            sendToPython(body)
        }
    }

    func connectToPython(host: String = "127.0.0.1", port: Int = 9876, retries: Int = 100) -> Bool {
        for i in 0..<retries {
            sockFd = socket(AF_INET, SOCK_STREAM, 0)
            if sockFd < 0 { Thread.sleep(forTimeInterval: 0.1); continue }
            var addr = sockaddr_in()
            addr.sin_family = sa_family_t(AF_INET)
            addr.sin_port = UInt16(port).bigEndian
            inet_pton(AF_INET, host, &addr.sin_addr)
            let result = withUnsafePointer(to: &addr) { ptr -> Int32 in
                ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                    connect(sockFd, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
            if result == 0 {
                NSLog("[swift] connected to python socket (attempt \(i+1))")
                // 验证连接可写：发一个 ping，若 Python 已 accept 会在 readLoop 收到响应
                let ping = "{\"type\":\"ping\"}\n"
                let pingData = ping.data(using: .utf8)!
                pingData.withUnsafeBytes { ptr in
                    _ = write(sockFd, ptr.baseAddress, pingData.count)
                }
                // 设置非阻塞
                let flags = fcntl(sockFd, F_GETFL, 0)
                _ = fcntl(sockFd, F_SETFL, flags | O_NONBLOCK)
                startReadLoop()
                return true
            }
            close(sockFd)
            sockFd = -1
            Thread.sleep(forTimeInterval: 0.1)
            if (i + 1) % 10 == 0 {
                NSLog("[swift] connect retry \(i+1)/\(retries)")
            }
        }
        return false
    }

    func startReadLoop() {
        socketQueue.async { [weak self] in
            guard let self = self else { return }
            var buf = [UInt8](repeating: 0, count: 65536)
            var idleTicks = 0
            while self.sockFd >= 0 {
                let n = read(self.sockFd, &buf, buf.count)
                if n > 0 {
                    idleTicks = 0
                    self.readBuffer.append(contentsOf: buf[0..<n])
                    self.processBuffer()
                } else if n == 0 {
                    // 对端关闭：可能是 Python 重启或初始化期间的临时断开，尝试重连一次
                    NSLog("[swift] python socket closed, attempting reconnect...")
                    close(self.sockFd)
                    self.sockFd = -1
                    Thread.sleep(forTimeInterval: 0.3)
                    if self.connectToPython() {
                        NSLog("[swift] reconnected to python")
                    } else {
                        NSLog("[swift] reconnect failed, giving up")
                    }
                    return
                } else {
                    if errno == EAGAIN || errno == EWOULDBLOCK {
                        Thread.sleep(forTimeInterval: 0.01)
                        idleTicks += 1
                        // 5 秒没收到任何数据，说明连接有问题，主动重连
                        if idleTicks > 500 {
                            NSLog("[swift] no data for 5s, reconnecting...")
                            close(self.sockFd)
                            self.sockFd = -1
                            if self.connectToPython() {
                                NSLog("[swift] reconnected after idle timeout")
                            }
                            return
                        }
                    } else {
                        NSLog("[swift] socket read error: \(errno)")
                        break
                    }
                }
            }
        }
    }

    func processBuffer() {
        while let idx = readBuffer.firstIndex(of: 0x0A) { // '\n'
            let lineData = readBuffer.subdata(in: 0..<idx)
            readBuffer.removeSubrange(0...idx)
            if let line = String(data: lineData, encoding: .utf8) {
                line.trimmingCharacters(in: .whitespacesAndNewlines)
                    .isEmpty ? () : dispatchToJS(line.trimmingCharacters(in: .whitespacesAndNewlines))
            }
        }
    }

    var stateDispatchLogged = false

    func dispatchToJS(_ json: String) {
        // 判断是 state 还是 resp
        DispatchQueue.main.async { [weak self] in
            guard let wv = self?.webView else { return }
            // 用 JSONSerialization 解析 type 字段，不依赖序列化的空格格式
            var typeName = ""
            if let data = json.data(using: .utf8),
               let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
               let t = obj["type"] as? String {
                typeName = t
            }
            let js: String
            if typeName == "state" {
                if self?.stateDispatchLogged == false {
                    NSLog("[swift] first state dispatched to JS (\(json.count) bytes)")
                    self?.stateDispatchLogged = true
                }
                js = "try{window.handleState(\(json));}catch(e){console.error('handleState:',e);}"
            } else if typeName == "resp" {
                js = "try{window.handleResp(\(json));}catch(e){console.error('handleResp:',e);}"
            } else {
                NSLog("[swift] unknown message (no type field), dropped")
                return
            }
            wv.evaluateJavaScript(js) { _, err in
                if let e = err { NSLog("[swift] evalJS error: \(e)") }
            }
        }
    }

    func sendToPython(_ json: String) {
        writeQueue.async { [weak self] in
            guard let self = self, self.sockFd >= 0 else { return }
            let payload = (json + "\n").data(using: .utf8)!
            payload.withUnsafeBytes { ptr in
                let _ = write(self.sockFd, ptr.baseAddress, payload.count)
            }
        }
    }

    func disconnect() {
        if sockFd >= 0 { close(sockFd); sockFd = -1 }
    }
}

// ===== AppDelegate =====
class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var bridge = GameBridge()
    var pythonProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let W = 900, H = 580
        window = NSWindow(contentRect: NSRect(x: 200, y: 200, width: W, height: H),
                          styleMask: [.titled, .closable, .miniaturizable],
                          backing: .buffered, defer: false)
        window.title = "塔防 · Chromatic Defense (8语言混搭版)"
        window.center()

        // WebView 配置
        let config = WKWebViewConfiguration()
        bridge.setupScriptHandler(config)
        webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        window.contentView = webView
        bridge.webView = webView

        // 启动 Python 子进程
        startPython()

        // 加载本地 HTML
        let htmlPath = Bundle.main.bundlePath + "/../../../web/index.html"
        var htmlURL = URL(fileURLWithPath: htmlPath)
        // 如果不在 bundle 里，用源码路径
        if !FileManager.default.fileExists(atPath: htmlPath) {
            let srcPath = ProcessInfo.processInfo.environment["TD_ROOT"]
                ?? FileManager.default.currentDirectoryPath + "/.."
            htmlURL = URL(fileURLWithPath: srcPath + "/web/index.html")
        }
        NSLog("[swift] loading: \(htmlURL.path)")
        webView.loadFileURL(htmlURL, allowingReadAccessTo: htmlURL.deletingLastPathComponent())

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // 异步连接 Python socket（等 Python 启动）
        DispatchQueue.global().async { [weak self] in
            let ok = self?.bridge.connectToPython() ?? false
            if !ok { NSLog("[swift] FAILED to connect python socket") }
        }
    }

    func startPython() {
        let root = ProcessInfo.processInfo.environment["TD_ROOT"]
            ?? (FileManager.default.currentDirectoryPath + "/..")
        let pyPath = root + "/python/main.py"
        let pyExe = ProcessInfo.processInfo.environment["TD_PYTHON"]
            ?? "/Users/bing1111/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

        let p = Process()
        p.executableURL = URL(fileURLWithPath: pyExe)
        p.arguments = [pyPath]
        var env = ProcessInfo.processInfo.environment
        env["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib"
        env["PYTHONPATH"] = root + "/python"
        env["TD_ROOT"] = root
        p.environment = env
        p.standardOutput = FileHandle.standardOutput
        p.standardError = FileHandle.standardError

        do {
            try p.run()
            pythonProcess = p
            NSLog("[swift] python started pid=\(p.processIdentifier)")
        } catch {
            NSLog("[swift] failed to start python: \(error)")
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        pythonProcess?.terminate()
        bridge.disconnect()
    }
}

extension AppDelegate: WKNavigationDelegate {
    func webView(_ wb: WKWebView, didFinish navigation: WKNavigation!) {
        NSLog("[swift] webview loaded")
    }
}

// ===== main =====
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
