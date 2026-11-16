// ytConvert masaüstü uygulaması.
// Arka planda launchd ile çalışan Flask sunucusunu (127.0.0.1:5001) native bir pencerede açar,
// indirilenleri ~/Downloads'a kaydeder.

import Cocoa
import WebKit

let serverURL = URL(string: "http://127.0.0.1:5001/")!
let agentLabel = "com.yigitsktas.ytconvert"
let supportedLink = try! NSRegularExpression(
    pattern: #"^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be|x\.com|twitter\.com|instagram\.com)/\S+$"#,
    options: [.caseInsensitive])

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKDownloadDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var lastDownload: URL?
    var retries = 0
    var lastClipboardChange = -1

    // MARK: - Pencere

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()

        let config = WKWebViewConfiguration()
        config.applicationNameForUserAgent = "ytConvertDesktop"
        config.userContentController.add(self, name: "reveal")

        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground") // yüklenirken beyaz flaş olmasın

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 760),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "ytConvert"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 420, height: 560)
        window.contentView = webView
        window.center()
        window.setFrameAutosaveName("ytConvertWindow")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        load()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window.makeKeyAndOrderFront(nil) }
        return true
    }

    // Pencere kapanınca uygulama kapanır; sunucu arka planda çalışmaya devam eder.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    // Uygulamaya dönünce panoda desteklenen bir link varsa kutuya otomatik yapıştır.
    func applicationDidBecomeActive(_ notification: Notification) {
        let pb = NSPasteboard.general
        guard pb.changeCount != lastClipboardChange,
              let text = pb.string(forType: .string)?.trimmingCharacters(in: .whitespacesAndNewlines),
              supportedLink.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
        else { return }
        // Sayfa henüz yüklenmediyse işlendi sayma; didFinish'te tekrar denenir.
        let change = pb.changeCount
        let js = "window.ytcPrefill ? (window.ytcPrefill(\(jsString(text))), true) : false"
        webView.evaluateJavaScript(js) { result, _ in
            if (result as? Bool) == true { self.lastClipboardChange = change }
        }
    }

    // MARK: - Sunucu bağlantısı

    @objc func load() {
        webView.load(URLRequest(url: serverURL))
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        retries += 1
        if retries == 1 { kickstartAgent() }
        if retries <= 15 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.load() }
        } else {
            retries = 0
            let alert = NSAlert()
            alert.messageText = "Sunucuya bağlanılamadı"
            alert.informativeText = "Arka plan servisi çalışmıyor olabilir. Proje klasöründe desktop/install.sh dosyasını tekrar çalıştır."
            alert.addButton(withTitle: "Tekrar dene")
            alert.addButton(withTitle: "Kapat")
            if alert.runModal() == .alertFirstButtonReturn { load() } else { NSApp.terminate(nil) }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        retries = 0
        applicationDidBecomeActive(Notification(name: NSApplication.didBecomeActiveNotification))
    }

    func kickstartAgent() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = ["kickstart", "gui/\(getuid())/\(agentLabel)"]
        try? p.run()
    }

    // MARK: - İndirme (blob <a download> → ~/Downloads)

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let dir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let target = uniqueURL(in: dir, name: suggestedFilename)
        lastDownload = target
        completionHandler(target)
    }

    func downloadDidFinish(_ download: WKDownload) {
        NSApp.requestUserAttention(.informationalRequest)
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let alert = NSAlert(error: error)
        alert.messageText = "Dosya kaydedilemedi"
        alert.runModal()
    }

    func uniqueURL(in dir: URL, name: String) -> URL {
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var url = dir.appendingPathComponent(name)
        var i = 1
        while FileManager.default.fileExists(atPath: url.path) {
            url = dir.appendingPathComponent("\(base) (\(i))").appendingPathExtension(ext)
            i += 1
        }
        return url
    }

    // Sayfadaki "Finder'da göster" butonu
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "reveal", let url = lastDownload {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        }
    }

    @objc func openDownloads() {
        NSWorkspace.shared.open(FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0])
    }

    // MARK: - yt-dlp güncelleme (YouTube değişince ilk çare)

    @objc func updateEngine() {
        guard let root = Bundle.main.object(forInfoDictionaryKey: "YTCProjectRoot") as? String else { return }
        let alert = NSAlert()
        alert.messageText = "İndirme motoru güncelleniyor…"
        alert.informativeText = "yt-dlp en son sürüme yükseltiliyor, birkaç saniye sürebilir."
        alert.addButton(withTitle: "Tamam")

        DispatchQueue.global().async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "\(root)/.venv/bin/pip")
            p.arguments = ["install", "-q", "--upgrade", "yt-dlp[default]"]
            let ok = (try? p.run()) != nil && { p.waitUntilExit(); return p.terminationStatus == 0 }()
            if ok {
                let k = Process()
                k.executableURL = URL(fileURLWithPath: "/bin/launchctl")
                k.arguments = ["kickstart", "-k", "gui/\(getuid())/\(agentLabel)"]
                try? k.run(); k.waitUntilExit()
            }
            DispatchQueue.main.async {
                let done = NSAlert()
                done.messageText = ok ? "Güncellendi" : "Güncelleme başarısız"
                done.informativeText = ok ? "yt-dlp güncel, servis yeniden başlatıldı." : "İnternet bağlantını kontrol et."
                done.runModal()
                self.load()
            }
        }
    }

    // MARK: - Menü (Cmd+V vb. için Edit menüsü şart)

    func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "ytConvert Hakkında", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "İndirme motorunu güncelle", action: #selector(updateEngine), keyEquivalent: "u")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "ytConvert'i Gizle", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "ytConvert'ten Çık", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Düzen")
        edit.addItem(withTitle: "Geri Al", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Yinele", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Kes", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Kopyala", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Yapıştır", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Tümünü Seç", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "Görünüm")
        view.addItem(withTitle: "Yenile", action: #selector(load), keyEquivalent: "r")
        view.addItem(withTitle: "İndirilenler Klasörü", action: #selector(openDownloads), keyEquivalent: "l")
        viewItem.submenu = view

        let windowItem = NSMenuItem(); main.addItem(windowItem)
        let win = NSMenu(title: "Pencere")
        win.addItem(withTitle: "Kapat", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        win.addItem(withTitle: "Küçült", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowItem.submenu = win
        NSApp.windowsMenu = win

        NSApp.mainMenu = main
    }

    func jsString(_ s: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [s])
        let arr = String(data: data, encoding: .utf8)!
        return String(arr.dropFirst().dropLast())
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
