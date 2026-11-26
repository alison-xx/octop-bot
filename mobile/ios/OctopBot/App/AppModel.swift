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
    private(set) var backend: ChatBackend? {
        willSet {
            if backend !== newValue { (backend as? ServerBackend)?.attachments.invalidate() }
        }
    }
    var bots: [BotProfile] = []
    var groups: [GroupSummary] = []
    /// The Bot opened most recently; voice mode talks to it.
    var lastBotId: String? {
        didSet { UserDefaults.standard.set(lastBotId, forKey: "chat.bot") }
    }
    var models: [ModelOption] = []
    /// The signed-in person's display name (never an internal username or account id).
    private(set) var accountName = ""
    private(set) var accountPhotoURL: URL?
    private(set) var localAccountImage: Data?
    private(set) var photoRefresh: Task<Void, Never>?

    /// The Lynxce wallet balance as shown: loading, failed (retry), or the number of credits.
    enum Balance: Equatable { case loading, failed, value(Double) }
    /// Below this the balance turns to a warning and chat offers a top-up.
    static let lowBalance: Double = 1_000
    static let lowBalanceDismissalDuration: TimeInterval = 24 * 60 * 60
    static func lowBalanceIsDismissed(at: TimeInterval, now: TimeInterval) -> Bool {
        at > 0 && now - at < lowBalanceDismissalDuration
    }
    /// nil when this account has no Lynxce wallet here (a self-hosted server).
    private(set) var balance: Balance?
    /// The wallet the balance belongs to; low-balance dismissals are remembered per wallet.
    private var walletAccount: String?
    private(set) var lowBalanceDismissed = false
    /// Shown once on the sign-in screen (e.g. after deleting the account).
    var signedOutNotice: String?
    var signupNotice: String?
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
    struct NotificationChat: Hashable {
        let botId: String
        let threadId: String
    }

    var notificationChat: NotificationChat?
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

    // Consent lasts for this sign-in and this recipient. Never restore an opt-in on upgrade.
    struct AIRecipient: Equatable {
        let destination: String
        let official: Bool
    }
    private(set) var allowedAIRecipient: AIRecipient?
    var aiRecipient: AIRecipient? {
        guard let backend else { return nil }
        if let server {
            let official = server.isOfficialCloud
            if official && serverKeys == nil { return nil }
            var destination = server.host
            if let keys = serverKeys, let id = keys.inUse {
                guard let key = keys.keys.first(where: { $0.id == id }) else { return nil }
                destination += " → " + key.displayName
                if let host = URL(string: key.baseURL)?.host { destination += " (" + host + ")" }
            } else if official {
                destination += " → Tencent Cloud TokenHub"
            }
            return AIRecipient(destination: destination, official: official)
        }
        if usesPhoneBots, let endpoint = PhoneModels.shared.endpoint(), let host = endpoint.baseURL.host {
            let source = PhoneModels.shared.current?.source ?? host
            let recipient = source + " (" + host + ")"
            return AIRecipient(destination: recipient, official: isLynxce)
        }
        if isDevice { return nil }
        return AIRecipient(destination: isLynxce ? "Lynxce → Tencent Cloud TokenHub" : backend.accountName, official: isLynxce)
    }
    var allowsAISharing: Bool { allowedAIRecipient != nil && allowedAIRecipient == aiRecipient }

    func allowAISharing(with recipient: AIRecipient) {
        if aiRecipient == recipient { allowedAIRecipient = recipient }
    }

    func revokeAISharing() {
        allowedAIRecipient = nil
        Speaker.shared.stop()
        for session in sessions.values {
            session.stop()
            session.cancel()
        }
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
        return AccountSummary(name: accountName, avatarURL: accountPhotoURL, localImage: localAccountImage, credits: credits, signupExpiryDay: creditAccount?.signupExpiryDay)
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

    private var recoveryTask: Task<Void, Never>?
    private(set) var recoveringHistory = false
    private(set) var historyRecoveryMessage: String?

    func recoverLegacyHistory(force: Bool = false) {
        guard let server, server.isOfficialCloud, !recoveringHistory else { return }
        let legacyGrant = LynxceBackend.restore()?.grant
        recoveringHistory = true
        recoveryTask = Task {
            defer { if self.server === server { recoveringHistory = false } }
            do {
                let owner = try await server.legacyHistoryOwner()
                let key = "cloud.legacyHistory.completed." + owner
                guard self.server === server, !Task.isCancelled,
                      force || legacyGrant?.accountId == owner || !UserDefaults.standard.bool(forKey: key) else { return }
                let complete = try await server.restoreLegacyHistory()
                guard self.server === server, !Task.isCancelled else { return }
                if complete, let legacyGrant, legacyGrant.accountId == owner {
                    let confirmedOwner = try await server.legacyHistoryOwner(refresh: true)
                    guard self.server === server, !Task.isCancelled, confirmedOwner == owner else { return }
                    LynxceBackend.retireRecoveredGrant(legacyGrant, owner: confirmedOwner)
                }
                UserDefaults.standard.set(complete, forKey: key)
                historyRecoveryMessage = L(complete ? "history.restored" : "history.restoreIncomplete")
                for chat in Array(sessions.values) { await chat.reloadConversations() }
            } catch {
                if self.server === server, !Task.isCancelled { historyRecoveryMessage = L("history.restoreRetry") }
            }
        }
    }

    private func stopHistoryRecovery() {
        recoveryTask?.cancel()
        recoveryTask = nil
        recoveringHistory = false
        historyRecoveryMessage = nil
    }

    static func archiveUnattributedPreviews(_ defaults: UserDefaults) {
        // 1.0.0 stored previews across accounts without an owner. Keep the original bytes on
        // this device, isolated from each signed-in cloud account and its recovered threads.
        if let data = defaults.data(forKey: "chat.previews") {
            var copies = defaults.array(forKey: "legacy.unattributedPreviews") as? [Data] ?? []
            if !copies.contains(data) { copies.append(data) }
            defaults.set(copies, forKey: "legacy.unattributedPreviews")
        }
        defaults.removeObject(forKey: "chat.previews")
        defaults.removeObject(forKey: "chat.unread")
    }

    enum SavedBackend: String, Codable {
        case server, device, signedOut

        static func restore(_ selected: Self?, hasLegacy: Bool, hasServer: Bool, official: Bool) -> Self {
            if let selected { return selected }
            if hasLegacy { return official ? .server : .signedOut }
            return hasServer ? .server : .device
        }
    }

    private static let backendSelectionKey = "session.selectedBackend"

    func start() async {
        let selected = Keychain.codable(SavedBackend.self, for: Self.backendSelectionKey)
        let legacy = LynxceBackend.restore()
        let server = ServerBackend.restore()
        let restored: ChatBackend?
        switch SavedBackend.restore(selected, hasLegacy: legacy != nil, hasServer: server != nil, official: server?.isOfficialCloud == true) {
        case .server: restored = server
        case .device: restored = DeviceBackend.restore()
        case .signedOut: restored = nil
        }
        if let restored {
            await use(restored, rememberSelection: false)
        } else {
            if selected == nil && legacy != nil {
                Self.archiveUnattributedPreviews(.standard)
                previews = [:]
                unread = []
                lastBotId = nil
                signedOutNotice = L("history.reauthenticate")
            }
            phase = .signedOut
        }
    }

    func use(_ backend: ChatBackend, rememberSelection: Bool = true) async {
        CreditStore.shared.clearCatalog()
        if rememberSelection {
            if backend is ServerBackend { Keychain.setCodable(SavedBackend.server, for: Self.backendSelectionKey) }
            if backend is DeviceBackend { Keychain.setCodable(SavedBackend.device, for: Self.backendSelectionKey) }
        }
        photoRefresh?.cancel()
        stopHistoryRecovery()
        for session in sessions.values { session.cancel() }
        if self.backend != nil, self.backend !== backend {
            previews = [:]
            unread = []
            lastBotId = nil
            UserDefaults.standard.removeObject(forKey: "chat.previews")
            UserDefaults.standard.removeObject(forKey: "chat.unread")
        }
        allowedAIRecipient = nil
        serverKeys = nil
        self.backend = backend
        CreditStore.shared.start(
            account: { [weak self] in self?.creditAccount },
            credited: { [weak self] in await self?.refreshBalance() }
        )
        recoverLegacyHistory()
        sessions = [:]
        accountName = backend.accountName
        accountPhotoURL = nil
        localAccountImage = nil
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
        guard self.backend === backend else { return }
        signupNotice = creditAccount?.signupCredits.map { value in
            let amount = LynxceBackend.formatCredits(value)
            if let expiry = creditAccount?.signupExpiryDay { return L("credits.signup %@ %@", amount, expiry) }
            return L("credits.signup %@", amount)
        }
        creditAccount?.signupCredits = nil
        phase = .ready
        await first.value
        guard self.backend === backend else { return }
        if let pushToken { await backend.registerPush(token: pushToken) }
        if creditAccount != nil {
            await CreditStore.shared.flush()
        }
    }

    func refreshServerKeys() async {
        guard let server, let store = modelKeys else {
            serverKeys = nil
            return
        }
        // An older server without own keys just keeps showing its own models.
        let keys = try? await store.list()
        guard self.server === server else { return }
        serverKeys = keys
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
            let dismissedAt = UserDefaults.standard.double(forKey: key)
            lowBalanceDismissed = Self.lowBalanceIsDismissed(at: dismissedAt, now: Date().timeIntervalSince1970)
            scheduleLowBalanceReset(dismissedAt: dismissedAt, wallet: wallet.accountId)
        } catch {
            guard creditAccount === account else { return }
            if credits == nil { balance = .failed }
        }
    }

    /// Hide the low-balance banner for this wallet for 24 hours.
    func dismissLowBalance() {
        lowBalanceDismissed = true
        if let walletAccount {
            let now = Date().timeIntervalSince1970
            UserDefaults.standard.set(now, forKey: Self.lowDismissedKey(walletAccount))
            scheduleLowBalanceReset(dismissedAt: now, wallet: walletAccount)
        }
    }

    private func scheduleLowBalanceReset(dismissedAt: TimeInterval, wallet: String) {
        let remaining = dismissedAt + Self.lowBalanceDismissalDuration - Date().timeIntervalSince1970
        guard remaining > 0, dismissedAt > 0 else { return }
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(remaining))
            guard let self, self.walletAccount == wallet,
                  UserDefaults.standard.double(forKey: Self.lowDismissedKey(wallet)) == dismissedAt else { return }
            self.lowBalanceDismissed = false
        }
    }

    private static func lowDismissedKey(_ account: String) -> String { "credits.lowDismissed.\(account)" }

    func refresh() async {
        guard let backend else { return }
        photoRefresh?.cancel()
        photoRefresh = Task { [weak self] in
            guard let photo = await backend.accountPhoto(), !Task.isCancelled, let self, self.backend === backend else { return }
            accountName = photo.name ?? backend.accountName
            accountPhotoURL = photo.url
            localAccountImage = photo.localImage
        }
        isLoading = true
        defer { if self.backend === backend { isLoading = false } }
        do {
            let loaded = try await backend.bots()
            guard self.backend === backend else { return }
            // Chief first, then the directory's order.
            bots = loaded.filter(\.isChief) + loaded.filter { !$0.isChief }
            for bot in bots { sessions[bot.id]?.bot = bot }
            loadError = nil
        } catch let error as APIError where error.kind == .unauthorized {
            guard self.backend === backend else { return }
            await signOut()
            return
        } catch {
            guard self.backend === backend else { return }
            loadError = error.localizedDescription
        }
        if let server {
            let refreshedGroups = try? await server.groups()
            guard self.backend === backend else { return }
            groups = refreshedGroups ?? groups
        }
        let refreshedModels = try? await backend.models()
        guard self.backend === backend else { return }
        models = refreshedModels ?? []
        await refreshServerKeys()
        await refreshBalance()
    }

    func refreshPreparingBots() async {
        guard let server else { return }
        do {
            let loaded = try await server.bots()
            bots = loaded.filter(\.isChief) + loaded.filter { !$0.isChief }
            for bot in bots { sessions[bot.id]?.bot = bot }
            loadError = nil
        } catch {
            if !Task.isCancelled { loadError = error.localizedDescription }
        }
    }

    func retryBot(_ bot: BotProfile) async {
        guard let server else { return }
        do {
            try await server.startBot(bot)
            await refreshPreparingBots()
        } catch { loadError = error.localizedDescription }
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
        guard creditAccount === account else { return }
        LocalBots.shared.deleteAll()
        await signOut()
        signedOutNotice = days.map { L("account.deleted.days %lld", $0) } ?? L("account.deleted")
    }

    func signOut() async {
        CreditStore.shared.clearCatalog()
        Keychain.setCodable(SavedBackend.signedOut, for: Self.backendSelectionKey)
        photoRefresh?.cancel()
        photoRefresh = nil
        notificationChat = nil
        UNUserNotificationCenter.current().removeAllDeliveredNotifications()
        stopHistoryRecovery()
        for session in sessions.values { session.cancel() }
        sessions = [:]
        let leaving = backend
        allowedAIRecipient = nil
        backend = nil
        isLoading = false
        bots = []
        groups = []
        serverKeys = nil
        balance = nil
        walletAccount = nil
        lowBalanceDismissed = false
        accountName = ""
        accountPhotoURL = nil
        localAccountImage = nil
        // Previews belong to the account that wrote them.
        previews = [:]
        unread = []
        UserDefaults.standard.removeObject(forKey: "chat.previews")
        UserDefaults.standard.removeObject(forKey: "chat.unread")
        lastBotId = nil
        phase = .signedOut
        await leaving?.signOut()
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
    static func replyFinished(bot: BotProfile, threadId: String?, text: String) {
        guard UIApplication.shared.applicationState != .active else { return }
        let content = UNMutableNotificationContent()
        content.title = bot.name
        if let threadId { content.userInfo = ["agent_id": bot.id, "thread_id": threadId] }
        content.body = String(Speaker.plain(text).split(separator: "\n").first ?? "").prefix(160).description
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
