import Foundation
import ObjectiveC
import Observation
import SwiftUI
import UIKit

/// The app's own language choice: follow the system, or force Chinese / English.
enum AppLanguage: String, CaseIterable, Identifiable {
    case system
    case chinese = "zh-Hans"
    case english = "en"

    var id: String { rawValue }

    /// The language actually shown: the forced one, or the best system match.
    var resolved: String {
        if self != .system { return rawValue }
        let preferred = Bundle.preferredLocalizations(from: ["en", "zh-Hans"], forPreferences: Locale.preferredLanguages)
        return preferred.first ?? "en"
    }

    var isChinese: Bool { resolved.hasPrefix("zh") }
    /// For `Accept-Language`, so servers answer and localize errors in the same language.
    var httpTag: String { isChinese ? "zh-CN" : "en-US" }
    var locale: Locale { Locale(identifier: isChinese ? "zh-Hans" : "en") }
}

enum AppAppearance: String, CaseIterable, Identifiable {
    case system, dark, light
    var id: String { rawValue }
    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .dark: .dark
        case .light: .light
        }
    }
}

/// Chat text size; scales message and composer text.
enum TextSize: String, CaseIterable, Identifiable {
    case small, standard, large
    var id: String { rawValue }
    var scale: CGFloat {
        switch self {
        case .small: 0.9
        case .standard: 1
        case .large: 1.15
        }
    }
    /// Body text in points (system body is 17).
    var body: CGFloat { 17 * scale }
}

/// How fast replies are read aloud.
enum SpeechSpeed: String, CaseIterable, Identifiable {
    case slow, normal, fast
    var id: String { rawValue }
    var rate: Float {
        switch self {
        case .slow: 0.85
        case .normal: 1
        case .fast: 1.2
        }
    }
}

@Observable
final class Preferences {
    static let shared = Preferences()

    var language: AppLanguage {
        didSet {
            UserDefaults.standard.set(language.rawValue, forKey: "app.language")
            LanguageBundle.use(language)
        }
    }
    var appearance: AppAppearance {
        didSet { UserDefaults.standard.set(appearance.rawValue, forKey: "app.appearance") }
    }
    var textSize: TextSize {
        didSet { UserDefaults.standard.set(textSize.rawValue, forKey: "app.textSize") }
    }
    var haptics: Bool {
        didSet { UserDefaults.standard.set(haptics, forKey: "app.haptics") }
    }
    var expandThinking: Bool {
        didSet { UserDefaults.standard.set(expandThinking, forKey: "chat.expandThinking") }
    }
    var speechSpeed: SpeechSpeed {
        didSet { UserDefaults.standard.set(speechSpeed.rawValue, forKey: "voice.speed") }
    }

    private init() {
        let defaults = UserDefaults.standard
        language = AppLanguage(rawValue: defaults.string(forKey: "app.language") ?? "") ?? .system
        appearance = AppAppearance(rawValue: defaults.string(forKey: "app.appearance") ?? "") ?? .system
        textSize = TextSize(rawValue: defaults.string(forKey: "app.textSize") ?? "") ?? .standard
        haptics = defaults.object(forKey: "app.haptics") as? Bool ?? true
        expandThinking = defaults.bool(forKey: "chat.expandThinking")
        speechSpeed = SpeechSpeed(rawValue: defaults.string(forKey: "voice.speed") ?? "") ?? .normal
        LanguageBundle.use(language)
    }
}

/// Haptic taps that respect the Settings switch.
enum Haptics {
    static func tap() {
        guard Preferences.shared.haptics else { return }
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }

    static func success() {
        guard Preferences.shared.haptics else { return }
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func error() {
        guard Preferences.shared.haptics else { return }
        UINotificationFeedbackGenerator().notificationOccurred(.error)
    }
}

/// Switches the strings `Bundle.main` returns without restarting the app.
/// SwiftUI `Text` and `L(_:)` read through `Bundle.main`; `String(localized:)` does not, so app code uses `L`.
nonisolated private final class LanguageBundle: Bundle, @unchecked Sendable {
    nonisolated(unsafe) private static var forced: Bundle?
    nonisolated(unsafe) private static var installed = false

    static func use(_ language: AppLanguage) {
        if !installed {
            object_setClass(Bundle.main, LanguageBundle.self)
            installed = true
        }
        forced = language == .system
            ? nil
            : Bundle.main.path(forResource: language.rawValue, ofType: "lproj").flatMap(Bundle.init(path:))
    }

    override func localizedString(forKey key: String, value: String?, table tableName: String?) -> String {
        if let forced = Self.forced {
            return forced.localizedString(forKey: key, value: value, table: tableName)
        }
        return super.localizedString(forKey: key, value: value, table: tableName)
    }
}

/// A localized string in the app's chosen language, with optional `String(format:)` arguments.
nonisolated func L(_ key: String, _ args: CVarArg...) -> String {
    let format = Bundle.main.localizedString(forKey: key, value: nil, table: nil)
    return args.isEmpty ? format : String(format: format, arguments: args)
}
