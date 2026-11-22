import Foundation
import ObjectiveC
import Observation
import SwiftUI

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

    private init() {
        language = AppLanguage(rawValue: UserDefaults.standard.string(forKey: "app.language") ?? "") ?? .system
        appearance = AppAppearance(rawValue: UserDefaults.standard.string(forKey: "app.appearance") ?? "") ?? .system
        LanguageBundle.use(language)
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
