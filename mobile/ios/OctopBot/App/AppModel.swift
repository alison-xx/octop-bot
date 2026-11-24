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
    /// The signed-in person's display name (never an internal username or account id).
    private(set) var accountName = ""

    /// The Lynxce wallet balance as shown: loading, failed (retry), or the number of credits.
    enum Balance: Equatable { case loading, failed, value(Double) }
    /// Below this the balance turns to a warning and chat offers a top-up.
    static let lowBalance: Double = 100
    /// nil when this account has no Lynxce wallet here (a self-hosted server).
    private(set) var balance: Balance?
    /// The wallet the balance belongs to; low-balance dismissals are remembered per wallet.
    private var walletAccount: String?
    private(set) var lowBalanceDismissed = false
    /// Shown once on the sign-in screen (e.g. after deleting the account).
    var signedOutNotice: String?
    var loadError: String?
    var isLoading = false
    private(set) var previews: [String: Preview]
    /// Bots with a reply the user hasn't seen yet.
    private(set) var unread: Set<String>
    /// Bots whose chat (or voice mode) is on screen; their replies are seen as they land.
    private var onScreen: [String: Int] = [:]
    /// Set by "Switch account or server" so the first screen reopens the server sheet.
    var reopenServerSheet = false
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
        unread = Set(UserDefaults.standard.stringArray(forKey: "chat.unread") ?? [])
    }

    var isLynxce: Bool { backend is LynxceBackend }
    /// Used without signing in: the phone calls the user's own model itself.
    var isDevice: Bool { backend is DeviceBackend }
    /// Bots defined on this phone (Lynxce account or no account), rather than a server's.
    var usesPhoneBots: Bool { isLynxce || isDevice }
    /// The Lynxce wallet: direct with Lynxce, or kept by Octop Bot cloud.
    var creditAccount: CreditAccount? {
        if let lynxce = backend as? LynxceBackend { return lynxce }
        if let server, server.isCloud { return server }
        return nil
    }
    var server: ServerBackend? { backend as? ServerBackend }
    var isCloud: Bool { server?.isCloud == true }

    /// Where "My API keys" live: the Octop server signed in to (cloud or self-hosted), or this phone.
    var modelKeys: ModelKeyStore? {
        if let server { return ServerModelKeys(server: server) }
        return backend == nil ? nil : PhoneModels.shared
    }

    /// The server account's own keys and the one in use, for the Settings row.
    var serverKeys: OwnKeyList?

    /// The model Bots reply with, as Settings → Models shows it: ("deepseek-flash", "DeepSeek").
    var currentModel: (model: String, source: String)? {
        if let server {
            guard let keys = serverKeys, let id = keys.inUse, let model = keys.selectedModel else {
                return server.isCloud
                    ? (L("models.lynxce.auto"), L("models.lynxce.title"))
                    : (L("models.server.default"), server.host)
            }
            return (model, keys.keys.first { $0.id == id }?.displayName ?? "")
        }
        if let phone = PhoneModels.shared.current, usesPhoneBots { return phone }
        guard isLynxce else { return nil }
        let name = models.first { $0.id == selectedModel }?.name ?? L("settings.model.auto")
        return (name, L("models.lynxce.title"))
    }

    /// Where the account lives: 灵策云端 (cloud), 灵策智算账号 (direct Lynxce), or a self-hosted server's host.
    var modeLabel: String {
        if isLynxce { return L("account.mode.lynxce") }
        if isDevice { return L("account.mode.device") }
        guard let server else { return "" }
        return server.isCloud ? L("settings.lynxce") : server.host
    }

    var modeSymbol: String {
        if isLynxce { return "person.crop.circle.fill" }
        if isDevice { return "iphone" }
        return isCloud ? "cloud.fill" : "server.rack"
    }

    /// The account card in Settings. Tier, avatar and the expiring/permanent split come with Lynxce's
    /// member profile; until then only the name and balance are known.
    var accountSummary: AccountSummary {
        #if DEBUG
        if UserDefaults.standard.bool(forKey: "demoAccount") { return .demo }
        #endif
        return AccountSummary(name: accountName, credits: credits)
    }

    var credits: Double? {
        if case .value(let credits) = balance { return credits }
        return nil
    }

    var isLowBalance: Bool { credits.map { $0 < Self.lowBalance } ?? false }
    var showsLowBalanceBanner: Bool { isLowBalance && !lowBalanceDismissed }
    var lastBot: BotProfile? { bots.first { $0.id == lastBotId } ?? bots.first { $0.isChief } ?? bots.first }

    /// The directory as shown: Chief pinned, then the newest reply first, then directory order.
    var orderedBots: [BotProfile] { Self.order(bots, previews: previews) }

    static func order(_ bots: [BotProfile], previews: [String: Preview]) -> [BotProfile] {
        let chief = bots.filter(\.isChief)
        let others = bots.enumerated().filter { !$0.element.isChief }.sorted { a, b in
            let da = previews[a.element.id]?.date, db = previews[b.element.id]?.date
            switch (da, db) {
            case let (x?, y?) where x != y: return x > y
            case (.some, nil): return true
            case (nil, .some): return false
            default: return a.offset < b.offset
            }
        }
        return chief + others.map(\.element)
    }

    func start() async {
        if let restored: ChatBackend = LynxceBackend.restore() ?? ServerBackend.restore() ?? DeviceBackend.restore() {
            await use(restored)
        } else {
            phase = .signedOut
        }
    }

    func use(_ backend: ChatBackend) async {
        self.backend = backend
        sessions = [:]
        accountName = backend.accountName
        signedOutNotice = nil
        balance = creditAccount == nil ? nil : .loading
        walletAccount = nil
        lowBalanceDismissed = false
        let first = Task { await refresh() }
        if phase == .launching {
            // Keep the launch art up until the directory is in, but never longer than a moment.
            await withTaskGroup(of: Void.self) { group in
                group.addTask { await first.value }
                group.addTask { try? await Task.sleep(for: .seconds(1.2)) }
                await group.next()
                group.cancelAll()
            }
        }
        phase = .ready
        await first.value
        if let pushToken { await backend.registerPush(token: pushToken) }
        if creditAccount != nil {
            CreditStore.shared.start(
                account: { [weak self] in self?.creditAccount },
                credited: { [weak self] in await self?.refreshBalance() }
            )
            await CreditStore.shared.flush()
        }
    }

    func refreshServerKeys() async {
        guard server != nil, let store = modelKeys else {
            serverKeys = nil
            return
        }
        // An older server without own keys just keeps showing its own models.
        serverKeys = try? await store.list()
    }

    func refreshBalance() async {
        guard let account = creditAccount else {
            balance = nil
            return
        }
        // A number already on screen stays while it refreshes, and through a failed refresh.
        if credits == nil { balance = .loading }
        do {
            let wallet = try await account.wallet()
            guard creditAccount === account else { return }
            balance = .value(wallet.credits)
            walletAccount = wallet.accountId
            let key = Self.lowDismissedKey(wallet.accountId)
            // Back above the line: the next time it runs low, the banner shows again.
            if wallet.credits >= Self.lowBalance { UserDefaults.standard.removeObject(forKey: key) }
            lowBalanceDismissed = UserDefaults.standard.bool(forKey: key)
        } catch {
            guard creditAccount === account else { return }
            if credits == nil { balance = .failed }
        }
    }

    /// Hide the low-balance banner for this wallet until the balance is back at 100 or more.
    func dismissLowBalance() {
        lowBalanceDismissed = true
        if let walletAccount { UserDefaults.standard.set(true, forKey: Self.lowDismissedKey(walletAccount)) }
    }

    private static func lowDismissedKey(_ account: String) -> String { "credits.lowDismissed.\(account)" }

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
        if let server {
            groups = (try? await server.groups()) ?? groups
            await server.refreshProfile()
            accountName = server.accountName
        }
        models = (try? await backend.models()) ?? []
        await refreshServerKeys()
        await refreshBalance()
    }

    /// One chat per Bot, so several Bots can reply at once.
    func session(for bot: BotProfile) -> ChatSession {
        if let session = sessions[bot.id] { return session }
        let session = ChatSession(bot: bot, app: self)
        sessions[bot.id] = session
        return session
    }

    /// Phone-local Bots can be edited fully; server Bots can change their look.
    func canEdit(_ bot: BotProfile) -> Bool { usesPhoneBots ? bot.isLocal : true }

    func motion(of bot: BotProfile) -> BotMotion { sessions[bot.id]?.motion ?? .idle }

    func recordPreview(_ text: String, for bot: BotProfile) {
        let line = Speaker.plain(text).split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        guard !line.isEmpty else { return }
        previews[bot.id] = Preview(text: String(line.prefix(120)), date: .now)
        UserDefaults.standard.set(try? JSONEncoder().encode(previews), forKey: "chat.previews")
        if (onScreen[bot.id] ?? 0) == 0 || UIApplication.shared.applicationState != .active {
            unread.insert(bot.id)
            saveUnread()
        }
    }

    /// A chat or voice screen for this Bot appeared; its replies count as read.
    func showing(_ bot: BotProfile) {
        onScreen[bot.id, default: 0] += 1
        markRead(bot)
    }

    func hiding(_ bot: BotProfile) {
        onScreen[bot.id] = max(0, (onScreen[bot.id] ?? 1) - 1)
    }

    func markRead(_ bot: BotProfile) {
        guard unread.remove(bot.id) != nil else { return }
        saveUnread()
    }

    private func saveUnread() {
        UserDefaults.standard.set(Array(unread), forKey: "chat.unread")
    }

    /// Settings → Storage: drop reply previews, unread marks and temporary files.
    func clearCache() {
        previews = [:]
        unread = []
        UserDefaults.standard.removeObject(forKey: "chat.previews")
        UserDefaults.standard.removeObject(forKey: "chat.unread")
        let tmp = FileManager.default.temporaryDirectory
        for file in (try? FileManager.default.contentsOfDirectory(at: tmp, includingPropertiesForKeys: nil)) ?? [] {
            try? FileManager.default.removeItem(at: file)
        }
    }

    /// Settings → "Switch account or server".
    func switchAccount() async {
        // Set first: the first screen reads it as it appears. Cloud users start over at the Lynxce
        // sign-in, not in the own-server sheet filled with the cloud's address.
        reopenServerSheet = server != nil && !isCloud
        await signOut()
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
        unread.remove(bot.id)
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

    /// Settings → Delete account: Lynxce starts its cooling-off period, then this phone signs out and
    /// the sign-in screen says how long the account can still be restored.
    func deleteAccount() async throws {
        guard let account = creditAccount else { return }
        let days = try await account.requestDeletion()
        LocalBots.shared.deleteAll()
        await signOut()
        signedOutNotice = days.map { L("account.deleted.days %lld", $0) } ?? L("account.deleted")
    }

    func signOut() async {
        for session in sessions.values { session.cancel() }
        sessions = [:]
        await backend?.signOut()
        backend = nil
        bots = []
        groups = []
        serverKeys = nil
        balance = nil
        walletAccount = nil
        lowBalanceDismissed = false
        accountName = ""
        // Previews belong to the account that wrote them.
        previews = [:]
        unread = []
        UserDefaults.standard.removeObject(forKey: "chat.previews")
        UserDefaults.standard.removeObject(forKey: "chat.unread")
        lastBotId = nil
        phase = .signedOut
    }
}

enum Notifier {
    private static var asked = false

    static func status() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

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
