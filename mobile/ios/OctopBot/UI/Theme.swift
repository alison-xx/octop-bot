import SwiftUI
import UIKit

/// Palette from mobile/README.md: dark-first, follows the system theme.
enum Palette {
    static let background = dynamic(light: 0xFFFFFF, dark: 0x000000)
    static let surface = dynamic(light: 0xF4F4F5, dark: 0x141416)
    static let raised = dynamic(light: 0xECECEF, dark: 0x1E1E22)
    static let hairline = dynamic(light: 0xE4E4E7, dark: 0x2A2A30)
    static let text = dynamic(light: 0x111113, dark: 0xF4F4F5)
    static let secondary = dynamic(light: 0x6B6B73, dark: 0x9A9AA3)

    /// The provider is `@Sendable` (not main-actor): SwiftUI resolves colors off the main thread,
    /// e.g. a live `Text(date, style: .relative)` while a sheet covers it, which crashed the app.
    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(UIColor { @Sendable traits in
            let value = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(
                red: CGFloat((value >> 16) & 0xFF) / 255,
                green: CGFloat((value >> 8) & 0xFF) / 255,
                blue: CGFloat(value & 0xFF) / 255,
                alpha: 1
            )
        })
    }
}

extension BotProfile {
    var accent: Color { look.isOctopus ? Characters.ink("rose") : Characters.ink(look.color) }
}

struct PillButtonStyle: ButtonStyle {
    var filled = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(filled ? Palette.text : Palette.surface, in: Capsule())
            .foregroundStyle(filled ? Palette.background : Palette.text)
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

extension Date {
    var relative: String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        formatter.locale = Preferences.shared.language.locale
        return formatter.localizedString(for: self, relativeTo: .now)
    }
}

/// Centered time captions between messages, like a messenger.
enum TimeLabel {
    /// A caption goes before the first message and after any gap of more than 10 minutes.
    static func needsSeparator(_ date: Date, after previous: Date?) -> Bool {
        guard let previous else { return true }
        return date.timeIntervalSince(previous) > 600
    }

    static func text(_ date: Date, now: Date = .now, calendar: Calendar = .current) -> String {
        let locale = Preferences.shared.language.locale
        let time = format(date, template: "HHmm", locale: locale, calendar: calendar)
        if calendar.isDate(date, inSameDayAs: now) { return time }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) {
            return L("time.yesterday %@", time)
        }
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: now)
        return format(date, template: sameYear ? "MMMdHHmm" : "yMMMdHHmm", locale: locale, calendar: calendar)
    }

    private static func format(_ date: Date, template: String, locale: Locale, calendar: Calendar) -> String {
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.setLocalizedDateFormatFromTemplate(template)
        return formatter.string(from: date)
    }
}

/// History sheet groups: Today / Yesterday / Previous 7 days / Earlier.
enum DateBucket: Int, CaseIterable, Identifiable {
    case today, yesterday, week, earlier
    var id: Int { rawValue }

    var title: String {
        switch self {
        case .today: L("history.today")
        case .yesterday: L("history.yesterday")
        case .week: L("history.week")
        case .earlier: L("history.earlier")
        }
    }

    static func of(_ date: Date?, now: Date = .now, calendar: Calendar = .current) -> DateBucket {
        guard let date else { return .earlier }
        let start = calendar.startOfDay(for: now)
        if date >= start { return .today }
        if let y = calendar.date(byAdding: .day, value: -1, to: start), date >= y { return .yesterday }
        if let w = calendar.date(byAdding: .day, value: -7, to: start), date >= w { return .week }
        return .earlier
    }
}

/// Chat text size from Settings, one Dynamic Type step around whatever the system uses.
struct ChatTextSize: ViewModifier {
    @Environment(\.dynamicTypeSize) private var system
    var size: TextSize

    func body(content: Content) -> some View {
        let all = DynamicTypeSize.allCases
        let index = all.firstIndex(of: system) ?? 3
        let step = size == .small ? -1 : size == .large ? 1 : 0
        content.dynamicTypeSize(all[min(max(index + step, 0), all.count - 1)])
    }
}

extension View {
    func chatTextSize() -> some View { modifier(ChatTextSize(size: Preferences.shared.textSize)) }
}
