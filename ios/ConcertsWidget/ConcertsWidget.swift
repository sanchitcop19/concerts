import SwiftUI
import WidgetKit

// Home screen + lock screen widget: your next show with a countdown, and how many shows you've been to.
// Data comes from data/widget.json on the website (written at every deploy), checked about once an hour.

private let feedURL = URL(string: "https://sanchitcop19.github.io/concerts/data/widget.json")!
private let cacheKey = "widget.json"

private let bg = Color(red: 11 / 255, green: 10 / 255, blue: 16 / 255)
private let accent = Color(red: 144 / 255, green: 133 / 255, blue: 233 / 255)

// MARK: Data

struct Show: Codable, Hashable {
    let date: String // yyyy-MM-dd
    let title: String
    let with: [String]
    let venue: String
    let city: String
    let id: String
    var start: String? = nil // "20:00", from Ticketmaster
    var doors: String? = nil

    /// "Doors 7 PM", or "Starts 8 PM" when only the show time is known.
    var timeLabel: String? {
        if let d = doors.flatMap(clock) { return "Doors \(d)" }
        if let s = start.flatMap(clock) { return "Starts \(s)" }
        return nil
    }

    var day: Date? {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: date)
    }

    var link: URL { URL(string: "stubs://show/\(id)")! }
}

struct Feed: Codable {
    let attended: Int
    let upcoming: [Show]
}

struct Entry: TimelineEntry {
    let date: Date
    let attended: Int
    let next: [Show]
}

extension Entry {
    /// Shows dated before `now` have happened, so they move from "next" into the count.
    init(feed: Feed, now: Date) {
        let today = Calendar.current.startOfDay(for: now)
        var passed = 0
        var next: [Show] = []
        for s in feed.upcoming {
            guard let d = s.day else { continue }
            if d < today { passed += 1 } else { next.append(s) }
        }
        self.init(date: now, attended: feed.attended + passed, next: next)
    }

    static let sample = Entry(date: Date(), attended: 318, next: [
        Show(date: "2026-11-15", title: "Russian Circles", with: ["Primitive Man"], venue: "The Showbox", city: "Seattle", id: ""),
        Show(date: "2026-12-11", title: "The Pineapple Thief", with: [], venue: "Neptune Theatre", city: "Seattle", id: ""),
    ])
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> Entry { .sample }

    func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
        if context.isPreview, cachedFeed() == nil { return completion(.sample) }
        Task { completion(Entry(feed: await loadFeed() ?? Feed(attended: 0, upcoming: []), now: Date())) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
        Task {
            let feed = await loadFeed() ?? Feed(attended: 0, upcoming: [])
            let now = Date()
            let cal = Calendar.current
            // One entry now and one at each of the next midnights, so "Tomorrow" becomes "Tonight" on time
            // even if the next refresh is late. Ask for fresh data in an hour.
            var entries = [Entry(feed: feed, now: now)]
            var day = cal.startOfDay(for: now)
            for _ in 0..<3 {
                day = cal.date(byAdding: .day, value: 1, to: day)!
                entries.append(Entry(feed: feed, now: day))
            }
            completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(60 * 60))))
        }
    }

    private func loadFeed() async -> Feed? {
        var req = URLRequest(url: feedURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        req.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        if let (data, resp) = try? await URLSession.shared.data(for: req),
           (resp as? HTTPURLResponse)?.statusCode == 200,
           let feed = try? JSONDecoder().decode(Feed.self, from: data) {
            UserDefaults.standard.set(data, forKey: cacheKey)
            return feed
        }
        return cachedFeed() // offline: use the last copy
    }

    private func cachedFeed() -> Feed? {
        guard let data = UserDefaults.standard.data(forKey: cacheKey) else { return nil }
        return try? JSONDecoder().decode(Feed.self, from: data)
    }
}

// MARK: Labels

/// "Tonight", "Tomorrow", "Friday", "In 12 days".
func whenLabel(_ show: Show, from now: Date) -> String {
    guard let d = show.day else { return "" }
    let cal = Calendar.current
    let days = cal.dateComponents([.day], from: cal.startOfDay(for: now), to: d).day ?? 0
    switch days {
    case ..<1: return "Tonight"
    case 1: return "Tomorrow"
    case 2...6:
        let f = DateFormatter()
        f.dateFormat = "EEEE"
        return f.string(from: d)
    default: return "In \(days) days"
    }
}

/// "19:30" -> "7:30 PM"
func clock(_ t: String) -> String? {
    let p = t.split(separator: ":").compactMap { Int($0) }
    guard p.count >= 2 else { return nil }
    let h = p[0] % 12 == 0 ? 12 : p[0] % 12
    return "\(h)\(p[1] == 0 ? "" : String(format: ":%02d", p[1])) \(p[0] < 12 ? "AM" : "PM")"
}

func monthDay(_ show: Show) -> (String, String) {
    guard let d = show.day else { return ("", "") }
    let f = DateFormatter()
    f.dateFormat = "MMM"
    let m = f.string(from: d).uppercased()
    f.dateFormat = "d"
    return (m, f.string(from: d))
}

func place(_ s: Show) -> String { [s.venue, s.city].filter { !$0.isEmpty }.joined(separator: " · ") }

// MARK: Views

struct WidgetView: View {
    @Environment(\.widgetFamily) var family
    let entry: Entry

    var body: some View {
        switch family {
        case .accessoryInline: inline
        case .accessoryRectangular: rectangular
        case .systemMedium: medium.widgetBackground(bg)
        default: small.widgetBackground(bg)
        }
    }

    // Small: the next show, big countdown. No shows booked: your total.
    @ViewBuilder var small: some View {
        if let s = entry.next.first {
            VStack(alignment: .leading, spacing: 3) {
                Text("NEXT SHOW").tracking(0.6).font(.caption2.weight(.bold)).foregroundStyle(accent)
                Spacer(minLength: 4)
                Text(s.title).font(.headline).foregroundStyle(.white).lineLimit(2).minimumScaleFactor(0.8)
                if s.timeLabel == nil, let other = s.with.first { // no room for both
                    Text("+ \(other)").font(.caption).foregroundStyle(.white.opacity(0.6)).lineLimit(1)
                }
                Text(s.venue).font(.caption).foregroundStyle(.white.opacity(0.6)).lineLimit(1)
                Spacer(minLength: 4)
                Text(whenLabel(s, from: entry.date)).font(.title3.weight(.bold)).foregroundStyle(accent)
                    .lineLimit(1).minimumScaleFactor(0.7)
                if let t = s.timeLabel {
                    Text(t).font(.caption.weight(.semibold)).foregroundStyle(.white.opacity(0.8)).lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .widgetURL(s.id.isEmpty ? nil : s.link)
        } else {
            total.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
    }

    var total: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("CONCERTS").tracking(0.6).font(.caption2.weight(.bold)).foregroundStyle(accent)
            Spacer(minLength: 0)
            Text("\(entry.attended)").font(.system(size: 46, weight: .heavy, design: .rounded))
                .foregroundStyle(.white).minimumScaleFactor(0.5).lineLimit(1)
            Text("shows and counting").font(.caption).foregroundStyle(.white.opacity(0.6))
        }
    }

    // Medium: total on the left, next three shows on the right.
    var medium: some View {
        HStack(alignment: .top, spacing: 14) {
            total.frame(width: 104, alignment: .leading).frame(maxHeight: .infinity, alignment: .leading)
            VStack(alignment: .leading, spacing: 8) {
                if entry.next.isEmpty {
                    Spacer()
                    Text("Nothing booked yet").font(.subheadline.weight(.semibold)).foregroundStyle(.white.opacity(0.7))
                    Spacer()
                } else {
                    ForEach(entry.next.prefix(3), id: \.self) { s in
                        Link(destination: s.link) { row(s) }
                    }
                    Spacer(minLength: 0)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    func row(_ s: Show) -> some View {
        let (m, d) = monthDay(s)
        return HStack(spacing: 9) {
            VStack(spacing: -1) {
                Text(m).font(.system(size: 9, weight: .bold)).foregroundStyle(accent)
                Text(d).font(.system(size: 17, weight: .heavy, design: .rounded)).foregroundStyle(.white)
            }
            .frame(width: 34, height: 34)
            .background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 1) {
                Text(s.title).font(.subheadline.weight(.semibold)).foregroundStyle(.white).lineLimit(1)
                Text("\(whenLabel(s, from: entry.date)) · \(s.venue)").font(.caption2)
                    .foregroundStyle(.white.opacity(0.6)).lineLimit(1)
            }
        }
    }

    // Lock screen
    @ViewBuilder var rectangular: some View {
        if let s = entry.next.first {
            VStack(alignment: .leading, spacing: 0) {
                Text([whenLabel(s, from: entry.date), s.timeLabel].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption.weight(.bold)).lineLimit(1)
                Text(s.title).font(.headline).lineLimit(1)
                Text(place(s)).font(.caption).lineLimit(1).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .widgetURL(s.id.isEmpty ? nil : s.link)
            .widgetBackground(.clear, padded: false)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                Text("\(entry.attended)").font(.title2.weight(.heavy))
                Text("shows and counting").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .widgetBackground(.clear, padded: false)
        }
    }

    @ViewBuilder var inline: some View {
        if let s = entry.next.first {
            Text("♪ \(s.title) · \(whenLabel(s, from: entry.date))")
        } else {
            Text("♪ \(entry.attended) shows")
        }
    }
}

extension View {
    /// iOS 17 wants widgets to declare their background and adds margins itself; iOS 16 needs both done by hand.
    @ViewBuilder func widgetBackground(_ color: Color, padded: Bool = true) -> some View {
        if #available(iOSApplicationExtension 17.0, *) {
            containerBackground(color, for: .widget)
        } else if padded {
            padding().background(color)
        } else {
            background(color)
        }
    }
}

// MARK: Widget

@main
struct ConcertsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "NextShow", provider: Provider()) { entry in
            WidgetView(entry: entry)
        }
        .configurationDisplayName("Next show")
        .description("Your next concert with a countdown, and how many you've been to.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular, .accessoryInline])
    }
}
