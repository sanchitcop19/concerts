import SwiftUI
import WebKit

/// The live dashboard. Each tab shows one part of it (?view=…), so every data
/// update or design change on the website shows up in the app with no new build.
let siteRoot = "https://sanchitcop19.github.io/concerts/"

/// Same near-black as the page's hero, so launch → page has no white flash.
let heroBlack = Color(red: 11 / 255, green: 10 / 255, blue: 16 / 255)

enum AppTab: String, CaseIterable, Identifiable {
    case home, stats, years, shows
    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: return "Home"
        case .stats: return "Stats"
        case .years: return "Years"
        case .shows: return "Shows"
        }
    }

    var icon: String {
        switch self {
        case .home: return "ticket.fill"
        case .stats: return "chart.bar.fill"
        case .years: return "calendar"
        case .shows: return "music.note.list"
        }
    }

    var url: URL { URL(string: "\(siteRoot)?view=\(rawValue)")! }
}

struct ContentView: View {
    // One web view per tab, so each keeps its own scroll position and back history.
    @StateObject private var home = PageModel(url: AppTab.home.url)
    @StateObject private var stats = PageModel(url: AppTab.stats.url)
    @StateObject private var years = PageModel(url: AppTab.years.url)
    @StateObject private var shows = PageModel(url: AppTab.shows.url)
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        TabView {
            ForEach(AppTab.allCases) { tab in
                TabPage(page: model(for: tab))
                    .tabItem { Label(tab.title, systemImage: tab.icon) }
                    .tag(tab)
            }
        }
        .tint(Color(red: 144 / 255, green: 133 / 255, blue: 233 / 255))
        // No pull-to-refresh (the page doesn't bounce), so refresh when you come back to the app.
        .onChange(of: scenePhase) { phase in
            if phase == .active {
                AppTab.allCases.forEach { model(for: $0).refreshIfStale() }
            }
        }
    }

    private func model(for tab: AppTab) -> PageModel {
        switch tab {
        case .home: return home
        case .stats: return stats
        case .years: return years
        case .shows: return shows
        }
    }
}

struct TabPage: View {
    @ObservedObject var page: PageModel

    var body: some View {
        ZStack {
            heroBlack.ignoresSafeArea()
            WebView(webView: page.webView)
                // Run under the status bar (the page pads itself for it), but stop above the tab bar.
                .ignoresSafeArea(edges: .top)
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
    let url: URL
    let webView: WKWebView
    private var triedCache = false
    private var lastLoaded = Date.distantPast

    init(url: URL) {
        self.url = url
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default() // keeps the HTTP cache so the last page works offline
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()

        webView.navigationDelegate = self
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        // No rubber-band: pulling past the top or bottom doesn't reveal empty space.
        webView.scrollView.bounces = false
        webView.allowsBackForwardNavigationGestures = true // swipe back from an artist/venue/concert page

        load()
    }

    func load() {
        failed = false
        triedCache = false
        webView.load(URLRequest(url: url, cachePolicy: .useProtocolCachePolicy, timeoutInterval: 20))
    }

    /// Reload if this tab hasn't been refreshed for a minute (called when the app comes back to the foreground).
    func refreshIfStale() {
        guard Date().timeIntervalSince(lastLoaded) > 60 else { return }
        if loaded {
            webView.reload()
        } else {
            load()
        }
    }

    // MARK: WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loaded = true
        failed = false
        lastLoaded = Date()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        handle(error)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handle(error)
    }

    private func handle(_ error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        // Offline: fall back to the last copy we downloaded, if there is one.
        if !triedCache {
            triedCache = true
            webView.load(URLRequest(url: url, cachePolicy: .returnCacheDataDontLoad))
            return
        }
        if !loaded { failed = true }
    }

    /// Links that leave the dashboard (e.g. a show's Concert Archives page) open in Safari.
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationAction: WKNavigationAction) async -> WKNavigationActionPolicy {
        if let target = navigationAction.request.url,
           target.host != url.host,
           navigationAction.navigationType == .linkActivated || navigationAction.targetFrame == nil {
            _ = await UIApplication.shared.open(target)
            return .cancel
        }
        return .allow
    }
}
