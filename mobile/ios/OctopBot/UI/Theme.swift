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

    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(UIColor { traits in
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
