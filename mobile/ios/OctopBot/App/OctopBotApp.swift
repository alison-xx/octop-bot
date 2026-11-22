import SwiftUI
import UIKit
import UserNotifications

@main
struct OctopBotApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()
    @State private var preferences = Preferences.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(preferences)
                .environment(\.locale, preferences.language.locale)
                .preferredColorScheme(preferences.appearance.colorScheme)
                .task {
                    delegate.model = model
                    await model.start()
                }
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    weak var model: AppModel?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        model?.pushToken = token
        Task { await model?.backend?.registerPush(token: token) }
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions { [] }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            switch model.phase {
            case .launching:
                ZStack {
                    Palette.background.ignoresSafeArea()
                    CharacterView(look: .chief, size: 96)
                }
            case .signedOut:
                OnboardingView()
            case .ready:
                HomeView()
            }
        }
        .tint(Palette.text)
    }
}
