import Foundation

/// Used without signing in: the Bots live on this phone and chat goes straight to the model the
/// user set up here (their own vendor API key, or a model server on their network). Nothing goes
/// through Lynxce or Octop Bot cloud, and conversations stay on this phone.
final class DeviceBackend: ChatBackend {
    private static let modeKey = "device.mode"

    private let bots: LocalBots
    private let models: PhoneModels
    private let store: DeviceConversations

    init(bots: LocalBots = .shared, models: PhoneModels = .shared, store: DeviceConversations = .shared) {
        self.bots = bots
        self.models = models
        self.store = store
    }

    /// The phone was last used without signing in.
    static func restore() -> DeviceBackend? {
        UserDefaults.standard.bool(forKey: modeKey) ? DeviceBackend() : nil
    }

    /// Start using the phone without an account.
    static func start() -> DeviceBackend {
        UserDefaults.standard.set(true, forKey: modeKey)
        return DeviceBackend()
    }

    var supportsGroups: Bool { false }
    var accountName: String { L("account.device") }

    func bots() async throws -> [BotProfile] { bots.all }

    func conversations(for bot: BotProfile) async throws -> [ConversationSummary] {
        store.conversations(for: bot.id)
    }

    func messages(in conversation: ConversationSummary, bot: BotProfile) async throws -> [ChatMessage] {
        store.messages(in: conversation.id)
    }

    func deleteConversation(_ conversation: ConversationSummary, bot: BotProfile) async throws {
        store.delete(conversation.id)
    }

    /// The model is chosen in Settings → Models, not per chat.
    func models() async throws -> [ModelOption] { [] }

    private lazy var chat = CompletionChat(
        stream: { turn, body, calls, onEvent in
            guard let endpoint = turn.endpoint else { throw APIError(kind: .rejected, status: 400, message: L("models.error.noModel")) }
            try await CompletionChat.streamEndpoint(endpoint, body, calls: &calls, onEvent: onEvent)
        },
        finished: { [unowned self] turn, sessionId in
            store.append(
                to: sessionId, user: turn.user, startedAt: turn.startedAt,
                answer: turn.answer.trimmingCharacters(in: .whitespacesAndNewlines), thinking: turn.thinking
            )
        }
    )

    func send(
        _ text: String, images: [Data], to bot: BotProfile, conversation: String?,
        history: [ChatMessage], model: String?
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        let sessionId = conversation ?? "device-" + UUID().uuidString.lowercased()
        let endpoint = models.endpoint()
        let tools = DeviceConnectors.shared.offeredSpecs.map(\.openAITool)
        let body = LynxceBackend.chatBody(
            text: text, images: images, bot: bot, history: history, sessionId: sessionId, model: endpoint?.model, tools: tools
        )
        let turn = CompletionChat.Turn(body: body, user: text, startedAt: Date(), model: endpoint?.model, endpoint: endpoint)
        let announce: (() -> Void)? = conversation == nil ? { [unowned self] in store.create(sessionId, bot: bot.id, title: text) } : nil
        return chat.start(turn, sessionId: sessionId, announce: announce)
    }

    func resume(
        _ pause: HitlPause, decisions: [[String: Any]], conversation: String, bot: BotProfile
    ) -> AsyncThrowingStream<StreamEvent, Error> {
        chat.resume(pause, decisions: decisions, conversation: conversation)
    }

    func stop(conversation: String, bot: BotProfile) async { chat.stop(conversation) }

    // The phone's own speech recognition and voice are used instead.
    func transcribe(_ audio: Data) async throws -> String? { nil }
    func speech(for text: String) async throws -> Data? { nil }
    func registerPush(token: String) async {}

    /// Leaving phone-only use keeps the keys and conversations here for next time.
    func signOut() async {
        chat.cancelAll()
        UserDefaults.standard.set(false, forKey: Self.modeKey)
    }
}

/// Conversations of phone-only use, kept in Application Support.
final class DeviceConversations {
    static let shared = DeviceConversations()
    private static let limit = 200

    struct Stored: Codable {
        var id: String
        var botId: String
        var title: String
        var updatedAt: Date
        var messages: [Message]
    }

    struct Message: Codable {
        var role: String
        var text: String
        var thinking: String?
        var createdAt: Date
    }

    private let file: URL
    private var all: [Stored]

    init(file: URL? = nil) {
        let url = file ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appending(path: "device-conversations.json")
        self.file = url
        all = (try? Data(contentsOf: url)).flatMap { try? Self.decoder.decode([Stored].self, from: $0) } ?? []
    }

    private static let encoder: JSONEncoder = { let e = JSONEncoder(); e.dateEncodingStrategy = .millisecondsSince1970; return e }()
    private static let decoder: JSONDecoder = { let d = JSONDecoder(); d.dateDecodingStrategy = .millisecondsSince1970; return d }()

    func conversations(for bot: String) -> [ConversationSummary] {
        all.filter { $0.botId == bot }
            .sorted { $0.updatedAt > $1.updatedAt }
            .map { ConversationSummary(id: $0.id, title: $0.title, updatedAt: $0.updatedAt, botId: $0.botId) }
    }

    func messages(in id: String) -> [ChatMessage] {
        guard let stored = all.first(where: { $0.id == id }) else { return [] }
        return stored.messages.compactMap { message in
            guard let role = MessageRole(rawValue: message.role) else { return nil }
            var chat = ChatMessage(role: role, text: message.text)
            chat.thinking = message.thinking ?? ""
            chat.createdAt = message.createdAt
            return chat
        }
    }

    func create(_ id: String, bot: String, title: String) {
        guard !all.contains(where: { $0.id == id }) else { return }
        let line = title.trimmingCharacters(in: .whitespacesAndNewlines).components(separatedBy: .newlines).first ?? ""
        all.append(Stored(id: id, botId: bot, title: String(line.prefix(40)), updatedAt: .now, messages: []))
        save()
    }

    func append(to id: String, user: String, startedAt: Date, answer: String, thinking: String) {
        guard let index = all.firstIndex(where: { $0.id == id }) else { return }
        all[index].messages.append(Message(role: "user", text: user, thinking: nil, createdAt: startedAt))
        if !answer.isEmpty {
            all[index].messages.append(Message(role: "assistant", text: answer, thinking: thinking.isEmpty ? nil : thinking, createdAt: .now))
        }
        all[index].updatedAt = .now
        if all.count > Self.limit {
            all = Array(all.sorted { $0.updatedAt > $1.updatedAt }.prefix(Self.limit))
        }
        save()
    }

    func delete(_ id: String) {
        all.removeAll { $0.id == id }
        save()
    }

    private func save() {
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? Self.encoder.encode(all).write(to: file, options: [.atomic, .completeFileProtection])
    }
}
