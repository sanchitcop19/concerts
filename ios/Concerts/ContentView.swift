import SwiftUI
import WebKit

/// The live dashboard. The app shows this page, so every data update or design
/// change on the website shows up in the app with no new build.
let siteURL = URL(string: "https://sanchitcop19.github.io/concerts/")!

/// Same near-black as the page's hero, so launch → page has no white flash.
let heroBlack = Color(red: 11 / 255, green: 10 / 255, blue: 16 / 255)

struct ContentView: View {
    @StateObject private var page = PageModel()

    var body: some View {
        ZStack {
            heroBlack.ignoresSafeArea()
            WebView(webView: page.webView)
                .ignoresSafeArea() // the page pads itself for the notch/status bar
                .opacity(page.loaded ? 1 : 0)
                .animation(.easeOut(duration: 0.25), value: page.loaded)

            if page.failed {
                VStack(spacing: 14) {
                    Image(systemName: "wifi.slash").font(.system(size: 34, weight: .semibold))
                    Text("Can't reach your concerts").font(.headline)
                    Text("Check your connection and try again.")
                        .font(.subheadline).foregroundStyle(.white.opacity(0.6))
                    Button("Try again") { page.load() }
                        .buttonStyle(.borderedProminent)
                        .tint(Color(red: 98 / 255, green: 80 / 255, blue: 214 / 255))
                        .padding(.top, 6)
                }
                .foregroundStyle(.white)
                .padding()
            } else if !page.loaded {
                ProgressView().tint(.white)
            }
        }
    }
}

struct WebView: UIViewRepresentable {
    let webView: WKWebView
    func makeUIView(context: Context) -> WKWebView { webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

@MainActor
final class PageModel: NSObject, ObservableObject, WKNavigationDelegate {
    @Published var loaded = false
    @Published var failed = false
    let webView: WKWebView
    private var triedCache = false

    override init() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default() // keeps the HTTP cache so the last page works offline
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()

        webView.navigationDelegate = self
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.allowsBackForwardNavigationGestures = true // swipe back from an artist/venue/city page

        let refresh = UIRefreshControl()
        refresh.tintColor = .white
        refresh.addTarget(self, action: #selector(pulledToRefresh), for: .valueChanged)
        webView.scrollView.refreshControl = refresh

        load()
    }

    func load() {
        failed = false
        triedCache = false
        webView.load(URLRequest(url: siteURL, cachePolicy: .useProtocolCachePolicy, timeoutInterval: 20))
    }

    @objc private func pulledToRefresh() {
        loaded ? webView.reload() : load()
    }

    // MARK: WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loaded = true
        failed = false
        webView.scrollView.refreshControl?.endRefreshing()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        handle(error)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handle(error)
    }

    private func handle(_ error: Error) {
        webView.scrollView.refreshControl?.endRefreshing()
        if (error as NSError).code == NSURLErrorCancelled { return }
        // Offline: fall back to the last copy we downloaded, if there is one.
        if !triedCache {
            triedCache = true
            webView.load(URLRequest(url: siteURL, cachePolicy: .returnCacheDataDontLoad))
            return
        }
        if !loaded { failed = true }
    }

    /// Links that leave the dashboard (e.g. a show's Concert Archives page) open in Safari.
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url,
           url.host != siteURL.host,
           navigationAction.navigationType == .linkActivated || navigationAction.targetFrame == nil {
            UIApplication.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
}
