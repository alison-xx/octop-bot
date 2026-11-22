import Foundation
import Observation
import UIKit
import UserNotifications

/// App-wide state: who we are signed in as, the Bot directory, and one live chat per Bot.
@Observable
final class AppModel {
    enum Phase { case launching, signedOut, ready }

    struct Preview: Codable, Hashable {
        var text: String
        var date: Date
    }

    var phase: Phase = .launching
    private(set) var backend: ChatBackend?
    var bots: [BotProfile] = []
    var groups: [GroupSummary] = []
    /// The Bot opened most recently; voice mode talks to it.
    var lastBotId: String? {
        didSet { UserDefaults.standard.set(lastBotId, forKey: "chat.bot") }
    }
    var models: [ModelOption] = []
    var balance: String?
    var loadError: String?
    var isLoading = false
    private(set) var previews: [String: Preview]
    private var sessions: [String: ChatSession] = [:]

    var selectedModel: String? {
        didSet { UserDefaults.standard.set(selectedModel, forKey: "chat.model") }
    }
    var readAloud: Bool {
        didSet { UserDefaults.standard.set(readAloud, forKey: "chat.readAloud") }
    }
    var notifyOnReply: Bool {
        didSet {
            UserDefaults.standard.set(notifyOnReply, forKey: "chat.notify")
            if notifyOnReply { Notifier.requestPermission() }
        }
    }
    var pushToken: String?

    init() {
        selectedModel = UserDefaults.standard.string(forKey: "chat.model")
        readAloud = UserDefaults.standard.bool(forKey: "chat.readAloud")
        notifyOnReply = UserDefaults.standard.object(forKey: "chat.notify") as? Bool ?? true
        lastBotId = UserDefaults.standard.string(forKey: "chat.bot")
        previews = UserDefaults.standard.data(forKey: "chat.previews")
            .flatMap { try? JSONDecoder().decode([String: Preview].self, from: $0) } ?? [:]
    }

    var isLynxce: Bool { backend is LynxceBackend }
    var server: ServerBackend? { backend as? ServerBackend }
    var lastBot: BotProfile? { bots.first { $0.id == lastBotId } ?? bots.first { $0.isChief } ?? bots.first }

    func start() async {
        if let restored: ChatBackend = LynxceBackend.restore() ?? ServerBackend.restore() {
            await use(restored)
        } else {
            phase = .signedOut
        }
    }

    func use(_ backend: ChatBackend) async {
        self.backend = backend
        sessions = [:]
        phase = .ready
        await refresh()
        if let pushToken { await backend.registerPush(token: pushToken) }
    }

    func refresh() async {
        guard let backend else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let loaded = try await backend.bots()
            // Chief first, then the directory's order.
            bots = loaded.filter(\.isChief) + loaded.filter { !$0.isChief }
            for bot in bots { sessions[bot.id]?.bot = bot }
            loadError = nil
        } catch let error as APIError where error.kind == .unauthorized {
            await signOut()
            return
        } catch {
            loadError = error.localizedDescription
        }
        if let server { groups = (try? await server.groups()) ?? groups }
        models = (try? await backend.models()) ?? []
        if let lynxce = backend as? LynxceBackend { balance = await lynxce.balance() }
    }

    /// One chat per Bot, so several Bots can reply at once.
    func session(for bot: BotProfile) -> ChatSession {
        if let session = sessions[bot.id] { return session }
        let session = ChatSession(bot: bot, app: self)
        sessions[bot.id] = session
        return session
    }

    /// Phone-local Bots can be edited fully; server Bots can change their look.
    func canEdit(_ bot: BotProfile) -> Bool { isLynxce ? bot.isLocal : true }

    func motion(of bot: BotProfile) -> BotMotion { sessions[bot.id]?.motion ?? .idle }

    func recordPreview(_ text: String, for bot: BotProfile) {
        let line = Speaker.plain(text).split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        guard !line.isEmpty else { return }
        previews[bot.id] = Preview(text: String(line.prefix(120)), date: .now)
        UserDefaults.standard.set(try? JSONEncoder().encode(previews), forKey: "chat.previews")
    }

    func saveLocalBot(_ bot: BotProfile) {
        LocalBots.shared.save(bot)
        Task { await refresh() }
    }

    func deleteLocalBot(_ bot: BotProfile) {
        LocalBots.shared.delete(bot.id)
        sessions[bot.id]?.cancel()
        sessions[bot.id] = nil
        previews[bot.id] = nil
        Task { await refresh() }
    }

    func createServerBot(_ bot: BotProfile) async throws {
        guard let server else { return }
        let id = try await server.createBot(name: bot.name, role: bot.systemPrompt ?? "", look: bot.look)
        await refresh()
        lastBotId = id
    }

    func createGroup(name: String, members: [BotProfile]) async throws {
        guard let server, let admin = members.first(where: \.isChief) ?? members.first else { return }
        try await server.createGroup(name: name, admin: admin.id, members: members.map(\.id))
        await refresh()
    }

    func setLook(_ look: Look, for bot: BotProfile) async throws {
        try await server?.setLook(look, for: bot)
        await refresh()
    }

    func signOut() async {
        for session in sessions.values { session.cancel() }
        sessions = [:]
        await backend?.signOut()
        backend = nil
        bots = []
        groups = []
        balance = nil
        // Previews belong to the account that wrote them.
        previews = [:]
        UserDefaults.standard.removeObject(forKey: "chat.previews")
        lastBotId = nil
        phase = .signedOut
    }
}

enum Notifier {
    private static var asked = false

    static func requestPermission() {
        guard !asked else { return }
        asked = true
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
            guard granted else { return }
            Task { @MainActor in UIApplication.shared.registerForRemoteNotifications() }
        }
    }

    /// Tell the user a reply landed while they were away.
    static func replyFinished(bot: String, text: String) {
        guard UIApplication.shared.applicationState != .active else { return }
        let content = UNMutableNotificationContent()
        content.title = bot
        content.body = String(Speaker.plain(text).split(separator: "\n").first ?? "").prefix(160).description
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
