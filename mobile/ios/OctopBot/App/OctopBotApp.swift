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
        ZStack {
            switch model.phase {
            case .launching:
                SplashView().transition(.opacity)
            case .signedOut:
                OnboardingView().transition(.opacity)
            case .ready:
                HomeView().transition(.opacity)
                    .overlay(alignment: .top) {
                        if let notice = model.signupNotice {
                            Text(verbatim: notice)
                                .font(.callout)
                                .padding()
                                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                                .padding(.horizontal)
                                .task(id: notice) {
                                    UIAccessibility.post(notification: .announcement, argument: notice)
                                    try? await Task.sleep(for: .seconds(5))
                                    if !Task.isCancelled { model.signupNotice = nil }
                                }
                        }
                    }
            }
        }
        .animation(.easeOut(duration: 0.35), value: model.phase)
        .tint(Palette.text)
        // Files a Bot links to live on its server; open them with this account's access.
        .environment(\.openURL, OpenURLAction { url in
            guard let server = model.server, ServerBackend.isWorkspaceDownload(url) else { return .systemAction }
            Task { await FileOpener.open(url, from: server) }
            return .handled
        })
    }
}

/// Continues the system launch screen: the same art in the same place, then the name fades in.
struct SplashView: View {
    static let artSize: CGFloat = 240
    @State private var shown = false

    var body: some View {
        ZStack {
            Color("LaunchBackground").ignoresSafeArea()
            Image("LaunchArt")
                .resizable()
                .scaledToFit()
                .frame(width: Self.artSize, height: Self.artSize)
                .scaleEffect(shown ? 1.03 : 1)
                .animation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true), value: shown)
            VStack(spacing: 6) {
                Text(verbatim: "Octop Bot")
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                    .foregroundStyle(Palette.text)
                Text("onboarding.tagline")
                    .font(.subheadline)
                    .foregroundStyle(Palette.secondary)
            }
            .offset(y: Self.artSize / 2 + 44)
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 8)
            .animation(.easeOut(duration: 0.45).delay(0.1), value: shown)
        }
        // The system launch screen centers its image in the whole screen, not the safe area.
        .ignoresSafeArea()
        .onAppear { shown = true }
        .accessibilityElement(children: .combine)
    }
}
